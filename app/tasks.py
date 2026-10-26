"""Task catalogue. Planner may pick one of these; it may not invent new work."""

from app import db
from app.schema import QUAL_FIELDS


def fact_value(facts: dict, key: str):
    item = facts.get(key)
    if not item or item.get("status") == "unknown":
        return None
    return item.get("value")


def summary(facts: dict) -> str:
    parts = []
    for key, item in facts.items():
        if item.get("status") == "unknown":
            parts.append(f"{key}: unknown")
        else:
            parts.append(f"{key}: {item.get('value')} ({item.get('status')})")
    return "; ".join(parts)


def missing_fields(facts: dict) -> list[str]:
    return [key for key in QUAL_FIELDS if fact_value(facts, key) is None]


def persist_human_task(session: dict, task: str, status: str, next_action: str, event: str) -> dict:
    from app.playbook import fit_summary
    from app.rules import arrangement_of

    narrative = fit_summary(session["facts"], arrangement_of(session["facts"]))
    saved = db.upsert_case(
        {
            "id": session.get("case_id"),
            "session_id": session["id"],
            "opportunity_id": session["opportunity_id"],
            "task": task,
            "status": status,
            "facts": session["facts"],
            "summary": narrative,
            "next_action": next_action,
        }
    )
    session["case_id"] = saved["id"]
    if task in {"setup_packet", "lease_agreement"}:
        from app import requirements

        requirements.issue(saved["id"], task, facts=session.get("facts") or {})
    db.add_event(event, {"caseId": saved["id"], "task": task, "status": status})
    from app import zoho

    zoho.queue_handoff(session, task, status, next_action)
    return saved
