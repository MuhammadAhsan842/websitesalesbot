"""Consultative replies from approved copy. The model drafts; this file validates and caps."""

from __future__ import annotations

import re

from app.knowledge import EQUIP_KEYS, lookup
from app.plan import allow_action_message, topic_lines, validate_plan
from app.schema import ASK_ORDER, CHIPS, EQUIP_LABELS, FACT_KEYS, QUESTIONS  # EQUIP_LABELS used in fit + first-equip ack


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
    if fact_value(facts, "equipmentSupport") == "out_of_scope":
        return None
    if mem.get("concern") in {
        "commitment",
        "net_after_costs",
        "pause",
        "payment_support",
        "insurance_affordability",
        "packet_progress",
        "negotiation",
        "fuel_requirement",
        "expired_demand",
        "existing_dispatcher",
        "privacy_boundary",
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


def _should_explain_equipment(facts: dict, memory: dict | None, user_text: str, topics: list[str]) -> bool:
    """Mention equipment fit on first ID, change, or a direct support question — not every turn."""
    equip = fact_value(facts, "equipment")
    if not equip:
        return False
    key = EQUIP_KEYS.get(str(equip))
    if not key:
        return False
    t = (user_text or "").lower()
    # Answering a pending length/size question is not a request for equipment specs.
    if re.fullmatch(r"\s*\d+\s*(?:-)?\s*(?:ft|foot|feet|pies)\s*", t or "") or (
        re.search(r"^\s*\d+\s*(?:-)?\s*(?:ft|foot|feet|pies)\b", t) and len(t) < 24
    ):
        return False
    if "equip_specs" in (topics or []) and not re.search(r"payload|lift\s*gate|spec|how long|accessories", t):
        return False
    explained = set((memory or {}).get("explained") or [])
    if key not in explained:
        return True
    if "services" in topics or re.search(r"\b(support|what (truck|do you)|do you dispatch)\b", t):
        return True
    return False


def mark_explained(memory: dict | None, keys: list[str]) -> list[str]:
    current = list((memory or {}).get("explained") or [])
    for key in keys:
        if key and key not in current:
            current.append(key)
    return current


def recorded_line(facts: dict, memory: dict | None = None) -> str:
    keys = (memory or {}).get("answered") or [key for key in FACT_KEYS if fact_value(facts, key) is not None]
    bits = []
    for key in keys[:6]:
        value = fact_value(facts, key)
        if value not in (None, "", False):
            bits.append(f"{key} {value}")
    if not bits:
        return "I don't have much on this chat yet — and I can't see papers onboarding hasn't received."
    return "I've got " + "; ".join(bits) + " on this chat. I still can't see papers onboarding hasn't received."


def fit_summary(facts: dict, arrangement: str | None) -> str:
    n = fact_value(facts, "fleetSize")
    equip = EQUIP_LABELS.get(str(fact_value(facts, "equipment") or ""), fact_value(facts, "equipment") or "equipment")
    plurals = {"dry van": "dry vans", "reefer": "reefers", "flatbed": "flatbeds", "box truck": "box trucks", "hotshot": "hotshots"}
    noun = plurals.get(str(equip), str(equip)) if n and n != 1 else equip
    count = f"{n} {noun}" if n else equip
    area = fact_value(facts, "operatingArea") or fact_value(facts, "lanes") or "an area we still need to pin down"
    lanes = fact_value(facts, "lanes")
    lane_bit = f", keeping {lanes} lanes" if lanes and lanes != area else ""
    start = fact_value(facts, "startDate")
    start_bit = f", looking to start {start}" if start else ""
    need = fact_value(facts, "supportNeed") or fact_value(facts, "primaryProblem")
    need_bit = f" You care most about {str(need).replace('_', ' ')}." if need else ""
    path = {
        "dispatch_service": "With your own MC, onboarding sends the setup packet — chat alone isn't eligibility.",
        "lease_on": "Lease-on means onboarding reviews fit and the agreement; asking here isn't approval.",
        "needs_clarification": "We still need own-MC vs lease-on before a packet can go out.",
    }.get(arrangement or "", "Onboarding still needs the arrangement before papers move.")
    unresolved = []
    if not fact_value(facts, "supportNeed"):
        unresolved.append("home time / support")
    if not fact_value(facts, "startDate"):
        unresolved.append("start timing")
    if arrangement == "needs_clarification" or not fact_value(facts, "mcOwnership"):
        unresolved.append("MC arrangement")
    open_bits = f" Still open: {', '.join(unresolved)}." if unresolved else ""
    return (
        f"So far you're looking for help with {count} out of {area}{lane_bit}{start_bit}. "
        f"That equipment is in scope for us.{need_bit} {path}{open_bits} "
        "No live freight from this chat, and nothing's approved yet."
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


def _closure_safe(spoken: str) -> bool:
    """Closure/privacy replies must not continue commercial probing."""
    return not re.search(
        r"\?|percent|%\s*|what (do they|does .{0,12}) charge|dispatcher charge|"
        r"how much (can|do) you (make|earn)|weekly gross|what type of truck|own MC or lease",
        spoken or "",
        re.I,
    )


def _wording_conflicts(spoken: str, facts: dict, ask: str | None, move: str | None, topics: list[str]) -> bool:
    """Reject model wording that re-asks answered fields or violates the selected move."""
    low = (spoken or "").lower()
    if not low:
        return False
    if fact_value(facts, "equipment") and re.search(
        r"what type of truck|what (truck|equipment) (are you|do you)|what are you running",
        low,
    ):
        return True
    if fact_value(facts, "mcOwnership") and re.search(r"own mc or lease|keeping your own mc", low):
        return True
    if (move == "pause" or any(t in topics for t in ("privacy_boundary", "expired_demand", "existing_dispatcher", "pause"))) and not _closure_safe(
        spoken
    ):
        return True
    if ask is None and re.search(r"what type of truck|what are you running", low):
        return True
    return False


def _is_reactivation(user_text: str) -> bool:
    return bool(
        re.search(
            r"situation changed|i'?m ready to start|ready to start|can we (talk|discuss).{0,20}dispatch|"
            r"considering switching|want to (try|start) again|let'?s (try|start) again",
            user_text or "",
            re.I,
        )
    )


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
    if _is_reactivation(user_text):
        # Current inbound need wins over a previous pause/expired closure.
        concern = None
        mem = {**mem, "concern": None, "follow_up": "assistant"}
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
    move = validated.get("conversation_move")
    receipt = action_confirmation(action_message, saved)

    def _covers(text: str, topic_list: list[str]) -> bool:
        low = (text or "").lower()
        if "dispatch_fee" in topic_list and not re.search(r"\bfee\b|percent|%|\bcharge\b", low):
            return False
        if "insurance" in topic_list and not re.search(r"insurance|cargo|liability|\bcoi\b|coverage", low):
            return False
        if "commitment" in topic_list and not re.search(r"sign|commit|binding|agreement|contract", low):
            return False
        return True

    # Never replay the opening greeting once qualification has started.
    if variant_text and variant_text.strip() == lookup("welcome").strip() and (mem.get("answered") or fact_value(facts, "equipment")):
        variant_text = None

    unsupported = fact_value(facts, "equipmentSupport") == "out_of_scope"
    if unsupported:
        eq = fact_value(facts, "equipment")
        length = fact_value(facts, "trailerLength")
        from app.knowledge import EQUIPMENT_LENGTHS_FT, UNSUPPORTED_EQUIPMENT

        if eq in UNSUPPORTED_EQUIPMENT:
            refusal = lookup(EQUIP_KEYS.get(str(eq or ""), "equip_unsupported"))
        elif eq == "box_truck" and length:
            refusal = lookup("equip_box_truck_short")
        elif eq in EQUIPMENT_LENGTHS_FT and length:
            refusal = lookup("equip_length_mismatch")
        else:
            refusal = lookup(EQUIP_KEYS.get(str(eq or ""), "equip_unsupported"))
        if not spoken or not re.search(
            r"don'?t provide|do not provide|outside|not (in |within )?scope|don'?t dispatch|do not dispatch|"
            r"only dispatch box trucks|24,\s*26,\s*or 28|catalog|outside our current service",
            spoken,
            re.I,
        ):
            spoken = refusal

    # Boundary / closure concerns before free model wording.
    if not _is_reactivation(user_text):
        if concern == "privacy_boundary" or re.search(
            r"private (business )?information|that'?s private|sensitive (business|question)|don'?t know you",
            user_text or "",
            re.I,
        ):
            parts.append(spoken if spoken and _closure_safe(spoken) else lookup("privacy_boundary"))
            return " ".join(_dedupe(parts)), [], None
        if concern == "expired_demand" or re.search(
            r"not anymore|that was for last |don'?t need (it|help|dispatch) (now|anymore)|was for (last )?(friday|monday|week)",
            user_text or "",
            re.I,
        ):
            parts.append(spoken if spoken and _closure_safe(spoken) else lookup("expired_demand"))
            return " ".join(_dedupe(parts)), [], None
        if concern == "existing_dispatcher" or re.search(
            r"already hired (a )?dispatcher|have (a |my )?dispatcher|working with (another |a )?dispatcher",
            user_text or "",
            re.I,
        ):
            if re.search(r"unhappy|not (happy|working)|switch|considering switching|want handled differently", user_text or "", re.I):
                parts.append(spoken or "Sorry it's not working out. What is the main issue you're hoping to resolve?")
                return " ".join(_dedupe(parts)), CHIPS["default"], None
            parts.append(spoken if spoken and _closure_safe(spoken) else lookup("existing_dispatcher"))
            return " ".join(_dedupe(parts)), [], None

    if _is_reactivation(user_text) and not spoken:
        parts.append(lookup("voluntary_return"))
        ask = next_ask(facts, mem, intent, repair)
        if ask and QUESTIONS.get(ask) and not _has_question(" ".join(parts)):
            parts.append(QUESTIONS[ask])
        return " ".join(_dedupe(parts)), CHIPS.get(ask) or CHIPS["default"], None

    if spoken and _wording_conflicts(spoken, facts, ask, move, topics):
        spoken = ""
        validated = {**validated, "wording": None}

    # Model-authored path: deliver the validated full reply without concatenating register paragraphs.
    if (
        spoken
        and len(spoken) >= 12
        and intent not in {"existing_customer"}
        and repair not in {"leave_sales", "email_delivery"}
        and (unsupported or _covers(spoken, topics))
    ):
        parts.append(spoken)
        # Never attach an onboarding receipt when the truck is out of scope.
        if receipt and not unsupported:
            parts.append(receipt)
        if equip_key := EQUIP_KEYS.get(str(fact_value(facts, "equipment") or "")):
            mem["explained"] = mark_explained(mem, [equip_key])
        chips = CHIPS.get(ask) if ask and ask not in (mem.get("answered") or []) else (
            CHIPS["assess"] if core_done else CHIPS["default"]
        )
        if unsupported:
            chips = CHIPS["default"]
        return " ".join(_dedupe(parts)), chips, None
    # Short human ack can ride with approved topic lines when wording alone misses coverage.
    ack_hold = ""
    if spoken and topics and not _covers(spoken, topics):
        if "?" not in spoken and spoken.count(".") <= 2 and len(spoken) <= 160:
            ack_hold = spoken
        spoken = ""
        validated = {**validated, "wording": None}

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

    if concern == "fuel_requirement" or re.search(
        r"fuel advance|diesel (money|before)|can'?t start without (fuel|diesel)|need (a )?fuel (card|advance)",
        user_text or "",
        re.I,
    ):
        parts.append(spoken or lookup("fuel_requirement"))
        return " ".join(_dedupe(parts)), CHIPS["default"], None

    if concern == "packet_progress":
        parts.append(spoken or lookup("packet_received"))
        return " ".join(_dedupe(parts)), CHIPS["handoff"], None

    if concern == "missing_equipment":
        parts.append(spoken or lookup("missing_equipment"))
        # MD success: don't pile qualify questions onto an equipment/affordability blocker.
        return " ".join(_dedupe(parts)), CHIPS["default"], None

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

    answers = topic_lines(topics, arrangement, bits, facts)[:2]
    ack = ack_hold or (spoken if spoken and "?" not in spoken and spoken.count(".") <= 2 else None)
    if answers:
        if ack:
            parts.append(ack)
        for line in answers:
            if line and line not in parts and line != spoken and line != ack:
                parts.append(line)
    elif spoken:
        parts.append(spoken)
    elif ack_hold:
        parts.append(ack_hold)
    for bit in bits or []:
        low = (bit or "").lower()
        if "unverified" in low and any(
            token in low for token in ("photo", "screenshot", "image", "outstanding", "w-9", "certificate of insurance")
        ) and bit not in parts:
            parts.append(bit)
            break

    explained_now: list[str] = []
    equip = fact_value(facts, "equipment")
    equip_key = EQUIP_KEYS.get(str(equip or ""))
    first_equip = bool(equip_key and equip_key not in set(mem.get("explained") or []))

    if not spoken and not answers:
        if intent == "service" or "services" in topics:
            if _should_explain_equipment(facts, mem, user_text, topics):
                line = _equip_line(facts)
                if line:
                    parts.append(line)
                    if equip_key:
                        explained_now.append(equip_key)
            else:
                parts.append(lookup("services"))
        elif intent == "freight":
            parts.append(lookup("freight"))
        elif intent in {"dispatch_inquiry"} and _should_explain_equipment(facts, mem, user_text, topics):
            line = _equip_line(facts)
            if line:
                parts.append(line)
                if equip_key:
                    explained_now.append(equip_key)
        elif first_equip and intent in {"general", "mc", "lease", "onboard", "unknown_detail", "dispatch_inquiry"}:
            label = EQUIP_LABELS.get(str(equip), str(equip).replace("_", " "))
            length = fact_value(facts, "trailerLength")
            focus = f"{length} {label}" if length else label
            if fact_value(facts, "equipmentSupport") == "out_of_scope":
                parts.append(lookup(equip_key) if equip_key else lookup("equip_unsupported"))
            else:
                parts.append(f"Let's focus on the {focus}.")
            if equip_key:
                explained_now.append(equip_key)
        elif variant_text:
            parts.append(variant_text)
    elif answers and _should_explain_equipment(facts, mem, user_text, topics) and intent in {"service", "dispatch_inquiry"}:
        line = _equip_line(facts)
        if line and line not in parts:
            parts.insert(0, line)
            if equip_key:
                explained_now.append(equip_key)
    if explained_now:
        mem["explained"] = mark_explained(mem, explained_now)

    if receipt and fact_value(facts, "equipmentSupport") != "out_of_scope":
        parts.append(receipt)

    if saved and fact_value(facts, "equipmentSupport") != "out_of_scope":
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
    if saved and fact_value(facts, "equipmentSupport") == "out_of_scope":
        # Never claim an onboarding request for a truck we do not dispatch.
        return " ".join(_dedupe(parts)), CHIPS.get("open") or CHIPS["default"], summary

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
