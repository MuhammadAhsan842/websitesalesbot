"""One local Qwen call. The model proposes JSON; it cannot execute."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

MODEL = os.getenv("QWEN_MODEL", "qwen3.5:2b")
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
log = logging.getLogger("ayyan.qwen")

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()
ready = False
last_error: str | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0))
    return _client


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


SYSTEM = """Ayyan dispatch LangGraph proposer. JSON only. /no_think
Schema: {"intent":"dispatch_inquiry|existing_customer|talk_here|call_me|fee|guarantee|freight|fuel|trust|commit|hometime|human|onboard|lease|mc|mc_new|service|status|unknown_detail|decline|general","facts":[{"key":"equipment|fleetSize|operatingArea|lanes|supportNeed|startDate|mcOwnership|primaryProblem|name|phone|requestedArrangement","value":"","status":"user_stated"}],"knowledge_keys":[],"blocked":[],"next_field":null,"arrangement":null,"action":"none","task":null}
Extract every fact. one box truck => equipment box_truck, fleetSize 1. Dual questions: every matching knowledge_key. own MC on a new inquiry is mc, not existing_customer. existing_customer only for detention, where's my load, or already a carrier. decline only for not interested / stop contacting. $ weekly/guarantee => intent guarantee, blocked guarantee, plus freight if they also ask to stay loaded. Never approve, quote %, or claim CRM saved."""


async def propose(user_text: str, facts: dict, conversation_state: str) -> dict[str, Any]:
    global last_error
    user = json.dumps(
        {"text": user_text, "facts": facts, "conversation_state": conversation_state},
        ensure_ascii=False,
    )
    async with _lock:
        try:
            response = await client().post(
                f"{OLLAMA}/api/chat",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user + "\n/no_think"},
                    ],
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0, "num_predict": 180, "num_ctx": 2048},
                },
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            parsed = _extract_json(content)
            if not parsed:
                last_error = "empty_json"
                log.warning("qwen returned no JSON: %s", content[:300])
                return {}
            parsed["_source"] = "qwen"
            last_error = None
            return parsed
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}".strip() or type(exc).__name__
            log.exception("qwen propose failed")
            return {}


async def warmup() -> None:
    global ready
    result = await propose("ping", {}, "understand_request")
    ready = bool(result)
    if ready:
        log.info("qwen ready: %s", MODEL)
    else:
        log.warning("qwen warmup failed: %s", last_error)
