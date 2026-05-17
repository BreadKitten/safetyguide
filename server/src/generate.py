"""Cited-answer synthesis over retrieved chunks.

The final stage of the RAG pipeline: takes a `PipelineResult` (parser output
plus retrieval result) and produces a grounded answer with `[n]` citation
markers. The module sits on two load-bearing rules:

  1. **Gating is non-negotiable.** If `retrieval.gated` is True, surface
     `retrieval.message` verbatim and never call the LLM. The retriever's
     confidence gate is the only authoritative "no answer" signal in this
     project -- wrong disaster advice is harmful, so the generator must
     respect a closed gate even if it could plausibly synthesize something.

  2. **One LLM, one load.** The Qwen2.5-7B Q4_K_M GGUF is ~4.7 GB. We import
     `_get_llm` from `src.query` rather than instantiating `Llama` again --
     a second load in the same process OOMs a laptop.

Safety-first reordering: before building the prompt we re-sort the 4 hits so
those containing imperative/warning language land at `[1]`/`[2]`. The cross-
encoder ranks for topical relevance, not life-safety priority; reordering
exploits both the LLM's primacy bias and the user's, so even a truncated
answer leads with the warning. `GenerationResult.citations` is returned in
the reordered order so `[n]` markers in the answer match the citations list.

`answer_stream` is the streaming entry point used by the FastAPI `/stream`
endpoint; it yields typed event dicts (meta, token, done) so the UI can
render tokens as they arrive.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict, dataclass, field

from server.src.pipeline import PipelineResult, run
from server.src.query import _get_llm
from server.src.retrieve import LOW_CONFIDENCE_MESSAGE, Hit

# --- tuning knobs ------------------------------------------------------------
# TEMPERATURE=0: deterministic decoding, matches src/query.py so reruns of
# the same query produce byte-identical answers for demo / debugging.
# MAX_TOKENS=384: budgeted against N_CTX=2048 (set in src/query.py). A
# typical call uses ~250 tokens for the system prompt, ~30 for the user
# wrapper + question, and 4 chunks × ~300 tokens = ~1500 used, leaving ~500
# of headroom. 384 covers a 4-6 bullet response with [n] markers.
TEMPERATURE = 0.0
MAX_TOKENS = 384


# --- safety-first reordering -------------------------------------------------
# Phrases that signal imperative warning or life-safety content rather than
# generic disaster vocabulary. Used only to rank chunks (not to filter), so
# additions are low-risk: a phrase that occasionally fires on non-safety
# text at worst nudges an irrelevant chunk up by one slot. Removals are
# slightly riskier -- a missing imperative phrase means warnings stay
# buried beneath procedural detail. Group by intent (imperatives,
# severity, shelter, hazard-specific, ...) so the rationale of each entry
# is visible at a glance.
_SAFETY_KEYWORDS: tuple[str, ...] = (
    # imperative warnings
    "do not",
    "don't",
    "never",
    "avoid",
    "stay away",
    # explicit warning / danger language
    "warning",
    "danger",
    "dangerous",
    "hazardous",
    "caution",
    # immediacy
    "immediately",
    "leave immediately",
    "get out",
    # evacuation
    "evacuate",
    "evacuation",
    # emergency-services action
    "call 9-1-1",
    "9-1-1",
    # severity language
    "life-threatening",
    "deadly",
    "lethal",
    "death",
    # shelter directives
    "shelter in place",
    "take shelter",
    "seek shelter",
    "away from windows",
    "high ground",
    # earthquake-specific (Drop, Cover, Hold On)
    "drop, cover",
    "drop and cover",
    # fire-specific
    "stay low",
    "get low",
    "crawl",
    # flood-specific
    "do not drive",
    "turn around",
    # utility hazard control
    "turn off",
    "shut off",
    "unplug",
)


def _safety_score(text: str) -> int:
    """Sum of safety-keyword occurrences in the chunk text (case-insensitive).

    Counts occurrences rather than presence so a chunk packed with imperative
    language ("do not", "evacuate immediately", "deadly") outscores one that
    only mentions a hazard in passing. Cheap (a handful of substring scans on
    a few hundred characters); runs ~1 ms per hit.
    """
    lower = text.lower()
    return sum(lower.count(kw) for kw in _SAFETY_KEYWORDS)


def _reorder_safety_first(hits: list[Hit]) -> list[Hit]:
    """Stable-sort hits so safety-heavy chunks rise to the front.

    Sort key is `(-safety_count, original_rank)`. Stable sort preserves the
    cross-encoder's order among ties, so chunks with equal safety signal stay
    in their reranker order; only hits with strictly higher safety counts
    move up. If every hit scores zero (e.g. a pure go-bag prep query), the
    sort is a no-op. The reorder never adds or removes hits.
    """
    scored = [(i, h, _safety_score(h.text)) for i, h in enumerate(hits)]
    scored.sort(key=lambda t: (-t[2], t[0]))
    return [h for _, h, _ in scored]


# --- prompt construction -----------------------------------------------------
# The system prompt encodes the project's two non-negotiables: ground every
# claim in the numbered context, and lead with safety language when any
# block contains it. Rule ordering matters -- the safety rule comes first so
# even a truncated chain-of-thought trace still attends to it.
_SYSTEM_PROMPT = (
    "You are an offline disaster-preparedness assistant. Lives may be at "
    "stake -- be precise, direct, and grounded.\n\n"
    "Rules, in priority order:\n\n"
    "1. SAFETY FIRST. If any numbered context block contains a warning, "
    "evacuation order, or \"do not / never\" directive that applies to the "
    "user's question, lead your answer with that warning before any other "
    "steps.\n\n"
    "2. GROUND EVERY CLAIM. Answer using ONLY the numbered context blocks "
    "below.\n"
    "2a. If NONE of the numbered blocks address the question at all, your "
    "entire reply must be exactly this sentence with no other text: "
    f"\"{LOW_CONFIDENCE_MESSAGE}\". Do not add citations, do not add "
    "disclaimers, do not partially answer.\n"
    "2b. If even ONE block addresses the question, answer from those blocks "
    "with [n] citations and DO NOT include the sentence from 2a anywhere in "
    "your reply. A partial cited answer is always preferred over the 2a "
    "phrase.\n\n"
    "3. CITE EVERY STATEMENT. After every factual statement, add a citation "
    "marker like [1] referring to the block number that supports it. "
    "Multiple citations like [1][3] are fine. No claim without a marker.\n\n"
    "4. DO NOT INVENT. No steps, statistics, phone numbers, agency names, "
    "or product names that are not in the context. No outside knowledge.\n\n"
    "5. FORMAT. Prefer short numbered or bulleted action steps over prose. "
    "Imperative voice (\"Drop to the floor\", not \"You should drop to the "
    "floor\"). No filler disclaimers (\"consult an expert\", \"results may "
    "vary\") unless they appear in the context."
)


def _build_user_message(question: str, hits: list[Hit]) -> str:
    """Assemble the numbered context blocks plus the user question.

    Numbering is 1-indexed and matches the order of `hits` -- callers must
    pass the safety-reordered list so the LLM's `[n]` markers and the
    returned `GenerationResult.citations` agree.
    """
    blocks: list[str] = ["Context (most safety-critical first):"]
    for i, h in enumerate(hits, start=1):
        blocks.append(
            f"\n[{i}] source={h.source} page={h.page} disaster={h.disaster_type}\n"
            f"{h.text}"
        )
    blocks.append(f"\nQuestion: {question}")
    blocks.append("\nAnswer with [n] citations. Lead with any safety warning that applies.")
    return "\n".join(blocks)


# --- LLM calls ---------------------------------------------------------------
# Regex for any `[n]` citation marker. Used by _strip_canned_phrase_from_cited_answer
# to detect whether a response is a cited answer or the bare canned phrase.
_CITATION_RE = re.compile(r"\[\d+\]")


def _has_citation_markers(text: str) -> bool:
    return _CITATION_RE.search(text) is not None


def _strip_canned_phrase_from_cited_answer(text: str) -> str:
    """Remove LOW_CONFIDENCE_MESSAGE from an answer that also contains [n] markers.

    A cited answer that also emits the canned no-answer sentence is self-
    contradicting: the retriever gate already passed, the LLM grounded its
    claims, and the canned phrase is reserved for the empty-context case
    (system prompt rule 2a). If both coexist, we trust the citations and
    drop the phrase. If the answer has no [n] markers, we leave it alone --
    it may legitimately BE the canned reply via rule 2a.
    """
    if not _has_citation_markers(text):
        return text
    if LOW_CONFIDENCE_MESSAGE not in text:
        return text
    cleaned = text.replace(LOW_CONFIDENCE_MESSAGE, "")
    # Collapse whitespace orphaned by the removal. No sentence-splitting --
    # Qwen's output is varied enough (markdown bullets, bare prose, numbered
    # lists) that any heuristic is more risk than reward; a double-space and
    # triple-newline collapse plus .strip() handles the common cases.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _call_llm(question: str, hits: list[Hit]) -> str:
    """Single LLM call. Returns the stripped assistant content."""
    llm = _get_llm()
    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(question, hits)},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    return resp["choices"][0]["message"]["content"].strip()


def _call_llm_stream(question: str, hits: list[Hit]):
    """Streaming LLM call. Yields raw token strings as they are produced."""
    llm = _get_llm()
    stream = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(question, hits)},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    for chunk in stream:
        delta = chunk["choices"][0]["delta"]
        token = delta.get("content")
        if token:
            yield token


# --- public types ------------------------------------------------------------
@dataclass
class GenerationResult:
    """LLM answer plus the hits used to produce it.

    Contract: when `gated=True`, `answer` is the canned retrieval message
    surfaced verbatim and `citations` is empty. Callers (UI, CLI) render the
    same way in both branches -- no special-casing required.

    `citations` is ordered to match the `[n]` markers in `answer` -- i.e.
    the safety-first reordered order, not the cross-encoder's original rank.
    """
    answer: str
    citations: list[Hit] = field(default_factory=list)
    gated: bool = False
    top_score: float = float("-inf")


# --- public entry points -----------------------------------------------------
def generate(result: PipelineResult) -> GenerationResult:
    """Synthesize a cited answer from a PipelineResult.

    Honors `result.retrieval.gated` strictly (surfaces the canned message
    and skips the LLM call). On the happy path, reorders hits safety-first,
    runs the LLM, then strips any spurious canned phrase from a cited answer.

    A bare `except Exception` wraps the LLM call so a model-runtime failure
    degrades to the canned low-confidence response instead of crashing the
    demo. This is graceful degradation, not a bypass: the real gate
    (CONF_THRESHOLD in src.retrieve) has already run.
    """
    retrieval = result.retrieval
    if retrieval.gated:
        return GenerationResult(
            answer=retrieval.message or LOW_CONFIDENCE_MESSAGE,
            citations=[],
            gated=True,
            top_score=retrieval.top_score,
        )

    ordered_hits = _reorder_safety_first(retrieval.hits)
    question = result.parsed.rewritten

    try:
        text = _call_llm(question, ordered_hits)
        text = _strip_canned_phrase_from_cited_answer(text)
    except Exception as exc:  # llama-cpp runtime errors, OOM, etc.
        print(f"generate: LLM call failed ({exc!r}); falling back.", file=sys.stderr)
        return GenerationResult(
            answer=LOW_CONFIDENCE_MESSAGE,
            citations=[],
            gated=True,
            top_score=retrieval.top_score,
        )

    return GenerationResult(
        answer=text,
        citations=ordered_hits,
        gated=False,
        top_score=retrieval.top_score,
    )


def answer(query: str) -> GenerationResult:
    """End-to-end convenience: parse_query -> retrieve -> generate."""
    return generate(run(query))


def answer_stream(query: str):
    """End-to-end streaming: parse -> retrieve -> stream LLM tokens.

    Yields typed dicts in order:
      {"type": "meta",  "gated": bool, "top_score": float, "citations": [...]}
      {"type": "token", "text": str}   -- one per LLM token
      {"type": "done"}

    Citations are known before the LLM call (they are the safety-reordered
    hits), so the meta event is emitted the moment retrieval completes and
    token events follow immediately -- no full-response buffering required.
    On LLM errors the fallback canned message is emitted as a token event
    rather than raising, so the caller always sees a clean done event.
    """
    result = run(query)
    retrieval = result.retrieval

    if retrieval.gated:
        yield {
            "type": "meta",
            "gated": True,
            "top_score": retrieval.top_score,
            "citations": [],
        }
        yield {"type": "token", "text": retrieval.message or LOW_CONFIDENCE_MESSAGE}
        yield {"type": "done"}
        return

    ordered_hits = _reorder_safety_first(retrieval.hits)
    question = result.parsed.rewritten

    yield {
        "type": "meta",
        "gated": False,
        "top_score": retrieval.top_score,
        "citations": [asdict(h) for h in ordered_hits],
    }

    try:
        for token in _call_llm_stream(question, ordered_hits):
            yield {"type": "token", "text": token}
    except Exception as exc:
        print(f"answer_stream: LLM error ({exc!r}); sending fallback.", file=sys.stderr)
        yield {"type": "token", "text": LOW_CONFIDENCE_MESSAGE}

    yield {"type": "done"}


# --- CLI ---------------------------------------------------------------------
def _format_result(query: str, result: GenerationResult) -> str:
    """Human-readable dump for `python -m src.generate <query>`."""
    lines = [
        f"query:     {query!r}",
        f"gated:     {result.gated}  top_score: {result.top_score:.4f}",
        "",
        result.answer,
    ]
    if result.citations:
        lines.append("")
        lines.append("Sources:")
        for i, h in enumerate(result.citations, start=1):
            lines.append(
                f"  [{i}] {h.source} page={h.page}  "
                f"(disaster={h.disaster_type}, score={h.score:.4f})"
            )
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Cited-answer generator CLI.")
    parser.add_argument("query")
    args = parser.parse_args(argv)
    result = answer(args.query)
    print(_format_result(args.query, result))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
