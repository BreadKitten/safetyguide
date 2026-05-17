"""Precision & recall evaluation for the hybrid retriever.

Run from the project root:

    PYTHONPATH=server python -m server.tests.test_retrieve

No LLM is needed — the cross-encoder (~140 MB) is the heaviest load, which
runs during the post-rerank query phase (~2–5 s per query).

The suite measures retrieval quality at two stages:

  Pre-rerank (FAISS + BM25 + RRF, top-15 candidates)
  ─────────────────────────────────────────────────────
  P@15  Precision at 15: fraction of the 15 RRF candidates that are relevant.
        Naturally lower than post-rerank — the fused pool is intentionally wide.
  R@15  Recall at 15: fraction of annotated-relevant chunks that appear in the
        top-15 candidates. This is the ceiling the cross-encoder can achieve;
        a chunk not in this pool can never be returned to the LLM.

  Post-rerank (cross-encoder top-4)
  ─────────────────────────────────────────────────────
  MRR   Mean Reciprocal Rank: 1 / rank of the first relevant hit in the top-4
        (0 if none appears). This is the metric that matters most for RAG —
        the LLM weights the first chunk most heavily (primacy bias), so having
        the most relevant chunk at rank 1 is what drives answer quality.

Ground truth is hand-annotated in server/tests/fixtures/retrieval_gold.json.
Off-corpus fixtures (relevant_ids=[]) are checked for gating instead.

Hard failure thresholds (empirically set for this 170-chunk corpus):
  R@15 >= 0.50, MRR >= 0.50
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from server.src.ingest import INDEX_DIR
from server.src.retrieve import (
    CONF_THRESHOLD,
    DENSE_TOP_K,
    BM25_TOP_K,
    FINAL_TOP_K,
    _build_allowed_ids,
    _load_indexes,
    _retrieve_candidates,
    retrieve,
)

# --- thresholds --------------------------------------------------------------
# Empirically set for this 170-chunk corpus. Tune after a re-ingest that
# meaningfully changes corpus coverage.
_MIN_R15 = 0.50   # hard fail
_WARN_R15 = 0.70  # soft warn
_MIN_MRR = 0.50   # hard fail
_WARN_MRR = 0.70  # soft warn
_WARN_TOP_SCORE = 0.30  # WARN if top_score near the 0.1 gate for an in-corpus query

_GOLD_PATH = Path(__file__).parent / "fixtures" / "retrieval_gold.json"
_CHUNKS_PATH = INDEX_DIR / "chunks.json"


# --- helpers -----------------------------------------------------------------
def _load_gold() -> list[dict]:
    with open(_GOLD_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_chunk_ids() -> set[int]:
    with open(_CHUNKS_PATH, encoding="utf-8") as f:
        return {c["id"] for c in json.load(f)}


def _load_disaster_types() -> set[str]:
    with open(_CHUNKS_PATH, encoding="utf-8") as f:
        return {c["disaster_type"] for c in json.load(f)}


def _precision(returned: list[int], relevant: set[int], k: int) -> float:
    pool = returned[:k]
    if not pool:
        return 0.0
    return len(set(pool) & relevant) / len(pool)


def _recall(returned: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    return min(1.0, len(set(returned[:k]) & relevant) / len(relevant))


def _mrr(returned: list[int], relevant: set[int]) -> float:
    for rank, cid in enumerate(returned, start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


# --- [1] fixture validation --------------------------------------------------
def test_fixtures_are_valid(gold: list[dict], chunk_ids: set[int], known_types: set[str]) -> None:
    """Every relevant_id must exist in chunks.json; every disaster_type must be indexed."""
    print("\n[1] test_fixtures_are_valid")
    seen_queries: set[str] = set()
    for i, fx in enumerate(gold):
        q = fx["query"]
        assert q not in seen_queries, f"Duplicate query at index {i}: {q!r}"
        seen_queries.add(q)

        for rid in fx["relevant_ids"]:
            assert rid in chunk_ids, (
                f"Fixture {i} ({q!r}): relevant_id {rid} not found in chunks.json. "
                "Re-annotate after re-ingesting."
            )

        dt = fx.get("disaster_type")
        if dt is not None:
            assert dt in known_types, (
                f"Fixture {i} ({q!r}): disaster_type {dt!r} not in index. "
                f"Known types: {sorted(known_types)}"
            )

    n_in_corpus = sum(1 for fx in gold if fx["relevant_ids"])
    n_off_corpus = sum(1 for fx in gold if not fx["relevant_ids"])
    print(f"    {len(gold)} fixtures: {n_in_corpus} in-corpus, {n_off_corpus} off-corpus  OK")


# --- [2] gating on off-corpus queries ----------------------------------------
def test_gating_on_off_corpus_queries(gold: list[dict]) -> None:
    """Off-corpus fixtures (relevant_ids=[]) must return gated=True."""
    print("\n[2] test_gating_on_off_corpus_queries")
    off_corpus = [fx for fx in gold if not fx["relevant_ids"]]
    if not off_corpus:
        print("    WARN: no off-corpus fixtures found — add some to test the confidence gate")
        return

    for fx in off_corpus:
        result = retrieve(fx["query"], disaster_type=fx.get("disaster_type"))
        score_str = f"{result.top_score:.4f}" if result.top_score != float("-inf") else "-inf"
        status = "GATED" if result.gated else "MISS"
        print(f"    [{status}] {fx['query']!r}  top_score={score_str}")
        assert result.gated, (
            f"Off-corpus query {fx['query']!r} was NOT gated. "
            f"top_score={result.top_score:.4f} (CONF_THRESHOLD={CONF_THRESHOLD}). "
            "Either CONF_THRESHOLD is too low or this query accidentally hit relevant chunks."
        )
    print(f"    All {len(off_corpus)} off-corpus queries correctly gated  OK")


# --- [3] precision & recall @15 (pre-rerank) ---------------------------------
def test_precision_and_recall_at_15(
    candidate_results: list[tuple[dict, list[int]]],
) -> None:
    """P@15 and R@15 on the RRF candidate pool before cross-encoder reranking.

    R@15 is the primary metric here — it is the ceiling for everything downstream.
    P@15 is informational (the pool is wide by design, so low precision is expected).
    """
    print("\n[3] test_precision_and_recall_at_15  (pre-rerank)")
    k = max(DENSE_TOP_K, BM25_TOP_K)
    p_scores: list[float] = []
    r_scores: list[float] = []

    for fx, candidates in candidate_results:
        relevant = set(fx["relevant_ids"])
        p = _precision(candidates, relevant, k)
        r = _recall(candidates, relevant, k)
        p_scores.append(p)
        r_scores.append(r)
        flag = "  " if r >= _WARN_R15 else ("W " if r >= _MIN_R15 else "!!")
        print(f"    [{flag}] P@{k}={p:.2f}  R@{k}={r:.2f}  {fx['query']!r}")

    mean_p = sum(p_scores) / len(p_scores)
    mean_r = sum(r_scores) / len(r_scores)
    print(f"\n    mean P@{k}={mean_p:.3f}  (informational)   mean R@{k}={mean_r:.3f}")

    if mean_r < _WARN_R15:
        print(f"    WARN: mean R@{k}={mean_r:.3f} < {_WARN_R15} — fewer relevant chunks "
              "are reaching the reranker than expected. Check embeddings or BM25 coverage.")
    assert mean_r >= _MIN_R15, (
        f"mean R@{k}={mean_r:.3f} < hard threshold {_MIN_R15}. "
        "The retrieval stage is losing too many relevant chunks before reranking. "
        "Investigate DENSE_TOP_K / BM25_TOP_K or re-ingest the corpus."
    )
    print(f"    R@{k}  OK")


# --- [4] MRR (post-rerank) ---------------------------------------------------
def test_mrr(hit_results: list[tuple[dict, list[int], float]]) -> None:
    """MRR on the cross-encoder top-4: 1 / rank of the first relevant hit.

    This is the primary post-rerank metric for RAG. The LLM is most influenced
    by whatever lands at rank 1, so getting the most relevant chunk there is
    what drives answer quality — not how many relevant chunks fit in the top-4.
    """
    print("\n[4] test_mrr  (post-rerank)")
    mrr_scores: list[float] = []

    for fx, hit_ids, _ in hit_results:
        relevant = set(fx["relevant_ids"])
        rr = _mrr(hit_ids, relevant)
        mrr_scores.append(rr)
        flag = "  " if rr >= _WARN_MRR else ("W " if rr > 0 else "!!")
        print(f"    [{flag}] RR={rr:.2f}  {fx['query']!r}")

    mean_mrr = sum(mrr_scores) / len(mrr_scores)
    print(f"\n    mean MRR={mean_mrr:.3f}")

    if mean_mrr < _WARN_MRR:
        print(f"    WARN: mean MRR={mean_mrr:.3f} < {_WARN_MRR} — first relevant hit "
              "is often not at rank 1. The reranker's ordering quality may be degraded.")
    assert mean_mrr >= _MIN_MRR, (
        f"mean MRR={mean_mrr:.3f} < hard threshold {_MIN_MRR}. "
        "The most relevant chunk frequently does not appear in the top-4 results."
    )
    print("    MRR  OK")


# --- [5] filter correctness --------------------------------------------------
def test_filtered_vs_unfiltered(hit_results: list[tuple[dict, list[int], float]]) -> None:
    """Filtered queries must only return hits whose disaster_type matches the filter."""
    print("\n[5] test_filtered_vs_unfiltered")
    filtered_fx = [(fx, hit_ids) for fx, hit_ids, _ in hit_results
                   if fx.get("disaster_type") is not None]

    if not filtered_fx:
        print("    WARN: no filtered fixtures found — add some to test the filter path")
        return

    with open(_CHUNKS_PATH, encoding="utf-8") as f:
        chunks_by_id = {c["id"]: c for c in json.load(f)}

    for fx, hit_ids in filtered_fx:
        wanted_type = fx["disaster_type"]
        for cid in hit_ids:
            actual_type = chunks_by_id[cid]["disaster_type"]
            assert actual_type == wanted_type, (
                f"Filtered query {fx['query']!r} (filter={wanted_type!r}) returned "
                f"chunk id={cid} with disaster_type={actual_type!r}. "
                "The metadata filter is broken."
            )
        print(f"    [OK] filter={wanted_type!r}  {len(hit_ids)} hits all match  {fx['query']!r}")

    print(f"    All {len(filtered_fx)} filtered fixtures pass  OK")


# --- [6] score regression watch ----------------------------------------------
def test_no_score_regression(hit_results: list[tuple[dict, list[int], float]]) -> None:
    """Warn if top_score is uncomfortably close to CONF_THRESHOLD on in-corpus queries."""
    print("\n[6] test_no_score_regression")
    flagged = 0
    for fx, _, top_score in hit_results:
        flag = "  "
        if top_score < _WARN_TOP_SCORE:
            flag = "W "
            flagged += 1
        print(f"    [{flag}] top_score={top_score:.4f}  {fx['query']!r}")

    if flagged:
        print(
            f"\n    WARN: {flagged} in-corpus queries have top_score < {_WARN_TOP_SCORE}. "
            f"CONF_THRESHOLD={CONF_THRESHOLD} — low scores risk flipping to gated "
            "after a re-ingest or model update."
        )
    else:
        print(f"\n    All top_scores >= {_WARN_TOP_SCORE}  OK")


# --- summary table -----------------------------------------------------------
def _print_summary(
    candidate_results: list[tuple[dict, list[int]]],
    hit_results: list[tuple[dict, list[int], float]],
) -> None:
    k15 = max(DENSE_TOP_K, BM25_TOP_K)

    p15_list, r15_list, mrr_list = [], [], []
    for (fx_c, candidates), (_, hit_ids, _) in zip(candidate_results, hit_results):
        rel = set(fx_c["relevant_ids"])
        p15_list.append(_precision(candidates, rel, k15))
        r15_list.append(_recall(candidates, rel, k15))
        mrr_list.append(_mrr(hit_ids, rel))

    def mean(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    mp15, mr15 = mean(p15_list), mean(r15_list)
    mmrr = mean(mrr_list)

    def status(val: float, threshold: float | None) -> str:
        if threshold is None:
            return "-"
        return "OK" if val >= threshold else "FAIL"

    header = f"{'Stage':<14} {'Metric':<8} {'Value':>7}  {'Threshold':>11}  {'Status'}"
    sep = "-" * len(header)
    print(f"\n{header}")
    print(sep)
    print(f"{'Pre-rerank':<14} {'P@' + str(k15):<8} {mp15:>7.3f}  {'         -':>11}  - (informational)")
    print(f"{'Pre-rerank':<14} {'R@' + str(k15):<8} {mr15:>7.3f}  {'>= ' + str(_MIN_R15):>11}  {status(mr15, _MIN_R15)}")
    print(f"{'Post-rerank':<14} {'MRR':<8} {mmrr:>7.3f}  {'>= ' + str(_MIN_MRR):>11}  {status(mmrr, _MIN_MRR)}")
    print(sep)


# --- runner ------------------------------------------------------------------
def main() -> int:
    gold = _load_gold()
    chunk_ids = _load_chunk_ids()
    known_types = _load_disaster_types()

    test_fixtures_are_valid(gold, chunk_ids, known_types)

    # Load indexes once — both _retrieve_candidates and retrieve() need them.
    print("\nLoading indexes and models (first call — cross-encoder ~140 MB)...")
    _load_indexes()

    in_corpus = [fx for fx in gold if fx["relevant_ids"]]
    off_corpus = [fx for fx in gold if not fx["relevant_ids"]]

    print(f"\nRunning {len(in_corpus)} in-corpus + {len(off_corpus)} off-corpus queries...")
    candidate_results: list[tuple[dict, list[int]]] = []
    hit_results: list[tuple[dict, list[int], float]] = []

    for fx in in_corpus:
        dt = fx.get("disaster_type")
        allowed_ids = _build_allowed_ids(dt)
        candidates = _retrieve_candidates(fx["query"], allowed_ids)
        candidate_results.append((fx, candidates))

        result = retrieve(fx["query"], disaster_type=dt)
        if result.gated:
            print(f"    WARN: in-corpus query gated unexpectedly: {fx['query']!r} "
                  f"top_score={result.top_score:.4f}")
            hit_results.append((fx, [], result.top_score))
        else:
            hit_ids = [h.chunk_id for h in result.hits]
            hit_results.append((fx, hit_ids, result.top_score))

    test_gating_on_off_corpus_queries(off_corpus)
    test_precision_and_recall_at_15(candidate_results)
    test_mrr(hit_results)
    test_filtered_vs_unfiltered(hit_results)
    test_no_score_regression(hit_results)

    _print_summary(candidate_results, hit_results)

    print("\nAll hard assertions passed. Review WARN lines above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
