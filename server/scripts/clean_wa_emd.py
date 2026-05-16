"""Clean copied WA EMD reader-mode text files for ingestion.

Reads raw text from `data/raw/wa_emd/` and, if present, `data/raw/WA_EMD/`.
Writes cleaned versions to `data/processed/wa_emd/`. The originals are never
modified.

Run from the project root:

    python -m scripts.clean_wa_emd

Mirrors the shape of `scripts.clean_ready_gov` and `scripts.clean_red_cross`:
stdlib-only, idempotent rebuild on each invocation.

WA EMD pages share the same 4-line header as the Ready.gov corpus
(title / author / "N min read" / URL), but the author line is
"efelle creative" (the CMS) instead of "Unknown". The body is heavily
decorated with `(Opens in a new window)` / `(Opens an external site in a
new window)` / `(PDF)` markers attached mid-line to link titles, so we
strip those as inline substrings rather than as whole-line drops.

Image alt-text lines are mixed: most are pure decoration ("A logo
showing different hazards..."), but a few embed real instructional
content that the chatbot needs verbatim (the "Color graphic showing
what to do when on the coast during a large earthquake. First, drop,
cover, and hold on..." line is the only Ready.gov-style source for
"drop, cover" in the tsunami corpus). We drop the decorative ones via a
small `_NOISE_EXACT` allowlist and let the instructional captions
through.
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIRS = (
    ROOT / "data" / "raw" / "wa_emd",
    ROOT / "data" / "raw" / "WA_EMD",
)
OUT_DIR = ROOT / "data" / "processed" / "wa_emd"

_URL_LINE_RE = re.compile(r"^https?://\S+\s*$")
_INLINE_URL_RE = re.compile(r"https?://\S+")
_HEADER_AUTHOR = "efelle creative"
_HEADER_READ_TIME_RE = re.compile(r"^\d+\s+min\s+read$", re.IGNORECASE)
_MD_LINK_UNDERSCORE_RE = re.compile(r"__\[([^\]]+)\]\([^)]+\)__")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

# Inline link-annotation markers. WA EMD's CMS renders link targets as
# trailing parentheticals attached directly to the visible link text, e.g.
# "2023 State Enhanced Hazard Mitigation Final Plan (Opens in a new window)(PDF)".
# Strip them as substrings so the bare link title survives in prose flow.
# We replace with a single space (not the empty string) because the raw HTML
# routinely has no space after the closing `)` — e.g. "alerts (Opens in a
# new window)to be warned" — and substituting "" would mash "alerts" and
# "to" into "alertsto". The leading-`\s*` plus substitute-with-space yields
# at most one extra space, which `_MULTI_SPACE_RE` then collapses.
_INLINE_LINK_ANNOTATION_RE = re.compile(
    r"\s*\(\s*(?:"
    r"Opens (?:an external site )?in a new window"
    r"|Opens an external site"
    r"|PDF"
    r")\s*\)"
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

# Pure-decoration captions that show up as standalone lines. Keep this set
# tight: only add a caption here if it carries no instructional content.
# The "Color graphic showing what to do when on the coast during a large
# earthquake. First, drop, cover, and hold on..." caption is deliberately
# NOT in this set — it is the only Ready.gov-style source of the
# "drop, cover" critical phrase in the WA EMD corpus.
_NOISE_EXACT = {
    "A logo showing different hazards. It reads Hazard Mitigation Assistance.",
    "Color graphic showing how a tsunami is formed by an underwater earthquake.",
    "A photo of Ocosta Elementary school in Westport, Washington. The two-story gym building has four large corner pillars which form the basis of the vertical evacuation structure.",
    # Trailing "Connect With Us" social-handles block at the foot of the
    # tsunami page. The bottom-up walker would catch most of these on the
    # short-line/no-terminal-punct rule, but listing them exactly is
    # cheaper than tuning that heuristic and survives small upstream edits.
    "Connect With Us",
    "BlueSky: @emd.wa.gov",
    "X/Twitter: @waEMD",
    "Facebook: WashEMD",
    "YouTube",
    "Nextdoor",
    "Color graphic showing different ways to get tsunami alerts. Text on the top says “Tsunamis can happen at any time. How will you be alerted? Mil.wa.gov/alerts.”",
    "Tsunami alert levels include warning, advisory, watch, and information statement.",
}

# Drop lines whose prefix marks them as page chrome we never want indexed.
_DROP_PREFIXES = (
    "Questions? Please email",
    "1. Click on or copy the following link into your browser:",
    "Learn about hazard mitigation grants at",
)

_DROP_EXACT = {
    "(Opens an external site in a new window)",
    "(Opens in a new window)",
}

# Page sections that are mostly link/resource lists rather than body content.
# The end marker itself is kept.
_SKIP_SECTIONS_BY_FILE = {
    "wa_emd_hazard_mitigation_grants.txt": (
        ("What is Hazard Mitigation?", "What is Hazard Mitigation?"),
        ("To continue receiving funding opportunity communication from us, we ask you to sign up for GovDelivery by following the simple steps below:", "This does not mean that this email, hma@mil.wa.gov is going away; we will still be here to answer questions and discuss specifics. However, no alerts for funding opportunities will be distributed this way moving forward."),
        ("Resources", None),
    ),
    "wa_emd_tsunami.txt": (
        ("Public Education Materials", "Maritime Guidance"),
        ("Port of Port Angeles' Port Angeles Harbor and Sequim Bay", "Tsunami Vertical Evacuation"),
        ("A Guide to Tsunami Vertical Evacuation Options on the Washington Coast Volume 1: Pacific County-20MB", "Planning a VES? Funding and Resources Explored"),
        ("Download our Manual for Tsunami Vertical Evacuation Structures and supporting documents to learn more about the process:", "Interested in bringing a VES to your community?"),
    ),
}

# Terminal sentence punctuation. Used by the trailing-chrome walker to
# distinguish real paragraphs (end with a period/!/?) from link titles
# (typically short, no terminal punctuation).
_TERMINAL_PUNCT = (".", "!", "?", ":")


def _strip_header(lines: list[str]) -> tuple[str, list[str]]:
    """Pop the reader-mode title / efelle creative / "N min read" / URL header."""
    if len(lines) < 4:
        return "", lines
    title = lines[0].strip()
    if (
        lines[1].strip() == _HEADER_AUTHOR
        and _HEADER_READ_TIME_RE.match(lines[2].strip())
        and _URL_LINE_RE.match(lines[3].strip())
    ):
        return title, lines[4:]
    return title, lines


def _strip_inline_annotations(line: str) -> str:
    """Remove `(Opens in a new window)` / `(PDF)` style markers attached to link titles."""
    line = _MD_LINK_UNDERSCORE_RE.sub(r"\1", line)
    line = _MD_LINK_RE.sub(r"\1", line)
    line = _INLINE_LINK_ANNOTATION_RE.sub(" ", line)
    line = _INLINE_URL_RE.sub("", line)
    return _normalize_line_spacing(line)


def _normalize_line_spacing(line: str) -> str:
    """Clean small spacing artifacts left by reader-mode link annotations."""
    line = line.replace("\u202f", " ")
    line = line.replace("\xa0", " ")
    line = line.replace("atmil.wa.gov", "at mil.wa.gov")
    line = line.replace("Copies of those strategies can be found below.", "")
    line = line.replace(" Download the county-specific VES assessment reports below:", "")
    line = line.replace("Download the county-specific VES assessment reports below:", "")
    line = line.replace(
        "Below are links to tsunami education resources, including external sites, materials available for download, and educational videos.",
        "WA EMD provides tsunami education resources, materials available for download, and educational videos.",
    )
    line = line.replace(
        "To help communities navigate the process, WA EMD has developed a step-by-step guide with lessons from Washington, Oregon, and beyond. Here’s how to get started:",
        "To help communities navigate the process, WA EMD has developed a step-by-step guide with lessons from Washington, Oregon, and beyond.",
    )
    line = line.replace(
        "the sirens play a wail sound (click here to listen to what it sounds like ) followed",
        "the sirens play a wail sound followed",
    )
    line = line.replace(
        "the sirens play the Westminster Chimes (click here to listen to what it sounds like ).",
        "the sirens play the Westminster Chimes.",
    )
    line = _MULTI_SPACE_RE.sub(" ", line)
    line = re.sub(r"\s+([,.;:!?])", r"\1", line)
    line = re.sub(r"\(\s+", "(", line)
    return line.strip()


def _clean_line(line: str) -> str | None:
    """Clean one raw line; return None when the line is page chrome to drop."""
    s = _strip_inline_annotations(line).strip()
    if not s:
        return ""
    if _URL_LINE_RE.match(s):
        return None
    if s in _DROP_EXACT:
        return None
    if s in _NOISE_EXACT:
        return None
    if any(s.startswith(prefix) for prefix in _DROP_PREFIXES):
        return None
    if s.startswith("Color graphic showing what to do when on the coast during a large earthquake."):
        return (
            "If you are on the coast during a large earthquake, first drop, cover, "
            "and hold on to protect yourself during the ground shaking. Then head "
            "inland to high ground; the shaking is your tsunami warning. Stay at "
            "high ground because tsunami waves may arrive for hours."
        )
    if s.startswith("Color graphic showing the four tsunami alert levels"):
        return None
    if s.startswith("Black and white graphic showing different factors a mariner should consider"):
        return (
            "Mariners should consider vessel capability and speed, vessel draft, "
            "provisions and equipment on board, crew skill level, communication "
            "services, time before tsunami impact, distance to land or deep water, "
            "and weather, tide stage, and sea state."
        )
    return s


def _strip_line_noise(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        cleaned = _clean_line(line)
        if cleaned is None:
            continue
        out.append(cleaned)
    return out


def _strip_resource_sections(lines: list[str], filename: str) -> list[str]:
    """Remove known mid-page resource/link-list blocks for a specific source."""
    sections = _SKIP_SECTIONS_BY_FILE.get(filename, ())
    if not sections:
        return lines

    out: list[str] = []
    skip_until: str | None = None
    seen_start: set[str] = set()

    for line in lines:
        s = line.strip()

        if skip_until is not None:
            if skip_until is not None and s == skip_until:
                out.append(line)
                skip_until = None
            continue

        matched = False
        for start, end in sections:
            # The grants page has a TOC entry and a real heading with the same
            # text. Skip only the first one.
            key = f"{start}\0{end}"
            if s == start and key not in seen_start:
                seen_start.add(key)
                skip_until = end
                matched = True
                if end is None:
                    return out
                break
        if matched:
            continue

        out.append(line)

    return out


def _cut_trailing_chrome(lines: list[str]) -> list[str]:
    """Walk bottom-up; cut the trailing run of link-title / social-handle lines.

    A real paragraph ends with terminal punctuation. WA EMD's trailing
    chrome (Connect-With-Us handles, PDF resource lists with link titles)
    is short and has no terminal punctuation after inline-annotation
    stripping, so the rule is: from the bottom, drop lines without
    terminal punctuation until we hit one that does. Blank lines don't
    end the run, but don't move the cut either.
    """
    cut_from = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if s.endswith(_TERMINAL_PUNCT):
            break
        cut_from = i
    return lines[:cut_from]


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "\n".join(_normalize_line_spacing(line) if line.strip() else "" for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.rstrip() + "\n"


def clean_file(raw_path: Path) -> tuple[str, int, int]:
    raw_text = raw_path.read_text(encoding="utf-8")
    raw_lines = raw_text.splitlines()
    in_lines = len(raw_lines)

    title, body = _strip_header(raw_lines)
    body = _strip_line_noise(body)
    body = _strip_resource_sections(body, raw_path.name)
    body = _cut_trailing_chrome(body)
    body = _collapse_blank_lines(body)

    header = f"# {title}\n\n" if title else ""
    cleaned = _normalize_whitespace(header + "\n".join(body))
    out_lines = cleaned.count("\n")
    return cleaned, in_lines, out_lines


def main() -> None:
    existing_raw_dirs: list[Path] = []
    seen_dirs: set[str] = set()
    for path in RAW_DIRS:
        if not path.is_dir():
            continue
        resolved = str(path.resolve()).lower()
        if resolved in seen_dirs:
            continue
        seen_dirs.add(resolved)
        existing_raw_dirs.append(path)
    if not existing_raw_dirs:
        joined = ", ".join(str(path) for path in RAW_DIRS)
        raise SystemExit(f"Missing input dir. Expected one of: {joined}")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_files_by_name: dict[str, Path] = {}
    for raw_dir in existing_raw_dirs:
        for path in sorted(raw_dir.glob("*.txt")):
            raw_files_by_name.setdefault(path.name.lower(), path)
    raw_files = [raw_files_by_name[name] for name in sorted(raw_files_by_name)]
    if not raw_files:
        joined = ", ".join(str(path) for path in existing_raw_dirs)
        raise SystemExit(f"No .txt files in {joined}")

    print(f"Cleaning {len(raw_files)} file(s) from {', '.join(str(path) for path in existing_raw_dirs)}")
    print(f"  -> {OUT_DIR}\n")

    total_in = 0
    total_out = 0
    for path in raw_files:
        cleaned, in_lines, out_lines = clean_file(path)
        out_path = OUT_DIR / path.name.lower()
        out_path.write_text(cleaned, encoding="utf-8")
        total_in += in_lines
        total_out += out_lines
        shrink = 100 * (1 - out_lines / max(in_lines, 1))
        print(
            f"  {path.name:<48} {in_lines:>4} -> {out_lines:>4} lines "
            f"({shrink:+5.1f}%)"
        )

    overall = 100 * (1 - total_out / max(total_in, 1))
    print(f"\nTotal: {total_in} -> {total_out} lines ({overall:+.1f}%)")


if __name__ == "__main__":
    main()
