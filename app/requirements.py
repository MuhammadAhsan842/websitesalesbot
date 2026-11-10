"""Issued packet requirements. A file is a transaction against a requirement, not a merged carrier record."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db

SLA_DAYS = 7

# Always for own-MC setup. NOA / voided check are conditional on payment arrangement.
# Customer-facing list: authority, W-9, COI, truck photos (+ conditional NOA / voided check).
CORE_SETUP = [
    ("setup", "Dispatch setup agreement"),
    ("authority", "MC authority sheet"),
    ("w9", "W-9"),
    ("coi", "Certificate of insurance"),
    ("equipment_photos", "Truck photos"),
]

CORE_LEASE = [
    ("licence", "Driving licence"),
    ("coi", "Certificate of insurance"),
    ("registration", "Truck registration"),
    ("equipment_photos", "Truck photos"),
]

# Quote-stage paperwork when coverage still needs arranging — never demand an existing COI.
INSURANCE_QUOTE = [
    ("licence", "Driving licence"),
    ("registration", "Truck registration"),
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
    from app.tasks import fact_value

    if task in {"callback", "clarification", "operations_support", "fit_check"}:
        return []
    insurance = fact_value(facts or {}, "insurance")
    route = fact_value(facts or {}, "insuranceRoute")
    if task in {"insurance_quote", "lease_agreement"} and (
        insurance == "needs_insurance" or route == "company_arranged"
    ):
        # Quote review precedes full lease packet; COI waits until coverage exists.
        return list(INSURANCE_QUOTE)
    if task == "lease_agreement":
        return list(CORE_LEASE)
    rows = list(CORE_SETUP)
    if insurance == "needs_insurance":
        rows = [(doc, label) for doc, label in rows if doc != "coi"]
    payment = (_payment_arrangement(facts) or "").lower()
    if payment == "factoring":
        rows.append(("notice_of_assignment", "Notice of assignment"))
    if payment in {"quick_pay", "factoring"}:
        rows.append(("voided_check", "Voided check"))
    # Unknown payment: do not auto-demand NOA or voided check.
    return rows


# Staff-only rows omitted from the customer document follow-up sentence.
_CUSTOMER_DOC_SKIP = frozenset({"setup"})


def customer_doc_labels(task: str | None = "setup_packet", facts: dict | None = None) -> list[str]:
    """Labels the driver should hear — kept in sync with catalog_for."""
    return [label for doc, label in catalog_for(task, facts) if doc not in _CUSTOMER_DOC_SKIP]


def customer_upload_options(task: str | None = None, facts: dict | None = None) -> list[dict]:
    """Document-type choices for the chat upload picker (checklist-aware + Not sure)."""
    from app.rules import arrangement_of, task_for

    facts = facts or {}
    arrangement = arrangement_of(facts)
    resolved = task or task_for(arrangement, "onboard", facts) or "setup_packet"
    options = [
        {"value": doc, "label": label}
        for doc, label in catalog_for(resolved, facts)
        if doc not in _CUSTOMER_DOC_SKIP
    ]
    options.append({"value": "unknown", "label": "Not sure"})
    return options


def customer_status_label(status: str | None) -> str:
    mapping = {
        "issued": "Requested",
        "received": "Received",
        "queued": "Received",
        "under_review": "Under review",
        "flagged": "Correction needed",
        "corrections": "Correction needed",
        "reopened": "Correction needed",
        "acknowledged": "Under review",
        "approved": "Approved",
        "waived": "Approved",
        "rejected": "Correction needed",
    }
    return mapping.get(str(status or "").lower(), "Received")


def customer_docs_sentence(task: str | None = "setup_packet", facts: dict | None = None) -> str:
    """Own-MC / lease document follow-up generated from the live requirements catalog."""
    labels = customer_doc_labels(task, facts)
    if not labels:
        return "Onboarding will confirm the live document list when they send the packet."
    payment = (_payment_arrangement(facts) or "").lower()
    core = [label for label in labels if label not in {"Notice of assignment", "Voided check"}]
    extras = []
    if "Notice of assignment" in labels:
        extras.append("a notice of assignment applies when you use factoring")
    elif payment != "factoring":
        extras.append("a notice of assignment applies if you use factoring")
    if "Voided check" in labels:
        extras.append("a voided check applies for quick-pay or factoring setups")
    elif payment not in {"quick_pay", "factoring"}:
        extras.append("a voided check applies where quick-pay or factoring requires it")
    if len(core) == 1:
        joined = core[0]
    elif len(core) == 2:
        joined = f"{core[0]} and {core[1]}"
    else:
        joined = ", ".join(core[:-1]) + f", and {core[-1]}"
    lead = (
        "For own-MC, onboarding usually asks for"
        if task == "setup_packet"
        else "Onboarding usually asks for"
    )
    sentence = f"{lead} the {joined}."
    if extras:
        sentence += " " + "; ".join(extras).capitalize() + "."
    sentence += " Files here stay unverified until they look — they'll confirm the live list with the packet."
    return sentence


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
    """An onboarding packet can clear review; quote intake cannot authorize dispatch."""
    case = db.get_case(case_id) or {}
    task = case.get("task")
    blockers = []
    if task not in {"setup_packet", "lease_agreement"}:
        blockers.append("insurance_quote_only" if task == "insurance_quote" else "not_onboarding_workflow")
    from app.tasks import fact_value

    if fact_value(case.get("facts") or {}, "insurance") == "needs_insurance":
        blockers.append("insurance_not_approved")
    rows = db.list_requirements(case_id)
    if not rows:
        return False, blockers + ["no_requirements_issued"]
    issued = {row["doc_type"] for row in rows}
    # A task/fact change must not reuse the smaller quote checklist as a full packet.
    for doc_type, _ in catalog_for(task, case.get("facts") or {}):
        if doc_type not in issued:
            blockers.append(f"{doc_type}:not_issued")
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
