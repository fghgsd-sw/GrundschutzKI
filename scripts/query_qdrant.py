"""
Qdrant inspection tool for GSKI collections.

Usage examples:
  # (a) Show metadata structure of chunks
  python query_qdrant.py structure
  python query_qdrant.py structure --collection grundschutz_bge_m3

  # (b) Filter by metadata fields
  python query_qdrant.py filter --where doc_type=anforderung --where baustein_id=OPS.2.2
  python query_qdrant.py filter --where standard_id=standard_200_2 --show-text

  # (c) Full-text search in chunk text
  python query_qdrant.py search --text "Basis-Absicherung Schritte"
  python query_qdrant.py search --text "Geltungsbereich" --where standard_id=standard_200_2
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Allow running from any directory by finding the project root
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "apps" / "chainlit"))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / "apps" / "chainlit" / ".env", override=False)
except ImportError:
    pass

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "grundschutz_bge_m3")


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def scroll_all(client: QdrantClient, collection: str, limit_per_page: int = 250) -> list[dict]:
    """Scroll through all points in a collection."""
    points = []
    offset = None
    while True:
        result = client.scroll(
            collection_name=collection,
            limit=limit_per_page,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        batch, next_offset = result
        points.extend(p.payload or {} for p in batch)
        if next_offset is None:
            break
        offset = next_offset
    return points


def cmd_structure(args: argparse.Namespace) -> None:
    """Show metadata structure: all keys, their types, and example values."""
    client = get_client()
    collection = args.collection

    print(f"Collection: {collection}")
    print("Sampling metadata structure...\n")

    result = client.scroll(
        collection_name=collection,
        limit=500,
        with_payload=True,
        with_vectors=False,
    )
    payloads = [p.payload or {} for p in result[0]]

    # Collect all keys with value types and examples
    key_types: dict[str, Counter] = defaultdict(Counter)
    key_examples: dict[str, list] = defaultdict(list)
    doc_type_keys: dict[str, set] = defaultdict(set)

    for pl in payloads:
        dt = pl.get("doc_type", "?")
        for k, v in pl.items():
            if k == "text":
                continue
            type_name = type(v).__name__
            key_types[k][type_name] += 1
            doc_type_keys[dt].add(k)
            if len(key_examples[k]) < 2 and v is not None:
                example = str(v)[:60]
                if example not in key_examples[k]:
                    key_examples[k].append(example)

    # doc_type breakdown
    dt_counts = Counter(pl.get("doc_type", "?") for pl in payloads)
    print("doc_type breakdown (sample 500):")
    for dt, count in dt_counts.most_common():
        keys = sorted(doc_type_keys[dt] - {"text"})
        print(f"  {dt:35s} {count:4d}x  keys: {', '.join(keys)}")

    print("\nAll metadata keys:")
    for key in sorted(key_types):
        types = "/".join(f"{t}({n})" for t, n in key_types[key].most_common(2))
        examples = " | ".join(key_examples[key])
        print(f"  {key:30s} {types:20s}  e.g.: {examples}")


def cmd_filter(args: argparse.Namespace) -> None:
    """Filter chunks by metadata field=value pairs."""
    client = get_client()
    collection = args.collection

    must = []
    for condition in args.where:
        if "=" not in condition:
            print(f"Invalid --where format: '{condition}' (use key=value)", file=sys.stderr)
            sys.exit(1)
        key, value = condition.split("=", 1)
        must.append(FieldCondition(key=key.strip(), match=MatchValue(value=value.strip())))

    result = client.scroll(
        collection_name=collection,
        limit=args.limit,
        with_payload=True,
        with_vectors=False,
        scroll_filter=Filter(must=must) if must else None,
    )
    points = result[0]
    print(f"Found {len(points)} chunks (limit={args.limit}):\n")

    for p in points:
        pl = p.payload or {}
        _print_chunk(pl, show_text=args.show_text)


def cmd_search(args: argparse.Namespace) -> None:
    """Search chunks by keyword in text payload (+ optional metadata filter)."""
    client = get_client()
    collection = args.collection
    keyword = args.text.lower()

    must = []
    for condition in (args.where or []):
        if "=" not in condition:
            continue
        key, value = condition.split("=", 1)
        must.append(FieldCondition(key=key.strip(), match=MatchValue(value=value.strip())))

    # Scroll and filter by text content
    matches = []
    offset = None
    while len(matches) < args.limit:
        result = client.scroll(
            collection_name=collection,
            limit=250,
            offset=offset,
            with_payload=True,
            with_vectors=False,
            scroll_filter=Filter(must=must) if must else None,
        )
        batch, next_offset = result
        for p in batch:
            text = (p.payload or {}).get("text", "").lower()
            if keyword in text:
                matches.append(p.payload or {})
                if len(matches) >= args.limit:
                    break
        if next_offset is None:
            break
        offset = next_offset

    print(f"Found {len(matches)} chunks containing '{args.text}':\n")
    for pl in matches:
        _print_chunk(pl, show_text=args.show_text)


def _print_chunk(pl: dict[str, Any], show_text: bool = False) -> None:
    doc_type = pl.get("doc_type", "?")
    page = f"S.{pl.get('page_start','?')}"
    if pl.get("page_end") and pl.get("page_end") != pl.get("page_start"):
        page += f"-{pl['page_end']}"

    # Build identifier line
    parts = [f"[{doc_type}]", page]
    for key in ("baustein_id", "anforderung_id", "standard_id", "section_title", "title"):
        v = pl.get(key)
        if v and str(v).strip():
            parts.append(str(v)[:60])
            break

    print("  " + "  ".join(parts))

    if show_text:
        text = (pl.get("text") or "").strip()[:300].replace("\n", " ")
        print(f"    → {text}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Qdrant collection metadata and chunks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--collection", "-c",
        default=DEFAULT_COLLECTION,
        help=f"Collection name (default: {DEFAULT_COLLECTION})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # structure
    sub.add_parser("structure", help="Show metadata key structure by doc_type")

    # filter
    p_filter = sub.add_parser("filter", help="Filter chunks by metadata key=value")
    p_filter.add_argument("--where", action="append", default=[], metavar="key=value",
                          help="Filter condition (repeatable)")
    p_filter.add_argument("--limit", type=int, default=20)
    p_filter.add_argument("--show-text", action="store_true")

    # search
    p_search = sub.add_parser("search", help="Find chunks by keyword in text")
    p_search.add_argument("--text", required=True, metavar="KEYWORD")
    p_search.add_argument("--where", action="append", default=[], metavar="key=value")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--show-text", action="store_true", default=True)

    args = parser.parse_args()

    dispatch = {"structure": cmd_structure, "filter": cmd_filter, "search": cmd_search}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
