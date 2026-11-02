"""Persistent inquiry work, independent of media connections and case approval.

This module records callback *requests*. It does not assign appointments, verify
phone ownership, dial, or claim that a voice runtime exists.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import db
from app.tasks import fact_value

CALLBACK_FIELDS = ("phone", "callbackTime", "callbackTimezone", "callbackDate")
CANCEL_CALLBACK = re.compile(
    r"\bcancel (?:my |the )?(?:callback|call)\b|\b(?:do not call|don't call|stop calling)(?: me)?\s*[.!]?\s*$", re.I
)
QUESTIONS = {
    "phone": "What number should the manager call? Please include the + country code.",
    "callbackTime": "What local time would you prefer for the callback?",
    "callbackTimezone": "Which timezone should the manager use for that time?",
    "callbackDate": "Which date would you prefer for the callback? You can use YYYY-MM-DD.",
}


def cancellation_requested(text: str) -> bool:
    if re.search(r"\b(?:do not|don't|never|not to) cancel\b", text, re.I):
        return False
    return bool(CANCEL_CALLBACK.search(text))


def callback_facts(text: str, pending: dict | None = None) -> list[dict]:
    """Parse contact answers only inside a requested callback, never vehicle numbers."""
    values = {}
    match = re.search(r"(?<!\w)\+[1-9][\d ().-]{6,}\d", text)
    if match:
        values["phone"] = match[0].strip()
    match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", text, re.I)
    if not match:
        match = re.search(r"\b((?:[01]\d|2[0-3]):[0-5]\d)\b", text)
    if match:
        values["callbackTime"] = match[1].strip().lower()
    match = re.search(r"\b([A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b", text)
    if match and _zone(match[1]):
        values["callbackTimezone"] = match[1]
    aliases = {"chicago": "America/Chicago", "new york": "America/New_York",
               "los angeles": "America/Los_Angeles", "denver": "America/Denver", "utc": "UTC"}
    for label, zone in aliases.items():
        if re.fullmatch(re.escape(label) + r"(?: time)?[.!]?", text.strip(), re.I):
            values["callbackTimezone"] = zone
    zone = _zone(values.get("callbackTimezone") or ((pending or {}).get("data") or {}).get("timezone"))
    preferred = _date(text, zone)
    if preferred:
        values["callbackDate"] = preferred
    elif match := re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
        values["callbackDate"] = match[0]  # Preserve invalid input for clarification, not approval.
    return [{"key": key, "value": value, "status": "user_stated"} for key, value in values.items()]


def _zone(value):
    if not value:
        return None
    try:
        return ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError):
        match = re.fullmatch(r"(?:UTC|GMT)\s*([+-])(\d{1,2})(?::?(\d{2}))?", str(value), re.I)
        if not match:
            return None
        hours, minutes = int(match[2]), int(match[3] or 0)
        if hours > 14 or minutes > 59 or (hours == 14 and minutes):
            return None
        offset = timedelta(hours=hours, minutes=minutes)
        return timezone(offset if match[1] == "+" else -offset)


def _date(text: str, zone, today: date | None = None) -> str | None:
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if match:
        try:
            return date.fromisoformat(match[0]).isoformat()
        except ValueError:
            return None
    # Relative dates require a known local timezone, never the server's date.
    if zone and re.search(r"\btoday\b|\btomorrow\b", text, re.I):
        local_date = today or datetime.now(zone).date()
        return (local_date + timedelta(days=int(bool(re.search(r"\btomorrow\b", text, re.I))))).isoformat()
    return None


def next_callback_field(data: dict) -> str | None:
    phone = str(data.get("phone_raw") or "")
    candidate = re.sub(r"[\s().-]", "", phone)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", candidate):
        return "phone"
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(data.get("local_time") or "")):
        return "callbackTime"
    if not _zone(data.get("timezone")):
        return "callbackTimezone"
    try:
        preferred = date.fromisoformat(data.get("local_date") or "")
    except ValueError:
        return "callbackDate"
    if preferred < datetime.now(_zone(data["timezone"])).date():
        return "callbackDate"
    return None


def callback_pending(session: dict) -> dict | None:
    row = db.get_workflow(session["id"], "callback")
    return row if row and row["status"] == "collecting" else None


def callback_context(session: dict) -> dict | None:
    row = db.get_workflow(session["id"], "callback")
    return row if row and row["status"] in {"collecting", "requested"} else None


def resumes_callback(session: dict, proposal: dict, text: str) -> bool:
    current = callback_context(session)
    if not current or session.get("manager_accepted"):
        return False
    # Service questions, readiness and human requests interrupt collection normally.
    if proposal.get("intent") not in {"general", "call_me", "unknown_detail"}:
        return False
    return current["status"] == "collecting" or any(item.get("key") in CALLBACK_FIELDS for item in proposal.get("facts") or [])


def update_callback(session: dict, text: str) -> dict:
    old = db.get_workflow(session["id"], "callback")
    data = dict((old or {}).get("data") or {})
    # A new explicit request after cancellation starts fresh, without old dates.
    if old and old["status"] == "cancelled":
        data = {}
    facts = session.get("facts") or {}
    for source, target in (("phone", "phone_raw"), ("callbackTimezone", "timezone"), ("callbackDate", "local_date")):
        if source == "callbackDate" and old and old["status"] == "cancelled":
            continue
        value = fact_value(facts, source)
        if value:
            data[target] = str(value)
    value = str(fact_value(facts, "callbackTime") or "").strip().lower()
    if value:
        data.pop("local_time", None)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
    if match:
        hour, minute, suffix = int(match[1]), int(match[2] or 0), match[3]
        if (suffix and 1 <= hour <= 12 or not suffix and ":" in value and 0 <= hour <= 23) and minute <= 59:
            hour = hour % 12 + (12 if suffix == "pm" else 0) if suffix else hour
            data["local_time"] = f"{hour:02}:{minute:02}"
    preferred = _date(text, _zone(data.get("timezone")))
    if preferred:
        data["local_date"] = preferred
    candidate = re.sub(r"[\s().-]", "", data.get("phone_raw") or "")
    data["phone_e164_candidate"] = candidate if re.fullmatch(r"\+[1-9]\d{7,14}", candidate) else None
    data["phone_validation"] = "format_only" if data["phone_e164_candidate"] else "country_or_format_needed"
    missing = next_callback_field(data)
    status = "collecting" if missing else "requested"
    if old and old["status"] == status and old["data"] == data:
        return old
    return db.save_workflow(session["id"], "callback", status, data, (old or {}).get("version", 0))


def cancel_callback(session: dict) -> dict | None:
    old = db.get_workflow(session["id"], "callback")
    if not old or old["status"] == "cancelled":
        return old
    return db.save_workflow(session["id"], "callback", "cancelled", old["data"], old["version"])


def public_state(session: dict) -> dict:
    """Client-safe progress; full contact data remains in the internal record."""
    callback = db.get_workflow(session["id"], "callback")
    voice = db.get_workflow(session["id"], "browser_voice")
    result = {}
    if callback:
        data = callback["data"]
        result["callback"] = {
            "id": callback["id"], "status": callback["status"], "version": callback["version"],
            "next_field": next_callback_field(data) if callback["status"] == "collecting" else None,
            "phone_last4": re.sub(r"\D", "", data.get("phone_raw") or "")[-4:] or None,
            "phone_validation": data.get("phone_validation"),
            "local_date": data.get("local_date"), "local_time": data.get("local_time"),
            "timezone": data.get("timezone"),
        }
    if voice:
        result["browser_voice"] = {"id": voice["id"], "status": voice["status"], "connected": False}
    return result
