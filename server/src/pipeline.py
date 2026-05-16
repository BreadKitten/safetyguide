"""End-to-end query orchestration: parse -> retrieve (-> generate, eventually).

Wires `src.query.parse_query` into `src.retrieve.retrieve` so a raw user
question becomes either a list of cited hits or the canned low-confidence
message. The generation step is intentionally out of scope here -- this
module returns the retrieval result as-is so `src.generate` can layer on
top once it exists.

Failure model: parser failures already degrade to `rewritten == original`
and `disaster_type is None`, so the pipeline always has *something* to
retrieve. The retriever's own gate (`RetrievalResult.gated`) is the only
authoritative "no answer" signal exposed to callers -- the pipeline does
not add a second gate.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from server.src.query import ParsedQuery, parse_query
from server.src.retrieve import FINAL_TOP_K, RetrievalResult, retrieve


# --- public types ------------------------------------------------------------
@dataclass
class PipelineResult:
    """Bundles the parser output with the retrieval result.

    `parsed.rewritten` is the query string that was sent to `retrieve`.
    `parsed.disaster_type` is the metadata filter (None == no filter).
    `retrieval` carries the gating contract -- callers must respect
    `retrieval.gated` and surface `retrieval.message` verbatim when it is
    set, exactly as a direct `retrieve()` caller would.
    """
    parsed: ParsedQuery
    retrieval: RetrievalResult


# --- public entry point ------------------------------------------------------
def run(query: str, top_k: int = FINAL_TOP_K) -> PipelineResult:
    """Parse the query, then retrieve. Single call, no side effects.

    The parser's `rewritten` query is what hits the retriever -- BM25 in
    particular benefits from canonical hazard tokens that the parser may
    have appended. The cross-encoder rerank inside `retrieve` then operates
    on the original-ish phrasing, so we get both signals.
    """
    parsed = parse_query(query)
    result = retrieve(
        parsed.rewritten,
        disaster_type=parsed.disaster_type,
        top_k=top_k,
    )
    return PipelineResult(parsed=parsed, retrieval=result)


# --- CLI ---------------------------------------------------------------------
def _format(result: PipelineResult) -> str:
    p, r = result.parsed, result.retrieval
    lines = [
        f"original:      {p.original!r}",
        f"rewritten:     {p.rewritten!r}",
        f"disaster_type: {p.disaster_type}",
        f"top_score:     {r.top_score:.4f}  gated: {r.gated}",
    ]
    if r.gated:
        lines.append(f"message:       {r.message}")
        return "\n".join(lines)
    for i, h in enumerate(r.hits, start=1):
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
    parser = argparse.ArgumentParser(description="End-to-end pipeline CLI.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=FINAL_TOP_K)
    args = parser.parse_args(argv)
    result = run(args.query, top_k=args.top_k)
    print(_format(result))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
