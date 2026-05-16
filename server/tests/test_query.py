"""Inspection-style sanity checks for the LLM query parser.

Run from the project root:

    python -m tests.test_query

These tests are not pytest. Each check prints what it sees and raises
AssertionError on a hard failure. Soft mismatches are printed as `WARN` so
you can eyeball borderline cases. The LLM is loaded once and reused across
cases; the full suite should finish in well under a minute on Apple Silicon.

What this verifies:
  1. Output schema: every call returns a ParsedQuery whose `rewritten` is
     non-empty and whose `disaster_type` is None or a value the index
     actually contains.
  2. Disaster tagging accuracy: hard-fail if accuracy on labeled cases drops
     below the (intentionally lenient) bar.
  3. Rewrite quality: print original vs rewritten side-by-side. No oracle,
     no hard assertion -- the operator eyeballs.
  4. Determinism: a query parsed twice must return identical results
     (temperature=0 + fixed seed).
  5. Fallback contract: when the LLM call yields unparseable garbage, the
     parser must still return the original text unchanged with
     disaster_type=None. This is the "never break retrieval" rule.
"""
from __future__ import annotations

from dataclasses import asdict

import server.src.query as query_module
from server.src.query import ParsedQuery, parse_query

# Accuracy bar for the labeled-tag test. 70% is deliberately lenient for v1
# -- we tighten it once we have a feel for Qwen's behavior on this corpus
# and after we add demo-day queries to the fixture set.
MIN_TAG_ACCURACY = 0.70

# (raw_query, expected_disaster_type)
# expected=None means we accept either None or a sensible non-None tag
# (printed as WARN, not hard-failed); use a string to demand exact match.
FIXTURES: list[tuple[str, str | None]] = [
    # Direct hazard mention with typos -- LLM must normalize and tag.
    ("what do i do if a earth quake hit", "earthquake"),
    # Misspelled, multi-word, clear hazard.
    ("how to prepare for a wild fire near my house", "wildfire"),
    # Colloquial / indirect -- the synonym fallback should fire if the LLM
    # is conservative.
    ("the ground is shaking", "earthquake"),
    ("a twister is coming our way", "tornado"),
    # Cross-cutting prep -- should be null. "go bag" appears in every hazard.
    ("what goes in a go bag", None),
    # Off-topic. Must be null.
    ("who won the 2024 world series", None),
    # Specific safety phrase -- BM25-friendly already, but the parser should
    # still tag it.
    ("drop cover and hold on", "earthquake"),
    # Power outage -- canonical hazard distinct from home_fire and storms.
    ("fridge food after power goes out for 2 days", "power_outage"),
    # Hurricane via colloquialism (synonym fallback path).
    ("typhoon shelter advice", "hurricane"),
    # Ambiguous multi-hazard -- accept either earthquake, tsunami, or null.
    ("earthquake and tsunami prep", None),
    # Plain hazard, well-spelled.
    ("flood evacuation route", "flood"),
    # Conversational framing.
    ("im worried about a blizzard tomorrow", "winter_weather"),
]


# --- 1. schema ---------------------------------------------------------------
def test_output_schema(results: list[tuple[str, str | None, ParsedQuery]]) -> None:
    """Every result must satisfy the ParsedQuery contract."""
    print("\n[1] Output schema")
    known = set(query_module._get_known_types())
    bad: list[str] = []
    for raw, _, r in results:
        if not isinstance(r, ParsedQuery):
            bad.append(f"{raw!r}: not a ParsedQuery instance")
            continue
        if not r.rewritten or not isinstance(r.rewritten, str):
            bad.append(f"{raw!r}: empty/non-string rewritten")
        if r.disaster_type is not None and r.disaster_type not in known:
            bad.append(f"{raw!r}: disaster_type={r.disaster_type!r} not in index")
    print(f"    {len(results)} parsed, {len(bad)} schema violations")
    assert not bad, "\n      ".join([""] + bad)


# --- 2. tagging accuracy -----------------------------------------------------
def test_tagging_accuracy(
    results: list[tuple[str, str | None, ParsedQuery]],
) -> None:
    """Hard-fail if accuracy on labeled cases drops below MIN_TAG_ACCURACY."""
    print("\n[2] Disaster tagging accuracy")
    labeled = [(raw, exp, r) for raw, exp, r in results if exp is not None]
    if not labeled:
        print("    (no labeled fixtures)")
        return

    correct = 0
    for raw, exp, r in labeled:
        ok = r.disaster_type == exp
        correct += int(ok)
        mark = "OK  " if ok else "MISS"
        print(f"    [{mark}] {raw!r:<55}  expected={exp!r:<18}  got={r.disaster_type!r}")

    acc = correct / len(labeled)
    print(f"    accuracy: {correct}/{len(labeled)} = {acc:.0%}  (min {MIN_TAG_ACCURACY:.0%})")
    assert acc >= MIN_TAG_ACCURACY, (
        f"Tag accuracy {acc:.0%} below threshold {MIN_TAG_ACCURACY:.0%}. "
        f"Look at the MISS lines above; either fix the prompt/few-shots, "
        f"add a synonym to _SYNONYMS, or relabel the fixture if the expected "
        f"value was wrong."
    )

    # Soft: print null-expected cases so operator can eyeball.
    null_cases = [(raw, r) for raw, exp, r in results if exp is None]
    if null_cases:
        print("\n    null-expected cases (any non-None tag is a soft signal):")
        for raw, r in null_cases:
            mark = "null" if r.disaster_type is None else "WARN"
            print(f"      [{mark}] {raw!r:<55}  got={r.disaster_type!r}")


# --- 3. rewrite quality (soft) ----------------------------------------------
def test_rewrite_quality(
    results: list[tuple[str, str | None, ParsedQuery]],
) -> None:
    """Print original vs rewritten so an operator can eyeball drift."""
    print("\n[3] Rewrite spot-check (soft -- no oracle)")
    for raw, _, r in results:
        marker = "  " if r.rewritten == raw else "->"
        print(f"    {marker} {raw!r}")
        if r.rewritten != raw:
            print(f"         -> rewritten: {r.rewritten!r}")
        if r.disaster_type:
            print(f"         -> tag: {r.disaster_type}")


# --- 4. determinism ----------------------------------------------------------
def test_determinism() -> None:
    """temperature=0 + fixed seed must give byte-identical output across reruns."""
    print("\n[4] Determinism (one query parsed twice)")
    q = "what to do during an earthquake"
    a = parse_query(q)
    b = parse_query(q)
    print(f"    first:  {asdict(a)}")
    print(f"    second: {asdict(b)}")
    assert a == b, (
        "Parser is non-deterministic at temperature=0. Either the seed isn't "
        "being honored, or post-processing reads from mutable state."
    )


# --- 5. fallback contract ----------------------------------------------------
def test_fallback_on_bad_llm(monkeypatch_target: str = "_llm_normalize") -> None:
    """When the LLM helper returns None (parse failure or junk), parse_query
    must still return the original text and disaster_type=None. Retrieval
    cannot be allowed to break because the parser had a bad day."""
    print("\n[5] Fallback contract (forced LLM failure)")
    original = query_module._llm_normalize
    query_module._llm_normalize = lambda text: None  # type: ignore[assignment]
    try:
        r = parse_query("what to do in an earthquake")
        print(f"    forced-failure result: {asdict(r)}")
        assert r.original == "what to do in an earthquake"
        assert r.rewritten == "what to do in an earthquake"
        assert r.disaster_type is None
    finally:
        query_module._llm_normalize = original  # type: ignore[assignment]


# --- runner ------------------------------------------------------------------
def main() -> None:
    print(f"Loading LLM (first call -- expect a few seconds)...")
    # Warm the model once so per-fixture latency is just inference.
    _ = parse_query("warmup")

    results: list[tuple[str, str | None, ParsedQuery]] = []
    for raw, expected in FIXTURES:
        r = parse_query(raw)
        results.append((raw, expected, r))

    test_output_schema(results)
    test_tagging_accuracy(results)
    test_rewrite_quality(results)
    test_determinism()
    test_fallback_on_bad_llm()

    print("\nAll hard assertions passed. Review WARN / MISS lines above.")


if __name__ == "__main__":
    main()
