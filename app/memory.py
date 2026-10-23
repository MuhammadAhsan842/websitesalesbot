"""Compact conversation state that changes asking, follow-up, and concern handling."""

from __future__ import annotations

import re

from app.schema import FACT_KEYS
from app.tasks import fact_value

CONCERNS = (
    "commitment",
    "net_after_costs",
    "repetition",
    "total_fees",
    "pause",
    "guarantee",
    "home_time",
    "email_delivery",
)

CONCERN_KEYS = {
    "total_fees": ("fee", "competitor", "payment_timing"),
    "guarantee": ("guarantee", "freight"),
    "commitment": ("commit",),
    "home_time": ("home_time",),
    "net_after_costs": (),
    "pause": (),
    "repetition": (),
    "email_delivery": ("email_delivery",),
}

MC_NORMALIZE = {
    "own_mc": "own_mc",
    "own mc": "own_mc",
    "my own mc": "own_mc",
    "own authority": "own_mc",
    "no_own_mc": "no_own_mc",
    "no own mc": "no_own_mc",
    "lease on": "no_own_mc",
    "lease-on": "no_own_mc",
    "unclear": "unclear",
    "not sure": "unclear",
}


def empty() -> dict:
    return {
        "goal": None,
        "hard_constraint": None,
        "concern": None,
        "answered": [],
        "blocker": None,
        "last_blocker": None,
        "last_offer": None,
        "last_channel": "chat",
        "last_move": None,
        "follow_up": "assistant",
        "preferred_channel": "chat",
        "next_step_readiness": "needs_explanation",
        "repair": None,
    }


def scoped_knowledge(
    keys: list[str],
    bits: list[str],
    concern: str | None,
    user_text: str = "",
) -> tuple[list[str], list[str]]:
    """Keep only the bits that answer this turn's concern."""
    keep = CONCERN_KEYS.get(concern) if concern else None
    if keep is None:
        return keys, bits
    allowed = set(keep)
    if concern == "total_fees" and not re.search(r"leo|atl|silver arrow|like \d+\s*%", user_text or "", re.I):
        allowed.discard("competitor")
    paired = [(key, bit) for key, bit in zip(keys, bits) if key in allowed]
    if concern == "total_fees":
        paired = paired[:1]
    return [key for key, _ in paired], [bit for _, bit in paired]


def compact(memory: dict | None) -> dict:
    state = memory or empty()
    return {
        "goal": state.get("goal"),
        "hard_constraint": state.get("hard_constraint"),
        "concern": state.get("concern"),
        "answered": list(state.get("answered") or []),
        "blocker": state.get("blocker"),
        "last_blocker": state.get("last_blocker"),
        "last_offer": state.get("last_offer"),
        "last_channel": state.get("last_channel") or "chat",
        "last_move": state.get("last_move"),
        "follow_up": state.get("follow_up") or "assistant",
        "preferred_channel": state.get("preferred_channel") or "chat",
        "next_step_readiness": state.get("next_step_readiness") or "needs_explanation",
        "repair": state.get("repair"),
    }


def normalize_mc(value) -> object:
    if value is None:
        return None
    key = str(value).strip().lower()
    return MC_NORMALIZE.get(key, value)


def answered_keys(facts: dict) -> list[str]:
    keys = []
    for key in FACT_KEYS:
        value = fact_value(facts, key)
        if value not in (None, "", False):
            keys.append(key)
    return keys


def detect_concern(text: str, intent: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"let you know|when i'?m ready|not right now|i'?ll think|maybe later|let'?s see about next week|busy this week", t):
        return "pause"
    if re.search(r"mailbox|inbox (is )?full|send (it )?again|sand again", t):
        return "email_delivery"
    if re.search(
        r"already (sent|gave|told|said|provided)|i have everything|i (just )?told you|you (already )?have (it|that|everything)|i already (did|sent)",
        t,
    ):
        return "repetition"
    if re.search(r"sign for nothing|don'?t want to sign|am i binding|just (asking|looking|chatting)", t):
        return "commitment"
    if re.search(r"after (fuel|fees|costs)|what'?s left|net (pay|after)|take[- ]home", t):
        return "net_after_costs"
    if intent == "guarantee" or re.search(r"guarantee|weekly gross", t):
        return "guarantee"
    if intent == "hometime" or re.search(r"home every night|daily home time", t):
        return "home_time"
    if intent == "fee" or re.search(r"total fees?|what do you charge|how much (do you|is the)", t):
        return "total_fees"
    return None


def detect_goal(facts: dict, arrangement: str | None, text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"\blocal\b|home every night|no otr|not otr", t):
        return "local_work"
    if fact_value(facts, "supportNeed") == "daily_home_time":
        area = str(fact_value(facts, "operatingArea") or "")
        if area and area not in {"otr"}:
            return "local_work"
    if arrangement == "lease_on":
        return "lease_on"
    if arrangement == "dispatch_service":
        return "dispatch"
    if arrangement == "needs_clarification":
        return "unclear"
    return None


def detect_constraint(facts: dict, text: str) -> str | None:
    t = (text or "").lower()
    if (
        fact_value(facts, "operatingMode") == "local"
        or fact_value(facts, "supportNeed") == "daily_home_time"
        or re.search(r"home every night|daily home|\blocal\b", t)
    ):
        return "home_every_night"
    return None


def detect_blocker(session: dict, intent: str, concern: str | None, text: str = "") -> str | None:
    t = (text or "").lower()
    if re.search(r"waiting on insurance|insurance delay|coi delay|getting several quotes", t):
        return "waiting_insurance"
    if re.search(r"pick(ing)? up (my )?truck|send (the )?registration (after|tomorrow|later)|registration after", t):
        return "waiting_registration"
    if concern == "pause":
        return "waiting_driver"
    if concern == "commitment":
        return "reviewing_terms"
    if session.get("handed_over") and session.get("case_id"):
        return "waiting_packet"
    if intent in {"fee", "guarantee"}:
        return "reviewing_terms"
    if not answered_keys(session.get("facts") or {}):
        return "missing_fit"
    return None


def episodic_line(memory: dict | None, user_text: str = "") -> str | None:
    last = (memory or {}).get("last_blocker")
    t = (user_text or "").lower()
    if last == "waiting_insurance" and not re.search(r"insurance|coi", t):
        return "Last time you were waiting on insurance — is that still the hold-up?"
    if last == "waiting_registration" and not re.search(r"registration|truck tomorrow|picked up", t):
        return "Last time you were collecting the truck, then sending registration."
    if last == "waiting_driver" and not re.search(r"ready|let you know|next week", t):
        return "Welcome back. You wanted to pick this up later."
    if last == "reviewing_terms" and not re.search(r"charge|fee|sign|guarantee|percent", t):
        return "Last time the open item was the agreement, not a new qualify."
    if last == "waiting_packet" and re.search(r"\b(i'?m back|hey|status|packet|document)\b", t):
        return "Last time a packet was waiting on staff. That is still not approval."
    return None


def update(session: dict, proposal: dict, user_text: str) -> dict:
    current = compact(session.get("memory"))
    facts = session.get("facts") or {}
    intent = proposal.get("intent") or "general"
    arrangement = proposal.get("arrangement")
    concern = detect_concern(user_text, intent)
    goal = detect_goal(facts, arrangement, user_text) or current.get("goal")
    constraint = detect_constraint(facts, user_text) or current.get("hard_constraint")
    answered = answered_keys(facts)
    repair = proposal.get("repair") or current.get("repair")
    if concern == "pause":
        follow_up = "driver_initiates"
    elif current.get("follow_up") == "driver_initiates" and concern != "pause":
        follow_up = "assistant"
    else:
        follow_up = current.get("follow_up") or "assistant"
    blocker = detect_blocker(session, intent, concern, user_text)
    last_blocker = blocker if blocker and blocker != "missing_fit" else current.get("last_blocker")
    readiness = "ready" if intent == "onboard" else ("paused" if follow_up == "driver_initiates" else "needs_explanation")
    state = {
        "goal": goal,
        "hard_constraint": constraint,
        "concern": concern,
        "answered": answered,
        "blocker": blocker,
        "last_blocker": last_blocker,
        "last_offer": proposal.get("reply_variant_id") or current.get("last_offer"),
        "last_channel": session.get("channel") or current.get("last_channel") or "chat",
        "last_move": proposal.get("conversation_move") or current.get("last_move"),
        "follow_up": follow_up,
        "preferred_channel": session.get("channel") or "chat",
        "next_step_readiness": readiness,
        "repair": repair,
    }
    session["memory"] = state
    return state
