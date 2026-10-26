"""Ayyan document checklist. Sample packet PDFs stay off the personality index."""

from __future__ import annotations

import re

from app.knowledge import lookup
from app.tasks import fact_value

ASK = re.compile(
    r"which (papers|docs|documents)|what (papers|documents|do i (send|need))|"
    r"setup packet|carrier packet|w-?9|\bcoi\b|certificate of insurance|"
    r"notice of assignment|\bnoa\b|voided check|authority sheet",
    re.I,
)
SENT = re.compile(r"\b(i (sent|uploaded|attached|submitted)|here('?s| is) (my |the )?(w-?9|coi|noa|packet))\b", re.I)

TEMPLATES = {
    "w9": {
        "key": "docs_w9",
        "label": "W-9",
        "match": re.compile(r"w-?9", re.I),
    },
    "coi": {
        "key": "docs_coi",
        "label": "Certificate of insurance",
        "match": re.compile(r"\bcoi\b|certificate of (liability|insurance)", re.I),
    },
    "notice_of_assignment": {
        "key": "docs_noa",
        "label": "Notice of assignment",
        "match": re.compile(r"\bnoa\b|notice of assignment", re.I),
    },
    "setup": {
        "key": "docs_packet",
        "label": "Setup packet",
        "match": re.compile(r"setup packet|carrier packet|onboarding (process|packet)", re.I),
    },
}


def asked(text: str) -> bool:
    return bool(ASK.search(text or "") or SENT.search(text or ""))


def keys_for(text: str, arrangement: str | None = None) -> list[str]:
    t = text or ""
    keys: list[str] = []
    for item in TEMPLATES.values():
        if item["match"].search(t):
            keys.append(item["key"])
    if not keys and asked(t):
        keys.append("docs_lease" if arrangement == "lease_on" else "docs_own")
    if SENT.search(t) and "photo_unverified" not in keys:
        keys.append("photo_unverified")
    if asked(t) and "docs_status" not in keys:
        keys.append("docs_status")
    return list(dict.fromkeys(keys))


def missing_line(session: dict | None) -> str:
    """Outstanding items on the issued case list. Never treats a chat upload as complete."""
    from app import requirements

    session = session or {}
    facts = session.get("facts") or {}
    arrangement = "lease_on" if fact_value(facts, "mcOwnership") == "no_own_mc" else None
    catalog = lookup("docs_lease") if arrangement == "lease_on" else lookup("docs_own")
    case_id = session.get("case_id")
    if not case_id:
        return catalog + " Onboarding hasn't sent a packet on this chat yet. A file here is just stored until they look at it."
    snap = requirements.snapshot(case_id)
    if not snap.get("issued"):
        return catalog + " Onboarding hasn't sent a packet on this case yet."
    outstanding = []
    labels = {key: item["label"] for key, item in TEMPLATES.items()}
    labels.update(
        {
            "authority": "MC authority sheet",
            "voided_check": "voided check",
            "lease": "lease agreement",
            "licence": "licence",
            "medical": "medical card",
            "inspection": "inspection",
            "registration": "registration",
            "equipment_photos": "truck photos",
            "setup": "setup agreement",
        }
    )
    for doc_type in snap.get("outstanding") or []:
        outstanding.append(labels.get(doc_type, doc_type.replace("_", " ")))
    if outstanding:
        return (
            "Still outstanding with onboarding: "
            + ", ".join(outstanding)
            + ". A file on this chat is unverified until onboarding looks at it. Received is not approved."
        )
    return "Onboarding has files on this case. They still need to review them. A COI on file isn't insurance approved."
