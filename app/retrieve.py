"""Hybrid retrieve over the approved register only. Packet PDFs are never indexed."""

from __future__ import annotations

import math
import re
from pathlib import Path

from app import embed, fees
from app.knowledge import REGISTER, lookup

_INDEX: list[dict] = []
SKIP = {"version", "unknown"}
TOKEN = re.compile(r"[a-z0-9]+")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
PACKET_DIR = Path(__file__).resolve().parent.parent / "data" / "packets"
MIN_RRF = 0.08
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


def _rows() -> list[dict]:
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
            }
        )
    return rows


def build_index() -> int:
    """Lexical index always; vectors only for changed register copy, one at a time."""
    rows = _rows()
    _INDEX[:] = rows
    embed.ensure("register", [{"id": row["key"], "text": row["text"]} for row in rows])
    return len(rows)


def status() -> dict:
    docs = {}
    try:
        from app import docindex, vectorstore

        docs = {
            "namespace": docindex.KIND,
            "files_discoverable": len(docindex.iter_files()),
            "pinecone": vectorstore.status(),
        }
    except Exception:
        docs = {"namespace": "docs"}
    return {
        "indexed": len(_INDEX),
        "source": REGISTER.get("version"),
        "packets_indexed": False,
        "keys": [row["key"] for row in _INDEX],
        "embed": embed.status(),
        "docs": docs,
    }


def search_docs(query: str, limit: int = 4) -> list[dict]:
    """Vector search over chunked project documents in Pinecone."""
    from app import docindex

    return docindex.search(query, top_k=limit)


def search(query: str, limit: int = 2) -> list[dict]:
    if not _INDEX:
        rows = _rows()
        _INDEX[:] = rows
    q_tokens = query_tokens(query)
    pine_hits = {doc_id: score for doc_id, score in embed.query_similar("register", query, top_k=12)}
    scored = []
    for item in _INDEX:
        lexical = _lex(q_tokens, item["tokens"])
        vector = pine_hits.get(item["key"], 0.0)
        if lexical <= 0 and vector <= 0:
            continue
        scored.append({"key": item["key"], "text": item["text"], "lexical": lexical, "vector": vector})
    if not scored:
        return [_unknown()]
    lex_rank = {row["key"]: i for i, row in enumerate(sorted((r for r in scored if r["lexical"] > 0), key=lambda r: r["lexical"], reverse=True))}
    vec_rank = {row["key"]: i for i, row in enumerate(sorted((r for r in scored if r["vector"] > 0), key=lambda r: r["vector"], reverse=True))}
    fused = embed.rrf(lex_rank, vec_rank, [row["key"] for row in scored])
    by_key = {row["key"]: row for row in scored}
    reranked = []
    for key, hybrid in fused:
        row = by_key[key]
        if row["text"] != REGISTER.get(key):
            continue
        if not _percent_ok(row["text"]):
            continue
        reranked.append(
            {
                "key": key,
                "text": row["text"],
                "lexical": round(row["lexical"], 4),
                "vector": round(row["vector"], 4),
                "hybrid": round(hybrid, 4),
            }
        )
    hits = [row for row in reranked if row["hybrid"] >= MIN_RRF][:limit]
    return hits or [_unknown()]
