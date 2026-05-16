"""Pass 1 chunking sanity checks.

Run from the project root:

    python -m tests.test_chunking

These are inspection-style tests, not pytest. Each check prints what it sees
and raises AssertionError on a hard failure. Soft issues are printed as
"WARN" so you can eyeball them.

What this verifies (without needing the retriever):
  1. Token-length distribution looks sane (cluster near CHUNK_SIZE).
  2. Random chunk boundaries are coherent (no mid-word splits, no leftover
     soft hyphens / ligatures).
  3. Critical disaster phrases survive intact inside at least one chunk.
  4. Metadata tagging (disaster_type) is producing variety, not all
     defaults.
  5. Every source PDF contributed at least one chunk.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from pathlib import Path

from server.src.ingest import _READY_GOV_TYPE_MAP, _tokenize  # reuse same tokenizer BM25 uses

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "index" / "chunks.json"
RAW_DIR = ROOT / "data" / "raw"
READY_GOV_DIR = ROOT / "data" / "processed" / "ready_gov"
RED_CROSS_DIR = ROOT / "data" / "processed" / "red_cross"
WA_EMD_DIR = ROOT / "data" / "processed" / "wa_emd"

# Bounds for the length-distribution check. ingest.CHUNK_SIZE is 300, overlap
# 50. We allow a wide envelope because page boundaries produce short tail
# chunks legitimately.
MIN_REASONABLE_TOKENS = 30
MAX_REASONABLE_TOKENS = 450

# Phrases the chatbot must be able to surface verbatim. If a phrase is split
# across two chunks, neither will retrieve cleanly — that's a chunker bug,
# not a retrieval bug.
CRITICAL_PHRASES = [
    "drop, cover",
    "hold on",
    "two weeks",
    "2 weeks",
    "go bag",
    "shelter in place",
    "evacuation route",
    "emergency alert",
]


def load_chunks() -> list[dict]:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        return json.load(f)


# --- 1. length distribution --------------------------------------------------
def test_length_distribution(chunks: list[dict]) -> None:
    """Token lengths should cluster near CHUNK_SIZE (300) with a short-chunk tail."""
    lengths = [len(_tokenize(c["text"])) for c in chunks]
    print("\n[1] Length distribution")
    print(f"    n={len(lengths)}  min={min(lengths)}  max={max(lengths)}"
          f"  mean={statistics.mean(lengths):.1f}  median={statistics.median(lengths)}")

    # crude histogram
    buckets = [0, 50, 100, 200, 300, 400, 500, 10_000]
    counts = [0] * (len(buckets) - 1)
    for n in lengths:
        for i in range(len(buckets) - 1):
            if buckets[i] <= n < buckets[i + 1]:
                counts[i] += 1
                break
    for i, c in enumerate(counts):
        print(f"    {buckets[i]:>4}-{buckets[i+1]:<5} {'#' * c} ({c})")

    too_small = [n for n in lengths if n < MIN_REASONABLE_TOKENS]
    too_big = [n for n in lengths if n > MAX_REASONABLE_TOKENS]
    if too_small:
        print(f"    WARN: {len(too_small)} chunk(s) below {MIN_REASONABLE_TOKENS} tokens: {too_small}")
    if too_big:
        print(f"    WARN: {len(too_big)} chunk(s) above {MAX_REASONABLE_TOKENS} tokens: {too_big}")

    # Hard failure: more than 25% of chunks are pathological.
    pathological = len(too_small) + len(too_big)
    assert pathological / len(lengths) < 0.25, (
        f"Too many out-of-bound chunks: {pathological}/{len(lengths)}"
    )


# --- 2. boundary spot-check --------------------------------------------------
def test_boundary_spotcheck(chunks: list[dict], sample_n: int = 10) -> None:
    """Print N random chunks; assert no leftover soft hyphens / ligatures."""
    print(f"\n[2] Boundary spot-check ({sample_n} random chunks)")
    rng = random.Random(42)  # deterministic so repeated runs print the same chunks
    picks = rng.sample(chunks, min(sample_n, len(chunks)))

    bad_chars = {"­": "soft hyphen", "ﬁ": "fi ligature", "ﬂ": "fl ligature"}
    offenders: list[tuple[int, str]] = []

    for c in picks:
        head = c["text"][:80].replace("\n", " ")
        tail = c["text"][-60:].replace("\n", " ")
        print(f"    id={c['id']:>3}  src={c['source'][:35]:<35}  p.{c['page']}")
        print(f"      head: {head!r}")
        print(f"      tail: {tail!r}")
        for ch, label in bad_chars.items():
            if ch in c["text"]:
                offenders.append((c["id"], label))

    if offenders:
        print(f"    WARN: leftover artifacts: {offenders}")
    assert not offenders, f"Cleaning missed artifacts in chunks: {offenders}"


# --- 3. critical phrases -----------------------------------------------------
def test_critical_phrases_survive(chunks: list[dict]) -> None:
    """Each critical phrase should appear intact inside at least one chunk."""
    print("\n[3] Critical-phrase survival")
    missing: list[str] = []
    for phrase in CRITICAL_PHRASES:
        hits = [c["id"] for c in chunks if phrase.lower() in c["text"].lower()]
        status = f"{len(hits)} hit(s)" if hits else "MISSING"
        print(f"    {phrase!r:<25}  -> {status}  ids={hits[:5]}")
        if not hits:
            missing.append(phrase)

    # Soft assertion: don't hard-fail if corpus genuinely doesn't cover a
    # phrase (e.g., no "shelter in place" content yet). Just print loudly.
    if missing:
        print(f"    WARN: corpus has no chunk containing: {missing}")
        print("          either add source docs, or remove from CRITICAL_PHRASES")


# --- 4. metadata distribution ------------------------------------------------
def test_metadata_distribution(chunks: list[dict]) -> None:
    """disaster_type should show variety, not collapse to all 'general'."""
    print("\n[4] Metadata distribution")
    by_type = Counter(c["disaster_type"] for c in chunks)
    print(f"    by_disaster_type: {dict(by_type)}")

    if set(by_type) == {"general"}:
        print("    WARN: every chunk is disaster_type='general' — "
              "_disaster_type_for rules aren't matching this corpus")


# --- 5. source coverage ------------------------------------------------------
def test_source_coverage(chunks: list[dict]) -> None:
    """Every PDF in data/raw/ (recursive) should produce at least one chunk."""
    print("\n[5] Source coverage (PDFs)")
    by_source = Counter(c["source"] for c in chunks)
    for src, n in sorted(by_source.items()):
        print(f"    {src:<60} {n} chunks")

    raw_pdfs = {p.name for p in RAW_DIR.rglob("*.pdf")}
    chunked = set(by_source)
    missing = raw_pdfs - chunked
    if missing:
        print(f"    WARN: PDFs with zero chunks (likely scanned/image PDFs): {missing}")
    assert not missing, f"Some PDFs produced no chunks: {missing}"


# --- 6. ready_gov coverage ---------------------------------------------------
def test_ready_gov_coverage(chunks: list[dict]) -> None:
    """Every cleaned .txt in data/processed/ready_gov/ should produce a chunk."""
    print("\n[6] Source coverage (Ready.gov text)")
    by_source = Counter(c["source"] for c in chunks if c["source"].endswith(".txt"))
    for src, n in sorted(by_source.items()):
        print(f"    {src:<60} {n} chunks")

    txt_files = {p.name for p in READY_GOV_DIR.glob("*.txt")}
    missing = txt_files - set(by_source)
    if missing:
        print(f"    WARN: cleaned text files with zero chunks: {missing}")
    assert not missing, f"Some Ready.gov files produced no chunks: {missing}"


# --- 6b. red_cross coverage --------------------------------------------------
def test_red_cross_coverage(chunks: list[dict]) -> None:
    """Every cleaned .txt in data/processed/red_cross/ should produce a chunk."""
    print("\n[6b] Source coverage (Red Cross text)")
    by_source = Counter(
        c["source"] for c in chunks if c["source"].startswith("red_cross_")
    )
    for src, n in sorted(by_source.items()):
        print(f"    {src:<60} {n} chunks")

    txt_files = {p.name for p in RED_CROSS_DIR.glob("*.txt")}
    missing = txt_files - set(by_source)
    if missing:
        print(f"    WARN: cleaned text files with zero chunks: {missing}")
    assert not missing, f"Some Red Cross files produced no chunks: {missing}"


# --- 6c. wa_emd coverage -----------------------------------------------------
def test_wa_emd_coverage(chunks: list[dict]) -> None:
    """Every cleaned .txt in data/processed/wa_emd/ should produce a chunk."""
    print("\n[6c] Source coverage (WA EMD text)")
    by_source = Counter(
        c["source"] for c in chunks if c["source"].startswith("wa_emd_")
    )
    for src, n in sorted(by_source.items()):
        print(f"    {src:<60} {n} chunks")

    txt_files = {p.name for p in WA_EMD_DIR.glob("*.txt")}
    missing = txt_files - set(by_source)
    if missing:
        print(f"    WARN: cleaned text files with zero chunks: {missing}")
    assert not missing, f"Some WA EMD files produced no chunks: {missing}"


# --- 7. disaster_type richness ----------------------------------------------
def test_disaster_type_richness(chunks: list[dict]) -> None:
    """We have ~24 hazards in the corpus — assert real variety, not just earthquake+general."""
    print("\n[7] Disaster type richness")
    by_type = Counter(c["disaster_type"] for c in chunks)
    print(f"    distinct types: {len(by_type)}")
    for dtype, n in by_type.most_common():
        print(f"    {dtype:<25} {n}")

    expected_types = set(_READY_GOV_TYPE_MAP.values())
    seen_types = set(by_type)
    missing_expected = expected_types - seen_types
    if missing_expected:
        print(f"    WARN: types declared in _READY_GOV_TYPE_MAP but absent from chunks: "
              f"{sorted(missing_expected)}")

    assert len(by_type) >= 5, (
        f"Expected at least 5 distinct disaster_types after Ready.gov ingest, "
        f"got {len(by_type)}: {dict(by_type)}"
    )


# --- runner ------------------------------------------------------------------
def main() -> None:
    if not CHUNKS_PATH.exists():
        raise SystemExit(f"Missing {CHUNKS_PATH}. Run `python -m src.ingest` first.")

    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH}")

    test_length_distribution(chunks)
    test_boundary_spotcheck(chunks)
    test_critical_phrases_survive(chunks)
    test_metadata_distribution(chunks)
    test_source_coverage(chunks)
    test_ready_gov_coverage(chunks)
    test_red_cross_coverage(chunks)
    test_wa_emd_coverage(chunks)
    test_disaster_type_richness(chunks)

    print("\nAll hard assertions passed. Review WARN lines above.")


if __name__ == "__main__":
    main()
