#!/usr/bin/env python3
"""Upsert all project text documents into Pinecone (namespace: docs)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-embed even when hash matches")
    parser.add_argument("--also-examples", action="store_true", help="Also refresh example+register namespaces")
    args = parser.parse_args()

    from app import docindex, examples, retrieve, vectorstore

    print("pinecone", vectorstore.status())
    if args.also_examples:
        print("examples", examples.ensure_embeddings())
        print("register", retrieve.build_index(), retrieve.status().get("embed"))
    report = docindex.ingest_all(force=args.force)
    # Don't dump every path in stdout if huge
    paths = report.pop("paths", [])
    print(json.dumps({**report, "path_count": len(paths), "sample_paths": paths[:12]}, indent=2))
    sample = docindex.search("own-MC onboarding documents checklist NOA factoring", top_k=5)
    print("sample_query", sample)


if __name__ == "__main__":
    main()
