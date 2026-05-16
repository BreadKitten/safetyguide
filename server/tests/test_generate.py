"""Inspection-style sanity checks for the cited-answer generation stage.

Run from the project root:

    python -m tests.test_generate            # fast: pure-unit + monkeypatched gate/fallback
    python -m tests.test_generate --with-llm # adds end-to-end checks (~1-2 min)

These tests are not pytest. Each check prints what it sees and raises
AssertionError on a hard failure. Soft signals (corpus-dependent, model
drift, latency) are printed as `WARN` so the operator eyeballs them.

The pure-unit pass exercises everything the project's four load-bearing
contracts depend on without loading the 4.7 GB GGUF:

  1. Safety-first reordering (`_safety_score`, `_reorder_safety_first`).
     Strict-greater inequality between imperative-heavy and topical-only
     chunks is what makes the prompt-time reorder do useful work.
  2. Citation marker detection (`_CITATION_RE`, `_has_citation_markers`).
     False negatives trigger an expensive useless re-prompt, so the regex
     contract is locked here.
  3. Numbered-context prompt assembly (`_build_user_message`). The `[n]`
     markers in the LLM's reply must agree with the slot order in this
     string, so its format is a contract.
  4. Gate-honored-verbatim. `generate()` must skip the LLM entirely when
     `retrieval.gated=True`. We enforce this by monkeypatching `_get_llm`
     to a function that raises on call.
  5. Graceful degradation. An LLM runtime exception inside `_call_llm`
     must produce a gated `GenerationResult` with `LOW_CONFIDENCE_MESSAGE`,
     never a stack trace.
  6. Citation retry. When the first answer has no `[n]` markers, the
     retry path must fire. When the retry *also* fails, the result must
     be suffixed with the soft warning (NOT gated -- formatting is not a
     gate criterion by design).

The `--with-llm` pass adds:

  7. End-to-end citations always appear on in-corpus queries.
  8. Off-topic queries gate cleanly through the production retriever.
  9. (Soft) safety-laden queries surface a warning-heavy chunk at slot 1.
 10. (Soft) determinism across two identical calls at temperature=0.
"""
from __future__ import annotations

import argparse
import sys

import server.src.generate as generate_module
from server.src.generate import (
    GenerationResult,
    _build_user_message,
    _CITATION_RE,
    _has_citation_markers,
    _reorder_safety_first,
    _safety_score,
    answer,
    generate,
)
from server.src.pipeline import PipelineResult
from server.src.query import ParsedQuery
from server.src.retrieve import LOW_CONFIDENCE_MESSAGE, EMPTY_FILTER_MESSAGE, Hit, RetrievalResult


# --- fixture helpers ---------------------------------------------------------
# Tiny constructors so each test reads as "set up Hit/PipelineResult, call,
# assert" instead of "fill 6 positional dataclass args". The defaults are
# uninteresting placeholder values -- override only what the specific test
# actually depends on.
def _hit(text: str, chunk_id: int = 0, score: float = 0.5) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        text=text,
        source="placeholder.txt",
        page=1,
        disaster_type="general",
        score=score,
    )


def _pipeline_result(
    *,
    gated: bool,
    hits: list[Hit] | None = None,
    message: str | None = None,
    top_score: float = 0.5,
    query: str = "test query",
) -> PipelineResult:
    return PipelineResult(
        parsed=ParsedQuery(original=query, rewritten=query, disaster_type=None),
        retrieval=RetrievalResult(
            hits=hits or [],
            top_score=top_score,
            gated=gated,
            message=message,
        ),
    )


# --- 1. safety scoring -------------------------------------------------------
def test_safety_score_counts_occurrences() -> None:
    """_safety_score must sum (case-insensitive) occurrences of safety phrases.

    The strict inequality between imperative-heavy and topical-only chunks is
    the contract _reorder_safety_first relies on. Locking the equality
    between upper/lower case also protects against a future "tidy up the
    .lower() call" refactor.
    """
    print("\n[1] _safety_score basics")

    print(f"    empty -> {_safety_score('')}")
    assert _safety_score("") == 0

    bare_topical = _safety_score("flood waters are rising in the valley")
    print(f"    bare topical ('flood waters ...') -> {bare_topical}")
    assert bare_topical == 0, (
        "Pure hazard-topic vocabulary must not score; _SAFETY_KEYWORDS is "
        "for imperatives/warnings, not topic terms."
    )

    multi = _safety_score("Do not drive through flood water. Do not approach.")
    print(f"    'Do not drive ... Do not approach.' -> {multi}")
    assert multi >= 2, (
        f"Expected at least 2 hits (two 'do not' + one 'do not drive'), got {multi}"
    )

    upper = _safety_score("DO NOT EVACUATE")
    lower = _safety_score("do not evacuate")
    print(f"    case-insensitive: upper={upper} lower={lower}")
    assert upper == lower and upper > 0, (
        "_safety_score must be case-insensitive (it lower-cases internally)."
    )

    heavy = _safety_score(
        "Evacuate immediately. Do not return. Stay away from windows."
    )
    light = _safety_score("Local evacuation information is available online.")
    print(f"    imperative-heavy={heavy}  topical-only={light}")
    assert heavy > light, (
        f"Imperative-heavy chunk ({heavy}) must outscore topical-only ({light}); "
        "this is the inequality _reorder_safety_first leans on."
    )


# --- 2. safety reordering ----------------------------------------------------
def test_reorder_safety_first_is_stable_and_score_descending() -> None:
    """Stable-sort by (-safety, original_rank). Ties keep cross-encoder order."""
    print("\n[2] _reorder_safety_first stability + score order")

    # Hand-crafted texts whose _safety_score values are [0, 3, 1, 1] in
    # input order. The single-keyword texts (2, 3) deliberately use
    # non-overlapping phrases so neither collides with another keyword --
    # e.g. "stay away from windows" would double-count on both "stay away"
    # and "away from windows". Tests 2 and 3 tying at 1 is the whole point
    # -- it lets us exercise stable-sort tie-breaking.
    texts = [
        # 0 -- pure topical, no imperatives.
        "Flood watches indicate that flooding is possible in your area.",
        # 1 -- three non-overlapping imperative keywords.
        "Evacuate immediately. Never return.",
        # 2 -- one imperative phrase ('shut off').
        "Always shut off the gas valve.",
        # 3 -- one imperative phrase ('crawl'), different keyword.
        "Crawl low under heavy smoke.",
    ]
    scores = [_safety_score(t) for t in texts]
    print(f"    raw scores by input order: {scores}")
    assert scores == [0, 3, 1, 1], (
        f"Fixture scores drifted to {scores}. Adjust the texts so they remain "
        "[0, 3, 1, 1] -- the rest of this test reads that pattern."
    )

    hits = [_hit(t, chunk_id=i) for i, t in enumerate(texts)]
    reordered = _reorder_safety_first(hits)
    order = [h.chunk_id for h in reordered]
    print(f"    reordered chunk_ids: {order}")
    assert order == [1, 2, 3, 0], (
        f"Expected order [1, 2, 3, 0] (3-score first, then 1-score ties in "
        f"original order via stable sort, then 0-score last); got {order}."
    )

    # All-zero edge case: reorder is a no-op on cid order.
    flat = [_hit("plain prose nothing imperative here", chunk_id=i) for i in range(3)]
    flat_reordered = _reorder_safety_first(flat)
    flat_order = [h.chunk_id for h in flat_reordered]
    print(f"    all-zero scores -> order unchanged: {flat_order}")
    assert flat_order == [0, 1, 2]

    # Empty edge case.
    empty = _reorder_safety_first([])
    print(f"    empty input -> {empty}")
    assert empty == []


# --- 3. citation marker detection -------------------------------------------
def test_has_citation_markers() -> None:
    """_CITATION_RE matches any [n] regardless of in-range validity.

    Per the module docstring: false negatives (missing a real marker, then
    triggering a useless re-prompt) are more harmful than false positives
    (letting a stray [42] through). Lock that trade-off here.
    """
    print("\n[3] _has_citation_markers")

    cases: list[tuple[str, bool]] = [
        ("answer [1]", True),
        ("answer [42]", True),       # out-of-range numbers still count as markers
        ("[1][2][3] stacked", True),
        ("answer", False),
        ("answer [a]", False),       # non-digit
        ("answer [1.5]", False),     # decimal -- not a marker we'd emit
        ("answer [ 1 ]", False),     # whitespace breaks the marker
        ("", False),
    ]
    for text, expected in cases:
        got = _has_citation_markers(text)
        mark = "OK  " if got == expected else "MISS"
        print(f"    [{mark}] {text!r:<28} -> {got} (expected {expected})")
        assert got == expected, (
            f"_has_citation_markers({text!r}) returned {got}, expected {expected}. "
            f"Regex is {_CITATION_RE.pattern!r}."
        )


# --- 4. user-message assembly -----------------------------------------------
def test_build_user_message_format() -> None:
    """_build_user_message must number context blocks 1..N in input order.

    The LLM's [n] markers index into this numbering, so the format is a hard
    contract. We don't enforce a specific spacing scheme, only the presence
    and ordering of the load-bearing tokens.
    """
    print("\n[4] _build_user_message format")
    hits = [
        Hit(
            chunk_id=11,
            text="If shaking starts, drop, cover, and hold on.",
            source="ready_gov_earthquakes.txt",
            page=3,
            disaster_type="earthquake",
            score=0.95,
        ),
        Hit(
            chunk_id=22,
            text="Have an emergency kit prepared in advance.",
            source="red_cross_prepare.txt",
            page=1,
            disaster_type="general",
            score=0.81,
        ),
    ]
    msg = _build_user_message("what do I do if shaking starts", hits)
    print(f"    message length: {len(msg)} chars")
    print("    --- excerpt ---")
    for line in msg.splitlines()[:8]:
        print(f"    {line}")
    print("    ---------------")

    assert msg.startswith("Context (most safety-critical first):"), (
        "Header must lead the user message so the LLM understands the slot "
        "ordering contract."
    )
    # 1-indexed numbering, in input order.
    assert "\n[1] source=ready_gov_earthquakes.txt page=3 disaster=earthquake" in msg, (
        "Slot [1] header must match the first hit's metadata exactly."
    )
    assert "\n[2] source=red_cross_prepare.txt page=1 disaster=general" in msg, (
        "Slot [2] header must match the second hit's metadata exactly."
    )
    # Both chunk texts surface verbatim (otherwise the LLM cites a chunk it can't read).
    assert "drop, cover, and hold on" in msg
    assert "emergency kit prepared in advance" in msg
    # [1] must precede [2] -- slot order matters.
    assert msg.index("\n[1] source=") < msg.index("\n[2] source="), (
        "Slot [1] header must appear before slot [2] -- input order is the contract."
    )
    # The trailing question + instruction lines.
    assert "Question: what do I do if shaking starts" in msg
    assert "Answer with [n] citations" in msg


# --- 5. gate-honored-verbatim (no LLM call) ---------------------------------
def test_generate_respects_gate_without_calling_llm() -> None:
    """When `retrieval.gated=True`, generate() must skip the LLM entirely.

    We prove this by monkeypatching `_get_llm` to a function that raises.
    If generate() so much as touches the LLM accessor on the gated path,
    the raise propagates and this test fails loudly.
    """
    print("\n[5] generate() honors the gate without touching the LLM")

    original = generate_module._get_llm

    def _explode(*_a, **_kw):
        raise AssertionError("LLM must not be loaded on the gated path")

    generate_module._get_llm = _explode  # type: ignore[assignment]
    try:
        # Explicit canned message: surfaced verbatim.
        out = generate(_pipeline_result(gated=True, message="CANNED"))
        print(f"    explicit message: answer={out.answer!r}  gated={out.gated}")
        assert out.answer == "CANNED"
        assert out.citations == []
        assert out.gated is True
        assert out.top_score == 0.5  # echoes retrieval.top_score

        # None message: falls back to LOW_CONFIDENCE_MESSAGE via `or`.
        out2 = generate(_pipeline_result(gated=True, message=None, top_score=0.0))
        print(f"    None message:     answer={out2.answer!r}  gated={out2.gated}")
        assert out2.answer == LOW_CONFIDENCE_MESSAGE, (
            "When retrieval.message is None, generate() must fall back to "
            f"LOW_CONFIDENCE_MESSAGE; got {out2.answer!r}."
        )
        assert out2.gated is True
        assert out2.citations == []
    finally:
        generate_module._get_llm = original  # type: ignore[assignment]


# --- 6. graceful degradation on LLM exception -------------------------------
def test_generate_falls_back_on_llm_exception() -> None:
    """A `_call_llm` exception must degrade to a gated low-confidence reply.

    The retriever's CONF_THRESHOLD has already vouched for these chunks, so
    a runtime crash is *not* "wrong disaster advice" territory -- we just
    refuse to answer rather than crashing the demo.
    """
    print("\n[6] generate() degrades gracefully on _call_llm exception")

    original = generate_module._call_llm

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated llama-cpp runtime crash")

    generate_module._call_llm = _boom  # type: ignore[assignment]
    try:
        result = _pipeline_result(
            gated=False,
            hits=[_hit("Evacuate immediately. Do not return.", chunk_id=1, score=0.9)],
            top_score=0.9,
        )
        out = generate(result)
        print(f"    answer={out.answer!r}  gated={out.gated}  citations={len(out.citations)}")
        assert out.answer == LOW_CONFIDENCE_MESSAGE, (
            f"On LLM exception, generate() must return LOW_CONFIDENCE_MESSAGE; "
            f"got {out.answer!r}."
        )
        assert out.gated is True, "Fallback must be gated so the UI surfaces the canned reply."
        assert out.citations == []
        assert out.top_score == 0.9  # original retrieval top_score is preserved
    finally:
        generate_module._call_llm = original  # type: ignore[assignment]


# --- 7. citation retry path -------------------------------------------------
def test_citation_retry_path_via_monkeypatch() -> None:
    """First answer without [n] -> retry. Retry without [n] -> soft-warning suffix.

    Drives both branches without depending on the LLM actually misbehaving.
    The counters confirm each step fires exactly once -- a regression that
    skipped the retry, or one that called it twice, would fail here.
    """
    print("\n[7] citation retry path (forced via monkeypatch)")

    original_call = generate_module._call_llm
    original_retry = generate_module._call_llm_retry_with_citation_demand
    result = _pipeline_result(
        gated=False,
        hits=[_hit("Do not drive through flood water.", chunk_id=2, score=0.88)],
        top_score=0.88,
    )

    # Scenario A: first answer unmarked, retry produces a marked answer.
    counters_a = {"call": 0, "retry": 0}

    def _call_unmarked(_q, _h):
        counters_a["call"] += 1
        return "answer with no markers"

    def _retry_marked(_q, _h, _prior):
        counters_a["retry"] += 1
        return "retried answer with [1] citation"

    generate_module._call_llm = _call_unmarked  # type: ignore[assignment]
    generate_module._call_llm_retry_with_citation_demand = _retry_marked  # type: ignore[assignment]
    try:
        out = generate(result)
        print(f"    A: call={counters_a['call']} retry={counters_a['retry']} "
              f"gated={out.gated} answer={out.answer!r}")
        assert counters_a == {"call": 1, "retry": 1}, (
            f"Expected one _call_llm and one retry; got {counters_a}."
        )
        assert out.answer == "retried answer with [1] citation"
        assert out.gated is False
        assert len(out.citations) == 1
    finally:
        generate_module._call_llm = original_call  # type: ignore[assignment]
        generate_module._call_llm_retry_with_citation_demand = original_retry  # type: ignore[assignment]

    # Scenario B: both first and retry produce unmarked answers -> soft warning.
    counters_b = {"call": 0, "retry": 0}

    def _call_unmarked_b(_q, _h):
        counters_b["call"] += 1
        return "still no markers"

    def _retry_unmarked(_q, _h, _prior):
        counters_b["retry"] += 1
        return "still none after retry"

    generate_module._call_llm = _call_unmarked_b  # type: ignore[assignment]
    generate_module._call_llm_retry_with_citation_demand = _retry_unmarked  # type: ignore[assignment]
    try:
        out = generate(result)
        print(f"    B: call={counters_b['call']} retry={counters_b['retry']} "
              f"gated={out.gated} answer={out.answer!r}")
        assert counters_b == {"call": 1, "retry": 1}
        assert out.answer.endswith("[warning: model produced no citation markers]"), (
            "When retry also fails, the answer must be suffixed with the soft "
            f"warning; got {out.answer!r}."
        )
        assert out.gated is False, (
            "A citation-formatting miss is NOT a gate condition by design -- "
            "the chunks already passed CONF_THRESHOLD."
        )
        assert len(out.citations) == 1, (
            "Citations list must still be populated on the soft-warning path."
        )
    finally:
        generate_module._call_llm = original_call  # type: ignore[assignment]
        generate_module._call_llm_retry_with_citation_demand = original_retry  # type: ignore[assignment]


# --- 8. canned-phrase strip from contaminated cited answers -----------------
def test_canned_phrase_stripped_from_cited_answer_via_monkeypatch() -> None:
    """A cited answer that also contains LOW_CONFIDENCE_MESSAGE must have the phrase stripped.

    Fixes a real Qwen behavior observed during the --with-llm run: when the
    context partially covers a question, the model sometimes emits BOTH a
    cited answer AND the canned no-answer sentence as a hedge. The retriever
    gate already passed at this point, so the canned phrase is a
    contradiction. We strip it only when the answer ALSO contains [n]
    markers; otherwise the answer might legitimately be the canned reply
    (rule 2a) or the soft-warning suffix from the retry path, and the strip
    must be a no-op there.
    """
    print("\n[8] canned-phrase strip from contaminated cited answers")

    original_call = generate_module._call_llm
    result = _pipeline_result(
        gated=False,
        hits=[
            _hit("Do not drink contaminated water.", chunk_id=10, score=0.91),
            _hit("Boil water for one minute before drinking.", chunk_id=11, score=0.83),
        ],
        top_score=0.91,
    )

    # Scenario A: contaminated cited answer -- canned phrase must be stripped.
    contaminated = f"Do not drink contaminated water. [1][2]  {LOW_CONFIDENCE_MESSAGE}"
    generate_module._call_llm = lambda *_a, **_kw: contaminated  # type: ignore[assignment]
    try:
        out = generate(result)
        print(f"    A (contaminated): answer={out.answer!r}")
        assert LOW_CONFIDENCE_MESSAGE not in out.answer, (
            f"Canned phrase must be stripped from a cited answer; got {out.answer!r}."
        )
        assert "[1]" in out.answer and "[2]" in out.answer, (
            "Strip must preserve [n] citation markers."
        )
        assert "Do not drink contaminated water." in out.answer, (
            "Strip must preserve the substantive answer text."
        )
        assert out.gated is False, "A stripped cited answer is still a real answer, not gated."
        assert len(out.citations) == 2
    finally:
        generate_module._call_llm = original_call  # type: ignore[assignment]

    # Scenario B: clean cited answer -- strip is a no-op.
    clean = "Boil water for one minute before drinking. [1]"
    generate_module._call_llm = lambda *_a, **_kw: clean  # type: ignore[assignment]
    try:
        out = generate(result)
        print(f"    B (clean):        answer={out.answer!r}")
        assert out.answer == clean, (
            f"Strip must not modify an uncontaminated cited answer; got {out.answer!r}."
        )
        assert out.gated is False
    finally:
        generate_module._call_llm = original_call  # type: ignore[assignment]

    # Scenario C: LLM returns the canned phrase standalone (no citations).
    # The retry path will fire (no [n] markers), so we patch the retry too --
    # and verify the strip leaves the canned phrase alone since the final
    # text still has no markers.
    original_retry = generate_module._call_llm_retry_with_citation_demand
    generate_module._call_llm = lambda *_a, **_kw: LOW_CONFIDENCE_MESSAGE  # type: ignore[assignment]
    generate_module._call_llm_retry_with_citation_demand = (  # type: ignore[assignment]
        lambda *_a, **_kw: LOW_CONFIDENCE_MESSAGE
    )
    try:
        out = generate(result)
        print(f"    C (canned alone): answer={out.answer!r}")
        # Retry path will append the soft warning since no markers ever appeared.
        assert LOW_CONFIDENCE_MESSAGE in out.answer, (
            "Strip must NOT remove the canned phrase when the answer has no [n] markers "
            "-- in that branch the phrase IS the answer (rule 2a) or the seed for the "
            f"soft-warning suffix. Got {out.answer!r}."
        )
        assert out.answer.endswith("[warning: model produced no citation markers]"), (
            "Marker-less canned answer should pick up the soft-warning suffix from the "
            f"retry path. Got {out.answer!r}."
        )
        assert out.gated is False
    finally:
        generate_module._call_llm = original_call  # type: ignore[assignment]
        generate_module._call_llm_retry_with_citation_demand = original_retry  # type: ignore[assignment]


# --- 9. end-to-end (LLM-backed) ---------------------------------------------
# Fixtures share a list with the LLM-backed tests so the warmup run amortizes
# the GGUF load (the same trick test_query.py uses). Queries are chosen to
# exercise distinct corpus regions without overlapping.
_E2E_IN_CORPUS_QUERIES = [
    "what should I do during an earthquake",
    "how do I prepare a go bag",
    "is the water safe to drink after a flood",
]
_E2E_OFF_TOPIC_QUERY = "what is the airspeed velocity of an unladen swallow"
_E2E_SAFETY_LEAD_QUERY = "my house is on fire what do I do"


def test_end_to_end_answer_returns_citations() -> None:
    """In-corpus queries must come back ungated with at least one [n] marker."""
    print("\n[9] end-to-end answer() on in-corpus queries")
    for q in _E2E_IN_CORPUS_QUERIES:
        out = answer(q)
        n_chars = len(out.answer)
        head = out.answer[:120].replace("\n", " ")
        print(f"    {q!r}")
        print(f"      gated={out.gated}  citations={len(out.citations)}  chars={n_chars}")
        print(f"      head: {head!r}")
        assert not out.gated, (
            f"In-corpus query {q!r} unexpectedly gated. "
            "Either CONF_THRESHOLD drifted, or the corpus lost coverage of this topic."
        )
        assert _has_citation_markers(out.answer), (
            f"Answer to {q!r} has no [n] markers even after the retry. "
            "Check the system prompt and the retry path."
        )
        assert out.citations, "Ungated answer must carry its source chunks for the UI."
        # Soft sanity check on length budget (MAX_TOKENS=384 -> roughly ~1500 chars).
        if n_chars > 2400:
            print(f"      WARN: answer is unusually long ({n_chars} chars); "
                  "MAX_TOKENS budget may be drifting.")


def test_end_to_end_off_topic_query_gates() -> None:
    """Off-corpus question must round-trip to the canned low-confidence reply."""
    print("\n[10] end-to-end answer() on an off-topic query")
    out = answer(_E2E_OFF_TOPIC_QUERY)
    print(f"    query: {_E2E_OFF_TOPIC_QUERY!r}")
    print(f"    gated={out.gated}  citations={len(out.citations)}  answer={out.answer!r}")
    assert out.gated is True, (
        "An off-corpus trivia query must gate. If it didn't, CONF_THRESHOLD "
        "or the corpus has drifted -- this is the single most important "
        "end-to-end test in the suite."
    )
    assert out.answer in (LOW_CONFIDENCE_MESSAGE, EMPTY_FILTER_MESSAGE), (
        f"Gated answer must be one of the canned messages; got {out.answer!r}."
    )
    assert out.citations == []


def test_end_to_end_safety_leads_when_applicable() -> None:
    """Imperative-heavy queries should bring safety content to slot [1].

    The slot-1 safety expectation is corpus-dependent (a future re-ingest
    could legitimately shuffle which chunks rank top), so we WARN rather
    than hard-fail. The hard assertion is just that the LLM cited *some*
    chunk -- the prompt requires it.
    """
    print("\n[11] end-to-end safety-first leading (soft)")
    out = answer(_E2E_SAFETY_LEAD_QUERY)
    print(f"    query: {_E2E_SAFETY_LEAD_QUERY!r}")
    print(f"    gated={out.gated}  citations={len(out.citations)}")
    if out.gated:
        print("    WARN: query gated unexpectedly; corpus may lack home-fire coverage")
        return

    assert _has_citation_markers(out.answer), (
        "Safety-prompt answers still must carry [n] markers."
    )
    top_score = _safety_score(out.citations[0].text)
    print(f"    slot [1] safety_score: {top_score}  source={out.citations[0].source}")
    if top_score == 0:
        print("    WARN: slot [1] chunk has zero safety_score -- "
              "_reorder_safety_first found no imperative chunks among the top 4.")


def test_end_to_end_determinism() -> None:
    """temperature=0 should produce identical answers across two calls. Soft."""
    print("\n[12] end-to-end determinism (soft)")
    q = _E2E_IN_CORPUS_QUERIES[0]
    a = answer(q)
    b = answer(q)
    same = a.answer == b.answer
    print(f"    same? {same}")
    if not same:
        # Treat as a soft signal -- llama-cpp non-determinism on Apple
        # Silicon does occasionally bite; test_query.py is similarly lenient.
        print(f"    WARN: answers differ across two calls.")
        print(f"      first:  {a.answer[:160]!r}")
        print(f"      second: {b.answer[:160]!r}")


# --- runner ------------------------------------------------------------------
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Inspection-style tests for src.generate.")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also run end-to-end tests that load the 4.7 GB GGUF (~1-2 min).",
    )
    args = parser.parse_args(argv)

    # Pure-unit pass: no heavy loads.
    test_safety_score_counts_occurrences()
    test_reorder_safety_first_is_stable_and_score_descending()
    test_has_citation_markers()
    test_build_user_message_format()
    test_generate_respects_gate_without_calling_llm()
    test_generate_falls_back_on_llm_exception()
    test_citation_retry_path_via_monkeypatch()
    test_canned_phrase_stripped_from_cited_answer_via_monkeypatch()

    if args.with_llm:
        print("\nLoading LLM + indexes for end-to-end tests "
              "(first call -- expect a few seconds)...")
        # Warmup so per-fixture timing is just inference + retrieval.
        _ = answer("warmup")
        test_end_to_end_answer_returns_citations()
        test_end_to_end_off_topic_query_gates()
        test_end_to_end_safety_leads_when_applicable()
        test_end_to_end_determinism()

    print("\nAll hard assertions passed. Review WARN lines above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
