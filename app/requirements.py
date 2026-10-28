"""Issued packet requirements. A file is a transaction against a requirement, not a merged carrier record."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db

SLA_DAYS = 7

# Always for own-MC setup. NOA / voided check are conditional on payment arrangement.
CORE_SETUP = [
    ("setup", "Dispatch setup agreement"),
    ("authority", "MC authority sheet"),
    ("w9", "W-9"),
    ("coi", "Certificate of insurance"),
]

CORE_LEASE = [
    ("lease", "Lease agreement"),
    ("licence", "Driver licence"),
    ("coi", "Certificate of insurance"),
    ("medical", "Medical card"),
    ("inspection", "Inspection"),
    ("w9", "W-9"),
    ("registration", "Cab card / registration"),
    ("equipment_photos", "Truck photos"),
]

SAMPLE_TYPES = {
    "lease": "lease",
    "setup": "setup",
    "registration": "registration",
    "coi": "coi",
}

# Acknowledge / received / flagged are never enough for handoff.
TERMINAL_OK = frozenset({"approved", "waived"})
OPEN_STATUSES = frozenset(
    {"issued", "received", "flagged", "reopened", "queued", "under_review", "corrections", "acknowledged"}
)


def _due(days: int = SLA_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _payment_arrangement(facts: dict | None) -> str | None:
    from app.tasks import fact_value

    return fact_value(facts or {}, "paymentArrangement")


def catalog_for(task: str | None, facts: dict | None = None) -> list[tuple[str, str]]:
    if task in {"callback", "clarification", "operations_support", "fit_check"}:
        return []
    if task == "lease_agreement":
        return list(CORE_LEASE)
    rows = list(CORE_SETUP)
    payment = (_payment_arrangement(facts) or "").lower()
    if payment == "factoring":
        rows.append(("notice_of_assignment", "Notice of assignment"))
    if payment in {"quick_pay", "factoring"}:
        rows.append(("voided_check", "Voided check"))
    # Unknown payment: do not auto-demand NOA or voided check.
    return rows


def issue(case_id: str, task: str | None, due_at: str | None = None, facts: dict | None = None) -> list[dict]:
    case = db.get_case(case_id) or {}
    facts = facts if facts is not None else (case.get("facts") or {})
    existing = {row["doc_type"]: row for row in db.list_requirements(case_id)}
    due = due_at or _due()
    saved = []
    wanted = {doc_type for doc_type, _ in catalog_for(task, facts)}
    for doc_type, label in catalog_for(task, facts):
        if doc_type in existing:
            saved.append(existing[doc_type])
            continue
        saved.append(
            db.add_requirement(
                {
                    "case_id": case_id,
                    "doc_type": doc_type,
                    "label": label,
                    "status": "issued",
                    "due_at": due,
                }
            )
        )
    # Drop auto-issued conditionals that no longer apply (only if still issued, never touched).
    for doc_type, row in existing.items():
        if doc_type in wanted:
            continue
        if doc_type in {"notice_of_assignment", "voided_check"} and row.get("status") == "issued" and not row.get(
            "current_file_id"
        ):
            decide(
                case_id,
                doc_type,
                "waived",
                reviewer="system",
                reason=f"Not applicable for payment arrangement {_payment_arrangement(facts) or 'unspecified'}",
            )
    return db.list_requirements(case_id)


def mark_due(case_id: str) -> list[dict]:
    due = _due()
    for row in db.list_requirements(case_id):
        if row["status"] == "issued" or not row.get("due_at"):
            db.update_requirement(row["id"], {"due_at": due})
    return db.list_requirements(case_id)


def receive(case_id: str, doc_type: str, file_id: str | None, status: str) -> dict | None:
    row = db.get_requirement(case_id, doc_type)
    if not row:
        row = db.add_requirement(
            {
                "case_id": case_id,
                "doc_type": doc_type,
                "label": doc_type.replace("_", " ").title(),
                "status": "issued",
                "due_at": _due(),
            }
        )
    # Received / queued is never approval.
    safe = status if status in {"received", "flagged", "queued", "reopened", "under_review"} else "received"
    db.update_requirement(
        row["id"],
        {"status": safe, "current_file_id": file_id},
    )
    return db.get_requirement_by_id(row["id"])


def reopen(case_id: str, doc_type: str, reason: str) -> None:
    row = db.get_requirement(case_id, doc_type)
    if row:
        db.update_requirement(row["id"], {"status": "reopened"})
    case = db.get_case(case_id)
    if not case:
        return
    if case.get("status") in {"approved_for_handoff", "production_accepted", "acknowledged"}:
        db.upsert_case(
            {
                "id": case_id,
                "status": "under_review",
                "next_action": "Human re-review — a replacement file reopened this requirement",
                "documents": case.get("documents") or [],
                "facts": case.get("facts") or {},
                "session_id": case.get("session_id"),
                "opportunity_id": case.get("opportunity_id"),
                "task": case.get("task"),
                "summary": case.get("summary"),
                "owner": case.get("owner"),
            }
        )
    db.add_event("Requirement reopened", {"caseId": case_id, "docType": doc_type, "reason": reason})


def _validate_decision_file(case_id: str, doc_type: str, file_id: str | None) -> str | None:
    """Approve only against a real, current case file for this requirement."""
    if not file_id:
        return None
    file_row = db.get_case_file(file_id)
    if not file_row:
        raise ValueError("file not found")
    if file_row.get("case_id") != case_id:
        raise ValueError("file does not belong to this case")
    file_doc = file_row.get("doc_type")
    if file_doc and file_doc != doc_type and file_doc not in {doc_type, "unknown", "other"}:
        # Allow unknown OCR class only when requirement already points at this file.
        raise ValueError("file document type does not match this requirement")
    latest = db.latest_file(case_id, doc_type) or db.latest_file(case_id, file_doc or doc_type)
    if latest and latest.get("id") != file_id:
        raise ValueError("file is not the current version for this requirement")
    return file_id


def decide(
    case_id: str,
    doc_type: str,
    decision: str,
    reviewer: str,
    reason: str = "",
    file_id: str | None = None,
) -> dict:
    """Explicit per-document decision. Acknowledge ≠ approve."""
    decision = (decision or "").lower().strip()
    if decision not in {"approve", "reject", "waive", "corrections"}:
        raise ValueError("decision must be approve, reject, waive, or corrections")
    if not (reviewer or "").strip():
        raise ValueError("reviewer is required")
    row = db.get_requirement(case_id, doc_type)
    if not row:
        raise ValueError(f"no requirement for {doc_type}")
    bound_file = None
    if decision == "approve":
        # Applicable conditionals (NOA / voided check) need evidence too — waive is separate.
        current_file = file_id or row.get("current_file_id")
        if not current_file:
            raise ValueError("cannot approve without a returned file on this requirement")
        bound_file = _validate_decision_file(case_id, doc_type, current_file)
        status = "approved"
    elif decision == "waive":
        if not (reason or "").strip():
            raise ValueError("waive requires an explicit reason (authorized waiver)")
        status = "waived"
    elif decision == "reject":
        status = "rejected"
        if file_id:
            bound_file = _validate_decision_file(case_id, doc_type, file_id)
    else:
        status = "corrections"
        if file_id:
            bound_file = _validate_decision_file(case_id, doc_type, file_id)
    patch: dict = {"status": status}
    if bound_file:
        patch["current_file_id"] = bound_file
    updated = db.update_requirement(row["id"], patch)
    db.add_event(
        "Requirement decision",
        {
            "caseId": case_id,
            "docType": doc_type,
            "decision": decision,
            "status": status,
            "reviewer": reviewer,
            "reason": reason,
            "fileId": bound_file or file_id or row.get("current_file_id"),
            "requirementId": row["id"],
        },
    )
    return updated or row


def outstanding(case_id: str) -> list[dict]:
    return [row for row in db.list_requirements(case_id) if row.get("status") in OPEN_STATUSES or row.get("status") == "rejected"]


def ready_for_handoff(case_id: str) -> tuple[bool, list[str]]:
    """All applicable requirements must be approved or waived. Ack/flag alone is not enough."""
    rows = db.list_requirements(case_id)
    if not rows:
        return False, ["no_requirements_issued"]
    blockers = []
    for row in rows:
        status = row.get("status")
        doc_type = row.get("doc_type")
        if status in TERMINAL_OK:
            if status == "approved":
                file_id = row.get("current_file_id")
                file_row = db.get_case_file(file_id) if file_id else None
                if not file_row or file_row.get("case_id") != case_id:
                    blockers.append(f"{doc_type}:missing_file")
                    continue
            # waived is an authorized exception — no file required
            continue
        blockers.append(f"{doc_type}:{status or 'missing'}")
    return (not blockers), blockers


def snapshot(case_id: str) -> dict:
    rows = db.list_requirements(case_id)
    now = datetime.now(timezone.utc)
    overdue = []
    for row in rows:
        due = row.get("due_at")
        if not due or row.get("status") in TERMINAL_OK | {"rejected"}:
            row["overdue"] = False
            continue
        try:
            stamp = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except ValueError:
            row["overdue"] = False
            continue
        row["overdue"] = stamp < now and row.get("status") in OPEN_STATUSES
        if row["overdue"]:
            overdue.append(row)
    returned = [row for row in rows if row.get("status") not in {"issued", None}]
    awaiting_review = [
        row["doc_type"]
        for row in rows
        if row.get("status") in {"received", "flagged", "queued", "under_review", "acknowledged"}
    ]
    ready, blockers = ready_for_handoff(case_id)
    return {
        "requirements": rows,
        "issued": len(rows),
        "returned": len(returned),
        "overdue": len(overdue),
        # Still needed from the driver (not yet returned).
        "outstanding": [row["doc_type"] for row in rows if row.get("status") in {"issued", "corrections", "reopened", "rejected"}],
        "awaiting_review": awaiting_review,
        "ready_for_handoff": ready,
        "handoff_blockers": blockers,
    }
