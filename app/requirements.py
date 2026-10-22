"""Issued packet requirements. A file is a transaction against a requirement, not a merged carrier record."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db

SLA_DAYS = 7

BY_TASK = {
    "setup_packet": [
        ("setup", "Dispatch setup agreement"),
        ("authority", "MC authority sheet"),
        ("w9", "W-9"),
        ("coi", "Certificate of insurance"),
        ("notice_of_assignment", "Notice of assignment"),
        ("voided_check", "Voided check"),
    ],
    "lease_agreement": [
        ("lease", "Lease agreement"),
        ("licence", "Driver licence"),
        ("coi", "Certificate of insurance"),
        ("medical", "Medical card"),
        ("inspection", "Inspection"),
        ("w9", "W-9"),
        ("registration", "Cab card / registration"),
        ("equipment_photos", "Truck photos"),
    ],
}

SAMPLE_TYPES = {
    "lease": "lease",
    "setup": "setup",
    "registration": "registration",
    "coi": "coi",
}


def _due(days: int = SLA_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def catalog_for(task: str | None) -> list[tuple[str, str]]:
    if task in BY_TASK:
        return BY_TASK[task]
    if task in {"callback", "clarification", "operations_support", "fit_check"}:
        return []
    return BY_TASK["setup_packet"]


def issue(case_id: str, task: str | None, due_at: str | None = None) -> list[dict]:
    existing = {row["doc_type"]: row for row in db.list_requirements(case_id)}
    due = due_at or _due()
    saved = []
    for doc_type, label in catalog_for(task):
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
    return saved


def mark_due(case_id: str) -> list[dict]:
    due = _due()
    for row in db.list_requirements(case_id):
        if row["status"] == "issued" or not row.get("due_at"):
            db.update_requirement(row["id"], {"due_at": due})
    return db.list_requirements(case_id)


def receive(case_id: str, doc_type: str, file_id: str, status: str) -> dict | None:
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
    db.update_requirement(
        row["id"],
        {"status": status, "current_file_id": file_id},
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


def snapshot(case_id: str) -> dict:
    rows = db.list_requirements(case_id)
    now = datetime.now(timezone.utc)
    overdue = []
    for row in rows:
        due = row.get("due_at")
        if not due or row.get("status") in {"acknowledged", "waived"}:
            row["overdue"] = False
            continue
        try:
            stamp = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except ValueError:
            row["overdue"] = False
            continue
        row["overdue"] = stamp < now and row.get("status") in {"issued", "received", "flagged", "reopened"}
        if row["overdue"]:
            overdue.append(row)
    returned = [row for row in rows if row.get("status") not in {"issued", None}]
    return {
        "requirements": rows,
        "issued": len(rows),
        "returned": len(returned),
        "overdue": len(overdue),
        "outstanding": [row["doc_type"] for row in rows if row.get("status") == "issued"],
    }
