"""Chat model routing — Gemini only."""

from __future__ import annotations

import os


def mode() -> str:
    """Always gemini. MODEL_ROUTER is ignored for chat (kept only for ops visibility)."""
    return "gemini"


def pick(
    user_text: str,
    intent: str | None = None,
    repair: str | None = None,
    memory: dict | None = None,
    gemma_ready: bool = False,
) -> dict:
    """Return {model, family, reason}. Chat inference is Gemini only."""
    gemini_model = os.getenv("GEMINI_CHAT_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    return {"model": gemini_model, "family": "gemini", "reason": "gemini_only"}
