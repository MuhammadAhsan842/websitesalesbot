"""Gemini API client for chat, embeddings, and speech synthesis."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from time import perf_counter
from typing import Any
import urllib.request

import httpx

log = logging.getLogger("ayyan.gemini")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PROJECT_NAME = os.getenv("GEMINI_PROJECT_NAME", "").strip()
PROJECT_NUMBER = os.getenv("GEMINI_PROJECT_NUMBER", "").strip()
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")).strip()
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2").strip()
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts").strip()
BASE_URL = os.getenv("GEMINI_BASE_URL", os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
API_BASE = BASE_URL
DEFAULT_MODEL = CHAT_MODEL


def is_configured() -> bool:
    return bool(api_key())


def api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or API_KEY).strip()


def enabled() -> bool:
    return is_configured() and (os.getenv("MODEL_ROUTER") or "").strip().lower() == "gemini"


def chat_model() -> str:
    return (os.getenv("GEMINI_CHAT_MODEL") or os.getenv("GEMINI_MODEL") or CHAT_MODEL).strip()


def model_name() -> str:
    return chat_model()


def embed_model() -> str:
    return os.getenv("GEMINI_EMBED_MODEL", EMBED_MODEL).strip()


def tts_model() -> str:
    return os.getenv("GEMINI_TTS_MODEL", TTS_MODEL).strip()


def status() -> dict:
    return {
        "enabled": enabled(),
        "configured": is_configured(),
        "model": chat_model(),
        "embed_model": embed_model(),
        "tts_model": tts_model(),
        "router": (os.getenv("MODEL_ROUTER") or "").strip().lower(),
    }


def embed(text: str, dims: int | None = None, timeout: float = 20.0) -> list[float] | None:
    key = api_key()
    if not key:
        return None
    model = embed_model()
    url = f"{BASE_URL}/models/{model}:embedContent?key={key}"
    payload: dict[str, Any] = {
        "content": {"parts": [{"text": text or ""}]}
    }
    if dims and dims > 0:
        payload["outputDimensionality"] = dims

    try:
        raw_json = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=raw_json, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            values = data.get("embedding", {}).get("values")
            if isinstance(values, list) and values:
                return [float(x) for x in values]
    except Exception as exc:
        log.warning("Gemini embed failed: %s", exc)
    return None


def generate_speech(text: str, voice: str | None = None, timeout: float = 30.0) -> bytes:
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model = tts_model()
    url = f"{BASE_URL}/models/{model}:generateContent?key={key}"
    gen_config: dict[str, Any] = {
        "responseModalities": ["AUDIO"]
    }
    target_voice = voice or os.getenv("GEMINI_VOICE_ID", "").strip()
    if target_voice and target_voice not in {"gemini", "owner", "demo"}:
        gen_config["speechConfig"] = {
            "voiceConfig": {
                "voice": target_voice
            }
        }

    payload = {
        "contents": [{"parts": [{"text": text or ""}]}],
        "generationConfig": gen_config
    }
    raw_json = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=raw_json, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    candidates = body.get("candidates") or []
    if not candidates:
        raise ValueError("No candidates returned from Gemini TTS")
    parts = candidates[0].get("content", {}).get("parts") or []
    for part in parts:
        inline = part.get("inlineData") or {}
        b64_data = inline.get("data")
        if b64_data:
            return base64.b64decode(b64_data)
    raise ValueError("No audio payload found in Gemini TTS response")


async def propose(
    user_text: str,
    facts: dict,
    conversation_state: str,
    memory: dict | None = None,
    examples: list | None = None,
    recent: list | None = None,
    approved: list | None = None,
    system_prompt: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model = chat_model()
    url = f"{BASE_URL}/models/{model}:generateContent?key={key}"

    from app import qwen
    from app.qwen import FACT_KEYS

    if not system_prompt:
        system_prompt = qwen.system_prompt(think=False)

    current = {
        k: rec.get("value")
        for k, rec in sorted(facts.items())
        if k in FACT_KEYS and isinstance(rec, dict)
    }
    user_payload: dict[str, Any] = {"state": conversation_state, "facts": current, "text": user_text}
    if memory:
        user_payload["memory"] = {
            "goal": memory.get("goal"),
            "hard_constraint": memory.get("hard_constraint"),
            "concern": memory.get("concern"),
            "answered": memory.get("answered") or [],
            "explained": memory.get("explained") or [],
            "blocker": memory.get("blocker"),
            "last_blocker": memory.get("last_blocker"),
            "last_question_id": memory.get("last_question_id"),
            "follow_up": memory.get("follow_up") or "assistant",
            "next_agreed": memory.get("next_agreed"),
            "records": [
                {"kind": row.get("kind"), "key": row.get("key"), "status": row.get("status")}
                for row in (memory.get("records") or [])
                if row.get("status") in {"active", "reopened"}
            ][:6],
        }
    if approved:
        user_payload["approved_info"] = approved[:8]
    if examples:
        from app.examples import prompt_examples
        user_payload["examples"] = prompt_examples(examples)
    if recent:
        user_payload["recent"] = [
            {"role": row.get("role"), "text": (row.get("text") or "")[:220]}
            for row in recent[:6]
        ]

    user_json = json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))

    req_body: dict[str, Any] = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": user_json}]}
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT", "2048")),
        }
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=req_body)
        resp.raise_for_status()
        body = resp.json()

    candidates = body.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned empty candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    content = ""
    for part in parts:
        if "text" in part:
            content += part["text"]
    content = content.strip()
    if not content:
        raise ValueError("Gemini returned empty text content")

    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start : end + 1]

    parsed = json.loads(content)
    return parsed


async def list_models(limit: int = 30) -> list[str]:
    key = api_key()
    if not key:
        return []
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{BASE_URL}/models", params={"key": key})
        response.raise_for_status()
        names = []
        for item in response.json().get("models") or []:
            name = (item.get("name") or "").replace("models/", "")
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" in methods and "embed" not in name.lower():
                names.append(name)
        return names[:limit]
