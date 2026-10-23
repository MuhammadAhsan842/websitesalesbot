"""One response plan per turn. The model proposes; the playbook validates against records."""

from __future__ import annotations

import re

from app import fees, memory
from app.knowledge import lookup
from app.schema import ANSWER_TOPICS, CATALOGUE, FACT_KEYS, MOVES, PERMITTED_ACTIONS, QUESTIONS
from app.tasks import fact_value

TOPIC_KEYS = {
    "dispatch_fee": ("fee", "fee_need_arrangement", "fee_lease_blank"),
    "commitment": ("commit", "concern_commitment"),
    "guarantee": ("guarantee",),
    "home_time": ("home_time",),
    "services": ("services",),
    "onboarding": ("onboarding",),
    "own_mc": ("own_mc",),
    "lease": ("lease",),
    "support": ("support",),
    "email_delivery": ("email_delivery",),
    "docs_status": ("docs_status",),
    "competitor": ("competitor",),
    "net_after_costs": ("concern_net",),
    "talk_here": ("talk_here",),
    "call_me": ("call_me",),
    "pause": ("concern_pause",),
}

FALSE_SUCCESS = re.compile(
    r"\b(emailed|e-mailed|booked|packet sent|packet was sent|documents were received|case was assigned|assigned in zoho|loads tomorrow|you're approved)\b",
    re.I,
)

PACKET_SLOTS = ("equipment", "mcOwnership", "operatingArea")


def detect_topics(text: str, intent: str | None = None, concern: str | None = None, repair: str | None = None) -> list[str]:
    t = (text or "").lower()
    topics: list[str] = []

    def add(topic: str) -> None:
        if topic in ANSWER_TOPICS and topic not in topics:
            topics.append(topic)

    if repair == "leave_sales" or intent == "existing_customer":
        add("support")
        return topics
    if repair == "email_delivery" or concern == "email_delivery" or re.search(r"mailbox|send (it )?again|sand again", t):
        add("email_delivery")
        return topics
    if concern == "pause" or re.search(
        r"let you know|when i'?m ready|not right now|i'?ll think|maybe later|let'?s see about next week|busy this week",
        t,
    ):
        add("pause")
        return topics
    if intent == "fee" or concern == "total_fees" or re.search(
        r"what do you charge|how much (do you|is the)|percent|\bfee\b|total fees?",
        t,
    ):
        add("dispatch_fee")
    if concern == "commitment" or re.search(
        r"sign for nothing|don'?t want to sign|am i binding|have to sign|sign now|do i (have to|need to) sign|just (asking|looking|chatting)",
        t,
    ):
        add("commitment")
    if intent == "guarantee" or concern == "guarantee" or re.search(r"guarantee|weekly gross", t):
        add("guarantee")
    if intent == "hometime" or concern == "home_time" or re.search(r"home every night|daily home time", t):
        add("home_time")
    if concern == "net_after_costs" or re.search(r"after (fuel|fees|costs)|what'?s left|net (pay|after)|take[- ]home", t):
        add("net_after_costs")
    if intent == "service" or re.search(r"what (equipment|do you (dispatch|support|haul))", t):
        add("services")
    if intent == "talk_here":
        add("talk_here")
    if intent == "call_me":
        add("call_me")
    if re.search(r"leo dispatch|silver arrow|\batl\b|like \d+\s*%", t):
        add("competitor")
    return topics


def _slot_filled(facts: dict, key: str, answered: set[str]) -> bool:
    if key in answered:
        return True
    return fact_value(facts, key) not in (None, "", False)


def validate_plan(user_text: str, session: dict, proposal: dict) -> dict:
    """Apply current facts, then accept, repair, or replace the model plan."""
    from app.playbook import next_ask

    facts = session.get("facts") or {}
    mem = session.get("memory") or {}
    intent = proposal.get("intent") or "general"
    repair = proposal.get("repair")
    concern = mem.get("concern") or memory.detect_concern(user_text, intent)
    answered = set(mem.get("answered") or [])
    required = detect_topics(user_text, intent, concern, repair)
    proposed = [topic for topic in (proposal.get("answer_topics") or []) if topic in ANSWER_TOPICS]
    topics = list(dict.fromkeys([*proposed, *required]))
    fallbacks: list[str] = []

    next_q = proposal.get("next_question_id") or proposal.get("next_field")
    if next_q not in QUESTIONS:
        next_q = None
    if next_q and _slot_filled(facts, next_q, answered):
        next_q = None
        fallbacks.append("repeat_question")

    paused = mem.get("follow_up") == "driver_initiates" or concern == "pause" or "pause" in topics
    action = proposal.get("action") if proposal.get("action") in PERMITTED_ACTIONS else "none"
    if action != (proposal.get("action") or "none"):
        fallbacks.append("action")

    if paused:
        topics = ["pause"]
        next_q = None
        action = "none"
        fallbacks.append("pause")
    elif repair == "leave_sales" or intent == "existing_customer":
        topics = ["support"]
        next_q = None
        action = "create_case"
        proposal = {**proposal, "task": "operations_support"}
    elif repair == "authority_uncertain":
        topics = [topic for topic in topics if topic != "own_mc"]
        next_q = "mcOwnership"
        action = "none"
    elif repair == "email_delivery":
        topics = ["email_delivery"]
        next_q = None
        action = "none"
    elif repair == "repetition_unverified":
        action = "none"

    driver_asked = any(topic not in {"pause"} for topic in topics)
    closing = {"dispatch_fee", "commitment", "guarantee", "pause", "email_delivery", "support", "net_after_costs"}
    if paused:
        pass
    elif driver_asked and (len(topics) > 1 or any(topic in closing for topic in topics)):
        if "dispatch_fee" in topics and not fact_value(facts, "mcOwnership"):
            next_q = "mcOwnership"
        else:
            next_q = None
    elif next_q is None:
        if any(row.get("key") == "home_time_vs_otr" for row in (mem.get("records") or []) if row.get("status") == "active"):
            next_q = "supportNeed"
        else:
            next_q = next_ask(facts, mem, intent, repair)

    if action == "create_case":
        task = proposal.get("task")
        if task not in CATALOGUE:
            action = "none"
            fallbacks.append("unspecified_task")
        elif task in {"setup_packet", "lease_agreement"} and any(not fact_value(facts, key) for key in PACKET_SLOTS):
            action = "none"
            fallbacks.append("underspecified_packet")
    if action == "callback" and not fact_value(facts, "phone"):
        next_q = "phone"
    if mem.get("follow_up") == "driver_initiates" and action == "create_case":
        action = "none"
        fallbacks.append("pause")

    move = proposal.get("conversation_move") if proposal.get("conversation_move") in MOVES else None
    if paused:
        move = "pause"
    elif repair == "authority_uncertain":
        move = "clarify"
    elif repair == "leave_sales":
        move = "offer_handoff"
    elif not move:
        move = "answer" if driver_asked else ("qualify" if next_q else "acknowledge")

    wording = proposal.get("wording") if isinstance(proposal.get("wording"), str) else None
    if wording and FALSE_SUCCESS.search(wording):
        wording = None
        fallbacks.append("wording")

    return {
        "facts_patch": [
            {"key": item.get("key"), "value": item.get("value")}
            for item in (proposal.get("facts") or [])
            if item.get("key") in FACT_KEYS or item.get("key") == "_unknown"
        ],
        "answer_topics": topics,
        "conversation_move": move,
        "next_question_id": next_q,
        "proposed_action": action,
        "wording": wording,
        "valid": not fallbacks,
        "fallbacks": fallbacks,
        "task": proposal.get("task"),
    }


def topic_lines(topics: list[str], arrangement: str | None, bits: list[str], facts: dict) -> list[str]:
    remaining = [bit for bit in (bits or []) if bit]
    lines: list[str] = []
    for topic in topics:
        if topic == "pause":
            lines.append(lookup("concern_pause"))
            continue
        if topic == "dispatch_fee":
            picked = next((bit for bit in remaining if "%" in bit or "fee" in bit.lower()), None)
            if picked:
                remaining.remove(picked)
                lines.append(picked)
            else:
                lines.append(fees.live_quote(arrangement) if fact_value(facts, "mcOwnership") else lookup("fee_need_arrangement"))
            continue
        if topic == "commitment":
            key = "commit" if "dispatch_fee" in topics else "concern_commitment"
            lines.append(lookup(key))
            continue
        if topic == "net_after_costs":
            lines.append(lookup("concern_net"))
            continue
        keys = TOPIC_KEYS.get(topic) or ()
        picked = next((bit for bit in remaining if any(token.replace("_", " ") in bit.lower() for token in keys)), None)
        if picked:
            remaining.remove(picked)
            lines.append(picked)
        elif keys:
            lines.append(lookup(keys[0]))
    return lines


def allow_action_message(message: str | None, saved: bool) -> bool:
    if not message:
        return False
    if FALSE_SUCCESS.search(message) and not saved:
        return False
    return True
