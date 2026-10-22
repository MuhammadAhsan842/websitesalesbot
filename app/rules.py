"""Deterministic guard. Qwen proposes every turn; these rules only constrain and fill gaps."""

from __future__ import annotations

import re

from app.playbook import next_ask
from app.schema import INTENTS


def detect_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"(existing|already (a )?carrier|where's my load|where is my load|detention|tonu)", t):
        return "existing_customer"
    if re.search(r"(talk here|speak|voice|microphone)", t):
        return "talk_here"
    if re.search(r"(call me|callback|phone me|dial)", t):
        return "call_me"
    if re.search(r"not interested|no thanks|don't call|stop (texting|messaging)|leave me alone", t):
        return "decline"
    if re.search(r"commit|signing up|am i binding|just (asking|looking|chatting)", t):
        return "commit"
    if re.search(r"when do (i|we) get paid|invoice now|pay after|payment timing", t):
        return "fee"
    if re.search(r"other dispatcher|leo dispatch|match (their|his) (rate|percent)|cheaper than (them|leo)", t):
        return "fee"
    if re.search(r"(fee|percent|%|charge|cost|how much|expensive|too much|cheaper)", t):
        return "fee"
    if re.search(r"(guarantee|earn|\$\d|weekly gross)", t):
        return "guarantee"
    if re.search(r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded", t):
        return "freight"
    if "fuel card" in t:
        return "fuel"
    if re.search(r"trust|scam|legit", t):
        return "trust"
    if re.search(r"home (every )?night|home time", t):
        return "hometime"
    if re.search(r"talk to (a )?(human|person|agent)|dispatcher please", t):
        return "human"
    if re.search(r"document|packet|onboard|ready to start|get started|i'm ready|how do i start", t):
        return "onboard"
    if re.search(r"new mc|pending (mc|authority)|authority is new", t):
        return "mc_new"
    if "lease" in t:
        return "lease"
    if re.search(r"\bmc\b|authority", t):
        return "mc"
    if re.search(r"(what (trucks|equipment)|do you (haul|dispatch|support))", t):
        return "service"
    if re.search(r"status|approved yet", t):
        return "status"
    if re.search(r"don'?t know|not sure yet|unknown|skip that", t):
        return "unknown_detail"
    if re.search(r"dispatch|need (a )?dispatcher|looking for dispatch", t):
        return "dispatch_inquiry"
    return "general"


def extract_facts(text: str) -> list[dict]:
    t = text.lower()
    items = []
    equip = re.search(r"reefer|dry van|flatbed|box truck|hotshot", t)
    if equip:
        items.append({"key": "equipment", "value": equip.group(0).replace(" ", "_"), "status": "user_stated"})
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
    if re.search(r"(own mc|my own mc|my authority|have (an? )?mc)", t) and not re.search(r"new mc|pending", t):
        items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    if re.search(r"(no mc|don'?t have.*mc|lease on|lease-on)", t):
        items.append({"key": "mcOwnership", "value": "no_own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "lease_on", "status": "user_stated"})
    if re.search(r"(pending|not sure|unsure|another company|new mc)", t) and re.search(r"\bmc\b|authority", t):
        items.append({"key": "mcOwnership", "value": "unclear", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "needs_clarification", "status": "user_stated"})
    area = re.search(
        r"midwest|southeast|northeast|southwest|west coast|texas|california|georgia|florida|otr|"
        r"dallas|houston|atlanta|chicago|irving",
        t,
        re.I,
    )
    if area:
        value = area.group(0).lower()
        items.append({"key": "operatingArea", "value": value, "status": "user_stated"})
        items.append({"key": "lanes", "value": value, "status": "user_stated"})
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


def knowledge_for(intent: str, blocked: list[str], equipment: str | None, text: str = "") -> list[str]:
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
        "hometime": ["home_time"],
        "lease": ["lease"],
        "mc": ["own_mc"],
        "mc_new": ["mc_new"],
        "onboard": ["commit"],
        "trust": ["trust"],
        "commit": ["commit"],
        "decline": ["commit"],
        "dispatch_inquiry": ["services"],
        "status": ["docs_status"],
    }
    keys.extend(mapping.get(intent, []))
    t = (text or "").lower()
    if re.search(r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded", t):
        keys.append("freight")
    if re.search(r"other dispatcher|leo dispatch|competitor", t):
        keys.append("competitor")
    if re.search(r"invoice|pay after|when.{0,20}paid|payment timing", t):
        keys.append("payment_timing")
    if equipment:
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


def propose(text: str, facts: dict) -> dict:
    intent = detect_intent(text)
    items = extract_facts(text)
    blocked = blocked_from_text(text)
    preview = dict(facts)
    for item in items:
        if item["key"] == "_unknown":
            continue
        preview[item["key"]] = {"value": item["value"], "status": item["status"]}
    arrangement = arrangement_of(preview)
    equip = preview.get("equipment", {}).get("value") if isinstance(preview.get("equipment"), dict) else None
    ask = next_ask(preview)
    action = "none"
    if intent == "talk_here":
        action = "talk_here"
    elif intent == "call_me":
        action = "callback"
    elif intent == "human":
        action = "takeover"
    elif intent == "existing_customer":
        action = "create_case"
    elif intent == "onboard" and arrangement and equip:
        action = "create_case"
    return {
        "intent": intent if intent in INTENTS else "general",
        "facts": items,
        "knowledge_keys": knowledge_for(intent, blocked, equip, text),
        "blocked": blocked,
        "next_field": ask,
        "arrangement": arrangement,
        "action": action,
        "task": task_for(arrangement, intent),
        "_source": "rules",
    }
