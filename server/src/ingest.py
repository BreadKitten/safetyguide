"""Build the local RAG index from PDFs in `data/raw/`.

Run from the project root:
    python -m src.ingest

Outputs:
    index/faiss.index   - dense vectors (bge-small, 384-d, cosine via IP)
    index/bm25.pkl      - BM25Okapi over tokenized chunks
    index/chunks.json   - chunk text + metadata, indices align with FAISS rows
"""
from __future__ import annotations

import json
import pickle
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_READY_GOV_DIR = ROOT / "data" / "processed" / "ready_gov"
PROCESSED_RED_CROSS_DIR = ROOT / "data" / "processed" / "red_cross"
PROCESSED_WA_EMD_DIR = ROOT / "data" / "processed" / "wa_emd"
MANUAL_PDF_DIR = ROOT / "data" / "processed" / "manual_pdfs"
INDEX_DIR = ROOT / "index"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 30
EMBED_BATCH = 32


# --- text cleaning -----------------------------------------------------------
_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    """Normalize whitespace and strip odd unicode artifacts from PDF extraction."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")  # soft hyphen
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")  # common ligatures
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


# --- metadata tagging --------------------------------------------------------
# Two-stage disaster_type classification. For ready_gov_<slug>.txt files the
# filename slug is authoritative (_READY_GOV_TYPE_MAP). For PDFs we use a
# filename default (_PDF_TYPE_MAP) and let a small set of strong-signal anchor
# phrases (_DISASTER_OVERRIDE_PHRASES) promote individual chunks to a specific
# hazard. A prior content-keyword classifier was removed because single-mention
# substrings ("earthquake" appearing once in a generic prep brochure) caused
# whole brochures to be mislabeled.

# Filename slug -> canonical disaster_type for ready_gov_<slug>.txt files.
# Singular form matches the existing "earthquake" convention. Cross-cutting
# topics (kit/plan/shelter/...) that apply to multiple hazards are mapped to
# "general".
_READY_GOV_TYPE_MAP: dict[str, str] = {
    "earthquakes": "earthquake", "tsunamis": "tsunami", "floods": "flood",
    "wildfires": "wildfire", "hurricanes": "hurricane", "tornadoes": "tornado",
    "volcanoes": "volcano", "landslides": "landslide", "thunderstorms": "thunderstorm",
    "avalanche": "avalanche", "drought": "drought", "extreme_heat": "extreme_heat",
    "winter_weather": "winter_weather", "space_weather": "space_weather",
    "severe_weather": "severe_weather", "pandemic": "pandemic",
    "biohazard": "biohazard", "radiation": "radiation", "explosions": "explosion",
    "household_chemicals": "household_chemicals", "home_fires": "home_fire",
    "power_outages": "power_outage", "mass_gatherings": "mass_gathering",
    "cybersecurity": "cybersecurity",
    "plan": "general", "kit": "general", "shelter": "general",
    "evacuation": "general", "recovering": "general", "home_safety": "general",
}

# Filename slug -> canonical disaster_type for red_cross_<slug>.txt files.
# Mirrors the ready_gov convention: cross-cutting prep content maps to
# "general"; add hazard-specific slugs here as the Red Cross corpus grows.
_RED_CROSS_TYPE_MAP: dict[str, str] = {
    "disaster_preparedness_plan": "general",
    "how_to_prepare_for_emergencies": "general",
    "survival_kit": "general",
}

# Filename slug -> canonical disaster_type for wa_emd_<slug>.txt files.
# WA EMD pages are either hazard-specific (tsunami) or multi-hazard
# policy/programmatic content (hazard mitigation overview + grants), which
# follows the same "general" convention used for cross-cutting prep content
# in the Ready.gov / Red Cross maps.
_WA_EMD_TYPE_MAP: dict[str, str] = {
    "tsunami": "tsunami",
    "hazard_mitigation": "general",
    "hazard_mitigation_grants": "general",
}

# PDF filename -> default disaster_type. Most 2-Weeks-Ready brochures are
# cross-cutting preparedness material that happens to mention earthquakes;
# they default to "general" and only chunks containing strong anchor phrases
# (see _DISASTER_OVERRIDE_PHRASES) get promoted to a specific hazard.
_PDF_TYPE_MAP: dict[str, str] = {
    "2-Weeks-Ready-Community-Brochure-04-Digital.pdf": "general",
    "2-Weeks-Ready-Community-Brochure-Build-Kits.pdf": "general",
    "2-Weeks-Ready-Individual-Family-Brochure-02-Digital-ENGLISH).pdf": "general",
    "When-an-Earthquake-Strikes.pdf": "earthquake",
}

# Anchor phrases strong enough to override the PDF filename default. Keep this
# list narrow — these must be phrases that only appear in content unambiguously
# focused on the named hazard (action verbs, official campaign names, event-
# specific guidance). Single-word mentions like "earthquake" are deliberately
# absent: they were the leak source in the previous content-keyword classifier.
_DISASTER_OVERRIDE_PHRASES: list[tuple[str, tuple[str, ...]]] = [
    ("earthquake", ("drop, cover, and hold", "drop and cover",
                    "during a quake", "during the shaking",
                    "actions to take during a quake",
                    "great washington shakeout")),
]


def _disaster_type_for(source: str, text: str) -> str:
    """Tag a chunk by hazard. Filename is authoritative; strong anchor phrases
    in the chunk text can override the PDF filename default."""
    if source.startswith("ready_gov_") and source.endswith(".txt"):
        slug = source[len("ready_gov_"):-len(".txt")]
        return _READY_GOV_TYPE_MAP.get(slug, "general")
    if source.startswith("red_cross_") and source.endswith(".txt"):
        slug = source[len("red_cross_"):-len(".txt")]
        return _RED_CROSS_TYPE_MAP.get(slug, "general")
    if source.startswith("wa_emd_") and source.endswith(".txt"):
        slug = source[len("wa_emd_"):-len(".txt")]
        return _WA_EMD_TYPE_MAP.get(slug, "general")
    base = _PDF_TYPE_MAP.get(source, "general")
    lower = text.lower()
    for dtype, phrases in _DISASTER_OVERRIDE_PHRASES:
        if any(p in lower for p in phrases):
            return dtype
    return base


# --- low-content filter ------------------------------------------------------
# Drop chunks that are mostly boilerplate / link stubs. Threshold is in
# meaningful tokens (alphanumeric word runs, lowercased), counted with the
# same _tokenize used by BM25. 40 was picked so link stubs like "Additional
# Resources / Preparedness is a journey / Learn more at mil.wa.gov..."
# (~15-25 tokens) drop out while legitimate short paragraphs (>50 tokens)
# survive.
_MIN_MEANINGFUL_TOKENS = 40
_MIN_SECTION_TOKENS = 80


def _is_low_content(text: str) -> bool:
    return len(_tokenize(text)) < _MIN_MEANINGFUL_TOKENS


# --- BM25 tokenization -------------------------------------------------------
_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# --- sectioning and deduplication -------------------------------------------
_PARA_RE = re.compile(r"\n\s*\n")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+\S")
_TRAILING_SENTENCE_PUNCT_RE = re.compile(r"[.!]$")


def _norm_for_dedupe(text: str) -> str:
    """Collapse text to a lowercase token stream for conservative dedupe tests."""
    return " ".join(_tokenize(text))


def _is_probable_heading(block: str) -> bool:
    """Return True for standalone headings in cleaned web/PDF text.

    The processed corpus has real headings both as Markdown (`# Floods`) and as
    plain standalone lines (`Before an Incident`). This intentionally favors
    recall, then `_merge_short_sections` repairs over-splitting from list-like
    short lines.
    """
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) != 1:
        return False

    line = lines[0]
    if _MARKDOWN_HEADING_RE.match(line):
        return True
    if line.startswith(("-", "*", "•")):
        return False

    words = _tokenize(line)
    if not words or len(words) > 10:
        return False
    if _TRAILING_SENTENCE_PUNCT_RE.search(line):
        return False
    if line.endswith((":", "?")):
        return True
    if _NUMBERED_HEADING_RE.match(line) and len(words) <= 6:
        return True

    alpha_words = re.findall(r"[A-Za-z][A-Za-z'-]*", line)
    if not alpha_words:
        return False
    titled = sum(1 for word in alpha_words if word[0].isupper() or word.isupper())
    return titled / len(alpha_words) >= 0.5


def _dedupe_redundant_paragraphs(text: str) -> str:
    """Drop redundant extraction echoes before chunking.

    Ready.gov pages often contain a combined card sentence followed by the same
    sentence as a standalone paragraph. We remove exact paragraph repeats and
    standalone paragraphs already contained in a longer kept paragraph. Very
    short repeats are preserved because they can be meaningful labels in lists.
    """
    kept: list[str] = []
    seen: set[str] = set()
    seen_long: list[str] = []

    for paragraph in _PARA_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        norm = _norm_for_dedupe(paragraph)
        if not norm:
            continue

        token_count = len(norm.split())
        is_heading = _is_probable_heading(paragraph)
        is_exact_repeat = token_count >= 8 and norm in seen
        is_contained_repeat = (
            token_count >= 8
            and not is_heading
            and any(norm in longer for longer in seen_long)
        )
        if is_exact_repeat or is_contained_repeat:
            continue

        kept.append(paragraph)
        seen.add(norm)
        if token_count >= 12:
            seen_long.append(norm)

    return "\n\n".join(kept)


def _merge_short_sections(sections: list[str]) -> list[str]:
    """Merge tiny heading sections so embeddings still have enough context."""
    merged: list[str] = []
    pending = ""

    for section in sections:
        section = section.strip()
        if not section:
            continue
        candidate = f"{pending}\n\n{section}".strip() if pending else section
        if len(_tokenize(candidate)) < _MIN_SECTION_TOKENS:
            pending = candidate
            continue
        merged.append(candidate)
        pending = ""

    if pending:
        if merged:
            merged[-1] = f"{merged[-1]}\n\n{pending}"
        else:
            merged.append(pending)
    return merged


def _split_into_sections(text: str) -> list[str]:
    """Split cleaned text into heading-bounded sections before token chunking."""
    text = _dedupe_redundant_paragraphs(text)
    blocks = [block.strip() for block in _PARA_RE.split(text) if block.strip()]
    if not blocks:
        return []

    sections: list[str] = []
    current: list[str] = []

    for block in blocks:
        starts_new_section = _is_probable_heading(block) and bool(current)
        if starts_new_section:
            sections.append("\n\n".join(current))
            current = [block]
        else:
            current.append(block)

    if current:
        sections.append("\n\n".join(current))
    return _merge_short_sections(sections)


def _trim_repeated_prefix(previous: str, current: str) -> str:
    """Remove paragraph overlap when a splitter tail is merged into context."""
    previous_norms = {
        _norm_for_dedupe(paragraph)
        for paragraph in _PARA_RE.split(previous)
        if paragraph.strip()
    }
    current_paragraphs = [
        paragraph.strip()
        for paragraph in _PARA_RE.split(current)
        if paragraph.strip()
    ]
    while current_paragraphs:
        first_norm = _norm_for_dedupe(current_paragraphs[0])
        if first_norm and first_norm in previous_norms:
            current_paragraphs.pop(0)
            continue
        break
    return "\n\n".join(current_paragraphs)


def _split_section_to_chunks(splitter, section: str) -> list[str]:
    """Token-split a section, then fold short tail pieces back into context."""
    pieces = [piece.strip() for piece in splitter.split_text(section) if piece.strip()]
    merged: list[str] = []
    for piece in pieces:
        if merged:
            piece = _trim_repeated_prefix(merged[-1], piece)
            if not piece:
                continue
        if merged and len(_tokenize(piece)) < _MIN_SECTION_TOKENS:
            merged[-1] = f"{merged[-1]}\n\n{piece}"
        else:
            merged.append(piece)
    return merged


# --- column-aware extraction -------------------------------------------------
# pdfplumber's default extract_text() reads row-by-row across the whole page,
# which interleaves text from adjacent columns in brochures. We instead pull
# words with bounding boxes, auto-detect column ranges by finding empty
# vertical stripes (gutters), and emit each column top-to-bottom.
# Was built initially for the pdfs in the 2-Weeks-Ready corpus, but later
# got replaced by handwritten sidecars since the format of the pdfs is unreliable.
# Keeping this code in case we want to re-run with auto-extraction for new pdfs, 
# but it's not currently in the pipeline.
_LINE_TOL = 3.0            # vertical px tolerance for "same line"
_BIN_WIDTH = 4.0           # x-axis bin width when building occupancy map
_MIN_GUTTER_WIDTH = 12.0   # smaller gaps are inter-word spacing, not gutters
_MIN_COL_WIDTH = 50.0      # narrower regions are margin artifacts / page nums


def _words_to_text(words: list[dict]) -> str:
    """Sort words by (top, x0) and join into lines."""
    if not words:
        return ""
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[str] = []
    current: list[str] = []
    last_top: float | None = None
    for w in words:
        if last_top is None or abs(w["top"] - last_top) < _LINE_TOL:
            current.append(w["text"])
        else:
            lines.append(" ".join(current))
            current = [w["text"]]
        last_top = w["top"]
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _detect_column_ranges(
    words: list[dict],
    page_left: float,
    page_right: float,
) -> list[tuple[float, float]]:
    """Find column x-ranges by locating empty vertical stripes on the page.

    Works for 1, 2, 3, or N columns. Approach:
      1. Build a horizontal occupancy bitmap (which x-bins contain ANY word).
      2. Group contiguous occupied bins into raw column candidates.
      3. Merge candidates separated by < _MIN_GUTTER_WIDTH (those gaps are
         inter-word spacing, not real gutters between columns).
      4. Drop candidates narrower than _MIN_COL_WIDTH (page numbers, etc.).
    """
    if not words:
        return []
    n_bins = max(1, int((page_right - page_left) / _BIN_WIDTH) + 1)
    occupied = [False] * n_bins
    for w in words:
        i0 = max(0, int((w["x0"] - page_left) / _BIN_WIDTH))
        i1 = min(n_bins - 1, int((w["x1"] - page_left) / _BIN_WIDTH))
        for i in range(i0, i1 + 1):
            occupied[i] = True

    raw: list[tuple[int, int]] = []
    start: int | None = None
    for i, occ in enumerate(occupied):
        if occ and start is None:
            start = i
        elif not occ and start is not None:
            raw.append((start, i))
            start = None
    if start is not None:
        raw.append((start, n_bins))

    cols = [(page_left + s * _BIN_WIDTH, page_left + e * _BIN_WIDTH)
            for s, e in raw]

    merged: list[tuple[float, float]] = []
    for col in cols:
        if merged and col[0] - merged[-1][1] < _MIN_GUTTER_WIDTH:
            merged[-1] = (merged[-1][0], col[1])
        else:
            merged.append(col)

    return [(a, b) for a, b in merged if (b - a) >= _MIN_COL_WIDTH]


def _extract_page_text(page) -> str:
    """Return page text in column-aware reading order (auto-detects N columns)."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not words:
        return ""

    page_left, _, page_right, _ = page.bbox
    columns = _detect_column_ranges(words, page_left, page_right)

    if len(columns) <= 1:
        return _words_to_text(words)

    parts: list[str] = []
    for x_start, x_end in columns:
        col_words = [w for w in words if x_start <= w["x0"] < x_end]
        if col_words:
            parts.append(_words_to_text(col_words))
    return "\n\n".join(parts)


# --- pipeline stages ---------------------------------------------------------
def load_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Return (page_number, cleaned_text) pairs, skipping empty pages."""
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw = _extract_page_text(page)
            cleaned = _clean(raw)
            if cleaned:
                pages.append((i, cleaned))
    return pages


_PAGE_HINT_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->", re.IGNORECASE)
_CHUNK_SEP_RE = re.compile(r"^---\s*$", re.MULTILINE)


def load_manual_sidecar(path: Path) -> list[tuple[int, str]]:
    """Parse a hand-curated sidecar into (page, text) blocks.

    Sidecar format: blocks separated by a `---` line. Each block may optionally
    begin with `<!-- page: N -->` to set the citation page; defaults to 1.
    Authors choose the chunk boundaries — we never re-split sidecar text.
    """
    raw = path.read_text(encoding="utf-8")
    blocks: list[tuple[int, str]] = []
    for block in _CHUNK_SEP_RE.split(raw):
        page_no = 1
        m = _PAGE_HINT_RE.search(block)
        if m:
            page_no = int(m.group(1))
            block = _PAGE_HINT_RE.sub("", block, count=1)
        cleaned = _clean(block)
        if cleaned:
            blocks.append((page_no, cleaned))
    return blocks


def chunk_manual_blocks(
    blocks: list[tuple[int, str]],
    source: str,
) -> tuple[list[dict], int]:
    """Emit one chunk per pre-split block. Honors author-chosen boundaries
    verbatim — no RecursiveCharacterTextSplitter pass, no min-token filter.
    The low-content filter that runs over auto-chunked content is bypassed
    here because sidecar authors deliberately use short, directive chunks
    (e.g. one-sentence earthquake-scenario callouts). Returns
    `(chunks, 0)` to match the `chunk_pages` signature."""
    chunks: list[dict] = []
    seen: set[str] = set()
    for page_no, text in blocks:
        norm = _norm_for_dedupe(text)
        if norm in seen:
            continue
        seen.add(norm)
        chunks.append({
            "text": text,
            "source": source,
            "page": page_no,
            "disaster_type": _disaster_type_for(source, text),
        })
    return chunks, 0


def load_text_file(path: Path) -> list[tuple[int, str]]:
    """Return a single (page=1, cleaned_text) tuple for a non-paginated .txt file.

    page=1 is a stable sentinel so chunks.json's `page: int` schema stays
    uniform across PDF and text sources. Re-running `_clean` on already-cleaned
    Ready.gov text is cheap and keeps the invariant consistent.
    """
    text = _clean(path.read_text(encoding="utf-8"))
    return [(1, text)] if text else []


def chunk_pages(pages: Iterable[tuple[int, str]], source: str) -> tuple[list[dict], int]:
    """Split pages into section-aware chunk records.

    Returns (chunks, n_dropped) where n_dropped counts chunks rejected by the
    low-content filter or exact post-split dedupe. We dedupe after splitting too
    because token overlap and source extraction can otherwise produce identical
    final chunks from neighboring sections.
    """
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks: list[dict] = []
    dropped = 0
    seen: set[str] = set()
    for page_no, text in pages:
        for section in _split_into_sections(text):
            for piece in _split_section_to_chunks(splitter, section):
                norm = _norm_for_dedupe(piece)
                if norm in seen:
                    dropped += 1
                    continue
                if _is_low_content(piece):
                    dropped += 1
                    continue
                seen.add(norm)
                chunks.append({
                    "text": piece,
                    "source": source,
                    "page": page_no,
                    "disaster_type": _disaster_type_for(source, piece),
                })
    return chunks, dropped


def build_indexes(chunks: list[dict]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading embedding model: {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)

    texts = [c["text"] for c in chunks]
    print(f"Embedding {len(texts)} chunks...")
    embeddings = model.encode(
        texts,
        batch_size=EMBED_BATCH,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    dim = embeddings.shape[1]
    faiss_index = faiss.IndexFlatIP(dim)
    faiss_index.add(embeddings)
    faiss.write_index(faiss_index, str(INDEX_DIR / "faiss.index"))
    print(f"Wrote FAISS index: {faiss_index.ntotal} vectors x {dim} dims")

    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    with open(INDEX_DIR / "bm25.pkl", "wb") as f:
        pickle.dump(bm25, f)
    print(f"Wrote BM25 index over {len(tokenized)} chunks")

    for i, c in enumerate(chunks):
        c["id"] = i
    chunks_out = [
        {"id": c["id"], "text": c["text"], "source": c["source"],
         "page": c["page"], "disaster_type": c["disaster_type"]}
        for c in chunks
    ]
    with open(INDEX_DIR / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks_out, f, ensure_ascii=False, indent=2)
    print(f"Wrote chunks.json with {len(chunks_out)} entries")


def main() -> None:
    pdf_paths = sorted(RAW_DIR.rglob("*.pdf")) # Left in intentionally in case future pdfs don't have a manual sidecar.
    txt_paths = sorted(PROCESSED_READY_GOV_DIR.glob("*.txt"))
    red_cross_paths = (
        sorted(PROCESSED_RED_CROSS_DIR.glob("*.txt"))
        if PROCESSED_RED_CROSS_DIR.exists() else []
    )
    wa_emd_paths = (
        sorted(PROCESSED_WA_EMD_DIR.glob("*.txt"))
        if PROCESSED_WA_EMD_DIR.exists() else []
    )
    sidecar_paths = sorted(MANUAL_PDF_DIR.glob("*.md")) if MANUAL_PDF_DIR.exists() else []
    sidecar_filenames = {p.name[:-len(".md")] for p in sidecar_paths}
    if (not pdf_paths and not txt_paths and not red_cross_paths
            and not wa_emd_paths and not sidecar_paths):
        raise SystemExit(
            f"No source documents found. Looked in:\n"
            f"  {RAW_DIR} (PDFs, recursive)\n"
            f"  {PROCESSED_READY_GOV_DIR} (cleaned .txt)\n"
            f"  {PROCESSED_RED_CROSS_DIR} (cleaned .txt)\n"
            f"  {PROCESSED_WA_EMD_DIR} (cleaned .txt)\n"
            f"  {MANUAL_PDF_DIR} (hand-curated PDF sidecars)"
        )

    print(f"Found {len(pdf_paths)} PDF(s) in {RAW_DIR}")
    print(f"Found {len(txt_paths)} text file(s) in {PROCESSED_READY_GOV_DIR}")
    print(f"Found {len(red_cross_paths)} text file(s) in {PROCESSED_RED_CROSS_DIR}")
    print(f"Found {len(wa_emd_paths)} text file(s) in {PROCESSED_WA_EMD_DIR}")
    print(f"Found {len(sidecar_paths)} manual sidecar(s) in {MANUAL_PDF_DIR}")
    all_chunks: list[dict] = []
    total_dropped = 0
    for path in tqdm(pdf_paths, desc="Extracting PDFs"):
        if path.name in sidecar_filenames:
            print(f"  using sidecar: {path.name}")
            continue
        pages = load_pdf_pages(path)
        if not pages:
            print(f"  skip (no text): {path.name}")
            continue
        chunks, dropped = chunk_pages(pages, source=path.name)
        all_chunks.extend(chunks)
        total_dropped += dropped
        print(f"  {path.name}: {len(pages)} pages -> {len(chunks)} chunks"
              + (f" ({dropped} dropped low-content)" if dropped else ""))

    for path in tqdm(txt_paths, desc="Extracting text"):
        pages = load_text_file(path)
        if not pages:
            print(f"  skip (empty): {path.name}")
            continue
        chunks, dropped = chunk_pages(pages, source=path.name)
        all_chunks.extend(chunks)
        total_dropped += dropped
        print(f"  {path.name}: {len(chunks)} chunks"
              + (f" ({dropped} dropped low-content)" if dropped else ""))

    for path in tqdm(red_cross_paths, desc="Extracting Red Cross"):
        pages = load_text_file(path)
        if not pages:
            print(f"  skip (empty): {path.name}")
            continue
        chunks, dropped = chunk_pages(pages, source=path.name)
        all_chunks.extend(chunks)
        total_dropped += dropped
        print(f"  {path.name}: {len(chunks)} chunks"
              + (f" ({dropped} dropped low-content)" if dropped else ""))

    for path in tqdm(wa_emd_paths, desc="Extracting WA EMD"):
        pages = load_text_file(path)
        if not pages:
            print(f"  skip (empty): {path.name}")
            continue
        chunks, dropped = chunk_pages(pages, source=path.name)
        all_chunks.extend(chunks)
        total_dropped += dropped
        print(f"  {path.name}: {len(chunks)} chunks"
              + (f" ({dropped} dropped low-content)" if dropped else ""))

    for path in tqdm(sidecar_paths, desc="Loading sidecars"):
        source = path.name[:-len(".md")]
        blocks = load_manual_sidecar(path)
        if not blocks:
            print(f"  skip (empty): {path.name}")
            continue
        chunks, dropped = chunk_manual_blocks(blocks, source=source)
        all_chunks.extend(chunks)
        total_dropped += dropped
        print(f"  {path.name}: {len(chunks)} chunks"
              + (f" ({dropped} dropped low-content)" if dropped else ""))

    if not all_chunks:
        raise SystemExit("No chunks produced — check PDF and text extraction.")

    by_type: dict[str, int] = {}
    for c in all_chunks:
        by_type[c["disaster_type"]] = by_type.get(c["disaster_type"], 0) + 1
    print(f"\nTotal chunks: {len(all_chunks)}")
    print(f"Dropped {total_dropped} low-content chunks (<{_MIN_MEANINGFUL_TOKENS} tokens)")
    print(f"  by disaster_type: {by_type}")

    build_indexes(all_chunks)
    print("\nDone.")


if __name__ == "__main__":
    main()
