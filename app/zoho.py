"""Chat → Zoho. Local save first. Drain submits once. A newer human decision wins."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app import db

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
TOKEN_PATH = ROOT / "data" / "zoho_token.json"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

TIMEOUT_SEC = int(os.getenv("ZOHO_SYNC_TIMEOUT_SEC", "60"))
REDIRECT = os.getenv("ZOHO_REDIRECT_URI", "http://127.0.0.1:8787/v1/zoho/callback")


def _client_id() -> str:
    return os.getenv("ZOHO_CLIENT_ID") or ""


def _client_secret() -> str:
    return os.getenv("ZOHO_CLIENT_SECRET") or ""


def _accounts() -> str:
    stored = _tokens().get("accounts_server")
    return (stored or os.getenv("ZOHO_ACCOUNTS_BASE") or "https://accounts.zoho.com").rstrip("/")


def _tokens() -> dict:
    if not TOKEN_PATH.exists():
        return {}
    try:
        data = json.loads(TOKEN_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tokens(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = _tokens()
    current.update({k: v for k, v in data.items() if v not in (None, "")})
    TOKEN_PATH.write_text(json.dumps(current, indent=2))


def _store_oauth(body: dict, accounts_server: str | None = None) -> dict:
    expires_in = int(body.get("expires_in") or 3600)
    payload = {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token") or _tokens().get("refresh_token"),
        "api_domain": body.get("api_domain"),
        "token_type": body.get("token_type"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 30, 60))).isoformat(),
        "accounts_server": accounts_server or _accounts(),
    }
    _save_tokens(payload)
    return payload


def api_base() -> str:
    domain = (_tokens().get("api_domain") or os.getenv("ZOHO_API_BASE") or "https://www.zohoapis.com/crm/v6").rstrip("/")
    if domain.endswith("/crm/v6"):
        return domain
    return f"{domain}/crm/v6"


def auth_url() -> str:
    params = {
        "scope": os.getenv("ZOHO_SCOPES", "ZohoCRM.modules.ALL,ZohoCRM.settings.ALL"),
        "client_id": _client_id(),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "redirect_uri": REDIRECT,
    }
    return f"{_accounts()}/oauth/v2/auth?{urlencode(params)}"


def exchange_code(code: str, accounts_server: str | None = None) -> dict:
    if not _client_id() or not _client_secret():
        raise RuntimeError("Zoho client id/secret are not configured")
    base = (accounts_server or _accounts()).rstrip("/")
    data = {
        "grant_type": "authorization_code",
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "code": code,
        "redirect_uri": REDIRECT,
    }
    response = httpx.post(f"{base}/oauth/v2/token", data=data, timeout=20.0)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code >= 400 or body.get("error"):
        retry = dict(data)
        retry.pop("redirect_uri", None)
        response = httpx.post(f"{base}/oauth/v2/token", data=retry, timeout=20.0)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code >= 400 or not body.get("access_token"):
        raise RuntimeError(body.get("error") or body.get("message") or response.text[:300] or "token exchange failed")
    return _store_oauth(body, accounts_server=base)


def _refresh(refresh_token: str) -> str | None:
    response = httpx.post(
        f"{_accounts()}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "refresh_token": refresh_token,
        },
        timeout=20.0,
    )
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code >= 400 or not body.get("access_token"):
        return None
    _store_oauth(body)
    return body.get("access_token")


def access_token() -> str | None:
    data = _tokens()
    token = data.get("access_token")
    expires_at = data.get("expires_at")
    if token and expires_at:
        try:
            if datetime.fromisoformat(str(expires_at)) <= datetime.now(timezone.utc):
                token = None
        except ValueError:
            token = None
    if token:
        return token
    if data.get("refresh_token"):
        refreshed = _refresh(data["refresh_token"])
        if refreshed:
            return refreshed
    return os.getenv("ZOHO_ACCESS_TOKEN") or None


def mode() -> str:
    return "live" if access_token() else "offline"


def connection() -> dict:
    data = _tokens()
    return {
        "mode": mode(),
        "client_configured": bool(_client_id() and _client_secret()),
        "connected": bool(access_token()),
        "has_refresh": bool(data.get("refresh_token")),
        "connect_url": "/v1/zoho/connect",
        "redirect_uri": REDIRECT,
        "api_base": api_base(),
    }

STAGES = {
    "inquiry": "Qualification",
    "fit_update": "Qualification",
    "callback": "Callback Requested",
    "setup_packet": "Onboarding",
    "lease_agreement": "Onboarding",
    "insurance_quote": "Onboarding",
    "clarification": "Needs Clarification",
    "operations_support": "Operations",
    "human_takeover": "Human Takeover",
    "manager_requested": "Onboarding",
    "talk_here": "Qualification",
    "packet_sent": "Packet Sent",
    "received": "Documents Received",
    "corrections": "Corrections Requested",
    "approve": "Approved for Handoff",
    "production": "Production Accepted",
    "document_review": "Documents Received",
    "decline": "Closed Lost",
}

# Fact updates must not pull a handoff deal back to Qualification.
STAGE_RANK = {
    "Qualification": 1,
    "Needs Clarification": 2,
    "Callback Requested": 3,
    "Onboarding": 4,
    "Packet Sent": 5,
    "Documents Received": 6,
    "Corrections Requested": 6,
    "Human Takeover": 7,
    "Approved for Handoff": 8,
    "Production Accepted": 9,
    "Closed Lost": 10,
    "Operations": 4,
}

FOLLOW_UP_DAYS = {
    "callback": 1,
    "setup_packet": 2,
    "lease_agreement": 2,
    "insurance_quote": 2,
    "clarification": 1,
    "operations_support": 1,
    "human_takeover": 0,
}


def _val(facts: dict, key: str):
    item = facts.get(key) if isinstance(facts, dict) else None
    if not item or item.get("status") == "unknown":
        return None
    return item.get("value")


def _objections(blocked: list | None, intent: str | None) -> list[str]:
    labels = []
    for item in blocked or []:
        labels.append(str(item))
    if intent in {"fee", "guarantee", "freight", "fuel", "trust", "hometime"}:
        labels.append(intent)
    return list(dict.fromkeys(labels))


def _due(kind: str) -> str | None:
    days = FOLLOW_UP_DAYS.get(kind)
    if days is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _is_handoff_scenario(scenario: str, task: str | None, status: str | None) -> bool:
    if scenario in {
        "callback",
        "setup_packet",
        "lease_agreement",
        "insurance_quote",
        "clarification",
        "human_takeover",
        "manager_requested",
        "operations_support",
    }:
        return True
    if status in {"manager_requested", "callback_requested", "awaiting_human_action", "human_takeover"}:
        return True
    if task in {"callback", "setup_packet", "lease_agreement", "insurance_quote", "clarification"}:
        return True
    return False


def _resolve_stage(scenario: str, task: str | None, status: str | None, act: str | None, opportunity_id: str | None) -> str:
    key = act or task or scenario
    if status == "manager_requested":
        key = "manager_requested"
    proposed = STAGES.get(key, "Qualification")
    stored = db.get_mirror(opportunity_id) if opportunity_id else None
    existing = (stored or {}).get("stage")
    if not existing:
        return proposed
    # Fit / inquiry / talk_here must not regress a handoff or onboarding stage.
    if scenario in {"fit_update", "inquiry", "talk_here"} and STAGE_RANK.get(existing, 0) >= STAGE_RANK.get(
        proposed, 0
    ):
        return existing
    # Callback is a contact method — do not demote an Onboarding deal.
    if scenario == "callback" and STAGE_RANK.get(existing, 0) > STAGE_RANK.get(proposed, 0):
        return existing
    if STAGE_RANK.get(existing, 0) > STAGE_RANK.get(proposed, 0) and scenario in {"fit_update", "inquiry", "talk_here"}:
        return existing
    return proposed


def _description(session: dict, extra: dict, arrangement: str | None) -> str:
    from app.playbook import fit_summary, handoff_brief

    facts = session.get("facts") or {}
    task = extra.get("task")
    status = extra.get("status")
    scenario = extra.get("scenario") or ""
    try:
        if _is_handoff_scenario(scenario, task, status):
            return handoff_brief(
                facts,
                arrangement,
                task=task,
                status=status,
                next_action=extra.get("next_action"),
                related_tasks=extra.get("related_tasks") or session.get("related_tasks"),
                opportunity_id=session.get("opportunity_id"),
                reason=extra.get("reason"),
            )
        return fit_summary(facts, arrangement)
    except Exception:
        return ""


def record(scenario: str, session: dict, extra: dict | None = None) -> dict:
    extra = extra or {}
    facts = session.get("facts") or {}
    from app.playbook import deal_title
    from app.rules import arrangement_of

    arrangement = extra.get("arrangement") or arrangement_of(facts)
    task = extra.get("task")
    status = extra.get("status") or session.get("conversation_state")
    owner = extra.get("owner") or "Unassigned desk"
    follow = extra.get("follow_up_due") or _due(task or scenario)
    stage = _resolve_stage(scenario, task, status, extra.get("act"), session.get("opportunity_id"))
    extra_for_desc = {**extra, "scenario": scenario, "task": task, "status": status}
    description = _description(session, extra_for_desc, arrangement)
    title = deal_title(facts, arrangement, task=task, opportunity_id=session.get("opportunity_id"))
    zoho_fields = {
        "Deal_Name": title,
        "Stage": stage,
        "Phone": _val(facts, "phone"),
        "Description": description,
    }
    # Follow-up timing belongs in the brief / Next Step — not Closing Date.
    next_step = extra.get("next_action")
    if next_step:
        zoho_fields["Description"] = f"{description}\n\nNext Step: {next_step}"
    payload = {
        "scenario": scenario,
        "module": extra.get("module") or "Deals",
        "session_id": session.get("id"),
        "opportunity_id": session.get("opportunity_id"),
        "case_id": extra.get("case_id") or session.get("case_id"),
        "state_version": session.get("state_version"),
        "human_version": int(extra.get("human_version") or 0),
        "channel": session.get("channel") or "chat",
        "follow_up_due": follow,
        "zoho": zoho_fields,
        "crm": {
            "inquiry_id": session.get("opportunity_id"),
            "arrangement": arrangement,
            "equipment": _val(facts, "equipment"),
            "trailer_length": _val(facts, "trailerLength"),
            "fleet_size": _val(facts, "fleetSize"),
            "lanes": _val(facts, "lanes") or _val(facts, "operatingArea"),
            "operating_mode": _val(facts, "operatingMode"),
            "miles_per_day": _val(facts, "milesPerDay"),
            "weekday_schedule": _val(facts, "weekdaySchedule"),
            "insurance": _val(facts, "insurance"),
            "insurance_route": _val(facts, "insuranceRoute"),
            "coverage_types": _val(facts, "coverageTypes"),
            "callback_phone": _val(facts, "phone"),
            "callback_time": _val(facts, "callbackTime"),
            "callback_timezone": _val(facts, "callbackTimezone"),
            "support_need": _val(facts, "supportNeed") or _val(facts, "primaryProblem"),
            "start_date": _val(facts, "startDate"),
            "mc_status": _val(facts, "mcOwnership"),
            "name": _val(facts, "name"),
            "needs_summary": description,
            "handoff_status": status,
            "unresolved_objections": _objections(extra.get("blocked"), extra.get("intent")),
            "next_action": next_step,
            "owner": owner,
            "follow_up_due": follow,
            "task": task,
            "related_tasks": extra.get("related_tasks") or session.get("related_tasks") or [],
            "status": status,
            "outcome": extra.get("outcome"),
            "lost_reason": extra.get("lost_reason"),
            "facts": {
                key: {"value": item.get("value"), "status": item.get("status")}
                for key, item in facts.items()
                if isinstance(item, dict)
            },
        },
    }
    return payload


def queue(scenario: str, session: dict, extra: dict | None = None) -> dict:
    extra = extra or {}
    payload = record(scenario, session, extra)
    action_id = extra.get("action_id") or f"{session.get('id')}:{scenario}:{session.get('state_version')}"
    return db.enqueue_outbox(action_id, scenario, payload)


def queue_inquiry(session: dict, page: str | None = None) -> dict:
    extra = {"action_id": f"{session['opportunity_id']}:inquiry", "intent": "dispatch_inquiry"}
    if page:
        extra["next_action"] = f"page:{page}"
    return queue("inquiry", session, extra)


def queue_fit(session: dict, proposal: dict | None = None) -> dict:
    proposal = proposal or {}
    # Stable action id per opportunity version — updates the same Deal via mirror id.
    return queue(
        "fit_update",
        session,
        {
            "blocked": proposal.get("blocked"),
            "intent": proposal.get("intent"),
            "arrangement": proposal.get("arrangement"),
            "action_id": f"{session.get('opportunity_id')}:fit:{session.get('state_version')}",
        },
    )


def queue_handoff(session: dict, task: str, status: str, next_action: str) -> dict:
    scenario = "callback" if task == "callback" else task
    if task == "operations_support":
        scenario = "operations_support"
    if status == "human_takeover":
        scenario = "human_takeover"
    if status == "manager_requested":
        scenario = "manager_requested"
    related = list(session.get("related_tasks") or [])
    case = db.get_case(session["case_id"]) if session.get("case_id") else None
    purpose = (case or {}).get("task")
    # Brief should show purpose (e.g. insurance_quote) even when this event is a callback.
    brief_task = purpose if purpose and task == "callback" else task
    if purpose and purpose != task and purpose not in related:
        related = [purpose, *related]
    if task == "callback" and "callback" not in related and purpose and purpose != "callback":
        related = list(dict.fromkeys([*related, "callback"]))
    return queue(
        scenario,
        session,
        {
            "task": brief_task,
            "status": status,
            "next_action": next_action,
            "related_tasks": related,
            "outcome": status,
            # Opportunity-scoped id so retries update one Deal, not one Deal per browser session.
            "action_id": f"{session.get('opportunity_id')}:{task}:{status}:{session.get('state_version')}",
        },
    )


def queue_stage(case: dict, act: str, status: str, next_action: str) -> dict | None:
    session = db.get_session(case["session_id"]) if case.get("session_id") else None
    if not session:
        session = {
            "id": case.get("session_id"),
            "opportunity_id": case.get("opportunity_id"),
            "case_id": case.get("id"),
            "facts": case.get("facts") or {},
            "channel": "chat",
            "state_version": 0,
            "conversation_state": status,
        }
    else:
        session["case_id"] = case.get("id")
        session["facts"] = case.get("facts") or session.get("facts") or {}
    stored = db.get_mirror(case.get("opportunity_id"))
    human_version = int((stored or {}).get("human_version") or 0) + 1
    return queue(
        "stage_change",
        session,
        {
            "act": act,
            "task": case.get("task"),
            "status": status,
            "next_action": next_action,
            "owner": case.get("owner"),
            "case_id": case.get("id"),
            "human_version": human_version,
            "outcome": status,
            "action_id": f"{case.get('id')}:{act}:{human_version}",
        },
    )


def sync_status(session_id: str | None = None, case_id: str | None = None, opportunity_id: str | None = None) -> dict:
    expire_stale()
    rows = db.list_outbox(session_id=session_id, case_id=case_id, opportunity_id=opportunity_id)
    pending = [row for row in rows if row["status"] == "queued"]
    failed = [row for row in rows if row["status"] in {"failed", "timeout"}]
    synced = [row for row in rows if row["status"] in {"synced", "synced_note"}]
    latest = rows[0] if rows else None
    verified = bool(latest) and latest["status"] in {"synced", "synced_note"} and not pending
    return {
        "mode": mode(),
        "verified": verified,
        "assigned": False if not verified else bool((latest or {}).get("zoho_id")),
        "pending": len(pending),
        "failed": len(failed),
        "latest": {
            "kind": latest.get("kind"),
            "status": latest.get("status"),
            "zoho_id": latest.get("zoho_id"),
            "error": latest.get("last_error"),
        }
        if latest
        else None,
        "rows": [
            {
                "action_id": row["action_id"],
                "kind": row["kind"],
                "status": row["status"],
                "zoho_id": row.get("zoho_id"),
                "error": row.get("last_error"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows[:12]
        ],
        "note": "Local save is not a Zoho assignment. Sync must be verified.",
    }


def expire_stale():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=TIMEOUT_SEC)
    for row in db.queued_outbox() or []:
        try:
            created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created < cutoff:
            db.mark_outbox(row["action_id"], "timeout", f"No verified Zoho write within {TIMEOUT_SEC}s")


def _human_newer(payload: dict) -> dict | None:
    stored = db.get_mirror(payload.get("opportunity_id"))
    if not stored:
        return None
    if int(payload.get("human_version") or 0) < int(stored.get("human_version") or 0):
        return stored
    return None


def _parse_zoho_record(response: httpx.Response, existing_id: str | None) -> str:
    """HTTP 200 is not enough — Zoho may return per-record errors in the body."""
    response.raise_for_status()
    rows = response.json().get("data") or []
    if not rows:
        raise RuntimeError("Zoho returned an empty data array")
    row = rows[0] or {}
    code = str(row.get("code") or "").upper()
    status = str(row.get("status") or "").lower()
    if status == "error" or code in {"INVALID_DATA", "DUPLICATE_DATA", "MANDATORY_NOT_FOUND", "AUTHORIZATION_ERROR"}:
        raise RuntimeError(f"Zoho record rejected: {row.get('message') or code or row}")
    details = row.get("details") or {}
    zoho_id = str(details.get("id") or existing_id or "").strip()
    if not zoho_id:
        raise RuntimeError("Zoho response omitted Deal id — leaving sync unresolved")
    return zoho_id


def _submit_live(payload: dict, existing_id: str | None) -> str:
    token = access_token()
    if not token:
        raise RuntimeError("Zoho is not connected")
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    body = {"data": [payload.get("zoho") or {}]}
    base = api_base()
    real_existing = existing_id if existing_id and not str(existing_id).startswith("zcrm_local_") else None
    if real_existing:
        url = f"{base}/Deals/{real_existing}"
        response = httpx.put(url, headers=headers, json=body, timeout=20.0)
        return _parse_zoho_record(response, real_existing)
    url = f"{base}/Deals"
    response = httpx.post(url, headers=headers, json=body, timeout=20.0)
    return _parse_zoho_record(response, None)


def _submit_offline(payload: dict, zoho_id: str | None = None) -> str:
    stored = db.get_mirror(payload.get("opportunity_id"))
    resolved = db.prefer_zoho_id(
        zoho_id or payload.get("zoho_id"),
        (stored or {}).get("id") or f"zcrm_local_{payload.get('opportunity_id')}",
    )
    db.upsert_mirror(
        {
            "id": resolved,
            "module": payload.get("module") or "Deals",
            "opportunity_id": payload.get("opportunity_id"),
            "case_id": payload.get("case_id"),
            "session_id": payload.get("session_id"),
            "human_version": payload.get("human_version") or 0,
            "stage": (payload.get("zoho") or {}).get("Stage"),
            "data": payload,
        }
    )
    return resolved


def drain() -> list[dict]:
    expire_stale()
    results = []
    for row in db.queued_outbox() or []:
        payload = db.loads(row["payload_json"], {})
        try:
            stored = _human_newer(payload)
            if stored:
                db.mark_outbox(row["action_id"], "synced_note", "Human decision is newer; stage was not overwritten")
                db.set_outbox_zoho(row["action_id"], stored.get("id"))
                db.add_event("Zoho skipped newer human decision", {"action_id": row["action_id"]})
                results.append({"action_id": row["action_id"], "status": "synced_note"})
                continue
            existing = (db.get_mirror(payload.get("opportunity_id")) or {}).get("id")
            if mode() == "live":
                zoho_id = _submit_live(payload, existing)
                payload["zoho_id"] = zoho_id
                # Persist the real Deal id so the next event updates instead of POSTing again.
                _submit_offline(payload, zoho_id)
            else:
                zoho_id = _submit_offline(payload, existing)
            db.mark_outbox(row["action_id"], "synced")
            db.set_outbox_zoho(row["action_id"], zoho_id)
            db.add_event("Zoho sync", {"action_id": row["action_id"], "kind": row["kind"], "mode": mode(), "zoho_id": zoho_id})
            results.append({"action_id": row["action_id"], "status": "synced", "zoho_id": zoho_id})
        except Exception as exc:
            db.mark_outbox(row["action_id"], "failed", str(exc))
            results.append({"action_id": row["action_id"], "status": "failed", "error": str(exc)})
    return results
