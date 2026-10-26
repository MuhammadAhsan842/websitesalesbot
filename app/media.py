"""Chat attachments: OCR + CLIP image index + optional background Qwen vision."""

from __future__ import annotations

import re
from pathlib import Path

from app import db, embed, ingest, ocr, vision
from app.knowledge import lookup

ROOT = Path(__file__).resolve().parent.parent / "data" / "attachments"
PHOTO = re.compile(r"\.(jpe?g|png|webp|gif|heic|jfif)$", re.I)
CHATTY = re.compile(r"\b(ok|yeah|thanks|hello|got it|what do you)\b", re.I)
VISUAL = re.compile(r"\b(photo|picture|pic|image|attached|screenshot|this is my (truck|trailer|rig))\b", re.I)


def _word_count(text: str) -> int:
    return len(re.findall(r"[a-z0-9]+", (text or "").lower()))


def classify_kind(filename: str, ocr_text: str = "") -> str:
    name = (filename or "").lower()
    words = _word_count(ocr_text)
    if any(hint in name for hint in ("coi", "w9", "w-9", "noa", "packet", "lease")):
        return "document"
    if words >= 25 or CHATTY.search(ocr_text or ""):
        return "screenshot"
    if PHOTO.search(name):
        return "photo"
    return "document" if words else "photo"


def public_row(row: dict) -> dict:
    vision_body = row.get("vision") or {}
    return {
        "id": row["id"],
        "filename": row.get("filename"),
        "kind": row.get("kind"),
        "ocr_confidence": row.get("ocr_confidence"),
        "vision_status": row.get("vision_status"),
        "description": (vision_body.get("description") or "")[:180],
        "unverified": True,
        "not_approval": True,
    }


def _evidence_line(row: dict) -> str:
    vision_body = row.get("vision") or {}
    description = (vision_body.get("description") or "").strip()
    ocr_text = (row.get("ocr_text") or "").strip()
    if row.get("kind") == "screenshot" and ocr_text:
        snippet = " ".join(ocr_text.split())[:160]
        return f"OCR from a screenshot on this chat (unverified): {snippet}. Speaker labels are reconstructed, not confirmed."
    if description:
        return f"Unverified photo note: {description[:160]}. That is not equipment eligibility, insurance, or approval."
    return lookup("photo_unverified")


def process(path: Path, session_id: str | None = None, case_id: str | None = None, look: bool = False) -> dict:
    """OCR + image embed + optional vision. Cached by file hash. Never approves."""
    path = Path(path)
    digest = ingest.sha256_file(path)
    prior = db.get_attachment_by_hash(digest, session_id=session_id)
    if prior:
        return {**public_row(prior), "status": "duplicate", "attachment": prior}
    dest_dir = ROOT / (session_id or case_id or "loose")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:12]}_{path.name}"
    dest.write_bytes(path.read_bytes())
    shared = db.get_attachment_by_hash(digest)
    if shared and shared.get("session_id") and shared.get("session_id") != session_id:
        kind = shared.get("kind") or classify_kind(path.name, shared.get("ocr_text") or "")
        row = db.save_attachment(
            {
                "session_id": session_id,
                "case_id": case_id,
                "filename": path.name,
                "path": shared.get("path") or str(dest),
                "sha256": f"{digest}:{session_id}",
                "kind": kind,
                "ocr_text": shared.get("ocr_text"),
                "ocr_confidence": shared.get("ocr_confidence"),
                "vision": dict(shared.get("vision") or {}),
                "vision_status": shared.get("vision_status") or "pending",
            }
        )
        return {**public_row(row), "status": "processed", "attachment": row}
    read = ocr.read_document(dest)
    kind = classify_kind(path.name, read.get("text") or "")
    row = db.save_attachment(
        {
            "session_id": session_id,
            "case_id": case_id,
            "filename": path.name,
            "path": str(dest),
            "sha256": digest,
            "kind": kind,
            "ocr_text": ingest.strip_pii(read.get("text") or "")[:4000],
            "ocr_confidence": read.get("confidence"),
            "vision": {},
            "vision_status": "skipped" if kind == "screenshot" else "pending",
        }
    )
    if kind == "screenshot":
        row = db.save_attachment({**row, "vision": {"kind": "screenshot", "skipped": "ocr_preferred"}})
    vision.upsert_image(row["id"], dest)
    if look and kind != "screenshot":
        row = interpret(row["id"])
    elif kind != "screenshot":
        from app import qwen

        if not qwen.vision_enabled():
            row = db.save_attachment({**row, "vision_status": "skipped"})
    return {**public_row(row), "status": "processed", "attachment": row}


def interpret(attachment_id: str) -> dict:
    from app import qwen

    row = db.get_attachment(attachment_id)
    if not row:
        raise FileNotFoundError(attachment_id)
    if row.get("vision_status") == "cached" and row.get("vision"):
        return row
    if row.get("kind") == "screenshot":
        return db.save_attachment({**row, "vision_status": "skipped", "vision": {"kind": "screenshot", "skipped": "ocr_preferred"}})
    looked = qwen.look(row.get("path") or "", kind=row.get("kind") or "photo")
    if not looked:
        return db.save_attachment({**row, "vision_status": "skipped" if not qwen.vision_enabled() else "failed"})
    looked = qwen._sanitize_look(looked)
    looked["unverified"] = True
    looked.pop("approved", None)
    # Proposed facts stay on the attachment. They are not session facts and are not approval.
    return db.save_attachment({**row, "vision": looked, "vision_status": "cached"})


def search(query: str, session_id: str | None = None, limit: int = 3) -> list[dict]:
    """Fuse OCR BM25 with CLIP rankings. MiniLM is not used here."""
    rows = db.list_attachments(session_id=session_id)
    if not rows:
        return []
    tokens = {tok for tok in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(tok) > 2}
    lex_scores = {}
    for row in rows:
        doc = {tok for tok in re.findall(r"[a-z0-9]+", (row.get("ocr_text") or "").lower()) if len(tok) > 2}
        lex_scores[row["id"]] = len(tokens & doc) / max(len(tokens) or 1, 1)
    lex_ranked = [
        row["id"]
        for row in sorted(rows, key=lambda item: lex_scores[item["id"]], reverse=True)
        if lex_scores[row["id"]] > 0
    ]
    q_vec = vision.embed_text(query) if vision.enabled() else None
    vec_scores = {}
    for row in rows:
        img = vision.get_image_vec(row["id"])
        vec_scores[row["id"]] = embed.cosine(q_vec, img)
    vec_ranked = [key for key, score in sorted(vec_scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
    keys = list(dict.fromkeys(lex_ranked + vec_ranked + [row["id"] for row in rows]))
    lex_rank = {key: i for i, key in enumerate(lex_ranked)}
    vec_rank = {key: i for i, key in enumerate(vec_ranked)}
    order = [key for key, _ in embed.rrf(lex_rank, vec_rank, keys)]
    by_id = {row["id"]: row for row in rows}
    picked = []
    for key in order:
        row = by_id.get(key)
        if not row:
            continue
        if lex_scores.get(key, 0) <= 0 and vec_scores.get(key, 0) <= 0:
            continue
        picked.append({**public_row(row), "lexical": round(lex_scores.get(key, 0), 3), "image": round(vec_scores.get(key, 0), 3)})
        if len(picked) >= limit:
            break
    return picked


def session_evidence(session_id: str, user_text: str = "") -> list[str]:
    rows = db.list_attachments(session_id=session_id)
    if not rows or not VISUAL.search(user_text or ""):
        return []
    hits = search(user_text, session_id=session_id)
    chosen = db.get_attachment((hits[0] if hits else rows[0])["id"])
    return [_evidence_line(chosen)] if chosen else [lookup("photo_unverified")]
