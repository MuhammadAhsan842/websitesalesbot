"""One bounded local model invocation per accepted turn. The model cannot execute."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
import re
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import router
from app.cpu import default_threads
from app.schema import CATALOGUE, FACT_KEYS, INTENTS, MOVES, VARIANTS

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
    num_gpu: int = -1

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
            num_gpu=_integer("QWEN_NUM_GPU", -1, -1, 1024),
        )


CONFIG = Settings.from_env()
MODEL = CONFIG.model
GEMMA_MODEL = router.GEMMA_MODEL
OLLAMA = CONFIG.url
_client: httpx.AsyncClient | None = None
ready = False
gemma_ready = False
last_error: str | None = None
last_route: dict = {"model": MODEL, "family": "qwen", "reason": "default"}
_installed: set[str] = set()


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
    arrangement: str | None = Field(
        default=None, json_schema_extra={"enum": ["dispatch_service", "lease_on", "needs_clarification", None]}
    )
    action: str = Field(default="none", json_schema_extra={"enum": ["none", "create_case", "callback", "talk_here", "takeover"]})
    task: str | None = Field(default=None, json_schema_extra={"enum": [*CATALOGUE, None]})
    conversation_move: str | None = Field(default=None, json_schema_extra={"enum": [*MOVES, None]})
    reply_variant_id: str | None = Field(default=None, json_schema_extra={"enum": [*VARIANTS, None]})
    wording: str | None = Field(default=None, max_length=180)

    @field_validator("intent", "next_field", "arrangement", "action", "task", "conversation_move", "reply_variant_id")
    @classmethod
    def allowed_value(cls, value: str | None, info):
        allowed = {
            "intent": INTENTS,
            "next_field": [*FACT_KEYS, None],
            "arrangement": ["dispatch_service", "lease_on", "needs_clarification", None],
            "action": ["none", "create_case", "callback", "talk_here", "takeover"],
            "task": [*CATALOGUE, None],
            "conversation_move": [*MOVES, None],
            "reply_variant_id": [*VARIANTS, None],
        }
        if value not in allowed[info.field_name]:
            raise ValueError(f"invalid {info.field_name}")
        return value


OUTPUT_SCHEMA = Proposal.model_json_schema()
_ACTIONS = {"none", "create_case", "callback", "talk_here", "takeover"}
_ARRANGEMENTS = {"dispatch_service", "lease_on", "needs_clarification"}


def _sanitize(raw: dict) -> dict:
    """Keep a 2b miss from discarding the whole turn. Graph still vetoes actions."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    facts = []
    for item in raw.get("facts") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key != "_unknown" and key not in FACT_KEYS:
            continue
        value = item.get("value")
        if value in ("N/A", "n/a", "null", ""):
            value = None
        if key != "_unknown" and value is None:
            continue
        facts.append({"key": key, "value": True if key == "_unknown" and value is None else value})
    next_field = raw.get("next_field")
    action = raw.get("action") if raw.get("action") in _ACTIONS else "none"
    wording = raw.get("wording") if isinstance(raw.get("wording"), str) else None
    if wording:
        wording = wording.strip()[:180]
        if re.search(r"\$|\d+\s*%|approved|zoho|loads tomorrow|guarantee", wording, re.I):
            wording = None
    return {
        "intent": raw.get("intent") if raw.get("intent") in INTENTS else "general",
        "facts": facts,
        "knowledge_keys": [k for k in raw.get("knowledge_keys") or [] if isinstance(k, str)][:32],
        "blocked": [b for b in raw.get("blocked") or [] if isinstance(b, str)][:16],
        "next_field": next_field if next_field in FACT_KEYS else None,
        "arrangement": raw.get("arrangement") if raw.get("arrangement") in _ARRANGEMENTS else None,
        "action": action or "none",
        "task": raw.get("task") if raw.get("task") in CATALOGUE else None,
        "conversation_move": raw.get("conversation_move") if raw.get("conversation_move") in MOVES else None,
        "reply_variant_id": raw.get("reply_variant_id") if raw.get("reply_variant_id") in VARIANTS else None,
        "wording": wording,
    }


def parse_content(content: str) -> Proposal:
    return Proposal.model_validate(_sanitize(json.loads(content or "{}")))


SYSTEM = """Ayyan Group sales proposer. JSON only. /no_think
Output: {"intent":"...","facts":[{"key":"...","value":"..."}],"knowledge_keys":[],"blocked":[],"conversation_move":"answer","reply_variant_id":null,"wording":null}. Omit empty optional fields.
conversation_move: acknowledge|answer|clarify|qualify|explain_objection|offer_handoff|pause.
Match example wording: acknowledge one stated fact, then at most one question. Short like the examples. No sir, no weekly gross.
Fact keys include trailerLength,payload,liftgate,deadline,operatingMode,commitmentStance. 26ft => trailerLength 26ft. local/no OTR => operatingMode local. Authority is ready without own vs lease => mcOwnership unclear, move clarify. I meant the fee => intent fee. Need to get paid / forget onboarding => existing_customer. Mailbox full / send again => move acknowledge, not a signature ask.
Extract only stated new/corrected facts. Code assigns status. Never approve, quote %, or claim CRM saved. wording: max 18 words, no $, %, approved, Zoho, loads.
Own MC => mcOwnership own_mc. Respect memory.answered and hard_constraint. If follow_up is driver_initiates, omit next_field."""


def request_payload(
    user_text: str,
    facts: dict,
    conversation_state: str,
    settings: Settings | None = None,
    memory: dict | None = None,
    examples: list | None = None,
    model: str | None = None,
) -> dict:
    cfg = settings or CONFIG
    current = {
        key: record.get("value")
        for key, record in sorted(facts.items())
        if key in FACT_KEYS and isinstance(record, dict)
    }
    payload: dict[str, Any] = {"state": conversation_state, "facts": current, "text": user_text}
    if memory:
        payload["memory"] = {
            "goal": memory.get("goal"),
            "hard_constraint": memory.get("hard_constraint"),
            "concern": memory.get("concern"),
            "answered": memory.get("answered") or [],
            "blocker": memory.get("blocker"),
            "last_blocker": memory.get("last_blocker"),
            "follow_up": memory.get("follow_up") or "assistant",
        }
    if examples:
        payload["examples"] = examples[:2]
    user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "model": model or cfg.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "think": False,
        "keep_alive": cfg.keep_alive,
        "options": {
            "temperature": 0,
            "num_predict": cfg.output,
            "num_ctx": cfg.context,
            "num_thread": cfg.threads,
            **({"num_gpu": cfg.num_gpu} if cfg.num_gpu >= 0 else {}),
        },
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
    return {
        "profile": "portable_cpu",
        "threads": CONFIG.threads,
        "context": CONFIG.context,
        "max_output": CONFIG.output,
        "max_inflight": CONFIG.parallel,
        "active": _gate.active,
        "waiting": _gate.pending - _gate.active,
        "max_waiting": CONFIG.max_waiting,
        "router": router.mode(),
        "qwen_model": MODEL,
        "gemma_model": GEMMA_MODEL,
        "gemma_ready": gemma_ready,
        "last_route": last_route,
        "installed": sorted(_installed),
    }


async def refresh_installed() -> set[str]:
    global _installed, gemma_ready
    try:
        response = await client().get(f"{OLLAMA}/api/tags")
        response.raise_for_status()
        names = {item.get("name") for item in (response.json().get("models") or []) if item.get("name")}
        _installed = {name for name in names if isinstance(name, str)}
    except (httpx.HTTPError, ValueError, TypeError):
        _installed = set(_installed)
    gemma_ready = GEMMA_MODEL in _installed or any(name.startswith("gemma4:e2b") for name in _installed)
    return _installed


async def _infer(
    model: str,
    family: str,
    user_text: str,
    facts: dict,
    conversation_state: str,
    memory: dict | None,
    examples: list | None,
    queue_ms: float,
) -> dict[str, Any]:
    global last_error, ready
    started = perf_counter()
    response = await client().post(
        f"{OLLAMA}/api/chat",
        json=request_payload(
            user_text, facts, conversation_state, memory=memory, examples=examples, model=model
        ),
    )
    response.raise_for_status()
    body = response.json()
    if body.get("done_reason") == "length":
        raise ValueError("model output truncated; increase QWEN_NUM_PREDICT")
    parsed = parse_content(body.get("message", {}).get("content", ""))
    result = parsed.model_dump()
    for fact in result["facts"]:
        fact["status"] = "user_stated"
    timing = {"queue_ms": round(queue_ms, 2), "request_ms": round((perf_counter() - started) * 1000, 2)}
    for key in ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration"):
        value = body.get(key)
        if isinstance(value, (int, float)):
            timing[key.replace("_duration", "_ms")] = round(value / 1_000_000, 2)
    for key in ("prompt_eval_count", "eval_count"):
        if isinstance(body.get(key), int):
            timing[key] = body[key]
    result.update(_source=family, _model=model, _timing=timing)
    last_error = None
    ready = True
    log.info("%s timing %s", family, timing)
    return result


async def propose(
    user_text: str,
    facts: dict,
    conversation_state: str,
    memory: dict | None = None,
    examples: list | None = None,
    intent: str | None = None,
    repair: str | None = None,
) -> dict[str, Any]:
    global last_error, ready, last_route
    choice = router.pick(user_text, intent, repair, memory, gemma_ready=gemma_ready)
    last_route = choice
    async with _gate.enter() as queue_ms:
        try:
            return await _infer(
                choice["model"], choice["family"], user_text, facts, conversation_state, memory, examples, queue_ms
            )
        except (httpx.HTTPError, ValidationError, ValueError, TypeError, AttributeError) as first:
            if choice["family"] == "gemma" and router.mode() != "gemma":
                try:
                    result = await _infer(
                        MODEL, "qwen", user_text, facts, conversation_state, memory, examples, queue_ms
                    )
                    last_route = {"model": MODEL, "family": "qwen", "reason": "gemma_failover_qwen"}
                    return result
                except (httpx.HTTPError, ValidationError, ValueError, TypeError, AttributeError):
                    pass
            last_error = "qwen_timeout" if isinstance(first, httpx.TimeoutException) else "qwen_request_or_schema_failed"
            ready = False
            log.warning("local inference failed (transport, timeout, or invalid output)")
            return {}


async def warmup() -> None:
    global ready, last_error, gemma_ready
    await refresh_installed()
    if router.mode() == "gemma":
        result = await propose("I need dispatch", {}, "understand_request", intent="dispatch_inquiry")
        if result and last_route.get("family") == "gemma":
            log.info("gemma ready: %s; cpu threads=%s", GEMMA_MODEL, CONFIG.threads)
        else:
            log.warning("gemma warmup failed: %s", last_error)
        return
    result = await propose("I need dispatch", {}, "understand_request", intent="dispatch_inquiry")
    if result:
        log.info("primary ready: %s; cpu threads=%s", MODEL, CONFIG.threads)
    else:
        log.warning("primary warmup failed: %s", last_error)
        return
    if not gemma_ready:
        return
    qwen_ready, qwen_error = ready, last_error
    gemma = await propose("I don't want to sign for nothing", {}, "understand_request", intent="commit")
    if gemma and last_route.get("family") == "gemma":
        log.info("gemma warmup ok: %s", GEMMA_MODEL)
        return
    ready, last_error = qwen_ready, qwen_error
    gemma_ready = False
    log.warning("gemma warmup failed; routing stays on %s", MODEL)
