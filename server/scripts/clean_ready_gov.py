"""Clean scraped Ready.gov text files for ingestion.

Reads raw scrapes from `data/raw/ready_gov/` and writes cleaned versions to
`data/processed/ready_gov/`. The originals are never modified.

Run from the project root:

    python -m scripts.clean_ready_gov

The cleaner is intentionally stdlib-only and re-runnable: each invocation
does a full rebuild of the processed directory.

Known limitation:
  `ready_gov_cybersecurity.txt` ends with a partner-orgs section where each
  entry is a full sentence ending in a period (e.g. "iSafe certifies digital
  products as compliant with..."). The bottom-up walker in _cut_trailing_links
  treats those as real paragraphs and stops on the first iteration, so the
  partner section survives the cut. After running this script, hand-trim
  cybersecurity from "Department of Homeland Security's Cybersecurity..." to
  EOF. No other file in the current corpus has this pattern.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "ready_gov"
OUT_DIR = ROOT / "data" / "processed" / "ready_gov"

# --- detection thresholds ----------------------------------------------------
# A "real paragraph" is long enough or ends with sentence punctuation. We use
# this both to terminate the top-of-page TOC strip and to stop the bottom-up
# link-list cut.
_PARAGRAPH_MIN_WORDS = 15
_TERMINAL_PUNCT = (".", "!", "?", ":")

# Used to recognize trailing-resource link fragments when there's no explicit
# "Additional Resources" header above them (the common case).
_LINK_FRAG_TOKENS = (
    "(PDF)", "(CDC)", "(EPA)", "(USFA)", "(NFIP)", "(HHS)",
    "Toolkit", "Graphics", "Social Media",
    "Partner Resources", "Additional Resources", "Associated Content",
)
_LINK_FRAG_EXACT = {
    "Additional Resources",
    "Partner Resources",
    "Associated Content",
    "Videos",
    "More Info",
}
_LINK_FRAG_MAX_WORDS = 10  # short + no terminal punct => probably a link title

# Standalone-line noise to drop anywhere in the file.
_NOISE_LINES = {
    "Unknown",
    "feature_mini img",
    "feature img",
    "PDF Link Icon",
    "alert - warning",
    "Português, Brasil",
}

_URL_LINE_RE = re.compile(r"^https?://\S+\s*$")
_LAST_UPDATED_RE = re.compile(r"^Last Updated:")
_FEMA_BOILERPLATE_RE = re.compile(
    r"please visit FEMA\.gov for up-to-date information on current disaster declarations",
    re.IGNORECASE,
)

# Defensive — current corpus has zero markdown links, but keep these in case a
# future scrape includes them.
_MD_LINK_UNDERSCORE_RE = re.compile(r"__\[([^\]]+)\]\([^)]+\)__")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


# --- helpers -----------------------------------------------------------------
def _word_count(s: str) -> int:
    return len(s.split())


def _is_paragraph(line: str) -> bool:
    """True if the line looks like substantive prose, not a heading/anchor/link."""
    s = line.strip()
    if not s:
        return False
    if _word_count(s) >= _PARAGRAPH_MIN_WORDS:
        return True
    return s.endswith(_TERMINAL_PUNCT)


def _is_link_fragment(line: str) -> bool:
    """True if the line looks like a trailing resource-list entry."""
    s = line.strip()
    if not s:
        return False
    if s in _LINK_FRAG_EXACT:
        return True
    if any(tok in s for tok in _LINK_FRAG_TOKENS):
        return True
    # Short and no terminal punctuation → probably a link/title fragment.
    if _word_count(s) < _LINK_FRAG_MAX_WORDS and not s.endswith(_TERMINAL_PUNCT):
        return True
    return False


# --- cleaning stages ---------------------------------------------------------
def _strip_header(lines: list[str]) -> tuple[str, list[str]]:
    """Pop the 4-line header. Returns (title, remaining_lines).

    All 30 files share the same shape: title / "Unknown" / read-time / URL.
    We trust the shape but tolerate minor drift (e.g. if line 3 isn't "Unknown"
    or "N min read", we still drop it because line 4 being a URL is the strong
    signal we're inside the header block).
    """
    if len(lines) < 4:
        return "", lines
    title = lines[0].strip()
    # Sanity: line 4 should be a URL. If not, leave the file alone.
    if not _URL_LINE_RE.match(lines[3]):
        return title, lines
    return title, lines[4:]


def _strip_top_toc(lines: list[str]) -> list[str]:
    """Drop the top-of-page section-anchor TOC.

    These are short standalone heading-like lines (e.g. "Before an Earthquake",
    "During an Earthquake", "After an Earthquake", "Additional Resources")
    appearing before the first real paragraph. They duplicate later headings
    and add noise to BM25.
    """
    out: list[str] = []
    i = 0
    n = len(lines)
    # Skip leading blanks
    while i < n and not lines[i].strip():
        i += 1
    # While each non-blank line at the top is short + no terminal punct, drop it.
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _is_paragraph(lines[i]):
            break
        # short, heading-shaped, anchor-shaped → drop
        i += 1
    out.extend(lines[i:])
    return out


def _strip_line_noise(lines: list[str]) -> list[str]:
    """Drop standalone-noise lines, URLs, and Last-Updated footers."""
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if s in _NOISE_LINES:
            continue
        if _URL_LINE_RE.match(line):
            continue
        if _LAST_UPDATED_RE.match(s):
            continue
        out.append(line)
    return out


def _strip_fema_boilerplate(lines: list[str]) -> list[str]:
    """Drop any line containing the FEMA helpline boilerplate."""
    return [ln for ln in lines if not _FEMA_BOILERPLATE_RE.search(ln)]


def _strip_markdown_links(lines: list[str]) -> list[str]:
    """Replace [text](url) and __[text](url)__ with bare text. No-op on current corpus."""
    out: list[str] = []
    for ln in lines:
        ln = _MD_LINK_UNDERSCORE_RE.sub(r"\1", ln)
        ln = _MD_LINK_RE.sub(r"\1", ln)
        out.append(ln)
    return out


def _cut_trailing_links(lines: list[str]) -> list[str]:
    """Walk bottom-up; drop the trailing run of link-fragment lines.

    Two-phase logic:
      Phase 1 (entry): use the strict `_is_link_fragment` heuristic to detect
        the first trailing link. Stop immediately if the bottom line is a real
        paragraph.
      Phase 2 (in-region): once at least one link has been cut, we're inside
        the trailing link region. From there, treat any line that does NOT
        end with terminal punctuation as a link continuation. Real paragraphs
        end with `.` / `!` / `?` — a non-terminal line near the tail is
        almost always a link title (e.g. "National Weather Service Weather
        Ready Nation Spring Safety Outreach Materials").
    """
    cut_from = len(lines)
    in_region = False
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        s = line.strip()
        if not s:
            # Blank lines don't end the run, but don't move the cut either.
            continue
        if in_region:
            # Inside the link region: cut anything that isn't a sentence.
            if s.endswith(_TERMINAL_PUNCT):
                break
            cut_from = i
            continue
        # Not yet in region — be conservative.
        if _is_paragraph(line):
            break
        if _is_link_fragment(line):
            cut_from = i
            in_region = True
            continue
        # Ambiguous and we haven't entered the link region yet: stop.
        break
    return lines[:cut_from]


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of 3+ newlines to exactly 2; strip trailing blank lines."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.rstrip() + "\n"


# --- per-file pipeline -------------------------------------------------------
def clean_file(raw_path: Path) -> tuple[str, int, int]:
    """Run all cleaning stages on one file. Returns (cleaned_text, in_lines, out_lines)."""
    raw_text = raw_path.read_text(encoding="utf-8")
    raw_lines = raw_text.splitlines()
    in_lines = len(raw_lines)

    title, body = _strip_header(raw_lines)
    body = _strip_top_toc(body)
    body = _strip_line_noise(body)
    body = _strip_fema_boilerplate(body)
    body = _strip_markdown_links(body)
    body = _cut_trailing_links(body)

    # Prepend the title as a markdown H1 so chunkers and readers can see it.
    header = f"# {title}\n\n" if title else ""
    cleaned = header + "\n".join(body)
    cleaned = _normalize_whitespace(cleaned)
    out_lines = cleaned.count("\n")
    return cleaned, in_lines, out_lines


# --- runner ------------------------------------------------------------------
def main() -> None:
    if not RAW_DIR.is_dir():
        raise SystemExit(f"Missing input dir: {RAW_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(RAW_DIR.glob("*.txt"))
    if not raw_files:
        raise SystemExit(f"No .txt files in {RAW_DIR}")

    print(f"Cleaning {len(raw_files)} file(s) from {RAW_DIR}")
    print(f"  -> {OUT_DIR}\n")

    total_in = 0
    total_out = 0
    warns: list[str] = []

    for path in raw_files:
        cleaned, in_lines, out_lines = clean_file(path)
        out_path = OUT_DIR / path.name
        out_path.write_text(cleaned, encoding="utf-8")
        total_in += in_lines
        total_out += out_lines

        shrink = 100 * (1 - out_lines / max(in_lines, 1))
        # Count paragraphs as blank-line-separated blocks of non-blank lines.
        paragraphs = [p for p in cleaned.split("\n\n") if p.strip()]
        flag = ""
        if len(paragraphs) < 5:
            warns.append(f"{path.name} (only {len(paragraphs)} paragraphs)")
            flag = "  WARN: under 5 paragraphs"
        print(f"  {path.name:<40} {in_lines:>4} -> {out_lines:>4} lines  "
              f"({shrink:+5.1f}%){flag}")

    overall = 100 * (1 - total_out / max(total_in, 1))
    print(f"\nTotal: {total_in} -> {total_out} lines ({overall:+.1f}%)")

    if warns:
        print(f"\n{len(warns)} file(s) flagged for review:")
        for w in warns:
            print(f"  - {w}")
    else:
        print("\nAll files passed the >=5-paragraph sanity check.")


if __name__ == "__main__":
    main()
