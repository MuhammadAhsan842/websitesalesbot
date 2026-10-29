"""Pinecone vector store for nomic embeddings. SQLite keeps hash/cache; Pinecone is the ANN index."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("ayyan.vectorstore")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

API_KEY = os.getenv("PINECONE_API_KEY", "").strip()
INDEX_NAME = os.getenv("PINECONE_INDEX", "ayyan-sales").strip() or "ayyan-sales"
CLOUD = os.getenv("PINECONE_CLOUD", "aws").strip() or "aws"
REGION = os.getenv("PINECONE_REGION", "us-east-1").strip() or "us-east-1"
# nomic-embed-text default dims
DIMS = int(os.getenv("PINECONE_DIMS", "768"))
METRIC = os.getenv("PINECONE_METRIC", "cosine").strip() or "cosine"

_pc = None
_index = None
_last: dict = {"enabled": False, "index": INDEX_NAME, "error": None, "upserted": 0, "queried": 0}


def enabled() -> bool:
    return bool(API_KEY)


def status() -> dict:
    return {
        "enabled": enabled(),
        "index": INDEX_NAME,
        "cloud": CLOUD,
        "region": REGION,
        "dims": DIMS,
        "metric": METRIC,
        "ready": _index is not None,
        "error": _last.get("error"),
        "upserted": _last.get("upserted") or 0,
        "queried": _last.get("queried") or 0,
        "backend": "pinecone" if enabled() else "sqlite-only",
    }


def _safe_id(kind: str, doc_id: str) -> str:
    raw = f"{kind}:{doc_id}"
    return re.sub(r"[^A-Za-z0-9_\-:=]", "_", raw)[:512]


def _client():
    global _pc, _index
    if not enabled():
        return None
    if _index is not None:
        return _index
    try:
        from pinecone import Pinecone, ServerlessSpec

        _pc = Pinecone(api_key=API_KEY)
        names = {idx["name"] for idx in _pc.list_indexes()}
        if INDEX_NAME not in names:
            _pc.create_index(
                name=INDEX_NAME,
                dimension=DIMS,
                metric=METRIC,
                spec=ServerlessSpec(cloud=CLOUD, region=REGION),
            )
            log.info("created pinecone index %s dims=%s", INDEX_NAME, DIMS)
        _index = _pc.Index(INDEX_NAME)
        _last["enabled"] = True
        _last["error"] = None
        return _index
    except Exception as exc:  # noqa: BLE001
        _last["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("pinecone init failed: %s", exc)
        return None


def upsert_vector(kind: str, doc_id: str, values: list[float], metadata: dict | None = None) -> bool:
    """Write one embedding into Pinecone namespace=kind."""
    if not values:
        return False
    index = _client()
    if index is None:
        return False
    if len(values) != DIMS:
        _last["error"] = f"dim mismatch got={len(values)} want={DIMS}"
        return False
    try:
        meta = {"kind": kind, "doc_id": doc_id, **(metadata or {})}
        # Pinecone metadata values must be str/number/bool/list[str]
        clean = {}
        for key, val in meta.items():
            if val is None:
                continue
            if isinstance(val, (str, int, float, bool)):
                clean[key] = val
            else:
                clean[key] = str(val)[:500]
        index.upsert(
            vectors=[{"id": _safe_id(kind, doc_id), "values": values, "metadata": clean}],
            namespace=kind,
        )
        _last["upserted"] = int(_last.get("upserted") or 0) + 1
        _last["error"] = None
        return True
    except Exception as exc:  # noqa: BLE001
        _last["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("pinecone upsert failed: %s", exc)
        return False


def query(kind: str, values: list[float], top_k: int = 8) -> list[tuple[str, float]]:
    """Return [(doc_id, score)] from Pinecone for this kind namespace."""
    if not values:
        return []
    index = _client()
    if index is None:
        return []
    try:
        res = index.query(vector=values, top_k=top_k, namespace=kind, include_metadata=True)
        matches = getattr(res, "matches", None) or res.get("matches") or []
        out: list[tuple[str, float]] = []
        for match in matches:
            mid = getattr(match, "id", None) or match.get("id")
            score = float(getattr(match, "score", None) or match.get("score") or 0.0)
            meta = getattr(match, "metadata", None) or match.get("metadata") or {}
            doc_id = meta.get("doc_id") or (mid.split(":", 1)[-1] if mid and ":" in mid else mid)
            if doc_id:
                out.append((str(doc_id), score))
        _last["queried"] = int(_last.get("queried") or 0) + 1
        _last["error"] = None
        return out
    except Exception as exc:  # noqa: BLE001
        _last["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("pinecone query failed: %s", exc)
        return []


def has_vector(kind: str, doc_id: str) -> bool:
    """True if Pinecone already holds this id (used to skip re-embed)."""
    index = _client()
    if index is None:
        return False
    try:
        res = index.fetch(ids=[_safe_id(kind, doc_id)], namespace=kind)
        vectors = getattr(res, "vectors", None) or res.get("vectors") or {}
        return bool(vectors)
    except Exception as exc:  # noqa: BLE001
        _last["error"] = f"{type(exc).__name__}: {exc}"
        return False


def sync_from_sqlite(kind: str | None = None) -> dict:
    """One-shot migration of legacy SQLite vector blobs into Pinecone (ignores empty blobs)."""
    from app import db, embed

    sql = "SELECT kind, doc_id, vec, dims FROM embeddings WHERE model=?"
    params: tuple = (embed.MODEL,)
    if kind:
        sql += " AND kind=?"
        params = (embed.MODEL, kind)
    rows = db.execute(sql, params, fetch="all") or []
    ok = 0
    fail = 0
    skipped = 0
    for row in rows:
        blob = row.get("vec") or b""
        if not blob or row.get("dims", 0) == 0:
            skipped += 1
            continue
        vec = embed.unpack(blob)
        if len(vec) < 8:
            skipped += 1
            continue
        if upsert_vector(row["kind"], row["doc_id"], vec):
            ok += 1
        else:
            fail += 1
    return {"synced": ok, "failed": fail, "skipped_empty": skipped, "total": len(rows), **status()}
