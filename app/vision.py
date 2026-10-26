"""CLIP-space image embeddings. Never mixed with MiniLM text vectors."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from time import perf_counter

import httpx

from app import db, embed

log = logging.getLogger("ayyan.vision")

MODEL = os.getenv("IMAGE_EMBED_MODEL", "off")
URL = os.getenv("IMAGE_EMBED_URL", os.getenv("EMBED_URL", "http://127.0.0.1:11434")).rstrip("/")
KIND = "image"

_last: dict = {"model": MODEL, "url": URL, "ready": False, "error": None, "query_ms": None, "backend": None}
_text_fn = None
_image_fn = None


def enabled() -> bool:
    return (os.getenv("IMAGE_EMBED_MODEL", MODEL) or "off").strip().lower() not in {"off", "none", "0", ""}


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ollama_embed(payload: dict) -> list[float] | None:
    try:
        response = httpx.post(f"{URL}/api/embed", json=payload, timeout=30.0)
        if response.status_code >= 400:
            response = httpx.post(f"{URL}/api/embeddings", json=payload, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        vec = body.get("embedding")
        if not vec and body.get("embeddings"):
            vec = body["embeddings"][0]
        if not isinstance(vec, list) or not vec:
            return None
        return [float(x) for x in vec]
    except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
        _last["error"] = type(exc).__name__
        return None


def _clip_backend():
    """Optional local CLIP/SigLIP. Missing deps stay off — not a required install."""
    try:
        import open_clip
        import torch
        from PIL import Image
    except Exception:
        return None
    name = os.getenv("IMAGE_CLIP_ARCH", "ViT-B-32")
    pretrained = os.getenv("IMAGE_CLIP_WEIGHTS", "openai")
    model, _, preprocess = open_clip.create_model_and_transforms(name, pretrained=pretrained)
    tokenizer = open_clip.get_tokenizer(name)
    model.eval()

    def image(path: Path) -> list[float] | None:
        with torch.no_grad():
            tensor = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)
            vec = model.encode_image(tensor)
            vec = vec / vec.norm(dim=-1, keepdim=True)
            return [float(x) for x in vec.squeeze().tolist()]

    def text(query: str) -> list[float] | None:
        with torch.no_grad():
            tokens = tokenizer([query])
            vec = model.encode_text(tokens)
            vec = vec / vec.norm(dim=-1, keepdim=True)
            return [float(x) for x in vec.squeeze().tolist()]

    return f"open_clip:{name}:{pretrained}", image, text


def _bind():
    global _text_fn, _image_fn
    if _text_fn and _image_fn:
        return
    if not enabled():
        _last.update(backend="off", ready=False)
        return
    clip = _clip_backend()
    if clip:
        backend, image_fn, text_fn = clip
        _image_fn, _text_fn = image_fn, text_fn
        _last.update(backend=backend, ready=True, error=None)
        return

    model = os.getenv("IMAGE_EMBED_MODEL", MODEL)

    def image(path: Path) -> list[float] | None:
        return _ollama_embed({"model": model, "input": path.name, "images": [_b64(path)]})

    def text(query: str) -> list[float] | None:
        return _ollama_embed({"model": model, "input": query or path_label(query)})

    _image_fn, _text_fn = image, text
    _last.update(backend=f"ollama:{model}", ready=False)


def path_label(query: str) -> str:
    return " ".join((query or "").split())[:200]


def embed_image(path: str | Path) -> list[float] | None:
    _bind()
    if not _image_fn:
        return None
    started = perf_counter()
    vec = _image_fn(Path(path))
    _last["query_ms"] = round((perf_counter() - started) * 1000, 2)
    _last["ready"] = bool(vec)
    return vec


def embed_text(query: str) -> list[float] | None:
    """Text queries into the image index must use this encoder, never MiniLM."""
    _bind()
    if not _text_fn:
        return None
    started = perf_counter()
    vec = _text_fn(query)
    _last["query_ms"] = round((perf_counter() - started) * 1000, 2)
    _last["ready"] = bool(vec)
    return vec


def upsert_image(doc_id: str, path: str | Path) -> list[float] | None:
    path = Path(path)
    if not path.exists():
        return None
    model = os.getenv("IMAGE_EMBED_MODEL", MODEL)
    sha = file_digest(path)
    row = db.execute(
        "SELECT sha256, vec FROM embeddings WHERE kind=? AND doc_id=? AND model=?",
        (KIND, doc_id, model),
        fetch="one",
    )
    if row and row.get("sha256") == sha:
        return embed.unpack(row["vec"])
    vec = embed_image(path)
    if not vec:
        return None
    db.execute(
        """INSERT INTO embeddings (id, kind, doc_id, model, dims, sha256, vec, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(kind, doc_id, model) DO UPDATE SET
             dims=excluded.dims, sha256=excluded.sha256, vec=excluded.vec, updated_at=excluded.updated_at""",
        (f"{KIND}:{doc_id}:{model}", KIND, doc_id, model, len(vec), sha, embed.pack(vec), db.now()),
    )
    return vec


def get_image_vec(doc_id: str) -> list[float] | None:
    model = os.getenv("IMAGE_EMBED_MODEL", MODEL)
    row = db.execute(
        "SELECT vec FROM embeddings WHERE kind=? AND doc_id=? AND model=?",
        (KIND, doc_id, model),
        fetch="one",
    )
    if not row:
        return None
    return embed.unpack(row["vec"])


def status() -> dict:
    return {
        "model": os.getenv("IMAGE_EMBED_MODEL", MODEL),
        "url": URL,
        "space": "clip",
        "separate_from": embed.MODEL,
        "backend": _last.get("backend") or ("off" if not enabled() else "unbound"),
        "ready": bool(_last.get("ready")),
        "query_ms": _last.get("query_ms"),
        "error": _last.get("error"),
        "note": "Image vectors are never compared to MiniLM. Fuse rankings with RRF.",
    }
