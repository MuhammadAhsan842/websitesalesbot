"""Persist embeddings at ingest. Chat Ollama stays on the generative model."""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import threading
from time import perf_counter

import httpx

from app import db

log = logging.getLogger("ayyan.embed")

# Laptop default: nomic-embed-text on system Ollama (11434), never the chat process.
MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")
COMPARE = os.getenv("EMBED_COMPARE", "all-minilm")
URL = os.getenv("EMBED_URL", "http://127.0.0.1:11434").rstrip("/")
MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "512"))
RRF_K = 10

_lock = threading.Lock()
_cache: dict[tuple[str, str], list[float]] = {}
_last: dict = {"model": MODEL, "url": URL, "ready": False, "embedded": 0, "skipped": 0, "query_ms": None, "error": None}


def clip(text: str) -> str:
    value = " ".join((text or "").split())
    if len(value) <= MAX_CHARS:
        return value
    return value[:MAX_CHARS]


def digest(text: str) -> str:
    return hashlib.sha256(clip(text).encode("utf-8")).hexdigest()


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rrf(lex_rank: dict[str, int], vec_rank: dict[str, int], keys: list[str]) -> list[tuple[str, float]]:
    scored = []
    for key in keys:
        score = 0.0
        if key in lex_rank:
            score += 1 / (RRF_K + lex_rank[key] + 1)
        if key in vec_rank:
            score += 1 / (RRF_K + vec_rank[key] + 1)
        scored.append((key, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _infer(text: str) -> list[float] | None:
    if os.getenv("EMBED_MODEL", MODEL).strip().lower() in {"off", "none", "0"}:
        return None
    try:
        response = httpx.post(
            f"{URL}/api/embeddings",
            json={"model": MODEL, "prompt": clip(text)},
            timeout=20.0,
        )
        response.raise_for_status()
        vec = response.json().get("embedding")
        if not isinstance(vec, list) or not vec:
            return None
        return [float(x) for x in vec]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        _last["error"] = type(exc).__name__
        return None


def embed(text: str) -> list[float] | None:
    started = perf_counter()
    with _lock:
        vec = _infer(text)
    _last["query_ms"] = round((perf_counter() - started) * 1000, 2)
    _last["ready"] = bool(vec)
    return vec


def get_cached(kind: str, doc_id: str) -> list[float] | None:
    return _cache.get((kind, doc_id))


def upsert(kind: str, doc_id: str, text: str) -> list[float] | None:
    """Embed only when the clipped text hash changed for this model."""
    body = clip(text)
    sha = digest(body)
    key = (kind, doc_id)
    row = db.execute(
        "SELECT sha256, vec FROM embeddings WHERE kind=? AND doc_id=? AND model=?",
        (kind, doc_id, MODEL),
        fetch="one",
    )
    if row and row.get("sha256") == sha:
        vec = unpack(row["vec"])
        _cache[key] = vec
        _last["skipped"] = int(_last.get("skipped") or 0) + 1
        return vec
    vec = embed(body)
    if not vec:
        return None
    db.execute(
        """INSERT INTO embeddings (id, kind, doc_id, model, dims, sha256, vec, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(kind, doc_id, model) DO UPDATE SET
             dims=excluded.dims, sha256=excluded.sha256, vec=excluded.vec, updated_at=excluded.updated_at""",
        (f"{kind}:{doc_id}:{MODEL}", kind, doc_id, MODEL, len(vec), sha, pack(vec), db.now()),
    )
    _cache[key] = vec
    _last["embedded"] = int(_last.get("embedded") or 0) + 1
    _last["ready"] = True
    _last["error"] = None
    return vec


def load_cache(kind: str | None = None) -> int:
    sql = "SELECT kind, doc_id, vec FROM embeddings WHERE model=?"
    params: tuple = (MODEL,)
    if kind:
        sql += " AND kind=?"
        params = (MODEL, kind)
    rows = db.execute(sql, params, fetch="all") or []
    for row in rows:
        _cache[(row["kind"], row["doc_id"])] = unpack(row["vec"])
    return len(rows)


def ensure(kind: str, docs: list[dict]) -> dict:
    """docs: {id, text}. Sequential; one embedding process, no chat-model workers."""
    _last.update(model=MODEL, url=URL, embedded=0, skipped=0)
    load_cache(kind)
    for doc in docs:
        upsert(kind, doc["id"], doc.get("text") or "")
    return status()


def status() -> dict:
    return {
        "model": MODEL,
        "compare": COMPARE,
        "url": URL,
        "max_chars": MAX_CHARS,
        "ready": bool(_last.get("ready") or _cache),
        "cached": len(_cache),
        "embedded": _last.get("embedded") or 0,
        "skipped": _last.get("skipped") or 0,
        "query_ms": _last.get("query_ms"),
        "error": _last.get("error"),
        "production": "postgresql+pgvector",
    }
