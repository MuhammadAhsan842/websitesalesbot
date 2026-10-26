"""Ayyan document checklist. Sample packet PDFs stay off the personality index."""

from __future__ import annotations

import re

from app.knowledge import lookup
from app.tasks import fact_value

ASK = re.compile(
    r"which (papers|docs|documents)|what (papers|documents|do i (send|need))|"
    r"setup packet|carrier packet|w-?9|\bcoi\b|certificate of insurance|"
    r"notice of assignment|\bnoa\b|voided check|authority sheet|"
    r"\busdot\b|\bmc authority|bill of lading|\bbol\b|rate conf|proof of delivery|\bpod\b|"
    r"\bifta\b|\beld\b|power of attorney|factoring agreement|"
    r"\bdetention\b|\blayover\b|\btonu\b|accessorial",
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
    "mc_authority": {
        "key": "docs_mc",
        "label": "MC authority",
        "match": re.compile(r"\bmc authority|authority sheet|motor carrier authority", re.I),
    },
    "usdot": {
        "key": "docs_usdot",
        "label": "USDOT number",
        "match": re.compile(r"\busdot\b|dot number", re.I),
    },
    "bol": {
        "key": "docs_bol",
        "label": "Bill of lading",
        "match": re.compile(r"bill of lading|\bbol\b", re.I),
    },
    "rate_con": {
        "key": "docs_rate_con",
        "label": "Rate confirmation",
        "match": re.compile(r"rate conf|rate confirmation", re.I),
    },
    "rate_con_detail": {
        "key": "docs_rate_con_detail",
        "label": "Rate confirmation scope",
        "match": re.compile(r"rate conf|rate confirmation|legal agreement for the load", re.I),
    },
    "pod": {
        "key": "docs_pod",
        "label": "Proof of delivery",
        "match": re.compile(r"proof of delivery|\bpod\b|delivery receipt", re.I),
    },
    "trip_invoice": {
        "key": "trip_docs_invoice",
        "label": "Trip paperwork and invoicing",
        "match": re.compile(
            r"paperwork.*invoic|invoic.*(bol|pod|paperwork)|after delivery.*(paper|doc)|"
            r"bol.*(pod|invoice)|pod.*(bol|invoice)",
            re.I,
        ),
    },
    "accessorials": {
        "key": "accessorials",
        "label": "Detention / layover / TONU",
        "match": re.compile(r"\bdetention\b|\blayover\b|\btonu\b|accessorial", re.I),
    },
    "ifta": {
        "key": "docs_ifta",
        "label": "IFTA",
        "match": re.compile(r"\bifta\b|fuel tax", re.I),
    },
    "eld": {
        "key": "docs_eld",
        "label": "ELD / logbook",
        "match": re.compile(r"\beld\b|logbook|hours of service|\bhos\b", re.I),
    },
    "poa": {
        "key": "docs_poa",
        "label": "Power of attorney",
        "match": re.compile(r"power of attorney|\bpoa\b", re.I),
    },
    "factoring": {
        "key": "docs_factoring",
        "label": "Factoring agreement",
        "match": re.compile(r"factoring agreement|factoring (company|paperwork)", re.I),
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
