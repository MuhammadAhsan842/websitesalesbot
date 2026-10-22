"""Hybrid retrieve + rerank over approved register only. Packet PDFs are never indexed."""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app import fees, qwen
from app.knowledge import REGISTER, lookup

_INDEX: list[dict] = []
SKIP = {"version", "unknown"}
TOKEN = re.compile(r"[a-z0-9]+")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
PACKET_DIR = Path(__file__).resolve().parent.parent / "data" / "packets"
RRF_K = 10
MIN_RRF = 0.12
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "can", "do", "does", "for", "from", "have", "how",
    "i", "in", "is", "it", "me", "my", "not", "of", "on", "or", "our", "that", "the", "this",
    "to", "we", "will", "with", "you", "your",
}
EXPAND = {
    "produce": ("reefer", "temperature"),
    "perishable": ("reefer", "temperature"),
    "frozen": ("reefer",),
    "percent": ("percentage", "fee"),
    "percentage": ("percent", "fee"),
    "fee": ("percent", "percentage"),
    "cost": ("fee",),
    "charge": ("fee",),
    "haul": ("dispatch", "services"),
}


def tokenize(text: str) -> set[str]:
    return {tok for tok in TOKEN.findall((text or "").lower()) if tok not in STOP and len(tok) > 2}


def query_tokens(text: str) -> set[str]:
    toks = tokenize(text)
    extra = set()
    for tok in toks:
        extra.update(EXPAND.get(tok, ()))
    return toks | extra


def _embed(text: str) -> list[float] | None:
    try:
        response = httpx.post(
            f"{qwen.OLLAMA}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=20.0,
        )
        response.raise_for_status()
        vec = response.json().get("embedding")
        return vec if isinstance(vec, list) else None
    except Exception:
        return None


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _lex(query: set[str], doc: set[str]) -> float:
    if not query or not doc:
        return 0.0
    return len(query & doc) / math.sqrt(len(query) * len(doc))


def _percent_ok(text: str) -> bool:
    allowed = fees.approved_percents()
    for match in PERCENT.finditer(text or ""):
        token = match.group(1)
        if token in allowed or (token.endswith(".0") and token[:-2] in allowed):
            continue
        return False
    return True


def _unknown() -> dict:
    return {"key": "unknown", "text": lookup("unknown"), "lexical": 0, "vector": 0, "hybrid": 0}


def build_index() -> int:
    rows = []
    for key, text in REGISTER.items():
        if key in SKIP or not text or not isinstance(text, str):
            continue
        if "pay 6%" in text or not _percent_ok(text):
            continue
        rows.append(
            {
                "key": key,
                "text": text,
                "tokens": tokenize(f"{key.replace('_', ' ')} {text}"),
                "vec": None,
            }
        )
    _INDEX[:] = rows
    if rows and _embed("dispatch fit check") is not None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            vectors = list(pool.map(lambda row: _embed(row["text"]), rows))
        for row, vec in zip(rows, vectors):
            row["vec"] = vec
    return len(rows)


def status() -> dict:
    return {
        "indexed": len(_INDEX),
        "source": REGISTER.get("version"),
        "packets_indexed": False,
        "keys": [row["key"] for row in _INDEX],
    }


def search(query: str, limit: int = 2) -> list[dict]:
    if not _INDEX:
        build_index()
    q_tokens = query_tokens(query)
    q_vec = _embed(query)
    scored = []
    for item in _INDEX:
        if not (q_tokens & item["tokens"]):
            continue
        lexical = _lex(q_tokens, item["tokens"])
        vector = _cosine(q_vec, item["vec"])
        scored.append({"key": item["key"], "text": item["text"], "lexical": lexical, "vector": vector})
    if not scored:
        return [_unknown()]
    lex_rank = {row["key"]: i for i, row in enumerate(sorted(scored, key=lambda r: r["lexical"], reverse=True))}
    vec_rank = {row["key"]: i for i, row in enumerate(sorted(scored, key=lambda r: r["vector"], reverse=True))}
    reranked = []
    for row in scored:
        if row["text"] != REGISTER.get(row["key"]):
            continue
        if not _percent_ok(row["text"]):
            continue
        key_toks = tokenize(row["key"].replace("_", " "))
        rrf = 1 / (RRF_K + lex_rank[row["key"]] + 1) + 1 / (RRF_K + vec_rank[row["key"]] + 1)
        if key_toks & q_tokens:
            rrf += 0.2
        reranked.append(
            {
                "key": row["key"],
                "text": row["text"],
                "lexical": round(row["lexical"], 4),
                "vector": round(row["vector"], 4),
                "hybrid": round(rrf, 4),
            }
        )
    reranked.sort(key=lambda row: row["hybrid"], reverse=True)
    hits = [row for row in reranked if row["hybrid"] >= MIN_RRF][:limit]
    return hits or [_unknown()]
