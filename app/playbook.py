"""Consultative replies from approved copy. Qwen does not write these sentences."""

from app.knowledge import EQUIP_KEYS, lookup
from app.schema import ASK_ORDER, CHIPS, EQUIP_LABELS, QUESTIONS


def fact_value(facts: dict, key: str):
    item = facts.get(key)
    if not item or item.get("status") == "unknown":
        return None
    return item.get("value")


def missing_core(facts: dict) -> list[str]:
    missing = []
    for key in ASK_ORDER:
        item = facts.get(key)
        if item and item.get("status") == "unknown":
            continue
        if fact_value(facts, key) is not None:
            continue
        if key == "primaryProblem" and not fact_value(facts, "equipment"):
            continue
        missing.append(key)
    return missing


def next_ask(facts: dict) -> str | None:
    missing = missing_core(facts)
    return missing[0] if missing else None


def _equip_line(facts: dict) -> str | None:
    equip = fact_value(facts, "equipment")
    key = EQUIP_KEYS.get(str(equip) if equip else "")
    return lookup(key) if key else None


def fit_summary(facts: dict, arrangement: str | None) -> str:
    n = fact_value(facts, "fleetSize")
    equip = EQUIP_LABELS.get(str(fact_value(facts, "equipment") or ""), fact_value(facts, "equipment") or "equipment")
    plurals = {"dry van": "dry vans", "reefer": "reefers", "flatbed": "flatbeds", "box truck": "box trucks", "hotshot": "hotshots"}
    noun = plurals.get(str(equip), str(equip)) if n and n != 1 else equip
    count = f"{n} {noun}" if n else equip
    area = fact_value(facts, "operatingArea") or fact_value(facts, "lanes") or "an area still to confirm"
    lanes = fact_value(facts, "lanes")
    lane_bit = f", keeping {lanes} lanes" if lanes and lanes != area else ""
    start = fact_value(facts, "startDate")
    start_bit = f", starting {start}" if start else ""
    need = fact_value(facts, "supportNeed") or fact_value(facts, "primaryProblem")
    need_bit = f" Main need on file: {str(need).replace('_', ' ')}." if need else ""
    path = {
        "dispatch_service": "That is an own-MC dispatch path: a person sends the setup packet. It is not eligibility yet.",
        "lease_on": "That is a lease-on path: a person reviews eligibility and the agreement. Asking is not approval.",
        "needs_clarification": "The MC arrangement is unclear, so staff must clarify before any packet.",
    }.get(arrangement or "", "Staff still confirm the arrangement before papers move.")
    unresolved = []
    if not fact_value(facts, "supportNeed"):
        unresolved.append("home time / support")
    if not fact_value(facts, "startDate"):
        unresolved.append("start date")
    if arrangement == "needs_clarification" or not fact_value(facts, "mcOwnership"):
        unresolved.append("MC arrangement")
    open_bits = f" Still open: {', '.join(unresolved)}." if unresolved else ""
    return (
        f"You're looking for support for {count} operating from {area}{lane_bit}{start_bit}. "
        f"That equipment is in the services we dispatch.{need_bit} {path}{open_bits} "
        "This is not live freight and not approval."
    )


def compose(intent: str, facts: dict, bits: list[str], arrangement: str | None, saved: bool, action_message: str | None, next_field: str | None) -> tuple[str, list[str], str | None]:
    parts: list[str] = []
    summary = None
    core_done = not missing_core(facts)

    if intent == "existing_customer":
        parts.append(lookup("support"))
        return "\n\n".join(parts), CHIPS["handoff"], None

    if bits:
        parts.extend(bits)
    elif intent == "service":
        parts.append(lookup("services"))
        parts.append(_equip_line(facts) or "")
    elif intent in {"dispatch_inquiry", "general", "mc", "lease", "onboard", "unknown_detail"} and fact_value(facts, "equipment"):
        line = _equip_line(facts)
        if line:
            parts.append(line)

    if action_message:
        parts.append(action_message)

    if saved:
        if arrangement == "dispatch_service":
            parts.append(lookup("docs_own"))
        elif arrangement == "lease_on":
            parts.append(lookup("docs_lease"))
        elif arrangement == "needs_clarification":
            parts.append("Staff will choose the arrangement before any packet is sent.")
        parts.append("I do not send, sign, or approve.")
        if core_done:
            summary = fit_summary(facts, arrangement)
            parts.insert(0, summary)
        return "\n\n".join(p for p in parts if p), CHIPS["handoff"], summary

    ask = next_field if next_field in QUESTIONS else next_ask(facts)
    if core_done:
        summary = fit_summary(facts, arrangement)
        parts.append(summary)
        parts.append(lookup("next_invite"))
        text = "\n\n".join(p for p in parts if p)
        return text, CHIPS["assess"], summary

    if ask and QUESTIONS.get(ask):
        parts.append(QUESTIONS[ask])
    elif not parts:
        parts.append(lookup("welcome"))

    chips = CHIPS.get(ask) or CHIPS["default"]
    return "\n\n".join(p for p in parts if p), chips, summary
