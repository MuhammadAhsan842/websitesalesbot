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

from app import db, fees, playbook, qwen, requirements as reqmod, retrieve, rules, second_pass, zoho
from app.knowledge import BLOCKED_CLAIMS, REGISTER, lookup
from app.schema import CATALOGUE, CHIPS, FACT_KEYS, INTENTS
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
    r"we guarantee|guaranteed \$?\d|you are approved|you're approved|insurance is approved|coi is valid",
    re.I,
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _leaks(text: str) -> bool:
    if LEAK_MONEY.search(text) or LEAK_CLAIM.search(text):
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


def _clean_facts(items: list | None) -> list[dict]:
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key != "_unknown" and key not in FACT_KEYS:
            continue
        value = item.get("value")
        if value in ("null", ""):
            value = None
        cleaned.append({"key": key, "value": value, "status": item.get("status") or "user_stated"})
    return cleaned


def _merge_facts(model_facts: list | None, ruled_facts: list | None) -> list[dict]:
    by_key: dict[str, dict] = {}
    for item in _clean_facts(ruled_facts):
        by_key[item["key"]] = item
    for item in _clean_facts(model_facts):
        if item.get("value") not in (None, False) or item["key"] not in by_key:
            by_key[item["key"]] = item
    return list(by_key.values())


def _from_qwen(model: dict, ruled: dict) -> dict:
    intent = model.get("intent") if model.get("intent") in INTENTS else None
    ruled_intent = ruled["intent"]
    if intent in {"existing_customer", "decline", "talk_here", "call_me", "human"} and ruled_intent not in {intent}:
        intent = ruled_intent
    if not intent or intent == "general":
        intent = ruled_intent
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
    next_field = model.get("next_field")
    if next_field in ("null", None, "") or (next_field and next_field not in FACT_KEYS):
        next_field = ruled.get("next_field")
    keys = [k for k in (model.get("knowledge_keys") or []) + ruled["knowledge_keys"] if isinstance(k, str)]
    blocked = [b for b in (model.get("blocked") or []) + ruled["blocked"] if isinstance(b, str)]
    return {
        "intent": intent,
        "facts": _merge_facts(model.get("facts"), ruled.get("facts")),
        "knowledge_keys": list(dict.fromkeys(keys)),
        "blocked": list(dict.fromkeys(blocked)),
        "next_field": next_field,
        "arrangement": arrangement,
        "action": action,
        "task": task,
        "_source": "qwen",
    }


async def node_propose(state: TurnState) -> dict:
    session = state["session"]
    text = state["user_text"]
    ruled = rules.propose(text, session["facts"])
    model = await qwen.propose(text, session["facts"], session["conversation_state"])
    if not model:
        return {
            "proposal": ruled,
            **_trace("propose", source="rules_fallback", intent=ruled["intent"], model=qwen.MODEL, error=qwen.last_error),
        }
    merged = _from_qwen(model, ruled)
    return {
        "proposal": merged,
        **_trace("propose", source="qwen", intent=merged["intent"], model=qwen.MODEL, action=merged["action"]),
    }


def node_reduce_facts(state: TurnState) -> dict:
    session = state["session"]
    proposal = state["proposal"]
    unknown = any(item.get("key") == "_unknown" for item in proposal.get("facts") or [])
    if unknown:
        missing = playbook.next_ask(session["facts"])
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
    for item in proposal.get("facts") or []:
        key = item.get("key")
        if key not in FACT_KEYS:
            continue
        status = item.get("status") or "user_stated"
        previous = session["facts"].get(key)
        if previous and previous.get("value") == item.get("value") and previous.get("status") != "unknown":
            continue
        if previous and previous.get("value") != item.get("value"):
            status = "corrected"
            db.cancel_unsent(session["id"], f"stale plan after {key} correction")
            cancelled = True
        session["facts"][key] = {
            "value": item.get("value"),
            "status": status,
            "sourceChannel": session["channel"],
            "version": session["state_version"],
            "previous": {"value": previous["value"], "status": previous["status"]} if previous else None,
        }
        session["state_version"] += 1
    if proposal.get("intent") == "hometime":
        session["facts"]["supportNeed"] = {
            "value": "daily_home_time",
            "status": "user_stated",
            "sourceChannel": session["channel"],
            "version": session["state_version"],
            "previous": session["facts"].get("supportNeed"),
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
    arrangement = proposal.get("arrangement") or rules.arrangement_of(state["session"]["facts"])
    hybrid = False
    hits = []
    bits = []
    if keys:
        for key in keys:
            if key == "fee":
                bits.append(fees.live_quote(arrangement))
            else:
                bits.append(lookup(key))
    else:
        hybrid = True
        hits = retrieve.search(state.get("user_text") or "")
        bits = [hit["text"] for hit in hits]
        keys = [hit["key"] for hit in hits]
    return {
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
    mc = fact_value(session["facts"], "mcOwnership")
    if mc == "own_mc":
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
    ask = playbook.next_ask(session["facts"])
    proposal["next_field"] = ask
    if proposal["intent"] == "talk_here":
        proposal["action"] = "talk_here"
    elif proposal["intent"] == "call_me":
        proposal["action"] = "callback"
    elif proposal["intent"] == "human":
        proposal["action"] = "takeover"
    elif proposal["intent"] == "existing_customer":
        proposal["action"] = "create_case"
        proposal["task"] = "operations_support"
    elif proposal["action"] == "create_case" and proposal["task"] not in CATALOGUE:
        proposal["action"] = "none"
    if proposal["action"] == "create_case" and proposal["task"] in {"setup_packet", "lease_agreement"} and (
        not fact_value(session["facts"], "equipment") or not mc
    ):
        proposal["action"] = "none"
    if proposal["action"] not in {"none", "create_case", "callback", "talk_here", "takeover"}:
        proposal["action"] = "none"
    if session["handed_over"]:
        session["conversation_state"] = "handed_over"
    elif not playbook.missing_core(session["facts"]):
        session["conversation_state"] = "assess_fit"
    elif proposal["intent"] == "dispatch_inquiry" or session["conversation_state"] != "understand_request":
        session["conversation_state"] = "discover_needs"
    return {"proposal": proposal, "session": session, **_trace("plan", action=proposal["action"], task=proposal.get("task"))}


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
                "message": "Callback recorded locally. It is not dialed and not assigned in Zoho until sync is verified.",
            }
        )
        return {"session": session, "action_result": result, **_trace("execute", action="callback", case_id=session.get("case_id"))}
    if action == "takeover":
        session["takeover"] = True
        persist_human_task(session, proposal.get("task") or "clarification", "human_takeover", "Staff owns conversation", "Human takeover")
        result.update({"saved": True, "message": "Automated follow-up is paused. Staff have the same session and facts."})
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
                "message": f"Human-owned {task.replace('_', ' ')} is saved locally. It is not approved and not assigned in Zoho until sync is verified.",
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
        result.update({"saved": True, "verified": False, "message": lookup("commit") + " I will not keep chasing this inquiry."})
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
    if not playbook.missing_core(session["facts"]):
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
        text = "A person owns this case. Automated selling is paused."
        return {"reply_text": text, "chips": _chips(session, proposal), **_trace("reply", composed="takeover")}
    if proposal.get("intent") == "status":
        if not session.get("case_id"):
            text = "No staff case is open yet."
        elif _voice_identity_required(session):
            text = "Confirm your name or callback number before I read case status on a voice channel."
        else:
            current = db.get_case(session["case_id"])
            crm = zoho.sync_status(session_id=session["id"], case_id=session["case_id"])
            text = f"Verified status: {current['status'] if current else 'unknown'}. That is not insurance or agreement approval."
            if crm.get("verified"):
                text += f" Zoho {crm['mode']} sync is verified ({(crm.get('latest') or {}).get('kind')}). Still not assigned unless staff own the desk."
            else:
                text += f" Zoho write is not verified yet ({(crm.get('latest') or {}).get('status') or 'none'}). Local save is not a Zoho assignment."
            snap = reqmod.snapshot(session["case_id"])
            if snap["issued"]:
                text += (
                    f" Packet requirements: {snap['returned']}/{snap['issued']} returned"
                    f"{', ' + str(snap['overdue']) + ' overdue' if snap['overdue'] else ''}."
                    " Extracted fields are unverified. I will not read a licence or COI aloud. A COI on file is not approved."
                )
            else:
                files = db.list_case_files(session["case_id"])
                if files:
                    flagged = sum(1 for item in files if item["status"] == "flagged")
                    text += f" Document worker read {len(files)} file(s); {flagged} still flagged for a person. A COI on file is not approved."
        return {"reply_text": text, "chips": _chips(session, proposal), **_trace("reply", composed="status")}
    text, chips, summary = playbook.compose(
        proposal.get("intent") or "general",
        session["facts"],
        bits,
        proposal.get("arrangement"),
        bool(action_result.get("saved")),
        action_result.get("message"),
        proposal.get("next_field"),
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
