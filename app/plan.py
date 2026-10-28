"""One response plan per turn. The model proposes; the playbook validates against records."""

from __future__ import annotations

import re

from app import fees, memory
from app.knowledge import lookup
from app.schema import ANSWER_TOPICS, CATALOGUE, EQUIP_LABELS, FACT_KEYS, MOVES, PERMITTED_ACTIONS, QUESTIONS
from app.tasks import fact_value

TOPIC_KEYS = {
    "dispatch_fee": ("fee", "fee_need_arrangement", "fee_lease_blank"),
    "commitment": ("commit", "concern_commitment"),
    "guarantee": ("guarantee",),
    "home_time": ("home_time",),
    "services": ("services", "dispatch_how", "dispatch_vs_onboarding", "equip_specs"),
    "onboarding": ("onboarding", "dispatch_vs_onboarding", "docs_checklist", "mc_age_review"),
    "own_mc": ("own_mc", "mc_age_review"),
    "lease": ("lease",),
    "support": ("support",),
    "email_delivery": ("email_delivery",),
    "docs_status": (
        "docs_own",
        "docs_lease",
        "docs_w9",
        "docs_coi",
        "docs_noa",
        "docs_packet",
        "docs_status",
        "docs_rate_con",
        "docs_rate_con_detail",
        "docs_bol",
        "docs_pod",
        "trip_docs_invoice",
        "docs_checklist",
    ),
    "competitor": ("competitor",),
    "net_after_costs": ("concern_net",),
    "talk_here": ("talk_here",),
    "call_me": ("call_me", "timezone_ops"),
    "pause": ("concern_pause", "deferred"),
    "freight": ("freight", "load_evaluate", "loads_after_onboarding"),
    "payment_support": (
        "payment_support",
        "support",
        "trip_docs_invoice",
        "payment_methods_broker",
        "pay_to_carrier",
        "fuel",
    ),
    "insurance": ("insurance_coverage_ask", "insurance", "insurance_affordability"),
    "negotiation": ("negotiation", "fee_route_manager", "broker_vs_fee"),
    "dispatch_how": ("dispatch_how", "dispatch_vs_onboarding", "services", "freight_roles", "pay_to_carrier"),
    "load_approval": ("load_approval", "docs_rate_con_detail"),
    "accessorials": ("accessorials",),
    "equip_specs": ("equip_specs", "services", "cab_driver_types"),
    "freight_roles": ("freight_roles", "dispatch_how", "pay_to_carrier"),
    "broker_pay": ("payment_methods_broker", "docs_noa", "fuel", "pay_to_carrier"),
    "lane_prefs": ("lane_prefs", "home_time"),
    "fuel_requirement": ("fuel_requirement", "fuel"),
    "expired_demand": ("expired_demand", "human_progress"),
    "existing_dispatcher": ("existing_dispatcher", "human_progress"),
    "privacy_boundary": ("privacy_boundary", "apology_no_pitch"),
}

FALSE_SUCCESS = re.compile(
    r"\b(emailed|e-mailed|booked|packet sent|packet was sent|documents were received|"
    r"case was assigned|assigned in zoho|loads tomorrow|you're approved|"
    r"i will check|i'?m checking|i am checking|check(ing)? (on )?(the )?(load|availability)|"
    r"update you shortly|i will update you)\b",
    re.I,
)

# Workflow claims belong to execute(), not to a draft. Phrase lists are a backstop.
OPERATIONAL_CLAIM = re.compile(
    r"(?:"
    r"\b(?:let me|let us|i(?:'ll| will| am|'m)|we(?:'ll| will))\b.{0,60}\b(?:check|look(?:\s+up)?|search|find|pull|send|email|book|assign|create)\b|"
    r"\b(?:checking|looking up|searching|sending|emailing)\b.{0,40}\b(?:load|availability|packet|document|email|freight)\b|"
    r"\b(?:packet|documents?|papers?|email|setup)\b.{0,40}\b(?:sent|emailed|received|filed|delivered)\b|"
    r"\b(?:sent|emailed|received|filed|delivered)\b.{0,40}\b(?:packet|documents?|papers?|email)\b|"
    r"\b(?:case|ticket|deal)\b.{0,30}\b(?:created|opened|assigned|logged)\b|"
    r"\b(?:booked|dispatched|found (?:a |the )?load|have (?:a |the )?load for you|available loads for you)\b|"
    r"\bi (?:booked|changed|updated|processed)\b|"
    r"\b(?:appointment (?:is |was )?(?:changed|updated)|payment is processing|payment (?:has been|was) (?:sent|processed))\b|"
    r"\byou(?:'re| are) (?:approved|eligible|set up|onboarded)\b"
    r")",
    re.I,
)

MC_UNKNOWN_TALK = re.compile(
    r"once we know.{0,80}(?:own mc|lease)|whether you (?:have|keep|want).{0,40}(?:own mc|lease)|"
    r"do you currently have your own mc|if you(?:'re| are) keeping your own mc or leasing|"
    r"once we know if you(?:'re| are) keeping your own mc",
    re.I,
)

HOME_TIME_ASKED = re.compile(r"home every night|daily home time|\bhome time\b", re.I)

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
        r"what do you charge|how much (do you|is the)|\bpercent\b|\bfees?\b|total fees?",
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
    if HOME_TIME_ASKED.search(t):
        add("home_time")
    if concern == "net_after_costs" or re.search(r"after (fuel|fees|costs)|what'?s left|net (pay|after)|take[- ]home", t):
        add("net_after_costs")
    if intent == "freight" or re.search(
        r"\b(have (a |any )?loads?|need (a )?loads?|looking for (a )?loads?|any loads?|"
        r"loads? in |load availability|do we have (a )?load)\b",
        t,
    ):
        add("freight")
    if re.search(
        r"what do you (actually )?do( for me)?|how (does |do )?(dispatch|your (service|dispatch)) work|"
        r"what (does|do) (a |the )?dispatcher|explain dispatch|how (do )?you (find|book|get) loads?",
        t,
    ):
        add("dispatch_how")
    elif intent == "service" or re.search(r"what (equipment|do you (dispatch|support|haul))", t):
        add("services")
    if re.search(
        r"approve (each |every |the )?load|load approval|do i (have to |need to )?approve|"
        r"who (signs|books)|sign(s|ing)? the rate (con|confirmation)|rate confirmation|"
        r"before (you |they )?book",
        t,
    ):
        add("load_approval")
    if re.search(r"\bdetention\b|\blayover\b|\btonu\b|accessorial", t):
        add("accessorials")
    if re.search(
        r"\b(payload|lift\s*gate|pallet\s*jack|how long (is|are)|day\s*cab|sleeper|"
        r"accessories|straps|tarps|binders|equipment (size|spec|specs))\b",
        t,
    ) and not re.fullmatch(r"\s*\d+\s*(?:-)?\s*(?:ft|foot|feet|pies)\s*", t):
        add("equip_specs")
    if re.search(
        r"\b(what (is|does) (a |the )?(broker|shipper|dispatcher|motor carrier)|"
        r"freight (ecosystem|roles)|who (pays|hires) (the )?(broker|carrier))\b",
        t,
    ):
        add("freight_roles")
    if re.search(
        r"\b(quick\s*pay|standard pay|factoring|voided check|how (do|does) (brokers? )?pay|"
        r"broker (pay|payment)|fuel advance)\b",
        t,
    ):
        add("broker_pay")
    if re.search(r"\b(otr|over[\s-]?the[\s-]?road|local (loads?|runs?)|miles (a|per) day)\b", t):
        add("lane_prefs")
    if re.search(
        r"fuel advance|diesel (money|before)|can'?t start without (fuel|diesel)|need (a )?fuel (card|advance)",
        t,
    ):
        add("fuel_requirement")
    if re.search(
        r"private (business )?information|that'?s private|sensitive (business|question)|don'?t know you",
        t,
    ):
        add("privacy_boundary")
    if re.search(
        r"not anymore|that was for last |don'?t need (it|help|dispatch) (now|anymore)|was for (last )?(friday|monday|week)",
        t,
    ):
        add("expired_demand")
    if re.search(r"already hired (a )?dispatcher|have (a |my )?dispatcher|working with (another |a )?dispatcher", t):
        add("existing_dispatcher")
    if re.search(r"\b(bol|b\.?o\.?l\.?|bill of lading|pod|proof of delivery)\b", t):
        add("docs_status")
    if intent == "talk_here":
        add("talk_here")
    if intent == "call_me":
        add("call_me")
    if intent == "existing_customer" or re.search(
        r"\b(pay\s*me|payme|payment|paid me|where'?s my (money|check|settlement)|waiting on you)\b",
        t,
    ):
        if re.search(r"pay|payment|invoice|money|settlement|check|zelle", t):
            add("payment_support")
            return topics
    if re.search(
        r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait|"
        r"need liability|need cargo|only physical|"
        r"do you need .{0,40}insurance|commercial (auto )?(and|&) cargo|cargo (and|&) commercial|"
        r"auto liability|both coverages?|commercial auto|cargo coverage",
        t,
    ):
        add("insurance")
    if re.search(r"do you (support|dispatch|haul).{0,24}sprinter|sprinter.{0,24}(support|dispatch)", t):
        add("services")
    if re.search(r"\d+\s*%|weekly cap|take it off the first delivery", t) and not re.search(
        r"leo dispatch|silver arrow|\batl\b", t
    ):
        add("negotiation")
    if re.search(r"leo dispatch|silver arrow|\batl\b|like \d+\s*%", t):
        add("competitor")
    if re.search(
        r"which (papers|docs|documents)|what (papers|documents|do i (send|need))|w-?9|\bcoi\b|"
        r"notice of assignment|\bnoa\b|setup packet|voided check|usdot|\bmc authority|bill of lading|"
        r"\bbol\b|rate conf|proof of delivery|\bpod\b|\bifta\b|\beld\b|power of attorney",
        t,
    ):
        add("docs_status")
    if re.search(r"i received (it|the packet)|received the packet|send it tomorrow", t):
        add("onboarding")
    return topics


def _slot_filled(facts: dict, key: str, answered: set[str]) -> bool:
    if key in answered:
        return True
    return fact_value(facts, key) not in (None, "", False)


def _topic_permitted(topic: str, user_text: str, facts: dict) -> bool:
    """Intent labels do not create driver facts. Home-time copy requires a home-time ask."""
    if topic == "home_time":
        return bool(HOME_TIME_ASKED.search(user_text or ""))
    return True


def _evidence_linked_topic(topic: str, user_text: str) -> bool:
    """Accept a model-proposed topic only when the message shows a related question or ask."""
    t = (user_text or "").lower()
    if topic == "insurance":
        return bool(
            re.search(
                r"do you need .{0,40}insurance|commercial|cargo coverage|auto liability|"
                r"both coverages|what (about |insurance)|insurance (required|needed)",
                t,
            )
        )
    if topic == "services":
        return bool(re.search(r"what (equipment|do you)|support|sprinter", t))
    if topic == "dispatch_how":
        return bool(re.search(r"what do you (actually )?do|how (do|does).{0,20}dispatch", t))
    if topic == "freight":
        return bool(re.search(r"\b(have|any|need|looking for) (a |any )?loads?\b|load availability", t))
    if topic == "dispatch_fee":
        return bool(re.search(r"fee|percent|charge|how much", t))
    if topic == "onboarding":
        return bool(re.search(r"onboard|packet|how do i start|ready to start", t))
    if topic == "own_mc":
        return bool(re.search(r"what (is |does ).{0,20}\bmc\b|keep my (own )?mc", t))
    if topic == "lease":
        return bool(re.search(r"what (is |does ).{0,20}lease|how (does |do )?lease", t))
    if topic == "equip_specs":
        return bool(re.search(r"payload|lift\s*gate|ft\b|cab|accessories|equipment (size|spec)", t))
    if topic == "freight_roles":
        return bool(re.search(r"broker|shipper|dispatcher|motor carrier|ecosystem", t))
    if topic == "broker_pay":
        return bool(re.search(r"quick\s*pay|factoring|standard pay|voided check|fuel advance", t))
    if topic == "lane_prefs":
        return bool(re.search(r"otr|local|miles|home time", t))
    return False


def _open_equipment_ambiguity(mem: dict | None) -> bool:
    return any(
        row.get("kind") == "ambiguity" and row.get("key") == "equipment" and row.get("status") == "active"
        for row in ((mem or {}).get("records") or [])
    )


def validate_plan(user_text: str, session: dict, proposal: dict) -> dict:
    """Apply current facts, then accept, repair, or replace the model plan."""
    from app.playbook import next_ask

    facts = session.get("facts") or {}
    mem = session.get("memory") or {}
    intent = proposal.get("intent") or "general"
    repair = proposal.get("repair")
    concern = mem.get("concern") or memory.detect_concern(user_text, intent)
    answered = set(mem.get("answered") or [])
    required = [
        topic
        for topic in detect_topics(user_text, intent, concern, repair)
        if _topic_permitted(topic, user_text, facts)
    ]
    proposed = [topic for topic in (proposal.get("answer_topics") or []) if topic in ANSWER_TOPICS]
    # Allowed is not the same as asked. This message's topics win; do not dump the catalogue.
    topics = [topic for topic in dict.fromkeys(required) if _topic_permitted(topic, user_text, facts)]
    # Model may spot a valid question whose wording the detector missed — keep only evidence-linked extras.
    for topic in proposed:
        if topic in topics or not _topic_permitted(topic, user_text, facts):
            continue
        if _evidence_linked_topic(topic, user_text):
            topics.append(topic)
    fallbacks: list[str] = []
    extras = set(proposed) - set(topics) - set(required)
    if required and proposed and extras and not any(_evidence_linked_topic(topic, user_text) for topic in extras):
        fallbacks.append("extra_topics")
    elif not required and proposed and not topics:
        fallbacks.append("topics")
    if proposal.get("answer_topics") and "home_time" in (proposal.get("answer_topics") or []) and "home_time" not in topics:
        fallbacks.append("unsupported_home_time")

    next_q = proposal.get("next_question_id") or proposal.get("next_field")
    if next_q not in QUESTIONS:
        next_q = None
    if next_q and _slot_filled(facts, next_q, answered):
        next_q = None
        fallbacks.append("repeat_question")

    reactivating = bool(
        re.search(
            r"situation changed|i'?m ready to start|ready to start|can we (talk|discuss).{0,20}dispatch|"
            r"considering switching|want to (try|start) again",
            user_text or "",
            re.I,
        )
    )
    paused = False
    if not reactivating:
        paused = (
            mem.get("follow_up") == "driver_initiates"
            or concern in {"pause", "expired_demand", "existing_dispatcher", "privacy_boundary"}
            or "pause" in topics
            or "expired_demand" in topics
            or "existing_dispatcher" in topics
            or "privacy_boundary" in topics
        )
        if concern == "existing_dispatcher" and re.search(
            r"unhappy|not (happy|working)|switch|considering switching",
            user_text or "",
            re.I,
        ):
            paused = False
    if reactivating:
        topics = [t for t in topics if t not in {"pause", "expired_demand", "privacy_boundary"}]
        concern = None
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
    elif repair == "equip_ambiguous":
        topics = []
        next_q = None
        action = "none"
        fallbacks.append("equip_ambiguous")
    elif _open_equipment_ambiguity(mem) and (action == "create_case" or intent == "onboard"):
        topics = []
        next_q = None
        action = "none"
        repair = "equip_ambiguous"
        fallbacks.append("equip_ambiguous")
    elif repair == "repetition_unverified":
        action = "none"

    driver_asked = any(topic not in {"pause"} for topic in topics)
    closing = {"dispatch_fee", "commitment", "guarantee", "pause", "email_delivery", "support", "net_after_costs"}
    unsupported = fact_value(facts, "equipmentSupport") == "out_of_scope"
    if paused:
        pass
    elif repair == "equip_ambiguous":
        next_q = None
    elif unsupported:
        next_q = None
        if "services" not in topics:
            topics = ["services"] + [topic for topic in topics if topic != "services"]
    elif "freight" in topics:
        if not fact_value(facts, "equipment"):
            next_q = "equipment"
        elif not fact_value(facts, "trailerLength"):
            next_q = "trailerLength"
        elif not fact_value(facts, "mcOwnership"):
            next_q = "mcOwnership"
        elif not (fact_value(facts, "operatingArea") or fact_value(facts, "lanes")):
            next_q = "operatingArea"
        else:
            next_q = None
    elif driver_asked:
        # Direct questions beat the next qualify slot (insurance/coverage before OTR/local).
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
        elif repair == "equip_ambiguous" or _open_equipment_ambiguity(mem):
            action = "none"
            fallbacks.append("equip_ambiguous")
        elif unsupported and task in {"setup_packet", "lease_agreement", "fit_check"}:
            # Eligibility must constrain execution, not only the spoken refusal.
            action = "none"
            fallbacks.append("out_of_scope_equipment")
        elif task in {"setup_packet", "lease_agreement"} and any(not fact_value(facts, key) for key in PACKET_SLOTS):
            action = "none"
            fallbacks.append("underspecified_packet")
    if action == "callback" and not fact_value(facts, "phone"):
        next_q = "phone"
    # Pause suppresses handoffs — but a voluntary return may onboard on this turn.
    if mem.get("follow_up") == "driver_initiates" and action == "create_case" and not reactivating:
        action = "none"
        fallbacks.append("pause")

    move = proposal.get("conversation_move") if proposal.get("conversation_move") in MOVES else None
    if paused:
        move = "pause"
    elif unsupported:
        move = "answer"
    elif repair == "authority_uncertain":
        move = "clarify"
    elif repair == "leave_sales":
        move = "offer_handoff"
    elif repair == "equip_ambiguous":
        move = "clarify"
    elif not move:
        move = "answer" if driver_asked else ("qualify" if next_q else "acknowledge")

    wording = _scrub_wording(
        proposal.get("wording") if isinstance(proposal.get("wording"), str) else None,
        facts,
        answered,
        saved=False,
    )
    if proposal.get("wording") and wording != (proposal.get("wording") or "").strip():
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


def _freight_line(facts: dict) -> str:
    equip = fact_value(facts, "equipment")
    label = EQUIP_LABELS.get(str(equip or ""), str(equip or "").replace("_", " "))
    area = fact_value(facts, "operatingArea") or fact_value(facts, "lanes")
    if equip and area:
        return f"I can't confirm a live {area} load from chat. Dispatch looks at freight after onboarding has the papers."
    if equip:
        return f"I can't confirm a live load from chat for the {label}. Dispatch looks at freight after onboarding has the papers."
    return lookup("freight")


def _scrub_wording(
    text: str | None,
    facts: dict | None = None,
    answered: set[str] | None = None,
    saved: bool = False,
) -> str | None:
    if not text:
        return None
    facts = facts or {}
    answered = answered or set()
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        bit = sentence.strip()
        if not bit:
            continue
        if not saved and (FALSE_SUCCESS.search(bit) or OPERATIONAL_CLAIM.search(bit)):
            continue
        if fact_value(facts, "mcOwnership") in {"own_mc", "no_own_mc"} and MC_UNKNOWN_TALK.search(bit):
            continue
        skip_question = False
        for key, question in QUESTIONS.items():
            if _slot_filled(facts, key, answered) and question.lower().rstrip("?") in bit.lower():
                skip_question = True
                break
        if skip_question:
            continue
        kept.append(bit)
    line = " ".join(part for part in kept if part).strip()
    return line or None


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
                # Never treat a customer counter-offer percent as the live Ayyan quote.
                from app import fees as feesmod

                try:
                    approved = feesmod.approved_percents()
                except Exception:
                    approved = set()
                offer_match = re.search(r"(\d+(?:\.\d+)?)\s*%", picked)
                if offer_match and approved and offer_match.group(1) not in approved and fact_value(facts, "mcOwnership"):
                    try:
                        lines.append(fees.live_quote(arrangement))
                    except Exception:
                        lines.append(picked.rstrip(". ") + ". " + lookup("fee_route_manager"))
                else:
                    if fact_value(facts, "mcOwnership") and "onboarding manager" not in picked.lower():
                        lines.append(picked.rstrip(". ") + ". " + lookup("fee_route_manager"))
                    else:
                        lines.append(picked)
            else:
                try:
                    lines.append(
                        fees.live_quote(arrangement) if fact_value(facts, "mcOwnership") else lookup("fee_need_arrangement")
                    )
                except Exception:
                    lines.append(lookup("fee_need_arrangement"))
            continue
        if topic == "commitment":
            key = "commit" if "dispatch_fee" in topics else "concern_commitment"
            lines.append(lookup(key))
            continue
        if topic == "net_after_costs":
            lines.append(lookup("concern_net"))
            continue
        if topic == "freight":
            picked = next((bit for bit in remaining if "live load" in bit.lower() or "live freight" in bit.lower()), None)
            if picked:
                remaining.remove(picked)
                lines.append(picked)
            else:
                lines.append(_freight_line(facts))
            continue
        if topic == "home_time":
            if fact_value(facts, "supportNeed") != "daily_home_time":
                continue
            lines.append(lookup("home_time"))
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
    if not saved and (FALSE_SUCCESS.search(message) or OPERATIONAL_CLAIM.search(message)):
        return False
    return True
