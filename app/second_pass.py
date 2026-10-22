"""Selective second pass on hard turns only. Not a live multi-agent debate."""

from __future__ import annotations

import re

from app import db, fees
from app.knowledge import lookup

HARD_INTENTS = {"guarantee", "freight", "trust"}
MONEY = re.compile(r"\$\s*\d+", re.I)
CLAIM = re.compile(
    r"we guarantee|guaranteed \$?\d|you are approved|you're approved|insurance is approved|coi is valid",
    re.I,
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def leaks(text: str) -> bool:
    if MONEY.search(text or "") or CLAIM.search(text or ""):
        return True
    allowed = fees.approved_percents()
    for match in PERCENT.finditer(text or ""):
        token = match.group(1)
        if token in allowed or (token.endswith(".0") and token[:-2] in allowed):
            continue
        return True
    return False


def is_hard(proposal: dict, hybrid: bool, leaked: bool, source: str) -> str | None:
    if leaked:
        return "leak_scan"
    if hybrid:
        return "hybrid_retrieval"
    if proposal.get("intent") in HARD_INTENTS:
        return "high_risk_intent"
    return None


def repair(text: str) -> str:
    if leaks(text):
        return lookup("unknown")
    allowed = fees.approved_percents()
    if "6%" in (text or "") and "6" not in allowed:
        return lookup("unknown")
    return text


def log(session_id: str, user_text: str, reply: str, reason: str, source: str):
    params = (session_id, user_text, reply, reason, source, db.now())
    try:
        db.execute(
            """INSERT INTO hard_turns (session_id, user_text, reply, reason, source, reviewed, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            params,
        )
    except Exception:
        db.execute(
            """INSERT INTO hard_turns (session_id, user_text, reply, reason, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            params,
        )


def count() -> int:
    row = db.execute("SELECT COUNT(*) AS n FROM hard_turns", fetch="one")
    return int(row["n"]) if row else 0


def reviewed_count() -> int:
    row = db.execute("SELECT COUNT(*) AS n FROM hard_turns WHERE reviewed = 1", fetch="one")
    return int(row["n"]) if row else 0
