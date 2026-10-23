"""Consultative replies from approved copy. The model drafts; this file validates and caps."""

from __future__ import annotations

from app.knowledge import EQUIP_KEYS, lookup
from app.schema import ASK_ORDER, CHIPS, EQUIP_LABELS, FACT_KEYS, QUESTIONS


def fact_value(facts: dict, key: str):
    item = facts.get(key)
    if not item or item.get("status") == "unknown":
        return None
    return item.get("value")


def missing_core(facts: dict, memory: dict | None = None) -> list[str]:
    answered = set((memory or {}).get("answered") or [])
    constraint = (memory or {}).get("hard_constraint")
    missing = []
    for key in ASK_ORDER:
        if key in answered:
            continue
        item = facts.get(key)
        if item and item.get("status") == "unknown":
            continue
        if fact_value(facts, key) is not None:
            continue
        if key == "primaryProblem" and not fact_value(facts, "equipment"):
            continue
        if key == "primaryProblem" and fact_value(facts, "supportNeed") is not None:
            continue
        if constraint == "home_every_night" and key in {"supportNeed", "primaryProblem"}:
            continue
        missing.append(key)
    return missing


UNBLOCK_ORDER = ["equipment", "mcOwnership", "operatingArea", "deadline", "fleetSize", "supportNeed", "startDate"]


def next_ask(facts: dict, memory: dict | None = None, intent: str | None = None, repair: str | None = None) -> str | None:
    mem = memory or {}
    if mem.get("follow_up") == "driver_initiates":
        return None
    if mem.get("concern") in {"commitment", "net_after_costs", "pause"}:
        return None
    if repair == "leave_sales" or intent == "existing_customer":
        return None
    if repair == "email_delivery" or (memory or {}).get("concern") == "email_delivery":
        return None
    if repair == "authority_uncertain":
        return "mcOwnership"
    if intent in {"fee", "guarantee"} or mem.get("concern") in {"total_fees", "guarantee"}:
        return None if fact_value(facts, "mcOwnership") else "mcOwnership"
    if intent == "onboard" or mem.get("next_step_readiness") == "ready":
        return None
    if repair == "topic_fee":
        return None if fact_value(facts, "mcOwnership") else "mcOwnership"
    if fact_value(facts, "deadline") and not fact_value(facts, "mcOwnership"):
        return "mcOwnership"
    missing = missing_core(facts, mem)
    if fact_value(facts, "deadline"):
        missing = [key for key in missing if key != "startDate"]
    if fact_value(facts, "operatingMode") == "local" or mem.get("hard_constraint") == "home_every_night":
        missing = [key for key in missing if key not in {"supportNeed", "primaryProblem"}]
    for key in UNBLOCK_ORDER:
        if key in missing:
            return key
    return missing[0] if missing else None


def _equip_line(facts: dict) -> str | None:
    equip = fact_value(facts, "equipment")
    key = EQUIP_KEYS.get(str(equip) if equip else "")
    return lookup(key) if key else None


def recorded_line(facts: dict, memory: dict | None = None) -> str:
    keys = (memory or {}).get("answered") or [key for key in FACT_KEYS if fact_value(facts, key) is not None]
    bits = []
    for key in keys:
        value = fact_value(facts, key)
        if value not in (None, "", False):
            bits.append(f"{key} {value}")
    if not bits:
        return "Nothing is recorded on this chat yet. I cannot see documents staff have not received."
    return "On this chat I have: " + "; ".join(bits) + ". I cannot see documents staff have not received."


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


def _has_question(text: str) -> bool:
    return "?" in (text or "")


def _dedupe(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for part in parts:
        bit = (part or "").strip()
        if not bit or bit in seen:
            continue
        seen.add(bit)
        out.append(bit)
    return out


def next_step(facts: dict, memory: dict | None, arrangement: str | None) -> str:
    mem = memory or {}
    if mem.get("follow_up") == "driver_initiates" or mem.get("concern") == "pause":
        return "Wait for the driver to return; do not chase."
    blocker = mem.get("last_blocker") or mem.get("blocker")
    if blocker == "waiting_insurance":
        return "Resume when they have a COI; do not re-qualify."
    if blocker == "waiting_registration":
        return "Continue after registration is on this case."
    if mem.get("concern") == "commitment":
        return "Address the signature concern before any packet."
    if mem.get("concern") in {"total_fees", "guarantee"}:
        return "Answer the live fee or freight question, then offer a staff packet if they are ready."
    if mem.get("concern") == "email_delivery":
        return "Resend the last email after mailbox can receive it."
    ask = next_ask(facts, mem)
    if ask:
        return f"Ask {ask} next; skip anything already on file."
    if arrangement == "dispatch_service":
        return "Offer a staff-owned own-MC setup packet. Bot does not send or approve."
    if arrangement == "lease_on":
        return "Offer a staff-owned lease-on review. Bot does not approve."
    return "Keep qualifying until equipment and own-MC vs lease-on are on file."


def desk_card(session: dict) -> dict:
    facts = session.get("facts") or {}
    mem = session.get("memory") or {}
    arrangement = None
    mc = fact_value(facts, "mcOwnership")
    if mc == "own_mc":
        arrangement = "dispatch_service"
    elif mc == "no_own_mc":
        arrangement = "lease_on"
    elif mc == "unclear":
        arrangement = "needs_clarification"
    ask = next_ask(facts, mem, repair=mem.get("repair"))
    known = {
        key: fact_value(facts, key)
        for key in ("equipment", "mcOwnership", "fleetSize", "operatingArea", "operatingMode", "supportNeed", "deadline", "payload")
        if fact_value(facts, key) not in (None, "", False)
    }
    owner = "staff" if session.get("takeover") or session.get("handed_over") else "assistant"
    step = next_step(facts, mem, arrangement)
    bits = []
    if known.get("equipment"):
        bits.append(str(known["equipment"]).replace("_", " "))
    if known.get("mcOwnership"):
        bits.append(str(known["mcOwnership"]).replace("_", " "))
    if mem.get("goal"):
        bits.append(str(mem["goal"]).replace("_", " "))
    if mem.get("hard_constraint"):
        bits.append(str(mem["hard_constraint"]).replace("_", " "))
    if mem.get("concern"):
        bits.append(f"concern {mem['concern']}")
    line = ". ".join(bits) + ". " + step if bits else step
    return {
        "goal": mem.get("goal"),
        "constraint": mem.get("hard_constraint"),
        "concern": mem.get("concern"),
        "blocker": mem.get("last_blocker") or mem.get("blocker"),
        "next_question": QUESTIONS.get(ask) if ask else None,
        "next_step": step,
        "owner": owner,
        "follow_up": mem.get("follow_up") or "assistant",
        "arrangement": arrangement,
        "facts": known,
        "line": line.strip(),
    }


def compose(
    intent: str,
    facts: dict,
    bits: list[str],
    arrangement: str | None,
    saved: bool,
    action_message: str | None,
    next_field: str | None,
    memory: dict | None = None,
    wording: str | None = None,
    variant_text: str | None = None,
    episodic: str | None = None,
    repair: str | None = None,
) -> tuple[str, list[str], str | None]:
    parts: list[str] = []
    summary = None
    mem = memory or {}
    concern = mem.get("concern")
    paused = mem.get("follow_up") == "driver_initiates" or concern == "pause"
    core_done = not missing_core(facts, mem)
    spoken = (wording or "").strip()

    if episodic:
        parts.append(episodic)
    if spoken:
        parts.append(spoken)

    def _use_variant() -> None:
        if spoken:
            return
        if variant_text and variant_text not in parts and not any(variant_text == (bit or "") for bit in bits):
            parts.append(variant_text)

    if paused:
        parts.append(variant_text or lookup("concern_pause"))
        return " ".join(_dedupe(parts)), [], None

    if intent == "existing_customer" or repair == "leave_sales":
        parts.append(lookup("support"))
        return " ".join(_dedupe(parts)), CHIPS["handoff"], None

    if repair == "email_delivery" or concern == "email_delivery":
        parts.append(spoken or variant_text or lookup("email_delivery"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if repair == "authority_uncertain":
        parts.append(spoken or lookup("mc_new"))
        ask = "mcOwnership"
        if not _has_question(" ".join(parts)):
            parts.append(QUESTIONS[ask])
        return " ".join(_dedupe(parts)), CHIPS.get(ask) or CHIPS["default"], None

    if concern == "commitment":
        _use_variant()
        if not spoken and not variant_text:
            parts.append(lookup("concern_commitment"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if concern == "net_after_costs":
        _use_variant()
        if not spoken and not variant_text:
            parts.append(lookup("concern_net"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if concern == "repetition" or repair == "repetition_unverified":
        _use_variant()
        if not spoken and not variant_text:
            parts.append(lookup("concern_repetition"))
        parts.append(recorded_line(facts, mem))

    claim_bits = [bit for bit in bits if bit and bit not in parts]
    if spoken:
        claim_bits = claim_bits[:1]
    if claim_bits:
        parts.extend(claim_bits[:1] if concern else claim_bits[:1])
    elif not spoken:
        if intent == "service":
            parts.append(lookup("services"))
            line = _equip_line(facts)
            if line:
                parts.append(line)
        elif intent in {"dispatch_inquiry", "general", "mc", "lease", "onboard", "unknown_detail"} and fact_value(facts, "equipment"):
            line = _equip_line(facts)
            if line:
                parts.append(line)
        else:
            _use_variant()

    if action_message:
        parts.append(action_message)

    if saved:
        if spoken:
            if not action_message:
                parts.append("A staff-owned request is saved locally. I do not send, sign, or approve.")
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if arrangement == "dispatch_service":
            parts.append(lookup("docs_own"))
        elif arrangement == "lease_on":
            parts.append(lookup("docs_lease"))
        elif arrangement == "needs_clarification":
            parts.append("Staff will choose the arrangement before any packet is sent.")
        parts.append("I do not send, sign, or approve.")
        return " ".join(_dedupe(parts)), CHIPS["handoff"], summary

    ask = None if concern in {"total_fees", "guarantee", "repetition", "home_time"} else (
        next_field if next_field in QUESTIONS else next_ask(facts, mem)
    )
    if concern in {"total_fees", "guarantee", "home_time"}:
        text = " ".join(_dedupe(parts)) or lookup("unknown")
        return text, CHIPS["assess"] if core_done else (CHIPS.get(next_ask(facts, mem)) or CHIPS["default"]), None

    if core_done and concern not in {"repetition"} and not bits and not spoken:
        summary = fit_summary(facts, arrangement)
        parts.append(summary)
        if mem.get("follow_up") != "driver_initiates":
            parts.append(lookup("next_invite"))
        return " ".join(_dedupe(parts)), CHIPS["assess"], summary

    joined = " ".join(_dedupe(parts))
    if ask and QUESTIONS.get(ask) and not _has_question(joined):
        parts.append(QUESTIONS[ask])
    elif not parts:
        parts.append(lookup("welcome"))

    chips = CHIPS.get(ask) or CHIPS["default"]
    return " ".join(_dedupe(parts)), chips, summary
