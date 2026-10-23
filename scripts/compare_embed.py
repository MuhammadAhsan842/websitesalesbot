"""MiniLM vs nomic on reviewed driver paraphrases. Run against EMBED_URL, not the chat process."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, embed, examples

CASES = (
    ("I don't wanna sign if you can't get me anything", "moses_wont_sign"),
    ("Hey not yet, still getting quotes", "jason_waiting_insurance"),
    ("busy this week, maybe next week", "union_pause_next_week"),
    ("picking the truck up tomorrow then I'll send papers", "moses_truck_tomorrow"),
    ("NJ Monday 26 box liftgate", "union_nj_monday"),
)


def score(model: str) -> dict:
    os.environ["EMBED_MODEL"] = model
    embed.MODEL = model
    embed._cache.clear()
    db.init()
    examples.reload_index()
    started = perf_counter()
    examples.ensure_embeddings()
    index_ms = (perf_counter() - started) * 1000
    hits = 0
    query_ms = []
    for question, expected in CASES:
        t0 = perf_counter()
        found = examples.search(question, limit=2)
        query_ms.append((perf_counter() - t0) * 1000)
        if found and found[0]["id"] == expected:
            hits += 1
        print(f"  {expected:28} -> {(found[0]['id'] if found else None)}  {question!r}")
    return {
        "model": model,
        "top1": f"{hits}/{len(CASES)}",
        "index_ms": round(index_ms, 1),
        "p95_query_ms": round(sorted(query_ms)[int(0.95 * (len(query_ms) - 1))], 1),
        "cached": embed.status()["cached"],
    }


def main() -> None:
    models = sys.argv[1:] or ["all-minilm", "nomic-embed-text"]
    for model in models:
        print(f"\n== {model} ==")
        print(score(model))


if __name__ == "__main__":
    main()
