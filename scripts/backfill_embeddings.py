#!/usr/bin/env python3
"""Optional manual embedding backfill for memory_items."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill memory_item embeddings")
    parser.add_argument("--limit", type=int, default=200, help="Max rows to embed")
    args = parser.parse_args()

    if crowley._memory_embed_provider() == "off":
        print("CROWLEY_EMBED_PROVIDER=off — set auto/local/openai to backfill.")
        return 1

    conn = crowley.connect_db()
    try:
        count = crowley.backfill_memory_item_embeddings(conn, limit=max(1, args.limit))
        conn.commit()
    finally:
        conn.close()

    print(f"Embedded {count} memory_items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
