"""Task catalogue. Planner may pick one of these; it may not invent new work."""

from app import db
from app.schema import QUAL_FIELDS

# Purpose tasks stay primary when a contact/callback task is added later.
PURPOSE_TASKS = frozenset(
    {"setup_packet", "lease_agreement", "insurance_quote", "clarification", "fit_check", "operations_support"}
)
CONTACT_TASKS = frozenset({"callback"})


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


def _merge_tasks(existing: dict | None, task: str) -> tuple[str, list[str]]:
    """Keep insurance/lease purpose when recording a callback on the same inquiry."""
    related = list((existing or {}).get("related_tasks") or [])
    prior = (existing or {}).get("task")
    if task in CONTACT_TASKS and prior in PURPOSE_TASKS:
        if task not in related:
            related.append(task)
        return prior, related
    if prior and prior != task and prior in PURPOSE_TASKS and task in PURPOSE_TASKS:
        if prior not in related:
            related.append(prior)
    related = [t for t in related if t != task]
    return task, related


def persist_human_task(session: dict, task: str, status: str, next_action: str, event: str) -> dict:
    from app.playbook import handoff_brief
    from app.rules import arrangement_of

    existing = db.get_case(session["case_id"]) if session.get("case_id") else None
    primary, related = _merge_tasks(existing, task)
    arrangement = arrangement_of(session["facts"])
    narrative = handoff_brief(
        session["facts"],
        arrangement,
        task=primary,
        status=status,
        next_action=next_action,
        related_tasks=related + ([task] if task != primary and task not in related else []),
        opportunity_id=session.get("opportunity_id"),
        reason=(
            "Driver requested a callback while a lease/insurance review is already open."
            if task in CONTACT_TASKS and primary in PURPOSE_TASKS
            else None
        ),
    )
    session["related_tasks"] = related
    saved = db.upsert_case(
        {
            "id": session.get("case_id"),
            "session_id": session["id"],
            "opportunity_id": session["opportunity_id"],
            "task": primary,
            "related_tasks": related,
            "status": status,
            "facts": session["facts"],
            "summary": narrative,
            "next_action": next_action,
        }
    )
    session["case_id"] = saved["id"]
    db.save_session(session)
    issue_task = primary if primary in {"setup_packet", "lease_agreement", "insurance_quote"} else None
    if issue_task:
        from app import requirements

        requirements.issue(saved["id"], issue_task, facts=session.get("facts") or {})
    db.add_event(
        event,
        {"caseId": saved["id"], "task": primary, "related_tasks": related, "status": status, "event_task": task},
    )
    from app import zoho

    # Queue under the event task so Zoho stage/brief reflect callback vs insurance correctly,
    # while the local case keeps the purpose task primary.
    zoho.queue_handoff(session, task, status, next_action)
    return saved
