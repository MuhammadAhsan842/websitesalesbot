"""Embed with Ollama nomic; store and query vectors in Pinecone only."""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import threading
from pathlib import Path
from time import perf_counter

import httpx

from app import db

log = logging.getLogger("ayyan.embed")

_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# Laptop default: nomic-embed-text on system Ollama (11434), never the chat process.
MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")
COMPARE = os.getenv("EMBED_COMPARE", "all-minilm")
URL = os.getenv("EMBED_URL", "http://127.0.0.1:11434").rstrip("/")
MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "512"))
RRF_K = 10

_lock = threading.Lock()
_last: dict = {"model": MODEL, "url": URL, "ready": False, "embedded": 0, "skipped": 0, "query_ms": None, "error": None}


def clip(text: str) -> str:
    value = " ".join((text or "").split())
    if len(value) <= MAX_CHARS:
        return value
    return value[:MAX_CHARS]


def digest(text: str) -> str:
    return hashlib.sha256(clip(text).encode("utf-8")).hexdigest()


def pack(vec: list[float]) -> bytes:
    """Kept for image/vision paths that still use SQLite blobs."""
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    """Kept for image/vision paths that still use SQLite blobs."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob)) if n else []


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
    """Text vectors live in Pinecone only — no local vector cache."""
    return None


def _remember_hash(kind: str, doc_id: str, sha: str, dims: int) -> None:
    """Hash-only row so we can skip re-embedding unchanged text (no vector blob used for search)."""
    db.execute(
        """INSERT INTO embeddings (id, kind, doc_id, model, dims, sha256, vec, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(kind, doc_id, model) DO UPDATE SET
             dims=excluded.dims, sha256=excluded.sha256, vec=excluded.vec, updated_at=excluded.updated_at""",
        (f"{kind}:{doc_id}:{MODEL}", kind, doc_id, MODEL, dims, sha, b"", db.now()),
    )


def upsert(kind: str, doc_id: str, text: str) -> list[float] | None:
    """Embed via Ollama; upsert vector to Pinecone only."""
    from app import vectorstore

    if not vectorstore.enabled():
        _last["error"] = "pinecone_disabled"
        log.error("PINECONE_API_KEY required — text vectors are Pinecone-only")
        return None

    body = clip(text)
    sha = digest(body)
    row = db.execute(
        "SELECT sha256 FROM embeddings WHERE kind=? AND doc_id=? AND model=?",
        (kind, doc_id, MODEL),
        fetch="one",
    )
    if row and row.get("sha256") == sha and vectorstore.has_vector(kind, doc_id):
        _last["skipped"] = int(_last.get("skipped") or 0) + 1
        return None

    vec = embed(body)
    if not vec:
        return None
    ok = vectorstore.upsert_vector(kind, doc_id, vec, metadata={"model": MODEL, "sha256": sha})
    if not ok:
        _last["error"] = vectorstore.status().get("error") or "pinecone_upsert_failed"
        return None
    _remember_hash(kind, doc_id, sha, len(vec))
    _last["embedded"] = int(_last.get("embedded") or 0) + 1
    _last["ready"] = True
    _last["error"] = None
    return vec


def query_similar(kind: str, text: str, top_k: int = 8) -> list[tuple[str, float]]:
    """ANN search against Pinecone only."""
    from app import vectorstore

    if not vectorstore.enabled():
        _last["error"] = "pinecone_disabled"
        return []
    q_vec = embed(text)
    if not q_vec:
        return []
    hits = vectorstore.query(kind, q_vec, top_k=top_k)
    if not hits and vectorstore.status().get("error"):
        _last["error"] = vectorstore.status().get("error")
    return hits


def load_cache(kind: str | None = None) -> int:
    """No-op: text vectors are not cached locally."""
    return 0


def ensure(kind: str, docs: list[dict]) -> dict:
    """docs: {id, text}. Sequential; vectors written only to Pinecone."""
    _last.update(model=MODEL, url=URL, embedded=0, skipped=0)
    for doc in docs:
        upsert(kind, doc["id"], doc.get("text") or "")
    return status()


def status() -> dict:
    pine = {}
    try:
        from app import vectorstore

        pine = vectorstore.status()
    except Exception:
        pine = {"enabled": False}
    return {
        "model": MODEL,
        "compare": COMPARE,
        "url": URL,
        "max_chars": MAX_CHARS,
        "ready": bool(pine.get("ready") or _last.get("ready")),
        "cached": 0,
        "embedded": _last.get("embedded") or 0,
        "skipped": _last.get("skipped") or 0,
        "query_ms": _last.get("query_ms"),
        "error": _last.get("error"),
        "production": "pinecone",
        "store": "pinecone-only",
        "pinecone": pine,
    }
