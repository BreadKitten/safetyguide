"""One-time helper for building retrieval_gold.json.

Prints chunks from the index so an annotator can read them and decide which
are relevant to a given query. No models are loaded — it only reads
server/index/chunks.json.

Usage:
    # Show all chunks for one disaster type
    PYTHONPATH=server python -m server.tests.build_retrieval_oracle --disaster-type earthquake

    # Show all chunks across every disaster type
    PYTHONPATH=server python -m server.tests.build_retrieval_oracle --all

    # List all known disaster types
    PYTHONPATH=server python -m server.tests.build_retrieval_oracle --list-types
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from server.src.ingest import INDEX_DIR

_CHUNKS_PATH = INDEX_DIR / "chunks.json"


def _load() -> list[dict]:
    if not _CHUNKS_PATH.exists():
        print(f"ERROR: {_CHUNKS_PATH} not found. Run `python -m src.ingest` first.")
        sys.exit(1)
    with open(_CHUNKS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _print_chunk(c: dict, max_text: int = 300) -> None:
    text = c["text"].replace("\n", " ")
    if len(text) > max_text:
        text = text[:max_text] + "..."
    print(f"\n  [id={c['id']}] ({c['disaster_type']}) {c['source']} p.{c['page']}")
    print(f"    {text}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Browse index chunks to assist retrieval_gold.json annotation."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--disaster-type", metavar="TYPE", help="Show chunks for this type only.")
    group.add_argument("--all", action="store_true", help="Show every chunk, grouped by type.")
    group.add_argument("--list-types", action="store_true", help="Print known disaster types.")
    parser.add_argument(
        "--max-text", type=int, default=300, help="Max chars of chunk text to show (default 300)."
    )
    args = parser.parse_args(argv)

    chunks = _load()

    if args.list_types:
        by_type: dict[str, list[int]] = defaultdict(list)
        for c in chunks:
            by_type[c["disaster_type"]].append(c["id"])
        print(f"{'disaster_type':<25} {'count':>5}  {'ids (first 5)':}")
        print("-" * 60)
        for dt, ids in sorted(by_type.items()):
            print(f"{dt:<25} {len(ids):>5}  {ids[:5]}")
        return 0

    if args.disaster_type:
        target = args.disaster_type
        matched = [c for c in chunks if c["disaster_type"] == target]
        if not matched:
            known = sorted({c["disaster_type"] for c in chunks})
            print(f"ERROR: '{target}' not found. Known types: {known}")
            return 1
        print(f"=== {target} ({len(matched)} chunks) ===")
        for c in matched:
            _print_chunk(c, args.max_text)
        return 0

    # --all
    by_type_list: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_type_list[c["disaster_type"]].append(c)
    for dt in sorted(by_type_list):
        group_chunks = by_type_list[dt]
        print(f"\n{'=' * 60}")
        print(f"=== {dt} ({len(group_chunks)} chunks) ===")
        for c in group_chunks:
            _print_chunk(c, args.max_text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
