"""Chat-PDF → candidate examples. Packets, COIs, W-9s, and IDs never enter the bank."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app import db, examples, ocr
from app.examples import LEAK, allowed

PACKET_HINTS = (
    "w-9",
    "w9",
    "coi",
    "acord",
    "noa",
    "setup packet",
    "carrier setup",
    "notice of assignment",
    "certificate of liability",
)
IDENTITY_HINTS = ("driver license", "driver licence", "buyer's plate", "plate receipt")
CHAT_HINTS = ("union", "ezequiel", "moses", "jason chat", "jason chats", "chats")
PII = re.compile(
    r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    r"|[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}"
    r"|\bMC[-\s]?\d{5,}\b"
    r"|\bDOT\s*\d{5,}\b"
    r"|\b1[A-HJ-NPR-Z0-9]{16}\b",
    re.I,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(filename: str, text: str = "") -> str:
    blob = f"{filename} {text[:800]}".lower()
    if any(hint in blob for hint in PACKET_HINTS):
        return "packet"
    if any(hint in blob for hint in IDENTITY_HINTS):
        return "identity"
    if any(hint in blob for hint in CHAT_HINTS):
        return "chat"
    return "other"


def strip_pii(text: str) -> str:
    return PII.sub("[redacted]", text or "")


def extract_turns(text: str) -> list[dict]:
    """Best-effort speaker split for OCR/native chat dumps. Order is preserved."""
    turns = []
    for raw in re.split(r"\n+", text or ""):
        line = strip_pii(raw).strip()
        if len(line) < 8:
            continue
        if re.search(r"certificate of liability|form w-9|notice of assignment", line, re.I):
            continue
        role = "driver" if not re.search(r"^(hello|hi |got it|perfect|sir,|we |i saw)", line, re.I) else "sales"
        if re.search(r"\b(i need|i have|i don't|im |i'm |tell him|let's see|too much|sign for)\b", line, re.I):
            role = "driver"
        turns.append({"role": role, "text": line[:400]})
    return turns[:80]


def _rewrite_reply(text: str) -> str | None:
    if not text or LEAK.search(text):
        return None
    cleaned = strip_pii(text).strip()
    if len(cleaned) < 12:
        return None
    return cleaned[:220]


def candidates_from_turns(turns: list[dict], source: str) -> list[dict]:
    out = []
    context = ""
    last_driver = None
    for turn in turns:
        if turn["role"] == "driver":
            last_driver = turn["text"]
            context = (context + " " + turn["text"]).strip()[-240:]
            continue
        if not last_driver:
            continue
        reply = _rewrite_reply(turn["text"])
        if not reply:
            continue
        item = {
            "id": f"{source}_{len(out)+1}",
            "source": source,
            "user": last_driver[:240],
            "context": context[:240],
            "reply": reply,
            "move": "acknowledge",
            "variant": "ack_constraints",
            "tags": [],
            "status": "candidate",
        }
        if allowed(item):
            out.append(item)
        last_driver = None
    return out[:40]


def ingest_path(path: Path, reviewed_by: str = "staff") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    digest = sha256_file(path)
    prior = db.get_example_source_by_hash(digest)
    if prior:
        return {"status": "duplicate", "source": prior, "examples": []}
    read = ocr.read_document(path)
    kind = classify(path.name, read.get("text") or "")
    row = db.save_example_source(
        {
            "filename": path.name,
            "sha256": digest,
            "kind": kind,
            "status": "rejected_kind" if kind != "chat" else "ingested",
            "pages": (read.get("text") or "").count("\f") + 1,
            "method": read.get("method"),
        }
    )
    if kind != "chat":
        return {"status": "rejected_kind", "source": row, "examples": [], "kind": kind}
    turns = extract_turns(read.get("text") or "")
    created = []
    for item in candidates_from_turns(turns, path.stem.lower().replace(" ", "_")[:40]):
        item["source_id"] = row["id"]
        created.append(db.save_example(item))
    examples.reload_index()
    return {"status": "ingested", "source": row, "examples": created, "kind": kind, "reviewed_by": reviewed_by}


CHAT_SEEDS = (
    Path("/home/muhammad/Downloads/Union moving.pdf"),
    Path("/home/muhammad/Downloads/Jason Chats.1.pdf"),
    Path("/home/muhammad/Downloads/Moses banks.pdf"),
    Path("/home/muhammad/Downloads/Ezequiel.pdf"),
)

SKIP_SEEDS = (
    Path("/home/muhammad/Downloads/ATL Fast Freight LLC Carrier Setup Packet (1).pdf"),
    Path("/home/muhammad/Downloads/W9(2).pdf"),
    Path("/home/muhammad/Downloads/Carroll Transport - COI - Leo Dispatch.pdf"),
    Path("/home/muhammad/Downloads/NOA - 2026-09-08T143520.312(2).pdf"),
)


def seed_reviewed_bank() -> dict:
    """Publish the rewritten bank without overwriting staff review decisions."""
    published = 0
    skipped_staff = 0
    for row in examples.BANK:
        if not allowed(row):
            continue
        current = db.get_example(row["id"])
        if current and (
            current.get("status") in {"withdrawn", "rejected"}
            or (current.get("reviewed_by") and current.get("reviewed_by") not in {"seed_rewrite", None})
        ):
            skipped_staff += 1
            continue
        db.save_example(
            {
                "id": row["id"],
                "source": row.get("source"),
                "user_text": row["user"],
                "context": row.get("context"),
                "situation": row.get("situation") or row.get("context"),
                "strategy": row.get("strategy"),
                "pattern": row.get("pattern"),
                "reply": row["reply"],
                "move": row["move"],
                "variant": row["variant"],
                "tags": list(row.get("tags") or ()),
                "applicability": list(row.get("tags") or ()),
                "status": "published",
                "reviewed_by": "seed_rewrite",
                "version": 1,
            }
        )
        published += 1
    sources = []
    for path in CHAT_SEEDS:
        if not path.exists():
            continue
        digest = sha256_file(path)
        sources.append(
            db.save_example_source(
                {
                    "filename": path.name,
                    "sha256": digest,
                    "kind": "chat",
                    "status": "ingested",
                    "pages": 0,
                    "method": "reviewed_seed",
                }
            )
        )
    skipped = []
    for path in SKIP_SEEDS:
        if not path.exists():
            continue
        digest = sha256_file(path)
        skipped.append(
            db.save_example_source(
                {
                    "filename": path.name,
                    "sha256": digest,
                    "kind": classify(path.name),
                    "status": "rejected_kind",
                    "pages": 0,
                    "method": "not_an_example",
                }
            )
        )
    n = examples.reload_index()
    return {
        "published": published,
        "preserved_staff": skipped_staff,
        "chat_sources": len(sources),
        "skipped_private": len(skipped),
        "index": n,
        "version": examples.VERSION,
    }
