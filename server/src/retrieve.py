"""Hybrid retrieval over the local index.

Two retrievers run in parallel and are merged with Reciprocal Rank Fusion:

  * Dense (semantic): the query is embedded with bge-small-en-v1.5 (384-d) and
    compared against the FAISS index. The index is IndexFlatIP over
    L2-normalized vectors, so inner product == cosine similarity.
  * Sparse (keyword): rank_bm25's BM25Okapi over the same `\\w+`-lowercased
    tokens used at ingest time. Catches literal term matches that embeddings
    sometimes blur (place names, model numbers, "drop cover hold on", etc.).

The two ranked lists are fused with Reciprocal Rank Fusion. RRF is
intentionally *unweighted*: each retriever contributes 1 / (k + rank) per
document with k=60, and we sum across lists. The `60` is the RRF paper's
smoothing constant on rank position, NOT a weight between retrievers — both
lists count equally (implicit weight 1.0 each). We deliberately avoid a
hand-tuned dense-vs-BM25 split because we have no held-out labels to fit it.

The fused top-N is then reranked by a cross-encoder (bge-reranker-base), which
scores (query, chunk) pairs jointly. We keep the top-k from the reranker and
gate on its top score: if it's below CONF_THRESHOLD we refuse to answer.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from dataclasses import dataclass, field
from typing import Iterable

import faiss
import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

from server.src.ingest import EMBED_MODEL, INDEX_DIR, _tokenize

# --- tuning knobs ------------------------------------------------------------
# DENSE_TOP_K / BM25_TOP_K: per-retriever candidate pool before fusion. 15
# each gives RRF enough breadth to work with while staying small enough that
# the cross-encoder rerank below is cheap.
# FINAL_TOP_K: chunks handed to the LLM. Keep this tight — Qwen2.5-7B's
# context is limited and noisy chunks degrade answers faster than missing
# ones do.
# RRF_K=60 is the standard constant from the original RRF paper (Cormack et
# al. 2009). Smaller -> more top-heavy fusion, larger -> flatter.
# CONF_THRESHOLD is a sigmoid-normalized cross-encoder score in [0, 1].
# Empirically on this corpus: relevant top hits score ~0.85-0.99, unrelated
# queries (e.g. random trivia) bottom out near 0.0001. 0.1 sits well above
# the noise floor and below typical real matches.
RERANKER_MODEL = "BAAI/bge-reranker-base"
DENSE_TOP_K = 15
BM25_TOP_K = 15
RRF_K = 60
FINAL_TOP_K = 4
CONF_THRESHOLD = 0.1

LOW_CONFIDENCE_MESSAGE = (
    "I could not find reliable information in the local emergency knowledge base."
)
EMPTY_FILTER_MESSAGE = "No chunks match the requested filter."


# --- lazy-loaded singletons --------------------------------------------------
# Index files and models are loaded on first call to `retrieve()`, not at
# import. Importing `retrieve` should be free so `pipeline.py` and tests can
# pull symbols without paying the ~140 MB cross-encoder load cost.
_chunks: list[dict] | None = None
_faiss = None
_bm25 = None
_embedder: SentenceTransformer | None = None
_reranker: CrossEncoder | None = None


# --- public types ------------------------------------------------------------
@dataclass
class Hit:
    """A single reranked retrieval result, ready for citation in the LLM prompt."""
    chunk_id: int
    text: str
    source: str
    page: int
    disaster_type: str
    score: float


@dataclass
class RetrievalResult:
    """Wraps a hit list plus gating state.

    When `gated=True`, `hits` is empty and `message` holds the canned response
    the caller should surface verbatim. This is how we enforce the "no
    hallucinated disaster advice" rule — callers don't get to bypass it by
    ignoring an empty list.
    """
    hits: list[Hit] = field(default_factory=list)
    top_score: float = float("-inf")
    gated: bool = False
    message: str | None = None


# --- index loading -----------------------------------------------------------
def _load_indexes() -> None:
    """Load chunks.json, FAISS, and BM25 once; assert they are row-aligned.

    Every downstream lookup is positional (FAISS row i == BM25 doc i ==
    chunks[i]). A mismatch almost always means ingest was interrupted; fail
    loudly rather than silently returning wrong sources.
    """
    global _chunks, _faiss, _bm25
    if _chunks is not None:
        return

    chunks_path = INDEX_DIR / "chunks.json"
    faiss_path = INDEX_DIR / "faiss.index"
    bm25_path = INDEX_DIR / "bm25.pkl"
    for p in (chunks_path, faiss_path, bm25_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Missing index file: {p}. Run `python -m src.ingest` first."
            )

    with open(chunks_path, "r", encoding="utf-8") as f:
        _chunks = json.load(f)
    _faiss = faiss.read_index(str(faiss_path))
    with open(bm25_path, "rb") as f:
        _bm25 = pickle.load(f)

    assert _chunks is not None
    n_chunks, n_faiss, n_bm25 = len(_chunks), _faiss.ntotal, len(_bm25.doc_freqs)
    if not (n_chunks == n_faiss == n_bm25):
        raise RuntimeError(
            f"Index row counts disagree: chunks.json={n_chunks}, "
            f"faiss={n_faiss}, bm25={n_bm25}. Re-run `python -m src.ingest`."
        )


def _get_embedder() -> SentenceTransformer:
    """Lazy bge-small-en-v1.5. Must use the same model as ingest — drift here
    silently degrades recall because the index was built with this model."""
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_reranker() -> CrossEncoder:
    """Lazy bge-reranker-base. Cross-encoders score (query, doc) jointly, so
    they're far more accurate than bi-encoders for top-k but ~100x slower per
    pair. We only call it on the fused candidate pool (≤30 chunks), never the
    full corpus."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker


# --- metadata filtering ------------------------------------------------------
def _build_allowed_ids(disaster_type: str | None) -> set[int] | None:
    """Resolve the disaster_type filter to a set of chunk ids. Returns None
    when no filter is active so callers can skip the set-membership check on
    the hot path."""
    if disaster_type is None:
        return None
    assert _chunks is not None
    return {c["id"] for c in _chunks if c["disaster_type"] == disaster_type}


# --- retrievers --------------------------------------------------------------
def _dense_search(
    query_vec: np.ndarray,
    k: int,
    allowed_ids: set[int] | None,
) -> list[tuple[int, int]]:
    """Top-k semantic neighbors via FAISS inner product (== cosine, since
    vectors are L2-normalized at ingest). When filtering, over-fetch 4x so
    post-hoc rejection still yields k survivors on typical selectivities."""
    assert _faiss is not None
    fetch = min(k * 4 if allowed_ids is not None else k, _faiss.ntotal)
    _, ids = _faiss.search(query_vec, fetch)
    out: list[tuple[int, int]] = []
    rank = 0
    for cid in ids[0]:
        cid = int(cid)
        if cid < 0:
            continue
        if allowed_ids is not None and cid not in allowed_ids:
            continue
        out.append((cid, rank))
        rank += 1
        if rank >= k:
            break
    return out


def _bm25_search(
    query_tokens: list[str],
    k: int,
    allowed_ids: set[int] | None,
) -> list[tuple[int, int]]:
    """Top-k by BM25 keyword score. Scores are computed against every doc
    (the corpus is small; this is faster than a Python-side inverted-index
    shortlist). Zero-score docs are dropped so RRF doesn't fuse pure noise."""
    assert _bm25 is not None and _chunks is not None
    scores = _bm25.get_scores(query_tokens)
    order = np.argsort(-scores)
    out: list[tuple[int, int]] = []
    rank = 0
    for cid in order:
        cid = int(cid)
        if scores[cid] <= 0:
            break
        if allowed_ids is not None and cid not in allowed_ids:
            continue
        out.append((cid, rank))
        rank += 1
        if rank >= k:
            break
    return out


# --- fusion + rerank ---------------------------------------------------------
def _rrf_fuse(
    rank_lists: Iterable[list[tuple[int, int]]],
    k: int = RRF_K,
) -> list[int]:
    """Reciprocal Rank Fusion: score(doc) = sum(1 / (k + rank_i)).

    Unweighted on purpose — each rank list contributes equally. The cross-
    encoder rerank downstream does the real quality decision; RRF just
    assembles a healthy candidate pool.
    """
    scores: dict[int, float] = {}
    for ranklist in rank_lists:
        for cid, rank in ranklist:
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.keys(), key=lambda c: scores[c], reverse=True)


def _rerank(query: str, candidate_ids: list[int]) -> list[tuple[int, float]]:
    """Score every (query, chunk.text) pair with the cross-encoder and sort
    by descending score. The cross-encoder logit is what CONF_THRESHOLD gates
    on — using it (rather than RRF score) means the gate decision uses the
    strongest signal we have."""
    assert _chunks is not None
    if not candidate_ids:
        return []
    pairs = [[query, _chunks[cid]["text"]] for cid in candidate_ids]
    scores = _get_reranker().predict(pairs)
    paired = list(zip(candidate_ids, [float(s) for s in scores]))
    paired.sort(key=lambda x: x[1], reverse=True)
    return paired


# --- public entry point ------------------------------------------------------
def retrieve(
    query: str,
    disaster_type: str | None = None,
    top_k: int = FINAL_TOP_K,
) -> RetrievalResult:
    """End-to-end retrieval: filter -> dense+BM25 -> RRF -> rerank -> gate.

    Returns a `RetrievalResult` whose `gated` field signals whether the caller
    should answer or surface `message` verbatim. The disaster_type filter
    narrows the candidate pool by exact metadata match before fusion.
    """
    _load_indexes()
    assert _chunks is not None

    allowed_ids = _build_allowed_ids(disaster_type)
    if allowed_ids is not None and not allowed_ids:
        return RetrievalResult(gated=True, message=EMPTY_FILTER_MESSAGE)

    query_vec = _get_embedder().encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    query_tokens = _tokenize(query)

    dense = _dense_search(query_vec, DENSE_TOP_K, allowed_ids)
    sparse = _bm25_search(query_tokens, BM25_TOP_K, allowed_ids)
    fused_ids = _rrf_fuse([dense, sparse])

    if not fused_ids:
        return RetrievalResult(gated=True, message=LOW_CONFIDENCE_MESSAGE)

    reranked = _rerank(query, fused_ids)
    top_score = reranked[0][1]

    if top_score < CONF_THRESHOLD:
        return RetrievalResult(
            top_score=top_score,
            gated=True,
            message=LOW_CONFIDENCE_MESSAGE,
        )

    hits: list[Hit] = []
    for cid, score in reranked[:top_k]:
        c = _chunks[cid]
        hits.append(Hit(
            chunk_id=cid,
            text=c["text"],
            source=c["source"],
            page=c["page"],
            disaster_type=c["disaster_type"],
            score=score,
        ))
    return RetrievalResult(hits=hits, top_score=top_score)


# --- CLI ---------------------------------------------------------------------
def _format_result(result: RetrievalResult) -> str:
    """Human-readable dump for the CLI. Always prints top_score so the
    operator can calibrate CONF_THRESHOLD against real queries."""
    lines = [f"top_score: {result.top_score:.4f}  gated: {result.gated}"]
    if result.gated:
        lines.append(f"message: {result.message}")
        return "\n".join(lines)
    for i, h in enumerate(result.hits, start=1):
        snippet = h.text.replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        lines.append(
            f"\n[{i}] score={h.score:.4f}  source={h.source}  page={h.page}  "
            f"disaster={h.disaster_type}"
        )
        lines.append(f"    {snippet}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Hybrid retrieval CLI.")
    parser.add_argument("query")
    parser.add_argument("--disaster-type", default=None)
    parser.add_argument("--top-k", type=int, default=FINAL_TOP_K)
    args = parser.parse_args(argv)

    result = retrieve(
        args.query,
        disaster_type=args.disaster_type,
        top_k=args.top_k,
    )
    print(_format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
