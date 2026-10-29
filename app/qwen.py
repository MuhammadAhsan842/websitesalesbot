"""One bounded local model invocation per accepted turn. The model cannot execute."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import base64
import json
import logging
import os
from pathlib import Path
import re
import threading
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Load .env before router/settings so QWEN_MODEL and timeouts stick even if
# another module has not imported dotenv yet.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from app import router
from app.cpu import default_threads
from app.schema import ANSWER_TOPICS, CATALOGUE, FACT_KEYS, INTENTS, MOVES, VARIANTS

log = logging.getLogger("ayyan.qwen")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    model: str = "qwen3.5:0.8b"
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
            model=os.getenv("QWEN_MODEL", "qwen3.5:0.8b"),
            url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            threads=_integer("QWEN_NUM_THREAD", default_threads(), 1, 1024),
            context=_integer("QWEN_NUM_CTX", 2048, 1024, 131072),
            output=_integer("QWEN_NUM_PREDICT", 384, 64, 2048),
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
vision_ready = False
last_error: str | None = None
last_route: dict = {"model": MODEL, "family": "qwen", "reason": "default"}
_installed: set[str] = set()
_look_lock = threading.Lock()
VISION_MODEL = os.getenv("QWEN_VISION_MODEL", MODEL)
LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["equipment_photo", "screenshot", "document", "unknown"]},
        "description": {"type": "string"},
        "visible_text": {"type": "string"},
        "proposed_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


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
    evidence: str | None = Field(default=None, max_length=80)

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
    answer_topics: list[str] = Field(default_factory=list, max_length=4)
    next_question_id: str | None = Field(default=None, json_schema_extra={"enum": [*dict.fromkeys(FACT_KEYS), None]})
    wording: str | None = Field(default=None, max_length=480)

    @field_validator(
        "intent",
        "next_field",
        "next_question_id",
        "arrangement",
        "action",
        "task",
        "conversation_move",
        "reply_variant_id",
    )
    @classmethod
    def allowed_value(cls, value: str | None, info):
        allowed = {
            "intent": INTENTS,
            "next_field": [*FACT_KEYS, None],
            "next_question_id": [*FACT_KEYS, None],
            "arrangement": ["dispatch_service", "lease_on", "needs_clarification", None],
            "action": ["none", "create_case", "callback", "talk_here", "takeover"],
            "task": [*CATALOGUE, None],
            "conversation_move": [*MOVES, None],
            "reply_variant_id": [*VARIANTS, None],
        }
        if value not in allowed[info.field_name]:
            raise ValueError(f"invalid {info.field_name}")
        return value

    @field_validator("answer_topics")
    @classmethod
    def known_topics(cls, value: list[str]) -> list[str]:
        return [topic for topic in value if topic in ANSWER_TOPICS][:6]


OUTPUT_SCHEMA = Proposal.model_json_schema()
_ACTIONS = {"none", "create_case", "callback", "talk_here", "takeover"}
_ARRANGEMENTS = {"dispatch_service", "lease_on", "needs_clarification"}


def _sanitize(raw: dict) -> dict:
    """Keep a 2b miss from discarding the whole turn. Graph still vetoes actions."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    facts = []
    for item in raw.get("facts_patch") or raw.get("facts") or []:
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
        evidence = item.get("evidence") if isinstance(item.get("evidence"), str) else None
        facts.append(
            {
                "key": key,
                "value": True if key == "_unknown" and value is None else value,
                "evidence": (evidence.strip()[:80] if evidence else None),
            }
        )
    next_question = raw.get("next_question_id") if raw.get("next_question_id") in FACT_KEYS else None
    next_field = next_question or (raw.get("next_field") if raw.get("next_field") in FACT_KEYS else None)
    action = raw.get("action") or raw.get("proposed_action")
    action = action if action in _ACTIONS else "none"
    wording = raw.get("reply") if isinstance(raw.get("reply"), str) else raw.get("wording")
    wording = wording if isinstance(wording, str) else None
    if wording:
        wording = wording.strip()[:480]
        from app.plan import OPERATIONAL_CLAIM

        # Drop operational falsehoods. Approved fee percents may appear when explaining live quotes.
        if re.search(
            r"zoho|loads tomorrow|emailed|booked|packet sent|"
            r"documents were received|case was assigned|i will check|i'?m checking|i am checking|"
            r"update you shortly|you're approved|insurance is approved",
            wording,
            re.I,
        ) or OPERATIONAL_CLAIM.search(wording):
            wording = None
        elif re.search(r"\d+\s*%", wording) and not re.search(r"\bfee\b|dispatch|charge|quote", wording, re.I):
            wording = None
    topics = [topic for topic in raw.get("answer_topics") or [] if topic in ANSWER_TOPICS][:4]
    return {
        "intent": raw.get("intent") if raw.get("intent") in INTENTS else "general",
        "facts": facts,
        "knowledge_keys": [k for k in raw.get("knowledge_keys") or [] if isinstance(k, str)][:32],
        "blocked": [b for b in raw.get("blocked") or [] if isinstance(b, str)][:16],
        "next_field": next_field,
        "next_question_id": next_field,
        "answer_topics": topics,
        "arrangement": raw.get("arrangement") if raw.get("arrangement") in _ARRANGEMENTS else None,
        "action": action or "none",
        "task": raw.get("task") if raw.get("task") in CATALOGUE else None,
        "conversation_move": raw.get("conversation_move") if raw.get("conversation_move") in MOVES else None,
        "reply_variant_id": None,
        "wording": wording,
    }


def parse_content(content: str) -> Proposal:
    return Proposal.model_validate(_sanitize(json.loads(content or "{}")))


SYSTEM = """Ayyan Group AI sales assistant. Human, warm, clear — like a sharp ops person, not a script bot. JSON only. /no_think
You write the COMPLETE customer reply in "wording" (also accept "reply"). Code validates; it will not append sales paragraphs when wording is valid.
Output: {"intent":"...","facts":[{"key":"...","value":"...","evidence":"..."}],"answer_topics":[],"conversation_move":"qualify","next_question_id":"mcOwnership","action":"none","wording":"Will you run under your own MC, or are you looking to lease on?"}
Rules:
- facts = new/corrected only, with evidence from this message. Keep every explicit fact already on file.
- Never invent equipment, length, city, phone, or insurance in wording. "Got it" only when that fact is already on file or newly evidenced in this message.
- Answer the driver's concern first, then at most one useful next question. Never re-ask known fields. Never append a second question onto a polluted draft — replace it.
- Sound human: acknowledge briefly, stay helpful under pressure, no paragraph dumps, no forced close.
- Show you understood: use what they just said and advance — never re-ask a known slot or jump to truck type after an insurance/owner concern.
- Out-of-scope equipment: refuse clearly and set action none — never create_case / setup packet for that vehicle.
- Success = accurate progress (clear no, honest blocker, respected pause, clarified concern) — not pushing every driver to sign.
- next_question_id is the question inside wording, or null. conversation_move: acknowledge|answer|clarify|qualify|explain_objection|offer_handoff|pause.
- Use approved_info for fees/docs/support. Never invent percents, paydays, load offers, emails, or approvals.
- Equipment catalog only: box 24/26/28 ft; hotshot 30/40 ft; dry van/reefer/flatbed/step deck 48/53 ft; power only. Any other type or non-catalog length => out of scope; stop qualifying that vehicle. Sprinter/cargo van => don't dispatch. If they also name a supported truck, switch to it without replaying the greeting.
- Never overwrite a stated truck/length with a different catalog item. Never invent binder/strap/lift-gate details unless they ask or that equipment needs them.
- Operating mode is OTR or local only — never offer regional. Local → miles/day → Monday–Friday availability → city/ZIP (one at a time). OTR → how long they can stay out.
- After they confirm insurance, ask coverage types (auto / cargo / both) before lanes. If they need insurance, do not demand an existing COI — route insurance review to onboarding.
- Fee answers: when arrangement is known, quote the approved schedule or say the manager must confirm — never pretend arrangement is unknown. Negotiation → onboarding manager review (not "best-fitting price").
- "Talk to onboarding manager" / human → request handoff; do not claim a manager is already on the chat until staff accepts.
- Callback answers (number, time, timezone) must not change equipment or length. Keep starting city separate from timezone city.
- Stated insurance ≠ verified. Upload saved ≠ approved. Ready to start ≠ cleared to dispatch. Temporary tag needs human review.
- Fuel advance needed before pickup is a real blocker — don't swap it for quick-pay-after-delivery or invent a program.
- Short answers ("26 ft", "si", "yes") answer last_question_id only. "Si" after a pause is not insurance active.
- Examples are behaviour strategy only — never copy another driver's truck, city, fee, name, or promise.
- Need to get paid / payme => existing_customer. Mailbox full => acknowledge. Own MC => mcOwnership own_mc.
- Keep wording to a few short natural sentences. Include the follow-up question in wording when move is qualify.
- Expired need ("not anymore" / "that was for last…"): acknowledge and close — no load promises, no MC/insurance probing.
- Already hired a dispatcher: acknowledge and stop unless they say they're unhappy or want to switch.
- Privacy / "that's private": apologize briefly, stop probing, never attach an earnings pitch after an apology.
- Never invent weekly gross, consistent freight, or match a customer-reported competitor fee. Strip formatting debris (e.g. "7)Hey!") from wording.
- A sale is not required for success — respectful closure is a valid outcome."""


def request_payload(
    user_text: str,
    facts: dict,
    conversation_state: str,
    settings: Settings | None = None,
    memory: dict | None = None,
    examples: list | None = None,
    model: str | None = None,
    recent: list | None = None,
    approved: list | None = None,
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
        payload["approved_info"] = approved[:8]
    if examples:
        from app.examples import prompt_examples

        payload["examples"] = prompt_examples(examples)
    if recent:
        payload["recent"] = [
            {"role": row.get("role"), "text": (row.get("text") or "")[:220]}
            for row in recent[:6]
        ]
    user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "model": model or cfg.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "think": False,
        "keep_alive": cfg.keep_alive,
        "options": {
            "temperature": 0.2,
            "num_predict": cfg.output,
            # Respect QWEN_NUM_CTX — forcing 3072+ on CPU RAM thrashing made browser turns 60–120s.
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
        "vision_ready": vision_ready,
        "vision_model": VISION_MODEL,
        "vision_enabled": vision_enabled(),
        "last_route": last_route,
        "installed": sorted(_installed),
    }


def vision_enabled() -> bool:
    return os.getenv("QWEN_VISION", "off").strip().lower() not in {"off", "none", "0", ""} and vision_ready


def _sanitize_look(raw: dict) -> dict:
    description = raw.get("description") if isinstance(raw.get("description"), str) else ""
    if re.search(r"approved|eligible|valid insurance|emailed|booked|\d+\s*%", description, re.I):
        description = re.sub(r"approved|eligible|valid insurance|emailed|booked", "unverified", description, flags=re.I)
    facts = []
    for item in raw.get("proposed_facts") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key not in FACT_KEYS:
            continue
        value = item.get("value")
        if value in (None, "", "null"):
            continue
        facts.append({"key": key, "value": str(value)[:80], "evidence": str(item.get("evidence") or "")[:80]})
    kind = raw.get("kind") if raw.get("kind") in {"equipment_photo", "screenshot", "document", "unknown"} else "unknown"
    return {
        "kind": kind,
        "description": description.strip()[:240],
        "visible_text": str(raw.get("visible_text") or "")[:400],
        "proposed_facts": facts[:6],
        "unverified": True,
    }


def look(path: str, kind: str = "photo") -> dict:
    """Background vision only. Never the live chat turn. Does not approve documents."""
    global vision_ready
    if not vision_enabled():
        return {}
    image = Path(path)
    if not image.exists():
        return {}
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Describe the image for a dispatch fit check. JSON only. Never approve, quote fees, or claim a document is valid.",
            },
            {
                "role": "user",
                "content": f"Kind hint: {kind}. What equipment or document is visible? Proposed facts must quote visible text.",
                "images": [base64.b64encode(image.read_bytes()).decode("ascii")],
            },
        ],
        "stream": False,
        "format": LOOK_SCHEMA,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_predict": 160, "num_ctx": 2048, "num_thread": CONFIG.threads},
    }
    with _look_lock:
        try:
            response = httpx.post(f"{OLLAMA}/api/chat", json=payload, timeout=60.0)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content") or "{}"
            return _sanitize_look(json.loads(content))
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
            vision_ready = False
            return {}


async def refresh_installed() -> set[str]:
    global _installed, gemma_ready, vision_ready
    try:
        response = await client().get(f"{OLLAMA}/api/tags")
        response.raise_for_status()
        names = {item.get("name") for item in (response.json().get("models") or []) if item.get("name")}
        _installed = {name for name in names if isinstance(name, str)}
    except (httpx.HTTPError, ValueError, TypeError):
        _installed = set(_installed)
    gemma_ready = GEMMA_MODEL in _installed or any(name.startswith("gemma4:e2b") for name in _installed)
    vision_ready = False
    target = VISION_MODEL if VISION_MODEL in _installed or any(name.startswith(str(VISION_MODEL).split(":")[0]) for name in _installed) else None
    if target:
        try:
            shown = await client().post(f"{OLLAMA}/api/show", json={"name": VISION_MODEL})
            shown.raise_for_status()
            blob = json.dumps(shown.json()).lower()
            vision_ready = "vision" in blob or "projector" in blob or "clip" in blob
        except (httpx.HTTPError, ValueError, TypeError):
            vision_ready = False
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
    recent: list | None = None,
    approved: list | None = None,
) -> dict[str, Any]:
    global last_error, ready
    started = perf_counter()
    response = await client().post(
        f"{OLLAMA}/api/chat",
        json=request_payload(
            user_text,
            facts,
            conversation_state,
            memory=memory,
            examples=examples,
            model=model,
            recent=recent,
            approved=approved,
        ),
    )
    response.raise_for_status()
    body = response.json()
    if body.get("done_reason") == "length":
        raise ValueError("model output truncated; increase QWEN_NUM_PREDICT")
    message = body.get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        # Qwen 3.5 may put JSON in thinking when think mode slips through.
        thinking = (message.get("thinking") or "").strip()
        if thinking.startswith("{") or '"intent"' in thinking:
            start = thinking.find("{")
            end = thinking.rfind("}")
            content = thinking[start : end + 1] if start >= 0 and end > start else thinking
    if not content:
        raise ValueError("model returned empty content")
    parsed = parse_content(content)
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
    recent: list | None = None,
    approved: list | None = None,
) -> dict[str, Any]:
    global last_error, ready, last_route
    choice = router.pick(user_text, intent, repair, memory, gemma_ready=gemma_ready)
    last_route = choice
    async with _gate.enter() as queue_ms:
        try:
            return await _infer(
                choice["model"],
                choice["family"],
                user_text,
                facts,
                conversation_state,
                memory,
                examples,
                queue_ms,
                recent,
                approved,
            )
        except (httpx.HTTPError, ValidationError, ValueError, TypeError, AttributeError) as first:
            # Always fall over to Qwen when Gemma is down — forced gemma with a dead host
            # was leaving every turn on rules_fallback (static canned replies).
            if choice["family"] == "gemma" and MODEL != choice["model"]:
                try:
                    result = await _infer(
                        MODEL,
                        "qwen",
                        user_text,
                        facts,
                        conversation_state,
                        memory,
                        examples,
                        queue_ms,
                        recent,
                        approved,
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
