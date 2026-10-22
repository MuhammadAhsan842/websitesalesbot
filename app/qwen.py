"""One bounded local Qwen invocation per accepted turn. The model cannot execute."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.cpu import default_threads
from app.schema import CATALOGUE, FACT_KEYS, INTENTS

log = logging.getLogger("ayyan.qwen")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    model: str = "qwen3.5:2b"
    url: str = "http://127.0.0.1:11434"
    threads: int = 4
    context: int = 2048
    output: int = 256
    parallel: int = 1
    max_waiting: int = 8
    queue_timeout: float = 15.0
    request_timeout: float = 90.0
    keep_alive: str = "30m"
    num_gpu: int = 0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model=os.getenv("QWEN_MODEL", "qwen3.5:2b"),
            url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            threads=_integer("QWEN_NUM_THREAD", default_threads(), 1, 1024),
            context=_integer("QWEN_NUM_CTX", 2048, 1024, 131072),
            output=_integer("QWEN_NUM_PREDICT", 256, 64, 2048),
            parallel=_integer("QWEN_MAX_INFLIGHT", 1, 1, 16),
            max_waiting=_integer("QWEN_MAX_WAITING", 8, 0, 1024),
            queue_timeout=_integer("QWEN_QUEUE_TIMEOUT_SEC", 15, 1, 300),
            request_timeout=_integer("QWEN_TIMEOUT_SEC", 90, 1, 600),
            keep_alive=os.getenv("QWEN_KEEP_ALIVE", "30m"),
            num_gpu=_integer("QWEN_NUM_GPU", 0, -1, 1024),
        )


CONFIG = Settings.from_env()
MODEL = CONFIG.model
OLLAMA = CONFIG.url
_client: httpx.AsyncClient | None = None
ready = False
last_error: str | None = None


class InferenceBusy(RuntimeError):
    """Turn was not accepted for inference; retry rather than silently skipping Qwen."""


class Admission:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.slots = asyncio.Semaphore(settings.parallel)
        self.pending = 0
        self.active = 0

    @asynccontextmanager
    async def enter(self):
        # No await between capacity check and reservation: atomic on this event loop.
        if self.pending >= self.settings.parallel + self.settings.max_waiting:
            raise InferenceBusy("Qwen queue is full")
        self.pending += 1
        acquired = False
        started = perf_counter()
        try:
            try:
                await asyncio.wait_for(self.slots.acquire(), self.settings.queue_timeout)
                acquired = True
            except TimeoutError as exc:
                raise InferenceBusy("Qwen queue wait expired") from exc
            self.active += 1
            yield (perf_counter() - started) * 1000
        finally:
            self.pending -= 1
            if acquired:
                self.active -= 1
                self.slots.release()


_gate = Admission(CONFIG)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(json_schema_extra={"enum": [*dict.fromkeys(FACT_KEYS), "_unknown"]})
    value: str | int | float | bool | None

    @field_validator("key")
    @classmethod
    def known_key(cls, value: str) -> str:
        if value not in FACT_KEYS and value != "_unknown":
            raise ValueError("unknown fact key")
        return value


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: str = Field(json_schema_extra={"enum": list(INTENTS)})
    facts: list[Fact] = Field(default_factory=list, max_length=len(set(FACT_KEYS)) + 1)
    knowledge_keys: list[str] = Field(default_factory=list, max_length=32)
    blocked: list[str] = Field(default_factory=list, max_length=16)
    next_field: str | None = Field(default=None, json_schema_extra={"enum": [*dict.fromkeys(FACT_KEYS), None]})
    arrangement: str | None = Field(default=None, json_schema_extra={"enum": ["dispatch_service", "lease_on", "needs_clarification", None]})
    action: str = Field(default="none", json_schema_extra={"enum": ["none", "create_case", "callback", "talk_here", "takeover"]})
    task: str | None = Field(default=None, json_schema_extra={"enum": [*CATALOGUE, None]})

    @field_validator("intent", "next_field", "arrangement", "action", "task")
    @classmethod
    def allowed_value(cls, value: str | None, info):
        allowed = {
            "intent": INTENTS,
            "next_field": [*FACT_KEYS, None],
            "arrangement": ["dispatch_service", "lease_on", "needs_clarification", None],
            "action": ["none", "create_case", "callback", "talk_here", "takeover"],
            "task": [*CATALOGUE, None],
        }
        if value not in allowed[info.field_name]:
            raise ValueError(f"invalid {info.field_name}")
        return value


OUTPUT_SCHEMA = Proposal.model_json_schema()
SYSTEM = """Ayyan dispatch intent/fact extractor. JSON only. /no_think
Output: {"intent":"...","facts":[{"key":"...","value":"..."}],"knowledge_keys":[],"blocked":[]}. Omit empty optional fields.
Fact keys: equipment,fleetSize,operatingArea,lanes,supportNeed,startDate,mcOwnership,primaryProblem,name,phone,requestedArrangement. Extract only stated new/corrected facts; fleetSize is an integer. Code assigns evidence status. Never approve, quote %, or claim CRM saved.
One box truck => box_truck and fleetSize 1. Own MC => mcOwnership own_mc, intent mc; lease on => no_own_mc. existing_customer only for detention, where's my load, or already a carrier. decline only for not interested/stop contacting. Weekly earnings/guarantee => intent guarantee, blocked guarantee, knowledge_keys guarantee; add freight if also asking to stay loaded. Keep home-time needs. Never invent missing facts."""


def request_payload(user_text: str, facts: dict, conversation_state: str, settings: Settings | None = None) -> dict:
    cfg = settings or CONFIG
    # Exclude recursive previous/source/version metadata, preserving current values.
    current = {key: record.get("value") for key, record in sorted(facts.items()) if key in FACT_KEYS and isinstance(record, dict)}
    user = json.dumps({"state": conversation_state, "facts": current, "text": user_text}, ensure_ascii=False, separators=(",", ":"))
    return {
        "model": cfg.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "think": False,
        "keep_alive": cfg.keep_alive,
        "options": {"temperature": 0, "num_predict": cfg.output, "num_ctx": cfg.context, "num_thread": cfg.threads, "num_gpu": cfg.num_gpu},
    }


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(CONFIG.request_timeout, connect=5.0),
            limits=httpx.Limits(max_connections=CONFIG.parallel, max_keepalive_connections=CONFIG.parallel),
        )
    return _client


async def close() -> None:
    global _client, ready
    if _client is not None:
        await _client.aclose()
        _client = None
    ready = False


def status() -> dict:
    return {"profile": "portable_cpu", "threads": CONFIG.threads, "context": CONFIG.context,
            "max_output": CONFIG.output, "max_inflight": CONFIG.parallel,
            "active": _gate.active, "waiting": _gate.pending - _gate.active, "max_waiting": CONFIG.max_waiting}


async def propose(user_text: str, facts: dict, conversation_state: str) -> dict[str, Any]:
    global last_error, ready
    async with _gate.enter() as queue_ms:
        started = perf_counter()
        try:
            response = await client().post(f"{OLLAMA}/api/chat", json=request_payload(user_text, facts, conversation_state))
            response.raise_for_status()
            body = response.json()
            if body.get("done_reason") == "length":
                raise ValueError("Qwen output truncated; increase QWEN_NUM_PREDICT")
            parsed = Proposal.model_validate_json(body.get("message", {}).get("content", ""))
            result = parsed.model_dump()
            for fact in result["facts"]:
                fact["status"] = "user_stated"  # Model never chooses verification status.
            # Timing contains no prompt, model content, or personal information.
            timing = {"queue_ms": round(queue_ms, 2), "request_ms": round((perf_counter() - started) * 1000, 2)}
            for key in ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration"):
                value = body.get(key)
                if isinstance(value, (int, float)):
                    timing[key.replace("_duration", "_ms")] = round(value / 1_000_000, 2)
            for key in ("prompt_eval_count", "eval_count"):
                if isinstance(body.get(key), int):
                    timing[key] = body[key]
            result.update(_source="qwen", _timing=timing)
            last_error = None
            ready = True
            log.info("qwen timing %s", timing)
            return result
        except (httpx.HTTPError, ValidationError, ValueError, TypeError, AttributeError) as exc:
            # Do not log response bodies/prompts; the existing graph fallback is explicit.
            last_error = "qwen_timeout" if isinstance(exc, httpx.TimeoutException) else "qwen_request_or_schema_failed"
            ready = False
            log.warning("qwen inference failed (transport, timeout, or invalid output)")
            return {}


async def warmup() -> None:
    result = await propose("I need dispatch", {}, "understand_request")
    if result:
        log.info("qwen ready: %s; cpu threads=%s", MODEL, CONFIG.threads)
    else:
        log.warning("qwen warmup failed: %s", last_error)
