"""Pick one local model per turn. Rules still execute; neither model quotes fees."""

from __future__ import annotations

import os
import re

QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.5:0.8b")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma4:e2b")

# Gemma 4 E2B is stronger at instruction-following and strategy; Qwen 3.5 2b is calibrated for our JSON extract.
GEMMA_INTENTS = {
    "fee",
    "guarantee",
    "commit",
    "human",
    "decline",
    "existing_customer",
    "trust",
}
GEMMA_REPAIRS = {
    "authority_uncertain",
    "topic_fee",
    "leave_sales",
    "repetition_unverified",
    "email_delivery",
}
GEMMA_CONCERNS = {
    "commitment",
    "pause",
    "net_after_costs",
    "total_fees",
    "email_delivery",
}
GEMMA_TEXT = re.compile(
    r"sign for nothing|too much|no thank you|next week|busy this week|what do you charge|"
    r"guarantee|worth it|mailbox|send again|need to get paid|i meant the fee|authority is ready",
    re.I,
)


def mode() -> str:
    value = (os.getenv("MODEL_ROUTER") or "auto").strip().lower()
    if value not in {"auto", "qwen", "gemma"}:
        return "auto"
    return value


def pick(
    user_text: str,
    intent: str | None = None,
    repair: str | None = None,
    memory: dict | None = None,
    gemma_ready: bool = True,
) -> dict:
    """Return {model, family, reason}. One inference; failover is the caller's job."""
    forced = mode()
    if forced == "qwen" or not gemma_ready:
        return {"model": QWEN_MODEL, "family": "qwen", "reason": "forced_qwen" if forced == "qwen" else "gemma_unavailable"}
    if forced == "gemma":
        return {"model": GEMMA_MODEL, "family": "gemma", "reason": "forced_gemma"}
    concern = (memory or {}).get("concern")
    if repair in GEMMA_REPAIRS or intent in GEMMA_INTENTS or concern in GEMMA_CONCERNS or GEMMA_TEXT.search(user_text or ""):
        return {"model": GEMMA_MODEL, "family": "gemma", "reason": repair or intent or concern or "objection_or_strategy"}
    return {"model": QWEN_MODEL, "family": "qwen", "reason": "qualify_extract"}
