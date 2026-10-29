"""Chunk project documents and upsert into Pinecone namespace `docs`."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from app import db, embed, ocr, vectorstore

log = logging.getLogger("ayyan.docindex")

ROOT = Path(__file__).resolve().parent.parent
KIND = "docs"

DOC_ROOTS = (
    ROOT / "notes-extract",
    ROOT / "docs",
    ROOT / "data" / "chats",
)

SKIP_NAMES = {"source_filename.txt", ".gitkeep"}
SKIP_SUFFIXES = {".jpeg", ".jpg", ".png", ".gif", ".webp", ".pdf", ".db", ".sqlite"}
TEXT_SUFFIXES = {".md", ".txt", ".jsonl", ".docx", ".json"}


def _chunk(text: str, size: int | None = None, overlap: int = 64) -> list[str]:
    size = size or max(200, embed.MAX_CHARS - 32)
    clean = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not clean:
        return []
    if len(clean) <= size:
        return [clean]
    parts: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            window = clean[start:end]
            br = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if br > size // 3:
                end = start + br + 1
        piece = clean[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return parts


def _read(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return (ocr.read_document(path).get("text") or "").strip()
    if suffix == ".jsonl":
        rows = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.dumps(json.loads(line), ensure_ascii=False))
            except json.JSONDecodeError:
                rows.append(line)
        return "\n".join(rows)
    if suffix in {".md", ".txt", ".json"}:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    return ""


def iter_files() -> list[Path]:
    found: list[Path] = []
    for root in DOC_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in SKIP_NAMES or path.name.startswith("."):
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            found.append(path)
    return sorted(found)


def _doc_id(path: Path, chunk_i: int, total: int) -> str:
    rel = path.relative_to(ROOT).as_posix()
    digest = hashlib.sha1(rel.encode()).hexdigest()[:10]
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", rel)[:80]
    return f"{safe}_{digest}_{chunk_i:04d}of{total:04d}"


def _hash_row(kind: str, doc_id: str) -> dict | None:
    return db.execute(
        "SELECT sha256 FROM embeddings WHERE kind=? AND doc_id=? AND model=?",
        (kind, doc_id, embed.MODEL),
        fetch="one",
    )


def _remember(kind: str, doc_id: str, sha: str, dims: int) -> None:
    db.execute(
        """INSERT INTO embeddings (id, kind, doc_id, model, dims, sha256, vec, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(kind, doc_id, model) DO UPDATE SET
             dims=excluded.dims, sha256=excluded.sha256, vec=excluded.vec, updated_at=excluded.updated_at""",
        (f"{kind}:{doc_id}:{embed.MODEL}", kind, doc_id, embed.MODEL, dims, sha, b"", db.now()),
    )


def ingest_all(*, force: bool = False) -> dict:
    """Embed every project text document into Pinecone `docs` namespace."""
    if not vectorstore.enabled():
        return {"ok": False, "error": "pinecone_disabled", "files": 0, "chunks": 0}
    files = iter_files()
    stats = {
        "files": len(files),
        "chunks": 0,
        "upserted": 0,
        "skipped": 0,
        "failed": 0,
        "empty": 0,
        "paths": [],
    }
    for path in files:
        try:
            text = _read(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("read failed %s: %s", path, exc)
            stats["failed"] += 1
            continue
        chunks = _chunk(text)
        if not chunks:
            stats["empty"] += 1
            continue
        rel = path.relative_to(ROOT).as_posix()
        stats["paths"].append(rel)
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            stats["chunks"] += 1
            doc_id = _doc_id(path, i, total)
            sha = embed.digest(chunk)
            row = _hash_row(KIND, doc_id)
            if (
                not force
                and row
                and row.get("sha256") == sha
                and vectorstore.has_vector(KIND, doc_id)
            ):
                stats["skipped"] += 1
                continue
            vec = embed.embed(chunk)
            if not vec:
                stats["failed"] += 1
                continue
            ok = vectorstore.upsert_vector(
                KIND,
                doc_id,
                vec,
                metadata={
                    "model": embed.MODEL,
                    "path": rel,
                    "chunk": i,
                    "chunks": total,
                    "source": path.suffix.lower().lstrip(".") or "txt",
                    "preview": chunk[:180],
                    "sha256": sha,
                },
            )
            if not ok:
                stats["failed"] += 1
                continue
            _remember(KIND, doc_id, sha, len(vec))
            stats["upserted"] += 1
    stats["pinecone"] = vectorstore.status()
    stats["ok"] = stats["failed"] == 0
    return stats


def search(query: str, top_k: int = 6) -> list[dict]:
    """Query document chunks from Pinecone."""
    hits = embed.query_similar(KIND, query, top_k=top_k)
    return [{"id": doc_id, "score": round(float(score), 4), "kind": KIND} for doc_id, score in hits]
