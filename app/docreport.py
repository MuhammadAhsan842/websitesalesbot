"""Case-wide document report. A later clean upload must not erase an earlier finding."""

from __future__ import annotations

import hashlib

from app import db
from app.docschema import arrangement_of, mask_value

OPEN = {
    "issued",
    "corrections",
    "reopened",
    "rejected",
    "clearer_copy",
    "information_missing",
    "possible_mismatch",
    "flagged",
}


def _latest_files(case_id: str) -> list[dict]:
    chosen: dict[str, dict] = {}
    for row in db.list_case_files(case_id):
        chosen[row.get("doc_type") or "unknown"] = row
    return list(chosen.values())


def _finding_lines(file_row: dict) -> list[str]:
    lines = []
    findings = file_row.get("findings") or file_row.get("flags") or []
    name = file_row.get("filename") or "upload"
    version = file_row.get("version") or 1
    for item in findings:
        if item.get("severity") == "info":
            continue
        field = item.get("field") or "document"
        outcome = item.get("outcome") or item.get("code")
        page = item.get("page") or "?"
        why = item.get("why") or item.get("message") or ""
        observed = item.get("observed")
        observed_bit = f" Observed: {mask_value(field, observed)}." if observed not in (None, "") else ""
        lines.append(
            f"{file_row.get('doc_type')} — {name}, version {version}, page {page}. "
            f"{field} is {outcome}.{observed_bit} {why} "
            f"Next: {item.get('next_action') or 'await_review'} ({item.get('actor') or 'reviewer'})."
        )
    return lines


def build(case_id: str) -> dict:
    case = db.get_case(case_id) or {}
    facts = case.get("facts") or {}
    arrangement = arrangement_of(facts)
    requirements = db.list_requirements(case_id)
    files = _latest_files(case_id)
    lines = []
    open_items = []
    for row in requirements:
        status = row.get("status") or "issued"
        label = row.get("label") or row.get("doc_type")
        if status in OPEN or status == "issued":
            open_items.append(f"{label}: {status}")
        else:
            lines.append(f"{label}: {status}.")
    finding_lines = []
    for file_row in files:
        finding_lines.extend(_finding_lines(file_row))
    title = "Lease-on" if arrangement == "lease_on" else "Own-MC" if arrangement == "own_mc" else "Document"
    if open_items or finding_lines:
        headline = f"{title} document review — corrections required. Onboarding approval: pending."
    else:
        headline = f"{title} document review — no configured issue on returned files. Onboarding approval: pending."
    body_parts = [headline]
    if finding_lines:
        body_parts.append("Findings:")
        body_parts.extend(f"- {line}" for line in finding_lines)
    if open_items:
        body_parts.append("Still open:")
        body_parts.extend(f"- {line}" for line in open_items)
    body_parts.append("Received is not approved. Insurance verification and dispatch permission stay separate.")
    text = "\n".join(body_parts)
    revision = hashlib.sha256(text.encode()).hexdigest()[:12]
    if open_items:
        next_action = "Document review still open: " + "; ".join(open_items[:8]) + ". Not approved."
    else:
        next_action = "Returned documents have no configured issue. Human approval remains pending. Not approved."
    return {
        "case_id": case_id,
        "arrangement": arrangement,
        "revision": revision,
        "text": text,
        "next_action": next_action[:800],
        "corrections": bool(open_items or finding_lines),
        "open_items": open_items,
        "files": [
            {
                "id": row.get("id"),
                "doc_type": row.get("doc_type"),
                "filename": row.get("filename"),
                "version": row.get("version"),
                "path": row.get("original_path") or row.get("path"),
                "sha": None,
            }
            for row in files
        ],
    }


def apply_next_action(case_id: str) -> dict:
    """Replace the case next action from the whole inquiry, not the newest file."""
    report = build(case_id)
    case = db.get_case(case_id) or {}
    db.upsert_case(
        {
            "id": case_id,
            "status": case.get("status") or "under_review",
            "next_action": report["next_action"],
            "documents": case.get("documents") or [],
            "facts": case.get("facts") or {},
            "session_id": case.get("session_id"),
            "opportunity_id": case.get("opportunity_id"),
            "task": case.get("task"),
            "summary": case.get("summary"),
            "owner": case.get("owner"),
        }
    )
    return report
