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


def awaiting_catalog_length(facts: dict) -> bool:
    """Supported length-gated type with no length yet — ask length; never refuse."""
    from app.knowledge import EQUIPMENT_LENGTHS_FT, SUPPORTED_EQUIPMENT

    eq = fact_value(facts, "equipment")
    if not eq or eq not in SUPPORTED_EQUIPMENT:
        return False
    if eq not in EQUIPMENT_LENGTHS_FT:
        return False
    return not fact_value(facts, "trailerLength")


def length_question(facts: dict) -> str:
    """One equipment-specific length ask (never the generic + specific pair)."""
    eq = fact_value(facts, "equipment")
    if eq == "box_truck":
        return "What length is the box — 24, 26, or 28 ft?"
    if eq == "hotshot":
        return "What length is your hotshot trailer — 30 or 40 ft?"
    if eq == "reefer":
        return "What length is your reefer trailer?"
    if eq == "flatbed":
        return "What length is your flatbed trailer?"
    if eq == "dry_van":
        return "What length is your dry van — 48 or 53 ft?"
    if eq == "step_deck":
        return "What length is your step deck — 48 or 53 ft?"
    return QUESTIONS.get("trailerLength") or "What length trailer are you running?"


def question_for(ask: str | None, facts: dict) -> str | None:
    if ask == "trailerLength":
        return length_question(facts)
    return QUESTIONS.get(ask) if ask else None


_OUT_OF_SCOPE_CLAIM = re.compile(
    r"outside what we dispatch|outside our current service|don'?t provide dispatch|"
    r"do not provide dispatch|that equipment is outside|we only serve box",
    re.I,
)

_EMAIL_INVENT_ASK = re.compile(
    r"best email|what(?:'s| is) (?:the )?best email|email (?:to|for) (?:send|the packet)|"
    r"send the packet to|what email|your email address",
    re.I,
)


def _mode(facts: dict) -> str | None:
    from app.rules import normalize_operating_mode

    return normalize_operating_mode(fact_value(facts, "operatingMode"))


def missing_core(facts: dict, memory: dict | None = None) -> list[str]:
    answered = set((memory or {}).get("answered") or [])
    constraint = (memory or {}).get("hard_constraint")
    mode = _mode(facts)
    insurance = fact_value(facts, "insurance")
    mc = fact_value(facts, "mcOwnership")
    own = mc == "own_mc"
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
        # Own-MC: insurance questionnaire is out — COI stays in document review.
        if own and key in {"insurance", "coverageTypes"}:
            continue
        # Coverage follow-up only after they say they have insurance (lease-on path).
        if key == "coverageTypes" and insurance != "own_insurance":
            continue
        # Types alone ("auto + cargo") do not satisfy limits — ask clarification when missing.
        if key == "coverageLimits":
            if insurance != "own_insurance":
                continue
            if not fact_value(facts, "coverageTypes") or fact_value(facts, "coverageLimits"):
                continue
        # MC age only for own-MC path.
        if key == "authorityAgeMonths" and not own:
            continue
        # City/ZIP is never a qualify slot (own-MC or lease-on).
        if key == "operatingArea":
            continue
        # OTR vs local first — then one branch only (never regional).
        if key in {"milesPerDay", "stayOutDuration", "weekdaySchedule"} and mode in (None, "unclear"):
            continue
        if own:
            # Own-MC local: miles/day → Monday–Friday → start date.
            # Own-MC OTR: start date only (no miles / weekday / stay-out / hours).
            if key == "stayOutDuration":
                continue
            if mode == "otr" and key in {"milesPerDay", "weekdaySchedule"}:
                continue
            if mode == "local" and key == "stayOutDuration":
                continue
        else:
            # Lease-on: never city. Local → miles → Mon–Fri → start.
            # Lease-on OTR → start only (no miles / weekday / stay-out).
            if key == "stayOutDuration":
                continue
            if mode == "otr" and key in {"milesPerDay", "weekdaySchedule"}:
                continue
            if mode == "local" and key == "stayOutDuration":
                continue
        missing.append(key)
    return missing


UNBLOCK_ORDER = [
    "equipment",
    "trailerLength",
    "mcOwnership",
    "authorityAgeMonths",
    "insurance",
    "coverageTypes",
    "coverageLimits",
    "operatingMode",
    "milesPerDay",
    "stayOutDuration",
    "weekdaySchedule",
    "operatingArea",
    "startDate",
]


def next_ask(facts: dict, memory: dict | None = None, intent: str | None = None, repair: str | None = None) -> str | None:
    mem = memory or {}
    if mem.get("follow_up") == "driver_initiates":
        return None
    # Length gate beats a premature / model-invented out_of_scope flag.
    if awaiting_catalog_length(facts):
        return "trailerLength"
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
        "repetition",
        "missing_equipment",
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
    mode = _mode(facts)
    mc = fact_value(facts, "mcOwnership")
    own = mc == "own_mc"
    if mode == "local" or mem.get("hard_constraint") == "home_every_night":
        # Keep weekdaySchedule for local; only drop support/problem and OTR stay-out.
        missing = [key for key in missing if key not in {"supportNeed", "primaryProblem", "stayOutDuration"}]
    if mode == "otr":
        # Own-MC and lease-on OTR → start only; never miles, weekday, or stay-out.
        missing = [
            key for key in missing if key not in {"milesPerDay", "weekdaySchedule", "stayOutDuration"}
        ]
    # Lease-on never collects city/ZIP during qualify.
    if not own:
        missing = [key for key in missing if key != "operatingArea"]
    # After own MC, authority maturity comes before OTR/local (no insurance questionnaire).
    if own and not fact_value(facts, "authorityAgeMonths") and "authorityAgeMonths" in missing:
        return "authorityAgeMonths"
    # Lease-on: after "yes I have insurance", ask coverage minimums before OTR/local.
    if (
        not own
        and fact_value(facts, "insurance") == "own_insurance"
        and not fact_value(facts, "coverageTypes")
        and "coverageTypes" in missing
    ):
        return "coverageTypes"
    # Types without limits confirmation → clarify amounts (do not assume minimums met).
    if (
        not own
        and fact_value(facts, "insurance") == "own_insurance"
        and fact_value(facts, "coverageTypes")
        and not fact_value(facts, "coverageLimits")
        and "coverageLimits" in missing
    ):
        return "coverageLimits"
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
    """Customer-facing fit narrative for chat — not the manager handoff brief."""
    n = fact_value(facts, "fleetSize")
    equip_key = fact_value(facts, "equipment")
    equip = EQUIP_LABELS.get(str(equip_key or ""), equip_key or "equipment") if equip_key else None
    length = fact_value(facts, "trailerLength")
    support = fact_value(facts, "equipmentSupport")
    if equip and length:
        equip_bit = f"{length} {equip}"
    elif equip:
        equip_bit = str(equip)
    else:
        equip_bit = "equipment still unconfirmed"
    plurals = {"dry van": "dry vans", "reefer": "reefers", "flatbed": "flatbeds", "box truck": "box trucks", "hotshot": "hotshots"}
    noun = plurals.get(str(equip), str(equip)) if n and n != 1 and equip else equip_bit
    count = f"{n} {noun}" if n and equip else equip_bit
    area = fact_value(facts, "operatingArea") or fact_value(facts, "lanes")
    area_bit = f" out of {area}" if area else ""
    mode = fact_value(facts, "operatingMode")
    miles = fact_value(facts, "milesPerDay")
    weekday = fact_value(facts, "weekdaySchedule")
    ops = []
    if mode:
        ops.append(str(mode).replace("_", " "))
    if miles:
        ops.append(f"{miles} miles/day")
    if weekday:
        ops.append(f"schedule {str(weekday).replace('_', ' ')}")
    ops_bit = f"; prefers {', '.join(ops)}" if ops else ""
    insurance = fact_value(facts, "insurance")
    ins_bit = ""
    if insurance == "needs_insurance":
        ins_bit = " Needs insurance arranged."
    elif insurance == "own_insurance":
        coverage = fact_value(facts, "coverageTypes")
        ins_bit = f" Own insurance on file ({coverage})." if coverage else " Own insurance on file."
    phone = fact_value(facts, "phone")
    cb_time = fact_value(facts, "callbackTime")
    cb_tz = fact_value(facts, "callbackTimezone")
    callback_bit = ""
    if phone or cb_time or cb_tz:
        pieces = [p for p in [phone and f"phone {phone}", cb_time and f"{cb_time}", cb_tz and str(cb_tz)] if p]
        callback_bit = f" Callback requested: {', '.join(pieces)}." if pieces else ""
    path = {
        "dispatch_service": "Own-MC path — onboarding sends the setup packet; chat alone isn't eligibility.",
        "lease_on": "Lease-on path — onboarding reviews fit and the agreement; asking here isn't approval.",
        "needs_clarification": "We still need own-MC vs lease-on before a packet can go out.",
    }.get(arrangement or "", "Onboarding still needs the arrangement before papers move.")
    if support == "in_scope" and equip:
        scope_bit = "In scope."
    elif support == "out_of_scope":
        scope_bit = "Outside current catalog."
    elif equip:
        scope_bit = "Catalog fit still to confirm."
    else:
        scope_bit = "Equipment not confirmed yet."
    unresolved = []
    if mode == "local" and not weekday:
        unresolved.append("Monday–Friday availability")
    # Own-MC does not collect city during qualify — only when they ask for load options.
    # Never treat missing city as a lease-on qualify gap.
    if not fact_value(facts, "startDate"):
        unresolved.append("start timing")
    if arrangement == "needs_clarification" or not fact_value(facts, "mcOwnership"):
        unresolved.append("MC arrangement")
    if insurance == "needs_insurance" and arrangement == "lease_on":
        unresolved.append("insurance options/quote")
    elif (
        insurance == "own_insurance"
        and arrangement == "lease_on"
        and fact_value(facts, "coverageTypes")
        and not fact_value(facts, "coverageLimits")
    ):
        unresolved.append("coverage limit confirmation")
    open_bits = f" Still open: {', '.join(unresolved)}." if unresolved else ""
    if arrangement == "lease_on" and insurance == "needs_insurance":
        title = "Lease-on, needs insurance"
    elif arrangement == "lease_on" and insurance == "own_insurance" and mode == "otr":
        title = "Lease-on, own insurance, OTR"
    elif arrangement == "lease_on" and insurance == "own_insurance" and mode == "local":
        title = "Lease-on, own insurance, local"
    elif arrangement == "dispatch_service":
        title = "Own-MC setup"
    elif arrangement == "lease_on":
        title = "Lease-on review"
    else:
        title = "Fit check"
    return (
        f"{title}: {count}{area_bit}{ops_bit}. "
        f"{scope_bit}{ins_bit} {path}{callback_bit}{open_bits} "
        "No live freight from this chat, and nothing's approved yet."
    )


def handoff_brief(
    facts: dict,
    arrangement: str | None,
    *,
    task: str | None = None,
    status: str | None = None,
    next_action: str | None = None,
    related_tasks: list[str] | None = None,
    opportunity_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Manager / Zoho summary — structured contact + qualify context."""
    equip_key = fact_value(facts, "equipment")
    equip = EQUIP_LABELS.get(str(equip_key or ""), equip_key) if equip_key else None
    length = fact_value(facts, "trailerLength")
    insurance = fact_value(facts, "insurance")
    route = fact_value(facts, "insuranceRoute")
    mode = _mode(facts)
    miles = fact_value(facts, "milesPerDay")
    weekday = fact_value(facts, "weekdaySchedule")
    phone = fact_value(facts, "phone")
    cb_time = fact_value(facts, "callbackTime")
    cb_tz = fact_value(facts, "callbackTimezone")
    support = fact_value(facts, "equipmentSupport")
    name = fact_value(facts, "name")
    email = fact_value(facts, "email")
    start = fact_value(facts, "startDate")
    authority_age = fact_value(facts, "authorityAgeMonths")

    contact = " · ".join(p for p in [name, email] if p) or "not captured yet"
    if length and equip:
        equipment_line = f"{length} {equip}"
    elif equip:
        equipment_line = str(equip)
    else:
        equipment_line = "not confirmed yet"

    if arrangement == "lease_on":
        if insurance == "needs_insurance":
            arrangement_line = "Lease-on, needs insurance"
        elif insurance == "own_insurance":
            arrangement_line = "Lease-on, own insurance"
        else:
            arrangement_line = "Lease-on"
    elif arrangement == "dispatch_service":
        arrangement_line = "Own-MC / dispatch service"
        if authority_age is not None:
            arrangement_line += f" (authority ~{authority_age} months)"
    else:
        arrangement_line = "Arrangement not confirmed"

    req_bits = []
    if mode:
        req_bits.append(str(mode).upper() if mode == "otr" else str(mode).replace("_", " ").title())
    if miles:
        req_bits.append(f"{miles} miles/day")
    if weekday:
        req_bits.append(str(weekday).replace("_", " "))
    if start:
        req_bits.append(f"start {start}")
    requirements_line = ", ".join(req_bits) if req_bits else "not confirmed yet"

    if not reason:
        if task == "insurance_quote" or (insurance == "needs_insurance" and arrangement == "lease_on"):
            reason = "Insurance and pricing review"
        elif task == "lease_agreement" and mode == "otr":
            reason = "Lease documents pending; manager to confirm OTR pricing"
        elif task == "lease_agreement" and mode == "local":
            reason = "Lease documents pending; manager for any fee negotiation"
        elif task == "lease_agreement":
            reason = "Lease agreement and papers pending review"
        elif task == "setup_packet":
            reason = "Own-MC setup review; documents pending"
        elif status == "manager_requested":
            reason = "Driver asked for an onboarding manager"
        elif task == "callback":
            reason = "Callback requested — contact timing recorded, not dialed"
        elif fact_value(facts, "requestedFeePercent"):
            reason = f"Pricing exception review — driver proposed {fact_value(facts, 'requestedFeePercent')}%"
        else:
            reason = "Fit / qualification update"

    action = next_action or "Manager to review and follow up"
    lines = [
        f"Name and email: {contact}",
        f"Equipment: {equipment_line}",
        f"Arrangement: {arrangement_line}",
        f"Requirements: {requirements_line}",
        f"Assistance requested: {reason}",
        f"Next action: {action}",
    ]
    if phone or cb_time or cb_tz:
        cb = ", ".join(p for p in [phone and f"phone {phone}", cb_time and str(cb_time), cb_tz and str(cb_tz)] if p)
        lines.append(f"Callback: {cb} (not dialed yet).")
    if support == "out_of_scope":
        lines.append("Note: equipment is outside current catalog.")
    if route == "company_arranged":
        lines.append("Insurance route: company-arranged.")
    related = [t for t in (related_tasks or []) if t and t != task]
    if related:
        lines.append(f"Related tasks: {', '.join(related)}.")
    if opportunity_id:
        lines.append(f"Inquiry ID: {opportunity_id}.")
    lines.append("Readiness interest is not clearance. Manager requested ≠ assigned ≠ accepted.")
    return "\n".join(lines)


def deal_title(facts: dict, arrangement: str | None, *, task: str | None = None, opportunity_id: str | None = None) -> str:
    equip_key = fact_value(facts, "equipment")
    equip = EQUIP_LABELS.get(str(equip_key or ""), equip_key) if equip_key else None
    length = fact_value(facts, "trailerLength")
    insurance = fact_value(facts, "insurance")
    suffix = (opportunity_id or "")[-8:]
    bits = []
    if arrangement == "lease_on":
        bits.append("Lease-on review")
    elif arrangement == "dispatch_service":
        bits.append("Own-MC setup")
    else:
        bits.append("Fit check")
    if length and equip:
        bits.append(f"{length} {equip}")
    elif equip:
        bits.append(str(equip))
    if insurance == "needs_insurance" or task == "insurance_quote":
        bits.append("Insurance assistance")
    elif task == "callback":
        bits.append("Callback")
    title = " | ".join(bits)
    return f"{title} ({suffix})" if suffix else title


def _has_question(text: str) -> bool:
    """True for '?' or period-ended interrogatives the model often emits."""
    if "?" in (text or ""):
        return True
    return bool(_INFO_REQUEST.search(text or ""))


# Model often asks without '?'. Count these as information requests for exclusivity checks.
_INFO_REQUEST = re.compile(
    r"(?:"
    r"what (?:is the )?length|"
    r"what (?:kind|type|coverage|number|city|zip|papers|documents)|"
    r"length (?:of|is) your|"
    r"what length|"
    r"do you (?:currently |still )?(?:have|prefer|need|want)|"
    r"are you (?:able|looking|running|interested)|"
    r"will you (?:run|be|need)|"
    r"when (?:would|do|can) you|"
    r"how (?:old|many|long|much)|"
    r"which (?:city|zip|papers|lanes)|"
    r"about how (?:old|many)|"
    r"best email|email (?:to|for) send"
    r")[^.?\n]{0,120}[.!]?",
    re.I,
)

_OWN_MC_FORBIDDEN_ASK = re.compile(
    r"(?:"
    r"own insurance|active commercial insurance|commercial auto|cargo insurance|"
    r"help getting (insurance )?set up|need help getting (insurance )?set up|"
    r"what coverage|coverage (?:does|do) your policy|"
    r"city or zip|which city|starting from|heading out from|operating from|"
    r"comfortable staying out|stay(?:ing)? out before"
    r")",
    re.I,
)

# Own-MC OTR must never surface these even if the model invents them.
_OWN_MC_OTR_FORBIDDEN_ASK = re.compile(
    r"(?:"
    r"miles (?:can you cover|a day|per day)|how many miles|"
    r"monday through friday|weekends (?:too|at home)|open to weekends|"
    r"comfortable staying out|stay(?:ing)? out before"
    r")",
    re.I,
)

_CITY_ASK = re.compile(
    r"city or zip|which city|starting from|heading out from|operating from|what (?:city|zip)|"
    r"what state are you|state are you based|based out of",
    re.I,
)

_LEASE_OTR_FORBIDDEN_ASK = re.compile(
    r"(?:"
    r"how many miles|miles (?:can you cover|are you|a day|per day|per\/day)|"
    r"miles.{0,24}(?:day|daily)|comfortable covering.{0,12}miles|"
    r"monday through friday|weekends (?:too|at home)|open to weekends|"
    r"comfortable staying out|stay(?:ing)? out before|"
    r"city or zip|which city|what state"
    r")",
    re.I,
)


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
    # Kill empty-ack / filler loops that never advance.
    if re.search(r"next open point|what'?s next on (your|the) (list|file)|anything else (i|we) (should|can) (note|cover)", low):
        return True
    # Stuck "fit already / future purchase / current setup" is not a qualify slot.
    if re.search(
        r"fit already|future purchase|current setup|planning a future purchase|"
        r"what'?s your current mc status|do you have a fit already",
        low,
    ):
        return True
    if fact_value(facts, "equipment") and re.search(
        r"what type of truck|what (truck|equipment) (are you|do you)|what are you running",
        low,
    ):
        return True
    # Reject replies that invent a different truck than the one on file.
    equip = fact_value(facts, "equipment")
    length = fact_value(facts, "trailerLength")
    if equip and length:
        length_num = re.match(r"(\d+)", str(length))
        if length_num and re.search(rf"\b(?!{length_num.group(1)}\b)\d{{2}}\s*(?:-)?\s*(?:ft|foot|feet)\b", low):
            # Another foot-length mentioned that isn't the stored one — likely hallucination.
            other = re.findall(r"(\d{2})\s*(?:-)?\s*(?:ft|foot|feet)\b", low)
            if any(n != length_num.group(1) for n in other):
                return True
    if equip == "box_truck" and re.search(r"\b(semi|dry van|reefer|flatbed|hotshot)\b", low) and not re.search(
        r"\bbox\b", low
    ):
        return True
    if equip in {"dry_van", "reefer", "flatbed", "step_deck"} and re.search(r"\b30\s*(?:-)?\s*ft.{0,20}box|box truck", low):
        return True
    if fact_value(facts, "mcOwnership") and re.search(r"own mc or lease|keeping your own mc", low):
        return True
    if (move == "pause" or any(t in topics for t in ("privacy_boundary", "expired_demand", "existing_dispatcher", "pause"))) and not _closure_safe(
        spoken
    ):
        return True
    if ask is None and re.search(r"what type of truck|what are you running", low):
        return True
    # Do not offer "regional" as a sold operating mode.
    if re.search(r"\bregional\b", low) and ask == "operatingMode":
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
        if "docs_status" in topic_list and not re.search(
            r"w-?9|authority|certificate|\bcoi\b|document|paper|photo|noa|voided|packet",
            low,
        ):
            return False
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

    # Supported type + unknown length → ask length. Never refuse / list catalog as a refusal.
    if awaiting_catalog_length(facts):
        unsupported = False
        ask = "trailerLength"
        if validated is not None:
            validated = {**validated, "next_question_id": "trailerLength"}
        if _OUT_OF_SCOPE_CLAIM.search(spoken or ""):
            spoken = ""
        if not spoken or _OUT_OF_SCOPE_CLAIM.search(spoken) or not _asks_about(spoken, "trailerLength"):
            label = EQUIP_LABELS.get(str(fact_value(facts, "equipment") or ""), "truck")
            spoken = f"Got it, {label}. {length_question(facts)}"
    else:
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
                # Length-gated but somehow marked out without a mismatch length — ask length instead.
                if eq in EQUIPMENT_LENGTHS_FT and not length:
                    unsupported = False
                    ask = "trailerLength"
                    spoken = length_question(facts)
                    refusal = None
                else:
                    refusal = lookup(EQUIP_KEYS.get(str(eq or ""), "equip_unsupported"))
            if unsupported and refusal and (
                not spoken
                or not re.search(
                    r"don'?t provide|do not provide|outside|not (in |within )?scope|don'?t dispatch|do not dispatch|"
                    r"only dispatch box trucks|24,\s*26,\s*or 28|catalog|outside our current service",
                    spoken,
                    re.I,
                )
            ):
                spoken = refusal

    # Own-MC / lease-on save always wins over model wording (one checklist; no city/fee mash).
    if (
        saved
        and arrangement in {"dispatch_service", "lease_on"}
        and fact_value(facts, "equipmentSupport") != "out_of_scope"
        and not awaiting_catalog_length(facts)
    ):
        if arrangement == "dispatch_service":
            parts[:] = [lookup("own_mc_review_saved")]
        elif fact_value(facts, "insurance") == "needs_insurance":
            parts[:] = [
                "I've asked our onboarding manager to take the lease agreement from here. They haven't approved anything yet.",
                lookup("docs_lease_needs_insurance"),
            ]
        else:
            parts[:] = [lookup("lease_review_saved")]
            try:
                from app import fees as feesmod

                parts.append(
                    feesmod.live_quote(
                        "lease_on",
                        insurance=fact_value(facts, "insurance"),
                        operating_mode=_mode(facts),
                    )
                )
            except Exception:
                pass
        return " ".join(_dedupe(parts)), CHIPS["handoff"], summary

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

    if _is_reactivation(user_text) and not spoken and intent != "onboard":
        parts.append(lookup("voluntary_return"))
        ask = next_ask(facts, mem, intent, repair)
        if ask and QUESTIONS.get(ask) and not _has_question(" ".join(parts)):
            parts.append(QUESTIONS[ask])
        return " ".join(_dedupe(parts)), CHIPS.get(ask) or CHIPS["default"], None

    if intent == "onboard" and arrangement in {"dispatch_service", "lease_on"} and not saved:
        # Qualify already complete — short status / one docs route only.
        if (
            arrangement == "dispatch_service"
            and fact_value(facts, "startDate")
            and not missing_core(facts, mem)
        ):
            parts.append(lookup("own_mc_ready_brief"))
            if receipt:
                parts.append(receipt)
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if arrangement == "lease_on" and not missing_core(facts, mem):
            if fact_value(facts, "insurance") == "needs_insurance":
                parts.append(lookup("ready_lease_needs_insurance"))
            else:
                # Start answered → docs first, then fee line (OTR negotiate / local 17%).
                parts.append(lookup("ready_lease_next"))
                parts.append(lookup("lease_docs_then_fee_bridge"))
                try:
                    from app import fees as feesmod

                    parts.append(
                        feesmod.live_quote(
                            "lease_on",
                            insurance=fact_value(facts, "insurance"),
                            operating_mode=_mode(facts),
                        )
                    )
                except Exception:
                    pass
            if receipt:
                parts.append(receipt)
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        # Ready before start date — ask start only (never city / miles on OTR).
        if (
            arrangement == "lease_on"
            and not fact_value(facts, "startDate")
            and next_ask(facts, mem, intent, repair) == "startDate"
        ):
            parts.append(lookup("ready_lease_need_start"))
            return " ".join(_dedupe(parts)), _chips_for_ask("startDate", facts), summary
        if arrangement == "dispatch_service":
            parts.append(lookup("ready_own_next"))
        elif fact_value(facts, "insurance") == "needs_insurance":
            parts.append(lookup("ready_lease_needs_insurance"))
        else:
            parts.append(lookup("ready_lease_next"))
        if receipt:
            parts.append(receipt)
        return " ".join(_dedupe(parts)), CHIPS["handoff"], summary

    if spoken and _wording_conflicts(spoken, facts, ask, move, topics):
        spoken = ""
        validated = {**validated, "wording": None}

    # Concern turns own the reply — don't let free model wording skip honesty/register lines.
    concern_owns_reply = concern in {
        "repetition",
        "packet_progress",
        "commitment",
        "pause",
        "privacy_boundary",
        "expired_demand",
        "existing_dispatcher",
        "missing_equipment",
        "negotiation",
        "fuel_requirement",
        "insurance_affordability",
        "payment_support",
    }

    # Model-authored path: deliver the validated full reply without concatenating register paragraphs.
    if (
        spoken
        and len(spoken) >= 12
        and not concern_owns_reply
        and intent not in {"existing_customer"}
        and repair not in {"leave_sales", "email_delivery", "repetition_unverified"}
        and (unsupported or _covers(spoken, topics))
    ):
        parts.append(spoken)
        # One question only: replace a wrong/missing ask with the playbook question.
        q = question_for(ask, facts)
        if ask and q and not unsupported and not _asks_about(" ".join(parts), ask):
            joined = " ".join(parts)
            if _has_question(joined):
                # Drop the model question; keep a short ack lead-in when safe.
                lead = re.split(r"[?]", joined, maxsplit=1)[0].strip().rstrip(".,;:")
                parts[:] = ([f"{lead}."] if lead and len(lead) <= 140 else []) + [q]
            else:
                parts.append(q)
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
        parts.append(lookup("fee_route_manager"))
        return " ".join(_dedupe(parts)), CHIPS["handoff"], None

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
        # One composition route (also handled earlier for model path).
        if arrangement == "dispatch_service":
            parts[:] = [lookup("own_mc_review_saved")]
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if arrangement == "lease_on":
            if fact_value(facts, "insurance") == "needs_insurance":
                parts[:] = [
                    "I've asked our onboarding manager to take the lease agreement from here. They haven't approved anything yet.",
                    lookup("docs_lease_needs_insurance"),
                ]
            else:
                parts[:] = [lookup("lease_review_saved")]
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if spoken and action_message:
            parts.append(spoken)
            parts.append(action_message)
            return " ".join(_dedupe(parts)), CHIPS["handoff"], summary
        if arrangement == "needs_clarification":
            parts.append("Onboarding will confirm own-MC vs lease-on before any packet goes out.")
        else:
            parts.append(
                action_message
                or "I've asked our onboarding manager to take this from here. They haven't approved anything yet."
            )
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

    pending_ask = (validated or {}).get("next_question_id")
    # After "I need insurance", acknowledge review before the next qualify question.
    if (
        pending_ask == "operatingMode"
        and fact_value(facts, "insurance") == "needs_insurance"
        and not any("insurance" in (p or "").lower() for p in parts)
        and not spoken
    ):
        parts.append(lookup("insurance_assist_ack"))

    question, ask = select_question(validated, parts, facts)
    if question:
        parts.append(question)
    elif not parts:
        parts.append(lookup("welcome"))

    chips = _chips_for_ask(ask, facts) if ask else (CHIPS["assess"] if core_done else CHIPS["default"])
    if not chips:
        chips = CHIPS.get(ask) or (CHIPS["assess"] if core_done else CHIPS["default"])
    return " ".join(_dedupe(parts)), chips, summary


def action_confirmation(action_message: str | None, saved: bool) -> str | None:
    return action_message if allow_action_message(action_message, saved) else None


def select_question(plan: dict, parts: list[str], facts: dict | None = None) -> tuple[str | None, str | None]:
    ask = (plan or {}).get("next_question_id")
    q = question_for(ask, facts or {})
    if ask and q and not _has_question(" ".join(parts)):
        return q, ask
    return None, ask


_ASK_MARKERS = {
    "equipment": r"what type of truck|what are you running",
    "trailerLength": (
        r"what (?:is the )?length|length (?:of|is) your|what length|"
        r"24,\s*26,\s*or 28|length trailer|length.*(?:box|reefer|flatbed|van|hotshot|deck)"
    ),
    "mcOwnership": r"own mc|lease on",
    "insurance": r"own insurance on the truck|have your own insurance",
    "coverageTypes": r"750,?000|100,?000|commercial auto liability|cargo coverage|both minimums",
    "coverageLimits": r"at or above those minimums|750,?000 auto|100,?000 cargo",
    "authorityAgeMonths": r"how old is your mc|age of your mc|authority\?",
    "operatingMode": r"otr or staying local|prefer otr|staying local",
    "milesPerDay": r"miles can you cover|miles.*a day|miles per day",
    "stayOutDuration": r"stay(?:ing)? out|comfortable staying out",
    "operatingArea": r"operating from|city or zip|which city",
    "weekdaySchedule": r"monday through friday|weekends at home|stay on the road monday",
    "startDate": r"when would you like to start|when do you (?:want|need) to start|start timing",
    "phone": r"what number should|callback number|timezone|country code",
}


def _asks_about(text: str, ask: str | None) -> bool:
    if not ask or not text:
        return False
    marker = _ASK_MARKERS.get(ask)
    if not marker:
        q = QUESTIONS.get(ask) or ""
        return bool(q) and q.lower().rstrip("?") in text.lower()
    return bool(re.search(marker, text, re.I))


_POLLUTED_DELIVERY = re.compile(
    r"fit already|future purchase|current setup|current mc status|"
    r"i don'?t have that answer|can'?t set up a case|cannot set up a case|"
    r"i'?ll keep the door open|outside our current|don'?t provide dispatch|"
    r"30 or 40-foot box truck|switch to a supported",
    re.I,
)


def _chips_for_ask(ask: str | None, facts: dict) -> list[str]:
    from app.schema import length_chip_labels

    if ask == "trailerLength":
        return length_chip_labels(fact_value(facts, "equipment"))
    return list(CHIPS.get(ask) or CHIPS["default"])


def _ungrounded_equipment_claim(spoken: str, facts: dict) -> bool:
    """True when wording asserts a truck/length that is not on file."""
    if not spoken:
        return False
    equip = fact_value(facts, "equipment")
    length = fact_value(facts, "trailerLength")
    claims_box = bool(re.search(r"\b\d+\s*-?\s*(foot|ft)?\s*box\s*truck\b|\bbox\s*truck\b", spoken, re.I))
    claims_hotshot = bool(re.search(r"\bhotshot\b|\bhot\s*shot\b", spoken, re.I))
    claims_length = re.search(r"\b(\d+)\s*-?\s*(foot|ft)\b", spoken, re.I)
    if claims_box and str(equip) not in {"box_truck"}:
        return True
    if claims_hotshot and str(equip) not in {"hotshot"}:
        return True
    if claims_length and not length:
        # "Got it—a 26-foot …" with no saved length is invented.
        if re.search(r"got it", spoken, re.I):
            return True
    if claims_length and length:
        claimed = claims_length.group(1)
        saved = re.sub(r"[^\d]", "", str(length))
        if claimed and saved and claimed != saved:
            return True
    return False


def _ack_for_ask(facts: dict, ask: str | None) -> str:
    """Acknowledge truck/length only on the turn that first advances off that fact.

    Later qualify slots must not re-stamp "Got it — 48ft reefer" on every question.
    """
    equip = fact_value(facts, "equipment")
    if not equip or ask == "equipment":
        return ""
    label = EQUIP_LABELS.get(str(equip), str(equip).replace("_", " "))
    length = fact_value(facts, "trailerLength")
    if ask == "trailerLength":
        return f"Got it — {label}. "
    if ask == "mcOwnership" and length:
        return f"Got it, {length} {label}. "
    if ask == "mcOwnership":
        return f"Got it — {label}. "
    return ""


_STALE_EQUIP_ECHO = re.compile(
    r"^\s*got it\s*[—\-–,.]?\s*"
    r"(?:a\s+)?"
    r"(?:\d+\s*-?\s*ft\s+)?"
    r"(?:reefer|flatbed|box\s*truck|hotshot|dry\s*van|step\s*deck|power\s*only)"
    r"[^.?!]*[.!]?\s*",
    re.I,
)


def _strip_stale_equip_echo(spoken: str, ask: str | None, facts: dict) -> str:
    """Drop repeated truck stamps once length is on file and we've moved past MC ownership."""
    if ask in {None, "equipment", "trailerLength", "mcOwnership"}:
        return spoken
    if not fact_value(facts, "equipment") or not fact_value(facts, "trailerLength"):
        return spoken
    cleaned = _STALE_EQUIP_ECHO.sub("", spoken or "").strip()
    return cleaned or spoken


def _info_request_count(text: str) -> int:
    return len(_INFO_REQUEST.findall(text or ""))


def align_delivery(text: str, ask: str | None, facts: dict) -> tuple[str, str | None, list[str]]:
    """Force wording, pending question, and chips to agree before the customer sees them.

    Every information request must map to the single permitted next field — presence of the
    expected question is not enough if a forbidden or extra ask also appears.
    """
    spoken = (text or "").strip()
    chips = _chips_for_ask(ask, facts) if ask else None
    own = fact_value(facts, "mcOwnership") == "own_mc"
    lease = fact_value(facts, "mcOwnership") == "no_own_mc"
    otr = _mode(facts) == "otr"

    def _replace_with_canonical() -> str:
        q = question_for(ask, facts) or ""
        return (_ack_for_ask(facts, ask) + q).strip()

    # Premature catalog refusal while length is still unknown — always one length ask.
    if awaiting_catalog_length(facts):
        ask = "trailerLength"
        spoken = (_ack_for_ask(facts, "trailerLength") + length_question(facts)).strip()
        return spoken, "trailerLength", list(_chips_for_ask("trailerLength", facts))

    # OTR (own-MC or lease-on): never deliver a miles / weekday / stay-out ask.
    if otr and ask in {"milesPerDay", "weekdaySchedule", "stayOutDuration"}:
        ask = "startDate" if not fact_value(facts, "startDate") else None
        if ask:
            spoken = (_ack_for_ask(facts, ask) + question_for(ask, facts)).strip()
            return spoken, ask, list(_chips_for_ask(ask, facts))
        spoken = lookup("lease_ready_brief" if lease else "own_mc_ready_brief")
        return spoken, None, list(CHIPS["handoff"])

    if ask and question_for(ask, facts):
        equip = fact_value(facts, "equipment")
        wrong_equip = bool(
            (str(equip) == "hotshot" and re.search(r"\bbox\s*truck\b", spoken, re.I))
            or (str(equip) == "box_truck" and re.search(r"\bhotshot\b", spoken, re.I))
        )
        invented = _ungrounded_equipment_claim(spoken, facts)
        about = _asks_about(spoken, ask)
        extras = _info_request_count(spoken) > 1
        forbidden = own and bool(_OWN_MC_FORBIDDEN_ASK.search(spoken))
        otr_polluted = (own or lease) and otr and bool(
            (_OWN_MC_OTR_FORBIDDEN_ASK if own else _LEASE_OTR_FORBIDDEN_ASK).search(spoken)
        )
        city_polluted = bool(_CITY_ASK.search(spoken)) and ask != "operatingArea"
        email_invent = own and bool(_EMAIL_INVENT_ASK.search(spoken))
        # Insurance/city/stay-out must not ride along even when the age/OTR/start ask is present.
        # Own-MC / lease OTR: strip miles / Monday–Friday / city invents when start is pending.
        wrong_or_polluted = (
            not about
            or extras
            or forbidden
            or otr_polluted
            or city_polluted
            or email_invent
            or _POLLUTED_DELIVERY.search(spoken)
            or wrong_equip
            or invented
            or (ask == "trailerLength" and _OUT_OF_SCOPE_CLAIM.search(spoken))
        )
        if wrong_or_polluted:
            spoken = _replace_with_canonical()
        elif not _has_question(spoken):
            spoken = f"{spoken} {question_for(ask, facts)}".strip()
        else:
            # Right slot only — keep first info request sentence + ensure canonical ask once.
            if not about or extras:
                spoken = _replace_with_canonical()
            else:
                # Strip any second '?'-style ask; period hybrids already caught via extras.
                spoken = re.sub(r"\?\s+.*\?", "?", spoken).strip()
                if extras or _info_request_count(spoken) > 1:
                    spoken = _replace_with_canonical()
                if own and (
                    _OWN_MC_FORBIDDEN_ASK.search(spoken)
                    or (otr and _OWN_MC_OTR_FORBIDDEN_ASK.search(spoken))
                    or _EMAIL_INVENT_ASK.search(spoken)
                    or _CITY_ASK.search(spoken)
                ):
                    spoken = _replace_with_canonical()
                if lease and (
                    _CITY_ASK.search(spoken)
                    or (otr and _LEASE_OTR_FORBIDDEN_ASK.search(spoken))
                ):
                    spoken = _replace_with_canonical()
        spoken = _strip_stale_equip_echo(spoken, ask, facts)
        # If stripping left only the question-less residue, restore canonical ask.
        if ask and question_for(ask, facts) and not _asks_about(spoken, ask):
            spoken = _replace_with_canonical()
        return spoken, ask, list(chips or _chips_for_ask(ask, facts))

    # No pending qualify question.
    if own and _EMAIL_INVENT_ASK.search(spoken):
        spoken = lookup("own_mc_ready_brief")
        return spoken, None, list(CHIPS["assess"] if not missing_core(facts) else CHIPS["handoff"])

    if (own or lease) and (
        (own and _OWN_MC_FORBIDDEN_ASK.search(spoken))
        or _CITY_ASK.search(spoken)
        or (own and otr and _OWN_MC_OTR_FORBIDDEN_ASK.search(spoken))
        or (lease and otr and _LEASE_OTR_FORBIDDEN_ASK.search(spoken))
    ):
        # Drop invented insurance/city asks after qualify is complete.
        if re.search(r"load|freight|dispatch", spoken, re.I):
            spoken = lookup("loads_route_team")
        elif lease and not missing_core(facts):
            spoken = lookup("lease_ready_brief")
        else:
            equip = fact_value(facts, "equipment")
            length = fact_value(facts, "trailerLength")
            if equip:
                label = EQUIP_LABELS.get(str(equip), str(equip).replace("_", " "))
                focus = f"{length} {label}" if length else label
                spoken = f"Got it — {focus} is on file. What else should we cover?"
            else:
                spoken = lookup("welcome")
        return spoken, None, list(CHIPS["assess"] if not missing_core(facts) else CHIPS["default"])

    if re.search(r"fit already|future purchase|current setup|current mc status", spoken, re.I):
        equip = fact_value(facts, "equipment")
        length = fact_value(facts, "trailerLength")
        if equip:
            label = EQUIP_LABELS.get(str(equip), str(equip).replace("_", " "))
            focus = f"{length} {label}" if length else label
            spoken = f"Got it — {focus} is on file. What else should we cover?"
        else:
            spoken = lookup("welcome")
    return spoken, None, list(CHIPS["default"])
