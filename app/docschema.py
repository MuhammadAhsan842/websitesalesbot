"""Document-review contracts. Findings are evidence, never approval."""

from __future__ import annotations

import os
import re

from app.tasks import fact_value

FIELD_PRESENT = "present"
FIELD_BLANK = "blank"
FIELD_UNREADABLE = "unreadable"
FIELD_NOT_LOCATED = "not_located"
FIELD_CONFLICTING = "conflicting"

OUTCOMES = (FIELD_PRESENT, FIELD_BLANK, FIELD_UNREADABLE, FIELD_NOT_LOCATED, FIELD_CONFLICTING)

# Requirement / file statuses shown to drivers. Received is not approved.
STATUS_CHECKING = "checking"
STATUS_CLEARER_COPY = "clearer_copy"
STATUS_INFO_MISSING = "information_missing"
STATUS_MISMATCH = "possible_mismatch"
STATUS_AWAITING_REVIEW = "awaiting_review"

CUSTOMER_STATUS = {
    "issued": "Requested",
    "received": "Received / checking",
    "queued": "Received / checking",
    "checking": "Received / checking",
    "clearer_copy": "Clearer copy needed",
    "information_missing": "Information missing",
    "possible_mismatch": "Possible mismatch",
    "awaiting_review": "Automated checks passed / awaiting review",
    "under_review": "Automated checks passed / awaiting review",
    "acknowledged": "Automated checks passed / awaiting review",
    "approved": "Approved by authorized reviewer",
    "waived": "Approved by authorized reviewer",
    "flagged": "Needs attention",
    "corrections": "Information missing",
    "reopened": "Possible mismatch",
    "rejected": "Needs attention",
}

DRIVER_ACTION = frozenset(
    {"issued", "corrections", "reopened", "rejected", STATUS_CLEARER_COPY, STATUS_INFO_MISSING, STATUS_MISMATCH}
)
MANAGER_ACTION = frozenset(
    {
        "received",
        "queued",
        STATUS_CHECKING,
        "flagged",
        "under_review",
        "acknowledged",
        STATUS_AWAITING_REVIEW,
        STATUS_MISMATCH,
        STATUS_CLEARER_COPY,
        STATUS_INFO_MISSING,
    }
)

SENSITIVE_FIELDS = frozenset(
    {
        "licence_number",
        "date_of_birth",
        "address",
        "ssn",
        "tin",
        "ein",
        "account_number",
        "routing_number",
    }
)

LEASE_AUTO_MIN = 750_000
LEASE_CARGO_MIN = 100_000

REQUIREMENT_ALIASES = {
    "operating_authority_certificate": "authority",
    "mc_authority_letter": "authority",
    "usdot_carrier_document": "authority",
    "third_party_authority_report": "authority",
    "authority_report": "authority",
    "coi_remarks": "coi",
    "ein": "w9",
    "equipment_photo": "equipment_photos",
}

AUTHORITY_EVIDENCE = frozenset(REQUIREMENT_ALIASES) | {"authority"}


def field(status: str, value=None, page: int | None = None, evidence: str = "", confidence: str = "low") -> dict:
    if status not in OUTCOMES:
        status = FIELD_NOT_LOCATED
    return {
        "value": value if status == FIELD_PRESENT else None,
        "raw_value": value,
        "status": status,
        "page": page,
        "evidence": (evidence or "")[:240],
        "confidence": confidence,
    }


def mask_value(name: str, value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if name in SENSITIVE_FIELDS:
        return "***"
    if name == "vin" and len(re.sub(r"[^A-Za-z0-9]", "", text)) >= 11:
        compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        return f"{compact[:3]}********{compact[-4:]}"
    if name in {"licence_number", "dl_number"}:
        return "***"
    return text


def finding(
    code: str,
    *,
    why: str,
    field_name: str | None = None,
    document: str | None = None,
    page: int | None = None,
    expected: str | None = None,
    observed=None,
    outcome: str | None = None,
    severity: str = "review",
    next_action: str = "await_review",
    actor: str = "reviewer",
    evidence: str = "",
    confidence: str = "medium",
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "document": document,
        "page": page,
        "field": field_name,
        "expected": expected,
        "observed": mask_value(field_name or "", observed) if observed not in (None, "") else observed,
        "outcome": outcome,
        "why": why,
        "confidence": confidence,
        "next_action": next_action,
        "actor": actor,
        "evidence": (evidence or "")[:240],
        "message": why,
        "span": (evidence or "")[:120],
        "approved": False,
    }


def legal_carrier_for(facts: dict | None) -> str | None:
    facts = facts or {}
    for key in ("legalOperatingCompany", "legalCarrier", "operatingCompany"):
        value = fact_value(facts, key)
        if value:
            return str(value).strip()
    env = (os.getenv("AYYAN_LEGAL_CARRIER") or "").strip()
    return env or None


def arrangement_of(facts: dict | None) -> str | None:
    facts = facts or {}
    ownership = (fact_value(facts, "mcOwnership") or "").lower()
    requested = (fact_value(facts, "requestedArrangement") or "").lower()
    if ownership == "no_own_mc" or requested == "lease_on":
        return "lease_on"
    if ownership == "own_mc" or requested == "own_mc":
        return "own_mc"
    return None


def requirement_of(doc_type: str | None) -> str:
    wanted = (doc_type or "unknown").strip().lower()
    return REQUIREMENT_ALIASES.get(wanted, wanted)


def status_from_findings(findings: list[dict], *, photo: bool = False) -> str:
    if photo and not findings:
        return STATUS_AWAITING_REVIEW
    codes = {row.get("code") for row in findings}
    outcomes = {row.get("outcome") for row in findings}
    if {"clearer_copy_needed", "holder_unreadable", "field_unreadable"} & codes or FIELD_UNREADABLE in outcomes:
        if any(row.get("severity") == "blocking" and row.get("outcome") == FIELD_UNREADABLE for row in findings):
            return STATUS_CLEARER_COPY
        if any(row.get("code") in {"clearer_copy_needed", "holder_unreadable", "field_unreadable"} for row in findings):
            return STATUS_CLEARER_COPY
    if {"required_holder_missing", "field_blank"} & codes or any(
        row.get("outcome") == FIELD_BLANK and row.get("severity") == "blocking" for row in findings
    ):
        return STATUS_INFO_MISSING
    if {"holder_mismatch", "possible_equipment_mismatch", "name_mismatch"} & codes:
        return STATUS_MISMATCH
    blocking = [row for row in findings if row.get("severity") == "blocking"]
    if blocking:
        return STATUS_INFO_MISSING
    return STATUS_AWAITING_REVIEW


def driver_summary(findings: list[dict]) -> str:
    if not findings:
        return (
            "The file was received and automated checks did not find a configured issue. "
            "Onboarding still has to review it. Received is not approved."
        )
    lines = []
    for row in findings:
        if row.get("actor") == "driver" or row.get("severity") == "blocking":
            lines.append(row.get("why") or row.get("message"))
    if not lines:
        lines = [findings[0].get("why")]
    text = " ".join(part for part in lines if part)[:500]
    return text + " Nothing is approved from chat."


def manager_summary(findings: list[dict], arrangement: str | None = None) -> str:
    kind = "Lease-on" if arrangement == "lease_on" else "Own-MC" if arrangement == "own_mc" else "Document"
    if not findings:
        return f"{kind} document review: files received. No configured issue found. Human approval remains pending."
    bits = [f"{row.get('code')}: {row.get('why')}" for row in findings[:8]]
    return f"{kind} document review: " + " ".join(bits)[:800]
