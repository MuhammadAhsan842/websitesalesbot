"""LangGraph conversation runtime. Qwen proposes every turn; nodes execute that proposal."""

from __future__ import annotations

import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph


def merge_traces(left: list, right: list) -> list:
    right = right or []
    if any(item.get("_reset") for item in right):
        return [item for item in right if not item.get("_reset")]
    return (left or []) + right

from app import db, examples, fees, media, memory, plan, playbook, qwen, requirements as reqmod, rules, second_pass, variants, zoho
from app.knowledge import BLOCKED_CLAIMS, REGISTER, lookup
from app.schema import ANSWER_TOPICS, CATALOGUE, CHIPS, FACT_KEYS, INTENTS, MOVES, VARIANTS
from app.tasks import fact_value, persist_human_task


class TurnState(TypedDict, total=False):
    session: dict
    user_text: str
    proposal: dict
    knowledge_bits: list
    action_result: dict
    reply_text: str
    chips: list
    traces: Annotated[list, merge_traces]


LEAK_MONEY = re.compile(r"\$\s*\d+", re.I)
LEAK_CLAIM = re.compile(
    r"we guarantee|guaranteed \$?\d|you are approved|you're approved|insurance is approved|coi is valid|"
    r"consistent loads|high[- ]paying loads|weekly gross|make \$\d|earn \$\d",
    re.I,
)
LEAK_DEBRIS = re.compile(r"(?:^|\s)\d+\)\s*hey!?|(?:^|\s)TODO:|\[insert|\{\{|placeholder", re.I)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _leaks(text: str) -> bool:
    if LEAK_MONEY.search(text) or LEAK_CLAIM.search(text) or LEAK_DEBRIS.search(text or ""):
        return True
    allowed = fees.approved_percents()
    for match in PERCENT.finditer(text):
        token = match.group(1)
        if token in allowed:
            continue
        if token.endswith(".0") and token[:-2] in allowed:
            continue
        return True
    return False


def _trace(stage: str, **detail) -> dict:
    return {"traces": [{"stage": stage, **detail}]}


ALLOWED_ACTIONS = {"none", "create_case", "callback", "talk_here", "takeover"}
ALLOWED_ARRANGEMENTS = {"dispatch_service", "lease_on", "needs_clarification"}

CASE_SAY = {
    "awaiting_human_action": "Onboarding has your request. They haven't sent the packet yet.",
    "awaiting_submissions": "Onboarding sent the packet and is waiting on your papers.",
    "under_review": "Onboarding is reviewing the files.",
    "corrections_requested": "Onboarding asked for a correction.",
    "approved_for_handoff": "Onboarding signed off for handoff to dispatch.",
    "production_accepted": "Dispatch has the truck.",
    "human_takeover": "Our onboarding manager is on this chat.",
    "callback_requested": "A callback is noted. Nobody has dialed yet.",
    "routed_support": "This went to operations.",
}


def _case_say(status: str) -> str:
    line = CASE_SAY.get(status, "Onboarding has this chat.")
    return line + " That's not insurance or agreement approval."


def _evidence_ok(evidence: str | None, user_text: str) -> bool:
    span = (evidence or "").strip().lower()
    if not span:
        return True
    return span in (user_text or "").lower()


def _clean_facts(items: list | None, user_text: str = "") -> list[dict]:
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key != "_unknown" and key not in FACT_KEYS:
            continue
        if not _evidence_ok(item.get("evidence"), user_text):
            continue
        value = item.get("value")
        if value in ("null", ""):
            value = None
        cleaned.append({"key": key, "value": value, "status": item.get("status") or "user_stated"})
    return cleaned


def _merge_facts(
    model_facts: list | None,
    ruled_facts: list | None,
    user_text: str = "",
    current_facts: dict | None = None,
) -> list[dict]:
    by_key: dict[str, dict] = {}
    advertised = rules.is_advertised_equipment(user_text)
    skip_equip = advertised or not rules.owned_equipment_claim(user_text)
    current_equip = None
    if isinstance((current_facts or {}).get("equipment"), dict):
        current_equip = (current_facts or {})["equipment"].get("value")
    for item in _clean_facts(ruled_facts, user_text):
        if advertised and item["key"] in {"equipment", "trailerLength"}:
            continue
        by_key[item["key"]] = item
    for item in _clean_facts(model_facts, user_text):
        if item["key"] in {"equipment", "trailerLength"} and advertised:
            continue
        if (
            item["key"] == "equipment"
            and current_equip
            and item.get("value") not in (None, current_equip)
            and skip_equip
        ):
            continue
        if item["key"] == "trailerLength" and advertised:
            continue
        if item.get("value") not in (None, False) or item["key"] not in by_key:
            by_key[item["key"]] = item
    return list(by_key.values())


def _from_qwen(model: dict, ruled: dict, user_text: str = "", current_facts: dict | None = None) -> dict:
    intent = model.get("intent") if model.get("intent") in INTENTS else None
    ruled_intent = ruled["intent"]
    t = (user_text or "").lower()
    payment_turn = bool(rules.PAYMENT_ASK.search(user_text or ""))
    # Model may correctly spot payment support when an older rule misfires (e.g. "please"⊃"lease").
    if payment_turn and intent == "existing_customer":
        pass
    elif intent in {"existing_customer", "decline", "talk_here", "call_me", "human"} and ruled_intent not in {intent}:
        intent = ruled_intent
    if payment_turn:
        intent = "existing_customer"
    if not intent or intent == "general":
        intent = ruled_intent
    fee_turn = ruled_intent == "fee" or bool(re.search(r"what do you charge|\bpercent\b|\d+\s*%|\bfees?\b", t))
    guarantee_said = bool(re.search(r"guarantee|weekly gross|\$\s*\d", t))
    if fee_turn and not guarantee_said and intent == "guarantee":
        intent = "fee"
    action = model.get("action") if model.get("action") in ALLOWED_ACTIONS else None
    ruled_action = ruled.get("action") or "none"
    if not action or action == "none":
        action = ruled_action
    if action in {"create_case", "takeover", "talk_here", "callback"} and ruled_action != action:
        action = ruled_action
    arrangement = model.get("arrangement") if model.get("arrangement") in ALLOWED_ARRANGEMENTS else None
    arrangement = arrangement or ruled.get("arrangement")
    task = model.get("task") if model.get("task") in CATALOGUE else None
    if action != "create_case":
        task = ruled.get("task") if ruled_action != "create_case" else task
    task = task or ruled.get("task")
    next_field = model.get("next_question_id") or model.get("next_field")
    if next_field in ("null", None, "") or (next_field and next_field not in FACT_KEYS):
        next_field = ruled.get("next_field")
    topics = [topic for topic in (model.get("answer_topics") or []) + (ruled.get("answer_topics") or []) if topic in ANSWER_TOPICS]
    keys = [k for k in (model.get("knowledge_keys") or []) + ruled["knowledge_keys"] if isinstance(k, str)]
    blocked = [b for b in (model.get("blocked") or []) + ruled["blocked"] if isinstance(b, str)]
    if fee_turn and not guarantee_said:
        keys = [k for k in keys if k != "guarantee"]
        blocked = [b for b in blocked if b != "guarantee"]
    repair = ruled.get("repair")
    if repair == "leave_sales":
        intent = "existing_customer"
        action = "create_case"
        task = "operations_support"
    elif repair == "topic_fee":
        intent = "fee"
    elif repair == "authority_uncertain":
        intent = "mc_new"
        action = "none"
        task = "clarification"
        arrangement = "needs_clarification"
    elif repair == "repetition_unverified":
        action = "none"
    facts = _merge_facts(model.get("facts"), ruled.get("facts"), user_text, current_facts)
    if repair == "equip_ambiguous" or rules.is_advertised_equipment(user_text):
        facts = [item for item in facts if item["key"] not in {"equipment", "trailerLength"}]
    if repair == "authority_uncertain":
        by_key = {item["key"]: item for item in facts}
        for item in _clean_facts(ruled.get("facts"), user_text):
            if item["key"] in {"mcOwnership", "requestedArrangement"}:
                by_key[item["key"]] = item
        facts = list(by_key.values())
    wording = model.get("wording") if isinstance(model.get("wording"), str) else None
    if wording and _leaks(wording):
        wording = None
    move = model.get("conversation_move") if model.get("conversation_move") in MOVES else None
    variant = model.get("reply_variant_id") if model.get("reply_variant_id") in VARIANTS else None
    return {
        "intent": intent,
        "facts": facts,
        "knowledge_keys": list(dict.fromkeys(keys)),
        "blocked": list(dict.fromkeys(blocked)),
        "next_field": next_field,
        "next_question_id": next_field,
        "answer_topics": list(dict.fromkeys(topics)),
        "arrangement": arrangement,
        "action": action,
        "task": task,
        "repair": repair,
        "conversation_move": move,
        "reply_variant_id": variant,
        "wording": wording,
        "advertised_equipment": ruled.get("advertised_equipment"),
        "advertised_length": ruled.get("advertised_length"),
        "_source": "qwen",
    }


async def node_propose(state: TurnState) -> dict:
    session = state["session"]
    text = state["user_text"]
    ruled = rules.propose(text, session["facts"], session.get("memory"))
    mem = session.get("memory") or {}
    tags = [
        tag
        for tag in (ruled.get("repair"), mem.get("concern"), mem.get("goal"), mem.get("last_blocker"))
        if tag
    ]
    hits = examples.search(text, tags=tags, limit=3)
    # Retrieve approved copy before generation so the model can write a grounded full reply.
    approved = []
    for key in (ruled.get("knowledge_keys") or [])[:8]:
        if key in REGISTER:
            approved.append({"key": key, "text": lookup(key)[:220]})
    recent = []
    try:
        recent = [
            {"role": row["role"], "text": (row.get("text") or "")[:220]}
            for row in (db.list_messages(session["id"]) or [])[-6:]
        ]
    except Exception:
        recent = []
    model = await qwen.propose(
        text,
        session["facts"],
        session["conversation_state"],
        session.get("memory"),
        examples=hits,
        intent=ruled.get("intent"),
        repair=ruled.get("repair"),
        recent=recent,
        approved=approved,
    )
    if not model:
        ruled = dict(ruled)
        ruled["retrieved"] = hits
        ruled["answer_topics"] = plan.detect_topics(text, ruled.get("intent"), None, ruled.get("repair"))
        return {
            "proposal": ruled,
            **_trace(
                "propose",
                source="rules_fallback",
                intent=ruled["intent"],
                model=(model or {}).get("_model") or qwen.last_route.get("model") or qwen.MODEL,
                error=qwen.last_error,
                route=qwen.last_route,
                examples=[hit["id"] for hit in hits],
            ),
        }
    merged = _from_qwen(model, ruled, text, session.get("facts"))
    merged["retrieved"] = hits
    if not merged.get("answer_topics"):
        merged["answer_topics"] = plan.detect_topics(text, merged.get("intent"), None, ruled.get("repair"))
    return {
        "proposal": merged,
        **_trace(
            "propose",
            source=model.get("_source") or "qwen",
            intent=merged["intent"],
            model=model.get("_model") or qwen.MODEL,
            action=merged["action"],
            timing=model.get("_timing", {}),
            examples=[hit["id"] for hit in hits],
            conversation_move=merged.get("conversation_move"),
            reply_variant_id=merged.get("reply_variant_id"),
            route=qwen.last_route,
        ),
    }


def node_reduce_facts(state: TurnState) -> dict:
    session = state["session"]
    proposal = state["proposal"]
    unknown = any(item.get("key") == "_unknown" for item in proposal.get("facts") or [])
    if unknown:
        missing = playbook.next_ask(session["facts"], session.get("memory"))
        if missing:
            session["facts"][missing] = {
                "value": None,
                "status": "unknown",
                "sourceChannel": session["channel"],
                "version": session["state_version"],
                "previous": session["facts"].get(missing),
            }
            session["state_version"] += 1
    cancelled = False
    text = state.get("user_text") or ""
    skip_equip = proposal.get("repair") == "equip_ambiguous" or rules.is_advertised_equipment(text)
    for item in proposal.get("facts") or []:
        key = item.get("key")
        if key not in FACT_KEYS:
            continue
        if skip_equip and key in {"equipment", "trailerLength"}:
            continue
        status = item.get("status") or "user_stated"
        previous = session["facts"].get(key)
        value = item.get("value")
        if key == "mcOwnership":
            value = memory.normalize_mc(value)
        if previous and previous.get("value") == value and previous.get("status") != "unknown":
            continue
        if previous and previous.get("value") != value:
            status = "corrected"
            db.cancel_unsent(session["id"], f"stale plan after {key} correction")
            cancelled = True
        session["facts"][key] = {
            "value": value,
            "status": status,
            "sourceChannel": session["channel"],
            "version": session["state_version"],
            "previous": {"value": previous["value"], "status": previous["status"]} if previous else None,
        }
        session["state_version"] += 1
    if cancelled or any(item.get("key") in FACT_KEYS for item in proposal.get("facts") or []):
        zoho.queue_fit(session, proposal)
    return {"session": session, **_trace("reduce_facts", cancelled_unsent=cancelled, version=session["state_version"])}


def node_knowledge(state: TurnState) -> dict:
    proposal = state["proposal"]
    keys = [k for k in proposal.get("knowledge_keys") or [] if k in REGISTER]
    blocked = [b for b in proposal.get("blocked") or [] if b in BLOCKED_CLAIMS]
    if "guarantee" in blocked and "guarantee" not in keys:
        keys.append("guarantee")
    if "invented_fee" in blocked and "fee" not in keys:
        keys.append("fee")
    asked_fee = "dispatch_fee" in (proposal.get("answer_topics") or []) or proposal.get("intent") == "fee"
    if (
        asked_fee
        and (state["session"].get("memory") or {}).get("concern") == "total_fees"
        and "fee" not in keys
    ):
        keys.insert(0, "fee")
    arrangement = proposal.get("arrangement") or rules.arrangement_of(state["session"]["facts"])
    hybrid = False
    hits = []
    bits = []
    if not keys and (
        proposal.get("intent") == "freight" or "freight" in (proposal.get("answer_topics") or [])
    ):
        keys = ["freight"]
    if keys:
        for key in keys:
            if key == "fee":
                bits.append(fees.live_quote(arrangement))
            else:
                bits.append(lookup(key))
    else:
        hybrid = False
    from app import docs as docmod

    user_text = state.get("user_text") or ""
    if docmod.asked(user_text):
        for key in docmod.keys_for(user_text, arrangement):
            if key not in keys and key in REGISTER:
                keys.append(key)
                bits.append(lookup(key))
        missing = docmod.missing_line(state["session"])
        if missing not in bits:
            bits.append(missing)
    evidence = media.session_evidence(state["session"]["id"], user_text)
    if evidence:
        if "photo_unverified" not in keys:
            keys.append("photo_unverified")
        for line in evidence:
            if line not in bits:
                bits.append(line)
    proposal = dict(state["proposal"])
    proposal["knowledge_keys"] = keys
    return {
        "proposal": proposal,
        "knowledge_bits": bits,
        **_trace(
            "knowledge",
            keys=keys,
            blocked=blocked,
            hybrid_rerank=hybrid,
            hits=[{"key": hit.get("key"), "hybrid": hit.get("hybrid")} for hit in hits],
            arrangement=arrangement,
        ),
    }


def node_plan(state: TurnState) -> dict:
    session = state["session"]
    proposal = dict(state["proposal"])
    text = state.get("user_text") or ""
    mem = session.get("memory") or {}
    repair = proposal.get("repair") or rules.detect_repair(text)
    if memory.open_ambiguity(mem, "equipment") and not rules.owned_equipment_claim(text):
        repair = "equip_ambiguous"
    proposal["repair"] = repair
    mc = fact_value(session["facts"], "mcOwnership")
    if repair == "authority_uncertain":
        proposal["arrangement"] = "needs_clarification"
        proposal["task"] = "clarification"
        proposal["action"] = "none"
        proposal["intent"] = "mc_new"
        mc = "unclear"
    elif mc == "own_mc":
        proposal["arrangement"] = "dispatch_service"
        proposal["task"] = "setup_packet"
    elif mc == "no_own_mc":
        proposal["arrangement"] = "lease_on"
        proposal["task"] = "lease_agreement"
    elif mc == "unclear":
        proposal["arrangement"] = "needs_clarification"
        proposal["task"] = "clarification"
    if proposal.get("task") not in CATALOGUE and proposal.get("task") is not None:
        proposal["task"] = None
        proposal["action"] = "none"
    concern = memory.detect_concern(state.get("user_text") or "", proposal.get("intent") or "general")
    if repair == "equip_ambiguous":
        proposal["action"] = "none"
        proposal["task"] = None
    elif repair == "leave_sales" or proposal["intent"] == "existing_customer":
        proposal["intent"] = "existing_customer"
        proposal["action"] = "create_case"
        proposal["task"] = "operations_support"
    elif proposal["intent"] == "talk_here":
        proposal["action"] = "talk_here"
    elif proposal["intent"] == "call_me":
        proposal["action"] = "callback"
    elif proposal["intent"] == "human":
        proposal["action"] = "takeover"
    validated = plan.validate_plan(state.get("user_text") or "", session, proposal)
    proposal["answer_topics"] = validated["answer_topics"]
    proposal["next_field"] = validated["next_question_id"]
    proposal["next_question_id"] = validated["next_question_id"]
    proposal["action"] = validated["proposed_action"]
    proposal["conversation_move"] = validated["conversation_move"]
    if validated.get("task"):
        proposal["task"] = validated["task"]
    if validated["wording"] is None:
        proposal["wording"] = None
    else:
        proposal["wording"] = validated["wording"]
    if proposal.get("wording") and _leaks(str(proposal["wording"])):
        proposal["wording"] = None
    proposal["plan"] = validated
    keys, bits = memory.scoped_knowledge(
        proposal.get("knowledge_keys") or [],
        state.get("knowledge_bits") or [],
        concern,
        state.get("user_text") or "",
        topics=validated["answer_topics"],
    )
    proposal["knowledge_keys"] = keys
    # Prefer model-authored wording. Variants are fallback labels only when wording is missing.
    move = validated["conversation_move"]
    variant = None
    if not proposal.get("wording"):
        variant = proposal.get("reply_variant_id") if proposal.get("reply_variant_id") in VARIANTS else None
        if not variant or repair in {"leave_sales", "authority_uncertain", "repetition_unverified", "email_delivery"} or concern in {
            "pause",
            "commitment",
            "net_after_costs",
            "email_delivery",
        }:
            variant = variants.default_variant(move, concern, proposal.get("intent"), repair)
    proposal["reply_variant_id"] = variant
    memory.update(session, proposal, state.get("user_text") or "")
    if (session.get("memory") or {}).get("follow_up") == "driver_initiates" and proposal["action"] == "create_case":
        proposal["action"] = "none"
    if session["handed_over"]:
        session["conversation_state"] = "handed_over"
    elif not playbook.missing_core(session["facts"], session.get("memory")):
        session["conversation_state"] = "assess_fit"
    elif proposal["intent"] == "dispatch_inquiry" or session["conversation_state"] != "understand_request":
        session["conversation_state"] = "discover_needs"
    return {
        "proposal": proposal,
        "session": session,
        "knowledge_bits": bits,
        **_trace(
            "plan",
            action=proposal["action"],
            task=proposal.get("task"),
            memory=session.get("memory") or {},
            knowledge_keys=keys,
            conversation_move=proposal.get("conversation_move"),
            reply_variant_id=proposal.get("reply_variant_id"),
            repair=proposal.get("repair"),
            answer_topics=proposal.get("answer_topics") or [],
            next_question_id=proposal.get("next_question_id"),
            plan_fallbacks=(proposal.get("plan") or {}).get("fallbacks") or [],
        ),
    }


def node_execute(state: TurnState) -> dict:
    session = state["session"]
    proposal = state["proposal"]
    action = proposal.get("action") or "none"
    result = {"verified": False, "saved": False, "message": None}
    if session["takeover"] and action != "none":
        return {"action_result": result, **_trace("execute", skipped="takeover")}
    if action == "talk_here":
        if session["channel"] != "browser_voice":
            session["channel"] = "browser_voice"
            session["identity_confirmed"] = True
            session["state_version"] += 1
            db.add_event("Channel chat → browser_voice", {"sessionId": session["id"]})
        result["message"] = lookup("talk_here")
        zoho.queue("talk_here", session, {"status": "talk_here", "next_action": "Same session; voice audio is not live"})
        return {"session": session, "action_result": result, **_trace("execute", action="talk_here")}
    if action == "callback":
        if not fact_value(session["facts"], "phone"):
            proposal["next_field"] = "phone"
            result["message"] = lookup("call_me")
            return {"proposal": proposal, "action_result": result, **_trace("execute", action="callback_wait_phone")}
        persist_human_task(session, "callback", "callback_requested", "Human or voice worker returns the call", "Callback recorded")
        session["handed_over"] = True
        session["conversation_state"] = "handed_over"
        session["channel"] = "callback_pending"
        session["identity_confirmed"] = True
        result.update(
            {
                "saved": True,
                "verified": False,
                "message": "I've noted the callback for our onboarding manager. Nobody has dialed yet.",
            }
        )
        return {"session": session, "action_result": result, **_trace("execute", action="callback", case_id=session.get("case_id"))}
    if action == "takeover":
        session["takeover"] = True
        persist_human_task(session, proposal.get("task") or "clarification", "human_takeover", "Onboarding manager owns conversation", "Human takeover")
        result.update({"saved": True, "message": "I'll pause the automated follow-up. Our onboarding manager has this same chat and what's on file."})
        return {"session": session, "action_result": result, **_trace("execute", action="takeover")}
    if action == "create_case":
        task = proposal.get("task")
        if task not in CATALOGUE:
            return {"action_result": result, **_trace("execute", blocked="unknown_task")}
        persist_human_task(session, task, "awaiting_human_action" if task != "operations_support" else "routed_support", task, "Human task queued")
        session["handed_over"] = True
        session["conversation_state"] = "handed_over"
        result.update(
            {
                "saved": True,
                "verified": False,
                "message": f"I've asked our onboarding manager to take the {task.replace('_', ' ')} from here. They haven't approved anything yet.",
            }
        )
        return {"session": session, "action_result": result, **_trace("execute", action="create_case", task=task)}
    if proposal.get("intent") == "decline":
        zoho.queue(
            "decline",
            session,
            {
                "outcome": "lost",
                "lost_reason": "Visitor declined from chat",
                "status": "lost",
                "next_action": "No automated follow-up",
                "action_id": f"{session['id']}:decline:{session['state_version']}",
            },
        )
        result.update({"saved": True, "verified": False, "message": lookup("commit") + " I won't keep chasing this inquiry."})
        return {"session": session, "action_result": result, **_trace("execute", action="decline")}
    return {"action_result": result, **_trace("execute", action="none")}


def _voice_identity_required(session: dict) -> bool:
    return session.get("channel") == "browser_voice" and not session.get("identity_confirmed")


def _chips(session: dict, proposal: dict) -> list[str]:
    if session["takeover"]:
        return CHIPS["handoff"][:1]
    if session["handed_over"]:
        return CHIPS["handoff"]
    if _voice_identity_required(session):
        return CHIPS["voice_id"]
    if not playbook.missing_core(session["facts"], session.get("memory")):
        return CHIPS["assess"]
    field = proposal.get("next_field")
    return CHIPS.get(field) or CHIPS["default"]


def node_reply(state: TurnState) -> dict:
    session = state["session"]
    proposal = state["proposal"]
    bits = list(state.get("knowledge_bits") or [])
    action_result = state.get("action_result") or {}
    if proposal.get("intent") == "decline":
        text = action_result.get("message") or lookup("commit")
        return {"reply_text": text, "chips": CHIPS["handoff"][:1], **_trace("reply", composed="decline")}
    if session["takeover"] and proposal.get("intent") != "status":
        text = "Our onboarding manager has this chat. I'll stay out of the way."
        return {"reply_text": text, "chips": _chips(session, proposal), **_trace("reply", composed="takeover")}
    if proposal.get("intent") == "status":
        if not session.get("case_id"):
            text = "Onboarding hasn't opened a case on this chat yet."
        elif _voice_identity_required(session):
            text = "Confirm your name or callback number before I read case status on a voice channel."
        else:
            current = db.get_case(session["case_id"])
            status_key = (current or {}).get("status") or "unknown"
            text = _case_say(status_key)
            snap = reqmod.snapshot(session["case_id"])
            if snap["issued"]:
                outstanding = snap.get("outstanding") or []
                text += f" Papers in: {snap['returned']}/{snap['issued']}."
                if outstanding:
                    text += " Still need: " + ", ".join(str(item).replace("_", " ") for item in outstanding) + "."
                if snap.get("overdue"):
                    text += f" {snap['overdue']} overdue."
                text += " I won't read a licence or COI back on this chat. A COI on file isn't approved."
            else:
                files = db.list_case_files(session["case_id"])
                if files:
                    flagged = sum(1 for item in files if item["status"] == "flagged")
                    text += f" Onboarding has {len(files)} file(s) on this case"
                    if flagged:
                        text += f"; {flagged} still need a look"
                    text += ". A COI on file isn't approved."
        return {"reply_text": text, "chips": _chips(session, proposal), **_trace("reply", composed="status")}
    variant_text = variants.text_for(proposal.get("reply_variant_id"))
    text, chips, summary = playbook.compose(
        proposal.get("intent") or "general",
        session["facts"],
        bits,
        proposal.get("arrangement"),
        bool(action_result.get("saved")),
        action_result.get("message"),
        proposal.get("next_field"),
        session.get("memory"),
        wording=proposal.get("wording"),
        variant_text=variant_text,
        episodic=memory.episodic_line(session.get("memory"), state.get("user_text") or ""),
        repair=proposal.get("repair"),
        plan=proposal.get("plan"),
        user_text=state.get("user_text") or "",
    )
    if not text:
        text = lookup("unknown")
    leaked = _leaks(text)
    if leaked:
        text = lookup("unknown")
    traces = state.get("traces") or []
    knowledge = next((item for item in traces if item.get("stage") == "knowledge"), {})
    propose = next((item for item in traces if item.get("stage") == "propose"), {})
    reason = second_pass.is_hard(proposal, bool(knowledge.get("hybrid_rerank")), leaked, propose.get("source") or "qwen")
    if reason:
        text = second_pass.repair(text)
        second_pass.log(session["id"], state.get("user_text") or "", text, reason, propose.get("source") or "qwen")
    session["fit_summary"] = summary
    if summary and session["conversation_state"] not in {"handed_over"}:
        session["conversation_state"] = "assess_fit"
    return {
        "reply_text": text,
        "chips": chips or _chips(session, proposal),
        "session": session,
        **_trace("reply", composed="playbook", second_pass=reason),
    }


def build_graph(checkpointer: Any):
    graph = StateGraph(TurnState)
    graph.add_node("propose", node_propose)
    graph.add_node("reduce_facts", node_reduce_facts)
    graph.add_node("knowledge", node_knowledge)
    graph.add_node("plan", node_plan)
    graph.add_node("execute", node_execute)
    graph.add_node("reply", node_reply)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "reduce_facts")
    graph.add_edge("reduce_facts", "knowledge")
    graph.add_edge("knowledge", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "reply")
    graph.add_edge("reply", END)
    return graph.compile(checkpointer=checkpointer)
