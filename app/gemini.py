"""Optional Gemini chat backend for A/B response tests. Embeddings stay on local nomic/Pinecone."""

from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

import httpx

from app import qwen, router

log = logging.getLogger("ayyan.gemini")

API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
# Fast, cheap default for sales-reply A/B; override with GEMINI_MODEL.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


def api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def enabled() -> bool:
    return bool(api_key()) and (os.getenv("MODEL_ROUTER") or "").strip().lower() == "gemini"


def model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_MODEL).strip()


def status() -> dict:
    return {
        "enabled": enabled(),
        "configured": bool(api_key()),
        "model": model_name(),
        "router": (os.getenv("MODEL_ROUTER") or "").strip().lower(),
        "embeddings": "unchanged (nomic / Pinecone 768)",
    }


def _user_blob(
    user_text: str,
    facts: dict,
    conversation_state: str,
    memory: dict | None,
    examples: list | None,
    recent: list | None,
    approved: list | None,
) -> str:
    # Reuse Qwen's compacted request body so Gemini sees the same grounding.
    payload = qwen.request_payload(
        user_text,
        facts,
        conversation_state,
        memory=memory,
        examples=examples,
        recent=recent,
        approved=approved,
        think=False,
    )
    return payload["messages"][1]["content"]


def _extract_text(body: dict) -> str:
    cands = body.get("candidates") or []
    if not cands:
        raise ValueError(f"gemini empty candidates: {body.get('error') or body}")
    parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    chunks = [p.get("text") or "" for p in parts if isinstance(p, dict)]
    text = "\n".join(chunks).strip()
    if not text:
        raise ValueError("gemini returned empty text")
    # Strip accidental fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return text


async def propose(
    user_text: str,
    facts: dict,
    conversation_state: str,
    memory: dict | None = None,
    examples: list | None = None,
    recent: list | None = None,
    approved: list | None = None,
) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    model = model_name()
    url = f"{API_BASE}/models/{model}:generateContent"
    system = qwen.system_prompt(think=False)
    user = _user_blob(user_text, facts, conversation_state, memory, examples, recent, approved)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT", "512")),
            "responseMimeType": "application/json",
        },
    }
    started = perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = await client.post(url, params={"key": key}, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"gemini HTTP {response.status_code}: {response.text[:400]}")
        raw = response.json()
    content = _extract_text(raw)
    parsed = qwen.parse_content(content)
    result = parsed.model_dump()
    for fact in result["facts"]:
        fact["status"] = "user_stated"
    timing = {"request_ms": round((perf_counter() - started) * 1000, 2), "queue_ms": 0}
    result.update(_source="gemini", _model=model, _timing=timing, _thinking=None, _think=False)
    router_last = {"model": model, "family": "gemini", "reason": "forced_gemini"}
    qwen.last_route = router_last
    qwen.ready = True
    qwen.last_error = None
    log.info("gemini timing %s model=%s", timing, model)
    return result


async def list_models(limit: int = 30) -> list[str]:
    key = api_key()
    if not key:
        return []
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{API_BASE}/models", params={"key": key})
        response.raise_for_status()
        names = []
        for item in response.json().get("models") or []:
            name = (item.get("name") or "").replace("models/", "")
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" in methods and "embed" not in name.lower():
                names.append(name)
        return names[:limit]
