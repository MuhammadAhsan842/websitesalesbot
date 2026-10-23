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
        "last_question_id": None,
        "follow_up": "assistant",
        "preferred_channel": "chat",
        "next_step_readiness": "needs_explanation",
        "repair": None,
        "records": [],
        "next_agreed": None,
        "follow_up_permission": "assistant",
    }


def scoped_knowledge(
    keys: list[str],
    bits: list[str],
    concern: str | None,
    user_text: str = "",
    topics: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Keep only the bits that answer this turn's topics or concern."""
    from app.plan import TOPIC_KEYS

    allowed: set[str] | None = None
    if topics:
        allowed = set()
        for topic in topics:
            allowed |= set(TOPIC_KEYS.get(topic) or ())
        if not allowed:
            allowed = None
    elif concern:
        allowed = set(CONCERN_KEYS.get(concern) or ())
        if concern == "total_fees" and not re.search(r"leo|atl|silver arrow|like \d+\s*%", user_text or "", re.I):
            allowed.discard("competitor")
    if not allowed:
        return keys, bits
    paired = [(key, bit) for key, bit in zip(keys, bits) if key in allowed]
    if topics:
        if "dispatch_fee" in topics:
            fee_first = [(key, bit) for key, bit in paired if key in {"fee", "fee_need_arrangement", "fee_lease_blank"}]
            rest = [(key, bit) for key, bit in paired if key not in {"fee", "fee_need_arrangement", "fee_lease_blank"}]
            paired = fee_first[:1] + rest
        return [key for key, _ in paired], [bit for _, bit in paired]
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
        "last_question_id": state.get("last_question_id"),
        "follow_up": state.get("follow_up") or "assistant",
        "preferred_channel": state.get("preferred_channel") or "chat",
        "next_step_readiness": state.get("next_step_readiness") or "needs_explanation",
        "repair": state.get("repair"),
        "records": list(state.get("records") or []),
        "next_agreed": state.get("next_agreed"),
        "follow_up_permission": state.get("follow_up_permission") or state.get("follow_up") or "assistant",
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
    if re.search(
        r"sign for nothing|don'?t want to sign|am i binding|have to sign|sign now|do i (have to|need to) sign|just (asking|looking|chatting)",
        t,
    ):
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
    if re.search(r"\botr\b|over the road", t):
        return "otr"
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
    if re.search(
        r"home time (is )?(not|no longer)|don'?t need (to be )?home|can stay out|no longer home every night",
        t,
    ):
        return ""
    if re.search(r"home every night|daily home", t) or fact_value(facts, "supportNeed") == "daily_home_time":
        return "home_every_night"
    if re.search(r"\botr\b|over the road", t) and not re.search(r"no otr|not otr", t):
        return None
    if fact_value(facts, "operatingMode") == "local" or re.search(r"\blocal\b|no otr|not otr", t):
        return "home_every_night"
    return None


def detect_blocker(session: dict, intent: str, concern: str | None, text: str = "") -> str | None:
    t = (text or "").lower()
    if re.search(
        r"(got|have|received) (my )?(insurance|coi)|insurance is (ready|done|sorted|active)|coi is (ready|done)",
        t,
    ):
        return ""
    if re.search(
        r"waiting on insurance|insurance delay|coi delay|getting several quotes|comparing quotes|agent hasn'?t finished",
        t,
    ):
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


def records_of(memory: dict | None, kind: str | None = None, status: str = "active") -> list[dict]:
    rows = (memory or {}).get("records") or []
    return [
        row
        for row in rows
        if (kind is None or row.get("kind") == kind) and (status is None or row.get("status") == status)
    ]


def set_record(records: list | None, kind: str, key: str, status: str, note: str | None = None) -> list[dict]:
    rows = [dict(row) for row in (records or [])]
    found = False
    for row in rows:
        if row.get("kind") != kind or row.get("key") != key:
            continue
        if row.get("status") in {"resolved", "superseded"} and status == "active":
            row["status"] = "reopened"
        else:
            row["status"] = status
        if note:
            row["note"] = note
        found = True
    if not found:
        rows.append({"kind": kind, "key": key, "status": status, "note": note})
    return rows


def episodic_line(memory: dict | None, user_text: str = "") -> str | None:
    last = (memory or {}).get("last_blocker")
    t = (user_text or "").lower()
    if any(row.get("key") == "home_time_vs_otr" for row in records_of(memory, "concern")):
        if not re.search(r"home every night|daily home|can stay out|not required", t):
            return "OTR is recorded. Daily home time is still on file — has that changed too?"
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
    detected_constraint = detect_constraint(facts, user_text)
    stated_home = fact_value(facts, "supportNeed") == "daily_home_time" or bool(
        re.search(r"home every night|daily home", user_text or "", re.I)
    )
    if detected_constraint == "":
        constraint = None
    elif detected_constraint:
        constraint = detected_constraint
    elif re.search(r"\botr\b|over the road", user_text or "", re.I) and not stated_home:
        constraint = None
    else:
        constraint = current.get("hard_constraint")
    answered = answered_keys(facts)
    repair = proposal.get("repair") or current.get("repair")
    if concern == "pause":
        follow_up = "driver_initiates"
    elif current.get("follow_up") == "driver_initiates" and concern != "pause":
        follow_up = "assistant"
    else:
        follow_up = current.get("follow_up") or "assistant"
    blocker = detect_blocker(session, intent, concern, user_text)
    records = list(current.get("records") or [])
    if blocker == "":
        records = set_record(
            records,
            "blocker",
            current.get("last_blocker") or "waiting_insurance",
            "superseded",
            "Driver reports insurance arranged. Certificate receipt and review remain separate.",
        )
        last_blocker = None
        blocker = None
    else:
        last_blocker = blocker if blocker and blocker != "missing_fit" else current.get("last_blocker")
        if blocker and blocker != "missing_fit":
            records = set_record(records, "blocker", blocker, "active")
    if re.search(r"\botr\b|over the road", user_text or "", re.I) and not re.search(r"no otr|not otr", user_text or "", re.I):
        if current.get("goal") == "local_work":
            records = set_record(records, "goal", "local_work", "superseded", "Operating preference updated to OTR")
        records = set_record(records, "goal", "otr", "active")
        if constraint == "home_every_night":
            records = set_record(
                records,
                "concern",
                "home_time_vs_otr",
                "active",
                "OTR stated; daily home time is still on file until the driver withdraws it.",
            )
        else:
            records = set_record(records, "concern", "home_time_vs_otr", "superseded")
    if constraint is None and current.get("hard_constraint") == "home_every_night" and detected_constraint == "":
        records = set_record(records, "constraint", "home_every_night", "superseded", "Home-time requirement withdrawn")
    elif constraint == "home_every_night":
        records = set_record(records, "constraint", "home_every_night", "active")
    action = proposal.get("action") or proposal.get("proposed_action") or "none"
    owner = "driver" if follow_up == "driver_initiates" else ("staff" if action in {"create_case", "callback", "takeover"} else "assistant")
    next_agreed = {
        "step": proposal.get("next_question_id") or proposal.get("next_field") or action,
        "owner": owner,
        "status": "proposed",
    }
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
        "last_question_id": proposal.get("next_question_id") or proposal.get("next_field"),
        "follow_up": follow_up,
        "preferred_channel": session.get("channel") or "chat",
        "next_step_readiness": readiness,
        "repair": repair,
        "records": records,
        "next_agreed": next_agreed,
        "follow_up_permission": follow_up,
    }
    session["memory"] = state
    return state
