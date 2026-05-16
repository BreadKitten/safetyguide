"""Clean copied Red Cross reader-mode text files for ingestion.

Reads raw text from `data/raw/red_cross/` and writes cleaned versions to
`data/processed/red_cross/`. The originals are never modified.

Run from the project root:

    python -m scripts.clean_red_cross

The cleaner follows the same stdlib-only, re-runnable shape as
`scripts.clean_ready_gov`: each invocation rebuilds the processed Red Cross
directory from the current raw files.
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "red_cross"
OUT_DIR = ROOT / "data" / "processed" / "red_cross"

_URL_LINE_RE = re.compile(r"^https?://\S+\s*$")
_HEADER_READ_TIME_RE = re.compile(r"^\d+\s+min\s+read$", re.IGNORECASE)
_MD_LINK_UNDERSCORE_RE = re.compile(r"__\[([^\]]+)\]\([^)]+\)__")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

_NOISE_EXACT = {
    "Unknown",
    "Need help? That's why we're here!",
    "Need help? That’s why we’re here!",
    "Habla español? Esté preparado de acuerdo con La Cruz Roja >>",
    "Red Cross and exclamation point",
    "Download the free Emergency app today. Available in English and Spanish. Search \"American Red Cross\" in your app store or text \"GETEMERGENCY\" to 90999.",
    "Available in the App Store® or Google PlayTM.",
    "Apple App Store Icon and QR code",
    "Google Play store icon and QR code",
    "Print out the Preparedness Essentials Checklist:",
    "Thank You to Our 2025 National Sponsor",
    "State Farm logo",
    "Map of the U.S.",
    "Girl holds up a home fire escape plan that she worked on",
    "Sister and brother",
    "Family picture, five members",
    "Woman with two dogs and two birds",
    "Pillowcase Project presentation in classroom",
    "CPR instructor teaches student chest compressions",
    "Keepsakes and old toys stored in an attic",
    "Red number one",
    "Red number two",
    "Red number three",
    "Emergency Contact Card",
    "Download Template >>",
    "Get Tips and Advice",
    "Disaster and Emergency Preparedness for Older Adults",
    "Households, Schools and Educators",
    "Prepare Your Workplace for Emergencies",
    "Commuter Safety",
    "Learn How to Preserve Your Memories",
    "number 1 icon",
    "number 2 icon",
    "number 3 icon",
    "number 4 icon",
    "number 5 icon",
}

_DROP_PREFIXES = (
    "For more information on emergency preparedness, please visit",
    "For more information on getting help during a disaster, please visit",
    "To make a financial donation, please visit",
)

_DROP_CONTAINS = (
    "#redcross",
)

_COMMERCIAL_SENTENCE_RE = re.compile(
    r"\s*Shop for Survival Kits and other first aid supplies at the Red Cross Store\.",
    re.IGNORECASE,
)


def _strip_header(lines: list[str]) -> tuple[str, list[str]]:
    """Pop the reader-mode title/read-time/URL header when present."""
    if len(lines) < 4:
        return "", lines
    title = lines[0].strip()
    if (
        lines[1].strip() == "Unknown"
        and _HEADER_READ_TIME_RE.match(lines[2].strip())
        and _URL_LINE_RE.match(lines[3].strip())
    ):
        return title, lines[4:]
    return title, lines


def _strip_markdown_links(line: str) -> str:
    """Replace markdown links with bare link text."""
    line = _MD_LINK_UNDERSCORE_RE.sub(r"\1", line)
    return _MD_LINK_RE.sub(r"\1", line)


def _clean_line(line: str) -> str | None:
    """Clean one raw line, returning None when the line is page chrome."""
    s = _strip_markdown_links(line.strip())
    if not s:
        return ""
    if _URL_LINE_RE.match(s):
        return None
    if s in _NOISE_EXACT:
        return None
    if any(s.startswith(prefix) for prefix in _DROP_PREFIXES):
        return None
    if any(token in s for token in _DROP_CONTAINS):
        return None

    s = s.replace('""', '"')
    s = s.replace("Google PlayTM", "Google Play")
    s = s.replace("Ready Rating™", "Ready Rating")
    s = s.replace("Ready RatingTM", "Ready Rating")
    s = s.replace("tips tips", "tips")
    s = _COMMERCIAL_SENTENCE_RE.sub("", s)
    return s.strip()


def _strip_line_noise(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        cleaned = _clean_line(line)
        if cleaned is None:
            continue
        out.append(cleaned)
    return out


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
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.rstrip() + "\n"


def clean_file(raw_path: Path) -> tuple[str, int, int]:
    raw_text = raw_path.read_text(encoding="utf-8")
    raw_lines = raw_text.splitlines()
    in_lines = len(raw_lines)

    title, body = _strip_header(raw_lines)
    body = _strip_line_noise(body)
    body = _collapse_blank_lines(body)

    header = f"# {title}\n\n" if title else ""
    cleaned = _normalize_whitespace(header + "\n".join(body))
    out_lines = cleaned.count("\n")
    return cleaned, in_lines, out_lines


def main() -> None:
    if not RAW_DIR.is_dir():
        raise SystemExit(f"Missing input dir: {RAW_DIR}")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(RAW_DIR.glob("*.txt"))
    if not raw_files:
        raise SystemExit(f"No .txt files in {RAW_DIR}")

    print(f"Cleaning {len(raw_files)} file(s) from {RAW_DIR}")
    print(f"  -> {OUT_DIR}\n")

    total_in = 0
    total_out = 0
    for path in raw_files:
        cleaned, in_lines, out_lines = clean_file(path)
        out_path = OUT_DIR / path.name
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
