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
    "payment_support",
    "insurance_affordability",
    "packet_progress",
    "missing_equipment",
    "negotiation",
    "fuel_requirement",
    "expired_demand",
    "existing_dispatcher",
    "privacy_boundary",
)

CONCERN_KEYS = {
    "total_fees": ("fee", "competitor", "payment_timing"),
    "guarantee": ("guarantee", "freight"),
    "commitment": ("commit", "concern_commitment"),
    "home_time": ("home_time",),
    "net_after_costs": ("concern_net",),
    "pause": ("concern_pause", "deferred"),
    "repetition": ("concern_repetition",),
    "email_delivery": ("email_delivery",),
    "payment_support": ("payment_support", "support"),
    "insurance_affordability": ("insurance_affordability", "insurance"),
    "packet_progress": ("packet_received", "docs_status", "docs_packet"),
    "missing_equipment": ("missing_equipment",),
    "negotiation": ("negotiation",),
    "fuel_requirement": ("fuel_requirement", "fuel"),
    "expired_demand": ("expired_demand", "deferred", "human_progress"),
    "existing_dispatcher": ("existing_dispatcher", "human_progress"),
    "privacy_boundary": ("privacy_boundary", "apology_no_pitch"),
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
        "explained": [],
        "blocker": None,
        "last_blocker": None,
        "last_offer": None,
        "last_channel": "chat",
        "last_move": None,
        "last_question_id": None,
        "proposed_question_id": None,
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
    visual = [
        bit
        for bit in (bits or [])
        if "unverified" in (bit or "").lower()
        and any(token in bit.lower() for token in ("photo", "screenshot", "image", "outstanding", "w-9", "certificate of insurance", "notice of assignment"))
    ]
    if not allowed:
        return keys, bits
    paired = [(key, bit) for key, bit in zip(keys, bits) if key in allowed]
    if topics:
        if "dispatch_fee" in topics:
            fee_first = [(key, bit) for key, bit in paired if key in {"fee", "fee_need_arrangement", "fee_lease_blank"}]
            rest = [(key, bit) for key, bit in paired if key not in {"fee", "fee_need_arrangement", "fee_lease_blank"}]
            paired = fee_first[:1] + rest
        kept = [bit for _, bit in paired]
        for line in visual:
            if line not in kept:
                kept.append(line)
        return [key for key, _ in paired], kept
    if concern == "total_fees":
        paired = paired[:1]
    kept = [bit for _, bit in paired]
    for line in visual:
        if line not in kept:
            kept.append(line)
    return [key for key, _ in paired], kept


def compact(memory: dict | None) -> dict:
    state = memory or empty()
    return {
        "goal": state.get("goal"),
        "hard_constraint": state.get("hard_constraint"),
        "concern": state.get("concern"),
        "answered": list(state.get("answered") or []),
        "explained": list(state.get("explained") or []),
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
    # Voluntary return clears prior pause/expired/privacy closure for this turn.
    if re.search(
        r"situation changed|i'?m ready to start|ready to start|can we (talk|discuss).{0,20}dispatch|"
        r"considering switching|want to (try|start) again",
        t,
    ):
        return None
    if re.search(
        r"private (business )?information|that'?s private|too personal|sensitive (business|question)|"
        r"don'?t know you|overstepping|none of your business|why (are you|do you) ask.{0,40}(make|earn|gross)",
        t,
    ):
        return "privacy_boundary"
    if re.search(
        r"already hired (a )?dispatcher|have (a |my )?dispatcher|working with (another |a )?dispatcher|"
        r"got (a )?dispatcher|i('?m| am) with (another|a) dispatcher",
        t,
    ):
        return "existing_dispatcher"
    if re.search(
        r"not anymore|that was for last |already sorted|don'?t need (it|help|dispatch) (now|anymore)|"
        r"no longer need|need has passed|that (load |request )?expired|was for (last )?(friday|monday|week)",
        t,
    ):
        return "expired_demand"
    if re.search(
        r"let you know|when i'?m ready|not right now|i'?ll think|maybe later|let'?s see about next week|"
        r"busy this week|next summer|i'?ll start again",
        t,
    ):
        return "pause"
    if re.search(r"mailbox|inbox (is )?full|send (it )?again|sand again", t):
        return "email_delivery"
    if intent == "existing_customer" or re.search(
        r"\b(pay\s*me|payme|payment|paid me|where'?s my (money|check|settlement)|waiting on you)\b",
        t,
    ):
        if re.search(r"pay|payment|invoice|money|settlement|check|zelle", t):
            return "payment_support"
    if re.search(
        r"i received (it|the packet)|received the packet|fill it out|send it tomorrow|i('?ll| will) (fill|send|return)",
        t,
    ):
        return "packet_progress"
    if re.search(
        r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait",
        t,
    ):
        return "insurance_affordability"
    if re.search(
        r"fuel advance|diesel (money|before)|can'?t start without (fuel|diesel)|need (a )?fuel (card|advance)|"
        r"upfront (fuel|diesel|money)",
        t,
    ):
        return "fuel_requirement"
    if re.search(r"need a trailer|buying (a |the )?truck|pick up the truck|don'?t have (a )?trailer", t):
        return "missing_equipment"
    if re.search(r"\d+\s*%|weekly cap|you pay \d+|take it off the first delivery", t):
        return "negotiation"
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
    if re.search(r"home every night|daily home time|\bhome time\b", t):
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
    return None


def detect_blocker(session: dict, intent: str, concern: str | None, text: str = "") -> str | None:
    t = (text or "").lower()
    if re.search(
        r"(got|have|received) (my )?(insurance|coi)|insurance is (ready|done|sorted|active)|coi is (ready|done)",
        t,
    ) and not re.search(r"too much|afford|expensive|owner will wait", t):
        return ""
    if re.search(
        r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait",
        t,
    ):
        return "insurance_affordability"
    if re.search(
        r"fuel advance|diesel (money|before)|can'?t start without (fuel|diesel)|need (a )?fuel (card|advance)",
        t,
    ):
        return "fuel_requirement"
    if re.search(
        r"waiting on insurance|insurance delay|coi delay|getting several quotes|comparing quotes|agent hasn'?t finished",
        t,
    ):
        return "waiting_insurance"
    if re.search(r"pick(ing)? up (my )?truck|send (the )?registration (after|tomorrow|later)|registration after|temp tag", t):
        return "waiting_registration"
    if re.search(r"i received (it|the packet)|received the packet|send it tomorrow", t):
        return "packet_return_pending"
    if concern == "payment_support":
        return "waiting_payment"
    if concern == "pause":
        return "waiting_driver"
    if concern == "commitment":
        return "reviewing_terms"
    if concern == "missing_equipment":
        return "waiting_equipment"
    if concern == "negotiation":
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


def set_record(
    records: list | None,
    kind: str,
    key: str,
    status: str,
    note: str | None = None,
    extra: dict | None = None,
) -> list[dict]:
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
        if extra:
            row.update(extra)
        found = True
    if not found:
        row = {"kind": kind, "key": key, "status": status, "note": note}
        if extra:
            row.update(extra)
        rows.append(row)
    return rows


def open_ambiguity(memory: dict | None, key: str) -> dict | None:
    for row in records_of(memory, "ambiguity"):
        if row.get("key") == key:
            return row
    return None


def episodic_line(memory: dict | None, user_text: str = "") -> str | None:
    last = (memory or {}).get("last_blocker")
    t = (user_text or "").lower()
    if any(row.get("key") == "home_time_vs_otr" for row in records_of(memory, "concern")):
        if not re.search(r"home every night|daily home|can stay out|not required", t):
            return "OTR is recorded. Daily home time is still on file — has that changed too?"
    if last == "waiting_insurance" and not re.search(r"insurance|coi", t):
        return "Last time you were waiting on insurance — is that still the hold-up?"
    if last == "insurance_affordability" and not re.search(r"insurance|afford|owner", t):
        return "Last time insurance cost was the hold-up — has that changed?"
    if last == "waiting_registration" and not re.search(r"registration|truck tomorrow|picked up|temp tag", t):
        return "Last time you were collecting the truck, then sending registration."
    if last == "packet_return_pending" and not re.search(r"packet|sent|returned|filled", t):
        return "Last time you had the packet and planned to return it — where does that stand?"
    if last == "waiting_payment" and not re.search(r"pay|payment|invoice|settlement", t):
        return "Last time this was about payment — which load or invoice should operations look at?"
    if last == "waiting_equipment" and not re.search(r"truck|trailer|bought|picked up", t):
        return "Last time equipment was still being sourced — what do you have on the road today?"
    if last == "waiting_driver" and not re.search(r"ready|let you know|next week|summer", t):
        return "Welcome back. You wanted to pick this up later."
    if last == "reviewing_terms" and re.search(r"\b(i'?m back|hey|status|still thinking|what'?s left|sign)\b", t):
        return "Last time we were still on the agreement. What would you like clarified?"
    if last == "waiting_packet" and re.search(r"\b(i'?m back|hey|status|packet|document)\b", t):
        return "Last time a packet was waiting on onboarding. That still isn't approval."
    return None


def update(session: dict, proposal: dict, user_text: str) -> dict:
    current = compact(session.get("memory"))
    facts = session.get("facts") or {}
    intent = proposal.get("intent") or "general"
    arrangement = proposal.get("arrangement")
    concern = detect_concern(user_text, intent)
    goal = detect_goal(facts, arrangement, user_text) or current.get("goal")
    owned_now = bool(
        re.search(
            r"\bmy\b.{0,32}(reefer|dry van|flatbed|box truck|hotshot|\bbox\b)|"
            r"\bi (run|have|drive|got) (a |my )?(reefer|dry van|flatbed|box truck|hotshot|\bbox\b)",
            user_text or "",
            re.I,
        )
    )
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
    explained = list(dict.fromkeys(list(current.get("explained") or []) + list(proposal.get("explained") or [])))
    repair = proposal.get("repair")
    if re.search(
        r"situation changed|i'?m ready to start|ready to start|can we (talk|discuss).{0,20}dispatch|"
        r"considering switching|want to (try|start) again",
        user_text or "",
        re.I,
    ):
        follow_up = "assistant"
        concern = None
    elif concern in {"pause", "expired_demand", "existing_dispatcher", "privacy_boundary"}:
        # Dissatisfied-with-dispatcher stays open for assistant follow-up.
        if concern == "existing_dispatcher" and re.search(
            r"unhappy|not (happy|working)|switch|considering switching",
            user_text or "",
            re.I,
        ):
            follow_up = "assistant"
        else:
            follow_up = "driver_initiates"
    elif current.get("follow_up") == "driver_initiates" and concern not in {
        "pause",
        "expired_demand",
        "existing_dispatcher",
        "privacy_boundary",
    }:
        follow_up = "assistant"
    else:
        follow_up = current.get("follow_up") or "assistant"
    blocker = detect_blocker(session, intent, concern, user_text)
    records = list(current.get("records") or [])
    if repair == "equip_ambiguous":
        open_row = open_ambiguity(current, "equipment") or {}
        records = set_record(
            records,
            "ambiguity",
            "equipment",
            "active",
            "Advertised equipment is not the truck on file",
            extra={
                "on_file": fact_value(facts, "equipment") or open_row.get("on_file"),
                "advertised": proposal.get("advertised_equipment") or open_row.get("advertised"),
                "advertised_length": proposal.get("advertised_length") or open_row.get("advertised_length"),
            },
        )
    elif open_ambiguity(current, "equipment"):
        if owned_now:
            records = set_record(records, "ambiguity", "equipment", "resolved", "Driver stated their own equipment")
            repair = None
        else:
            repair = "equip_ambiguous"
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
    owner = "driver" if follow_up == "driver_initiates" else ("onboarding" if action in {"create_case", "callback", "takeover"} else "assistant")
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
        "explained": explained,
        "blocker": blocker,
        "last_blocker": last_blocker,
        "last_offer": proposal.get("reply_variant_id") or current.get("last_offer"),
        "last_channel": session.get("channel") or current.get("last_channel") or "chat",
        "last_move": proposal.get("conversation_move") or current.get("last_move"),
        # Keep prior delivered question until reply commits the one the customer actually saw.
        "last_question_id": current.get("last_question_id"),
        "proposed_question_id": proposal.get("next_question_id") or proposal.get("next_field"),
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
