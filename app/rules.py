"""Deterministic guard. Qwen proposes every turn; these rules only constrain and fill gaps."""

from __future__ import annotations

import re

from app.playbook import next_ask
from app.schema import INTENTS


def detect_repair(text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"mailbox|inbox (is )?full|email (couldn'?t|could not|bounced)|send (it )?again|sand again", t):
        return "email_delivery"
    if re.search(r"forget (onboarding|the packet|sales)|need to get paid|where'?s my (money|settlement|paycheck)", t):
        return "leave_sales"
    if re.search(r"no,? i meant|i meant (the )?(fee|percent|charge)|i was asking about (the )?(fee|percent|charge)", t):
        return "topic_fee"
    if re.search(r"authority is ready|mc is ready|authority came (in|through)", t) and not re.search(
        r"own mc|lease on|lease-on", t
    ):
        return "authority_uncertain"
    if re.search(r"already (sent|gave|provided) everything|i have everything", t):
        return "repetition_unverified"
    if re.search(r"actually|make that|not two|three instead|correction", t):
        return "correct_fact"
    return None


PAYMENT_ASK = re.compile(
    r"\b(pay\s*me|payme|payment|paid me|where'?s my (money|check|settlement|paycheck)|"
    r"when (do|will) (i|we) get paid|invoice now|zelle|quick\s*pay)\b",
    re.I,
)


def detect_intent(text: str) -> str:
    t = text.lower()
    repair = detect_repair(text)
    if repair == "leave_sales":
        return "existing_customer"
    if repair == "topic_fee":
        return "fee"
    if repair == "authority_uncertain":
        return "mc_new"
    # Payment complaints are operations — never match substring "lease" inside "please".
    if PAYMENT_ASK.search(text or ""):
        return "existing_customer"
    if re.search(r"(existing|already (a )?carrier|where's my load|where is my load|detention|tonu)", t):
        return "existing_customer"
    if re.search(r"let you know|not right now|i'?ll think|maybe later|next summer", t):
        return "general"
    if re.search(r"(talk here|speak|voice|microphone)", t):
        return "talk_here"
    if re.search(r"(call me|callback|phone me|dial)", t):
        return "call_me"
    if re.search(r"not interested|no thanks|don't call|stop (texting|messaging)|leave me alone", t):
        return "decline"
    if re.search(r"sign for nothing|don'?t want to sign|am i binding|just (asking|looking|chatting)|signing up", t):
        return "commit"
    if re.search(r"when do (i|we) get paid|invoice now|pay after|payment timing", t):
        return "fee"
    if re.search(r"other dispatcher|leo dispatch|match (their|his) (rate|percent)|cheaper than (them|leo)", t):
        return "fee"
    if re.search(
        r"\bfees?\b|\bpercent\b|%|\bcharge\b|\bcost\b|how much|expensive|too much|\bcheaper\b",
        t,
    ):
        return "fee"
    if re.search(r"(guarantee|earn|\$\d|weekly gross)", t):
        return "guarantee"
    if re.search(
        r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded|"
        r"\b(have (a |any )?loads?|need (a )?loads?|looking for (a )?loads?|any loads?|"
        r"loads? in |load availability|do we have (a )?load|facebook.{0,40}loads?)\b",
        t,
    ):
        return "freight"
    if "fuel card" in t or re.search(r"\bfuel advance\b", t):
        return "fuel"
    if re.search(r"trust|scam|legit", t):
        return "trust"
    if re.search(r"home (every )?night|home time", t):
        return "hometime"
    if re.search(r"talk to (a )?(human|person|agent)|dispatcher please", t):
        return "human"
    if re.search(r"document|packet|onboard|ready to start|get started|i'm ready|how do i start", t):
        return "onboard"
    if re.search(r"new mc|pending (mc|authority)|authority is new|\bi('?m| am) new\b|brand new (mc|authority)", t):
        return "mc_new"
    if re.search(r"\blease(-?on)?\b", t):
        return "lease"
    if re.search(r"\bmc\b|authority", t):
        return "mc"
    if re.search(r"(what (trucks|equipment)|do you (haul|dispatch|support)|packages or pallets)", t):
        return "service"
    if re.search(r"status|approved yet|dispatcher'?s name|waiting on you", t):
        return "status"
    if re.search(r"don'?t know|not sure yet|unknown|skip that", t):
        return "unknown_detail"
    if re.search(r"dispatch|need (a )?dispatcher|looking for dispatch", t):
        return "dispatch_inquiry"
    return "general"


AD_LOAD = re.compile(
    r"facebook|(i (saw|seen|have seen) your)|your post|you seem to have|advertis",
    re.I,
)
OWNED_TRUCK = re.compile(r"\bmy\b.{0,32}(reefer|dry van|flatbed|box truck|hotshot|\bbox\b)", re.I)
EQUIP_WORD = re.compile(r"reefer|dry van|flatbed|box truck|hotshot|\bbox\b", re.I)
OWNED_CLAIM = re.compile(
    r"\bi (run|have|drive|got) (a |my )?(reefer|dry van|flatbed|box truck|hotshot|\bbox\b)",
    re.I,
)


def normalize_equip(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.lower().replace(" ", "_")
    return "box_truck" if value == "box" else value


def is_advertised_equipment(text: str) -> bool:
    return bool(AD_LOAD.search(text or "")) and not OWNED_TRUCK.search(text or "")


def advertised_mention(text: str) -> tuple[str | None, str | None]:
    if not is_advertised_equipment(text):
        return None, None
    mentioned = EQUIP_WORD.search(text or "")
    length = re.search(r"(\d+)\s*(?:-)?\s*(?:ft|foot|feet)\b", (text or "").lower())
    eq = normalize_equip(mentioned.group(0) if mentioned else None)
    ln = f"{length.group(1)}ft" if length else None
    return eq, ln


def owned_equipment_claim(text: str) -> bool:
    t = text or ""
    return bool(OWNED_TRUCK.search(t) or OWNED_CLAIM.search(t))


def extract_facts(text: str) -> list[dict]:
    t = text.lower()
    items = []
    equip = EQUIP_WORD.search(t)
    advertised = is_advertised_equipment(text)
    if equip and not advertised:
        items.append({"key": "equipment", "value": normalize_equip(equip.group(0)), "status": "user_stated"})
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a": 1}
    count = re.search(
        r"(\d+|one|two|three|four|five|six|a)\s+(?:box\s+|dry\s+|flatbed\s+|reefer\s+|hotshot\s+)?(trucks?|reefers?|vans?|hotshots?)",
        t,
    )
    if count:
        raw = count.group(1)
        value = words.get(raw, int(raw) if raw.isdigit() else None)
        if value is not None:
            status = "corrected" if re.search(r"actually|make that|correction|not one|changed|three instead|now \d", t) else "user_stated"
            items.append({"key": "fleetSize", "value": value, "status": status})
    if re.search(r"authority is ready|mc is ready|authority came (in|through)", t) and not re.search(
        r"own mc|lease on|lease-on", t
    ):
        items.append({"key": "mcOwnership", "value": "unclear", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "needs_clarification", "status": "user_stated"})
    elif re.search(r"(own mc|my own mc|have (an? )?mc|my mc (is|has|was)|mc is \d)", t) and not re.search(
        r"new mc|pending|authority is ready|i am new|i'm new", t
    ):
        items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    elif re.search(r"my authority", t) and not re.search(r"ready|pending|new mc", t):
        items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    if re.search(r"(no mc|don'?t have.*mc|lease on|lease-on)", t):
        items.append({"key": "mcOwnership", "value": "no_own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "lease_on", "status": "user_stated"})
    if re.search(r"\bi('?m| am) new\b|new to (this|dispatch|trucking)|brand new mc|just got (my )?mc", t) or (
        re.search(r"(pending|not sure|unsure|another company|new mc)", t) and re.search(r"\bmc\b|authority", t)
    ):
        items.append({"key": "mcOwnership", "value": "unclear", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "needs_clarification", "status": "user_stated"})
    area = re.search(
        r"midwest|southeast|northeast|southwest|west coast|southern states|texas|california|georgia|florida|"
        r"dallas|houston|atlanta|chicago|irving|utah|michigan|new jersey|\bnj\b|jersey",
        t,
        re.I,
    )
    if area:
        value = area.group(0).lower().replace("new jersey", "nj").replace("southern states", "southern_states")
        if value in {"jersey"}:
            value = "nj"
        items.append({"key": "operatingArea", "value": value, "status": "user_stated"})
        items.append({"key": "lanes", "value": value, "status": "user_stated"})
    # "pies" = feet in Spanish length answers (e.g. "26 pies").
    length = re.search(r"(\d+)\s*(?:-)?\s*(?:ft|foot|feet|pies)\b", t)
    if length and not advertised:
        items.append({"key": "trailerLength", "value": f"{length.group(1)}ft", "status": "user_stated"})
    payload = re.search(r"(?:payload|weigh(?:t|s)|haul)\s*(?:of\s*)?(\d[\d,]*)\s*(lb|lbs|pound)", t) or re.search(
        r"(\d[\d,]*)\s*(lb|lbs|pounds)\s*(?:payload)?", t
    )
    preferred = re.search(
        r"(?:about |around |prefer(?:ring)? |want(?:ing)? |can (?:do|haul) )?(\d[\d,]*)\s*(?:-|to|–)\s*(\d[\d,]*)\s*(lb|lbs|pounds)?",
        t,
    )
    rejected_load = bool(re.search(r"too much|can'?t (haul|take|do)|over (my|the)|not for my|exceed", t))
    if preferred and preferred.group(2).isdigit():
        items.append(
            {
                "key": "preferredPayload",
                "value": f"{preferred.group(1).replace(',', '')}-{preferred.group(2).replace(',', '')}",
                "status": "user_stated",
            }
        )
    elif payload and rejected_load:
        items.append(
            {
                "key": "rejectedLoadWeight",
                "value": payload.group(1).replace(",", ""),
                "status": "user_stated",
            }
        )
    elif payload:
        items.append({"key": "payload", "value": payload.group(1).replace(",", ""), "status": "user_stated"})
    if re.search(r"liftgate", t):
        items.append({"key": "liftgate", "value": "yes" if not re.search(r"no liftgate|without liftgate", t) else "no", "status": "user_stated"})
    if re.search(
        r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait",
        t,
    ):
        items.append({"key": "insurance", "value": "needs_insurance", "status": "user_stated"})
    elif re.search(r"need insurance|no insurance|don'?t have insurance|looking for insurance", t):
        items.append({"key": "insurance", "value": "needs_insurance", "status": "user_stated"})
    elif re.search(r"have (my |our )?(own )?insurance|i('m| am) insured|got insurance", t) and not re.search(
        r"need liability|need cargo|only physical", t
    ):
        items.append({"key": "insurance", "value": "own_insurance", "status": "user_stated"})
    if re.search(r"monday through friday|mon(day)?\s*(to|-|through)\s*fri|weekdays", t):
        items.append({"key": "weekdaySchedule", "value": "monday_friday", "status": "user_stated"})
    elif re.search(r"home weekends|weekends? home|flexible schedule", t):
        items.append({"key": "weekdaySchedule", "value": "flexible", "status": "user_stated"})
    miles = re.search(r"(\d{2,4})\s*(?:-|to)\s*(\d{2,4})(?:\s*miles)?", t) or re.search(
        r"(\d{2,4})\s*miles (a|per) day", t
    )
    if miles:
        if miles.lastindex and miles.lastindex >= 2 and (miles.group(2) or "").isdigit():
            value = f"{miles.group(1)}-{miles.group(2)}"
        else:
            value = miles.group(1)
        items.append({"key": "milesPerDay", "value": value, "status": "user_stated"})
    if re.search(r"\blocal\b|no otr|not otr|home every night", t):
        items.append({"key": "operatingMode", "value": "local", "status": "user_stated"})
    elif re.search(r"\botr\b", t):
        items.append({"key": "operatingMode", "value": "otr", "status": "user_stated"})
    if re.search(r"don'?t want to sign|won'?t sign|sign for nothing", t):
        items.append({"key": "commitmentStance", "value": "wont_sign", "status": "user_stated"})
    if not any(item["key"] == "weekdaySchedule" for item in items):
        day = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|asap|immediately)\b", t)
        if day:
            items.append({"key": "deadline", "value": day.group(1), "status": "user_stated"})
            items.append({"key": "startDate", "value": day.group(1), "status": "user_stated"})
    if re.search(r"home every night|daily home|home time", t):
        items.append({"key": "supportNeed", "value": "daily_home_time", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "home_time", "status": "user_stated"})
    if re.search(r"paperwork|factoring|broker calls", t):
        items.append({"key": "supportNeed", "value": "paperwork", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "paperwork", "status": "user_stated"})
    if re.search(r"better loads?|keep(ing)? (me |the truck )?loaded|empty miles", t):
        items.append({"key": "supportNeed", "value": "keep_loaded", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "freight", "status": "user_stated"})
    if re.search(r"expensive|too much|cheaper|rates", t):
        items.append({"key": "primaryProblem", "value": "rates", "status": "user_stated"})
    if re.search(r"start (next week|immediately|asap|monday)", t):
        items.append({"key": "startDate", "value": re.search(r"next week|immediately|asap|monday", t).group(0), "status": "user_stated"})
    if re.search(r"\bnext week\b", t) and "start" not in t:
        items.append({"key": "startDate", "value": "next week", "status": "user_stated"})
    phone = re.search(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
    if phone:
        items.append({"key": "phone", "value": phone.group(0), "status": "confirmed"})
    name = re.search(r"my name is ([a-z][a-z ]{1,40})", text, re.I)
    if name:
        items.append({"key": "name", "value": name.group(1).strip(), "status": "confirmed"})
    if re.search(r"don'?t know|not sure yet|unknown|skip that", t):
        items.append({"key": "_unknown", "value": True, "status": "unknown"})
    # Customer counteroffer — recorded for review, never auto-accepted as the live fee.
    offer = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
    cap = re.search(r"\$?\s*(\d[\d,]*)\s*(?:weekly|week)?\s*cap", t)
    if offer and re.search(r"%|percent|cap|you pay|i (want|need|propose)", t):
        items.append({"key": "requestedFeePercent", "value": offer.group(1), "status": "user_stated"})
    if cap:
        items.append({"key": "requestedWeeklyCap", "value": cap.group(1).replace(",", ""), "status": "user_stated"})
    return items


def blocked_from_text(text: str) -> list[str]:
    t = text.lower()
    blocked = []
    if re.search(r"guarantee|\$\s*\d|weekly gross|10k|per week", t):
        blocked.append("guarantee")
    if re.search(r"\d+\s*%|discount", t):
        blocked.append("invented_fee")
    if re.search(r"coi is valid|insurance (is )?good|you('re| are) approved", t):
        blocked.append("insurance_approved")
    return blocked


def knowledge_for(
    intent: str,
    blocked: list[str],
    equipment: str | None,
    text: str = "",
    extracted: list | None = None,
    arrangement: str | None = None,
) -> list[str]:
    keys = []
    if "guarantee" in blocked or intent == "guarantee":
        keys.append("guarantee")
    mapping = {
        "fee": ["fee"],
        "fuel": ["fuel"],
        "freight": ["freight"],
        "service": ["services"],
        "talk_here": ["talk_here"],
        "call_me": ["call_me"],
        "existing_customer": ["support"],
        "lease": ["lease"],
        "mc": ["own_mc"],
        "mc_new": ["mc_new"],
        "onboard": ["onboarding", "dispatch_vs_onboarding"],
        "trust": ["trust"],
        "commit": ["concern_commitment", "commit"],
        "email_delivery": ["email_delivery"],
        "decline": ["commit"],
        "dispatch_inquiry": ["services", "dispatch_how"],
        "status": ["docs_status"],
        "freight": ["freight", "load_evaluate", "loads_after_onboarding"],
    }
    keys.extend(mapping.get(intent, []))
    t = (text or "").lower()
    if PAYMENT_ASK.search(text or ""):
        keys = ["payment_support", "support", "trip_docs_invoice"]
    if re.search(
        r"what do you (actually )?do( for me)?|how (does |do )?(dispatch|your (service|dispatch)) work|"
        r"what (does|do) (a |the )?dispatcher|explain dispatch",
        t,
    ):
        keys.extend(["dispatch_how", "dispatch_vs_onboarding", "load_approval"])
    if re.search(r"approve (each |every |the )?load|rate confirmation|who (signs|books)", t):
        keys.extend(["load_approval", "docs_rate_con_detail"])
    if re.search(r"\bdetention\b|\blayover\b|\btonu\b|accessorial", t):
        keys.append("accessorials")
    if re.search(r"home every night|daily home time|\bhome time\b", t):
        keys.append("home_time")
    if re.search(r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait", t):
        keys.append("insurance_affordability")
    if re.search(r"i received (it|the packet)|received the packet|send it tomorrow", t):
        keys.append("packet_received")
    if re.search(r"\d+\s*%|weekly cap|take it off the first delivery", t):
        keys.extend(["negotiation", "broker_vs_fee"])
    if re.search(r"need a trailer|buying (a |the )?truck|don'?t have (a )?trailer", t):
        keys.append("missing_equipment")
    if re.search(r"next summer|i'?ll start again", t):
        keys.append("deferred")
    if re.search(r"sign for nothing|don'?t want to sign", t):
        keys.append("concern_commitment")
    if re.search(r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded|deadhead", t):
        keys.extend(["freight", "load_evaluate"])
    if re.search(r"other dispatcher|leo dispatch|competitor", t):
        keys.append("competitor")
    if re.search(r"invoice|pay after|when.{0,20}paid|payment timing", t):
        keys.extend(["payment_timing", "trip_docs_invoice"])
    from app import docs as docmod

    for key in docmod.keys_for(text, arrangement):
        if key not in keys:
            keys.append(key)
    stated = {item.get("key") for item in extracted or []}
    if equipment and intent in {"service", "dispatch_inquiry"}:
        from app.knowledge import EQUIP_KEYS

        extra = EQUIP_KEYS.get(str(equipment))
        if extra:
            keys.append(extra)
    elif equipment and "equipment" in stated and intent not in {"fee", "guarantee", "commit", "mc", "lease"}:
        from app.knowledge import EQUIP_KEYS

        extra = EQUIP_KEYS.get(str(equipment))
        if extra:
            keys.append(extra)
    return list(dict.fromkeys(keys))


def arrangement_of(facts: dict) -> str | None:
    mc = facts.get("mcOwnership", {}).get("value") if isinstance(facts.get("mcOwnership"), dict) else None
    if mc == "own_mc":
        return "dispatch_service"
    if mc == "no_own_mc":
        return "lease_on"
    if mc == "unclear":
        return "needs_clarification"
    return None


def task_for(arrangement: str | None, intent: str) -> str | None:
    if intent == "existing_customer":
        return "operations_support"
    if intent == "call_me":
        return "callback"
    if arrangement == "dispatch_service":
        return "setup_packet"
    if arrangement == "lease_on":
        return "lease_agreement"
    if arrangement == "needs_clarification":
        return "clarification"
    return None


def propose(text: str, facts: dict, memory: dict | None = None) -> dict:
    from app import plan as planmod

    from app import memory as memmod

    intent = detect_intent(text)
    repair = detect_repair(text)
    items = extract_facts(text)
    current_equip = facts.get("equipment", {}).get("value") if isinstance(facts.get("equipment"), dict) else None
    ad_value, ad_length = advertised_mention(text)
    if ad_value and current_equip and ad_value != current_equip:
        repair = "equip_ambiguous"
    elif memmod.open_ambiguity(memory, "equipment") and not owned_equipment_claim(text):
        repair = "equip_ambiguous"
    blocked = blocked_from_text(text)
    preview = dict(facts)
    for item in items:
        if item["key"] == "_unknown":
            continue
        preview[item["key"]] = {"value": item["value"], "status": item["status"]}
    arrangement = arrangement_of(preview)
    equip = preview.get("equipment", {}).get("value") if isinstance(preview.get("equipment"), dict) else None
    ask = next_ask(preview, memory, intent, repair)
    action = "none"
    if intent == "talk_here":
        action = "talk_here"
    elif intent == "call_me":
        action = "callback"
    elif intent == "human":
        action = "takeover"
    elif intent == "existing_customer" or repair == "leave_sales":
        action = "create_case"
        intent = "existing_customer"
    elif intent == "onboard" and arrangement and equip:
        action = "create_case"
    if repair == "authority_uncertain":
        action = "none"
    if repair == "equip_ambiguous":
        action = "none"
        ask = None
    if repair == "repetition_unverified":
        blocked.append("insurance_approved")
    return {
        "intent": intent if intent in INTENTS else "general",
        "facts": items,
        "knowledge_keys": (
            ["email_delivery"]
            if repair == "email_delivery"
            else knowledge_for(intent, blocked, equip, text, items, arrangement)
        ),
        "blocked": blocked,
        "next_field": ask,
        "arrangement": arrangement,
        "action": action,
        "task": task_for(arrangement, intent),
        "repair": repair,
        "advertised_equipment": ad_value,
        "advertised_length": ad_length,
        "answer_topics": planmod.detect_topics(text, intent, None, repair),
        "_source": "rules",
    }
