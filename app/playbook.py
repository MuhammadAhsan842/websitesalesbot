"""Consultative replies from approved copy. The model drafts; this file validates and caps."""

from __future__ import annotations

import re

from app.knowledge import EQUIP_KEYS, lookup
from app.plan import allow_action_message, topic_lines, validate_plan
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
        if constraint == "home_every_night" and key in {"supportNeed", "primaryProblem", "weekdaySchedule"}:
            continue
        if fact_value(facts, "operatingMode") == "local" and key in {"weekdaySchedule", "milesPerDay"}:
            continue
        missing.append(key)
    return missing


UNBLOCK_ORDER = [
    "equipment",
    "trailerLength",
    "mcOwnership",
    "insurance",
    "operatingMode",
    "weekdaySchedule",
    "milesPerDay",
    "operatingArea",
    "startDate",
]


def next_ask(facts: dict, memory: dict | None = None, intent: str | None = None, repair: str | None = None) -> str | None:
    mem = memory or {}
    if mem.get("follow_up") == "driver_initiates":
        return None
    if mem.get("concern") in {
        "commitment",
        "net_after_costs",
        "pause",
        "payment_support",
        "insurance_affordability",
        "packet_progress",
        "negotiation",
    }:
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
        missing = [key for key in missing if key not in {"supportNeed", "primaryProblem", "weekdaySchedule"}]
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
        return "Nothing is recorded on this chat yet. I can't see papers onboarding hasn't received."
    return "On this chat I have: " + "; ".join(bits) + ". I can't see papers onboarding hasn't received."


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
        "dispatch_service": "That's own-MC dispatch: our onboarding manager sends the setup packet. You're not eligible just from this chat.",
        "lease_on": "That's a lease-on path: our onboarding manager reviews eligibility and the agreement. Asking isn't approval.",
        "needs_clarification": "We still need own-MC vs lease-on before onboarding can send a packet.",
    }.get(arrangement or "", "Onboarding still needs the arrangement before papers move.")
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
        return "Answer the live fee or freight question, then offer an onboarding packet if they are ready."
    if mem.get("concern") == "email_delivery":
        return "Resend the last email after mailbox can receive it."
    ask = next_ask(facts, mem)
    if ask:
        return f"Ask {ask} next; skip anything already on file."
    if arrangement == "dispatch_service":
        return "Offer an own-MC setup packet for the onboarding manager. Bot does not send or approve."
    if arrangement == "lease_on":
        return "Offer a lease-on review for the onboarding manager. Bot does not approve."
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
    owner = "onboarding" if session.get("takeover") or session.get("handed_over") else "assistant"
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
        "next_agreed": mem.get("next_agreed") or {"step": step, "owner": owner, "status": "active"},
        "owner": owner,
        "follow_up": mem.get("follow_up") or "assistant",
        "follow_up_permission": mem.get("follow_up_permission") or mem.get("follow_up") or "assistant",
        "records": list(mem.get("records") or []),
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
    plan: dict | None = None,
    user_text: str = "",
) -> tuple[str, list[str], str | None]:
    parts: list[str] = []
    summary = None
    mem = memory or {}
    concern = mem.get("concern")
    core_done = not missing_core(facts, mem)
    spoken = (wording or "").strip()
    validated = plan if plan and "answer_topics" in plan else validate_plan(
        user_text,
        {"facts": facts, "memory": mem},
        {
            "intent": intent,
            "facts": [],
            "answer_topics": (plan or {}).get("answer_topics") or [],
            "next_question_id": (plan or {}).get("next_question_id", next_field),
            "next_field": next_field,
            "action": (plan or {}).get("proposed_action") or ("create_case" if saved else "none"),
            "task": (plan or {}).get("task"),
            "wording": spoken or None,
            "repair": repair,
            "conversation_move": (plan or {}).get("conversation_move"),
        },
    )
    topics = list(validated.get("answer_topics") or [])
    ask = validated.get("next_question_id")
    spoken = (validated.get("wording") or "").strip()
    receipt = action_confirmation(action_message, saved)

    if episodic:
        parts.append(episodic)

    if intent == "existing_customer" or repair == "leave_sales" or "payment_support" in topics or concern == "payment_support":
        parts.append(spoken or lookup("payment_support" if concern == "payment_support" or "payment_support" in topics else "support"))
        if receipt:
            parts.append(receipt)
        return " ".join(_dedupe(parts)), CHIPS["handoff"], None

    if repair == "email_delivery" or concern == "email_delivery" or "email_delivery" in topics:
        parts.append(spoken or variant_text or lookup("email_delivery"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if concern == "insurance_affordability" or (
        "insurance" in topics and re.search(r"afford|too much|expensive|owner will wait", user_text or "", re.I)
    ):
        parts.append(spoken or lookup("insurance_affordability"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if concern == "packet_progress":
        parts.append(spoken or lookup("packet_received"))
        return " ".join(_dedupe(parts)), CHIPS["handoff"], None

    if concern == "missing_equipment":
        parts.append(spoken or lookup("missing_equipment"))
        ask = next_ask(facts, mem, intent, repair)
        if ask and QUESTIONS.get(ask) and not _has_question(" ".join(parts)):
            parts.append(QUESTIONS[ask])
        return " ".join(_dedupe(parts)), CHIPS.get(ask) or CHIPS["default"], None

    if concern == "negotiation" or "negotiation" in topics:
        percent = fact_value(facts, "requestedFeePercent")
        cap = fact_value(facts, "requestedWeeklyCap")
        if percent and cap:
            parts.append(
                f"You're proposing {percent}% with a ${cap} weekly cap. I can record that for review; it isn't an agreed rate."
            )
        elif percent:
            parts.append(f"You're proposing {percent}%. I can record that for review; it isn't an agreed rate.")
        else:
            parts.append(spoken or lookup("negotiation"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if repair == "authority_uncertain":
        parts.append(spoken or lookup("mc_new"))
        ask = "mcOwnership"
        if not _has_question(" ".join(parts)):
            parts.append(QUESTIONS[ask])
        return " ".join(_dedupe(parts)), CHIPS.get(ask) or CHIPS["default"], None

    if repair == "equip_ambiguous":
        row = next(
            (
                item
                for item in (mem.get("records") or [])
                if item.get("kind") == "ambiguity" and item.get("key") == "equipment" and item.get("status") == "active"
            ),
            {},
        )
        current = row.get("on_file") or fact_value(facts, "equipment")
        advertised = row.get("advertised")
        label = EQUIP_LABELS.get(str(current or ""), str(current or "").replace("_", " ")) or "truck on file"
        if advertised:
            adv_label = EQUIP_LABELS.get(str(advertised), str(advertised).replace("_", " "))
            target = f"that advertised {adv_label}"
        else:
            target = "that advertised load"
        parts.append(
            f"Are you asking whether {target} could work for your {label}, or do you also have that other truck?"
        )
        return " ".join(_dedupe(parts)), CHIPS.get("equipment") or CHIPS["default"], None

    if "pause" in topics or mem.get("follow_up") == "driver_initiates" or concern == "pause":
        if re.search(r"next summer|start again|i'?ll let you know", user_text or "", re.I):
            parts.append(spoken or lookup("deferred"))
        else:
            parts.append(spoken or variant_text or lookup("concern_pause"))
        return " ".join(_dedupe(parts)), [], None

    if concern == "repetition" or repair == "repetition_unverified":
        if not spoken:
            parts.append(variant_text or lookup("concern_repetition"))
        parts.append(recorded_line(facts, mem))

    answers = topic_lines(topics, arrangement, bits, facts)
    ack = spoken if spoken and "?" not in spoken and spoken.count(".") <= 1 else None
    if answers:
        if ack:
            parts.append(ack)
        for line in answers:
            if line and line not in parts and line != spoken:
                parts.append(line)
    elif spoken:
        parts.append(spoken)
    for bit in bits or []:
        low = (bit or "").lower()
        if "unverified" in low and any(
            token in low for token in ("photo", "screenshot", "image", "outstanding", "w-9", "certificate of insurance")
        ) and bit not in parts:
            parts.append(bit)
            break

    if not spoken and not answers:
        if intent == "service":
            parts.append(lookup("services"))
            line = _equip_line(facts)
            if line:
                parts.append(line)
        elif intent == "freight":
            parts.append(lookup("freight"))
        elif intent in {"dispatch_inquiry", "general", "mc", "lease", "onboard", "unknown_detail"} and fact_value(facts, "equipment"):
            line = _equip_line(facts)
            if line:
                parts.append(line)
        elif variant_text:
            parts.append(variant_text)

    if receipt:
        parts.append(receipt)

    if saved:
        if spoken:
            if not action_message:
                parts.append("I've passed this to our onboarding manager. I don't send, sign, or approve from chat.")
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if arrangement == "dispatch_service":
            parts.append(lookup("docs_own"))
        elif arrangement == "lease_on":
            parts.append(lookup("docs_lease"))
        elif arrangement == "needs_clarification":
            parts.append("Onboarding will confirm own-MC vs lease-on before any packet goes out.")
        parts.append("I don't send, sign, or approve from here — that's onboarding.")
        return " ".join(_dedupe(parts)), CHIPS["handoff"], summary

    if core_done and concern not in {"repetition"} and not bits and not spoken and not topics:
        summary = fit_summary(facts, arrangement)
        parts.append(summary)
        if mem.get("follow_up") != "driver_initiates":
            parts.append(lookup("next_invite"))
        return " ".join(_dedupe(parts)), CHIPS["assess"], summary

    question, ask = select_question(validated, parts)
    if question:
        parts.append(question)
    elif not parts:
        parts.append(lookup("welcome"))

    chips = CHIPS.get(ask) or (CHIPS["assess"] if core_done else CHIPS["default"])
    return " ".join(_dedupe(parts)), chips, summary


def action_confirmation(action_message: str | None, saved: bool) -> str | None:
    return action_message if allow_action_message(action_message, saved) else None


def select_question(plan: dict, parts: list[str]) -> tuple[str | None, str | None]:
    ask = (plan or {}).get("next_question_id")
    if ask and QUESTIONS.get(ask) and not _has_question(" ".join(parts)):
        return QUESTIONS[ask], ask
    return None, ask
