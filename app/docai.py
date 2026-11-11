"""Gemini document-review adapter. Interprets pages; never approves or looks up FMCSA."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx

from app import gemini
from app.docschema import FIELD_BLANK, FIELD_NOT_LOCATED, FIELD_PRESENT, FIELD_UNREADABLE, OUTCOMES

log = logging.getLogger("ayyan.docai")

SYSTEM = """You review carrier onboarding documents. JSON only.
Never approve, never invent fees, never claim insurance or authority is currently active.
If a critical field cannot be read, status=unreadable and value=null. Do not guess digits.
If the field region is visible and empty, status=blank.
If you cannot find the field, status=not_located.
Do not treat another customer's name, insurer, address, or layout as the required answer.
Classify each page group separately. Link a COI to its ACORD 101 / remarks pages.
Equipment photos are not documents; do not fail them for missing OCR text.
"""

PROMPT = """Inquiry arrangement: {arrangement}
Approved legal carrier for holder checks (may be empty): {legal_carrier}
Filename: {filename}
Suggested type: {suggested}

Page text (may be incomplete). Use images when provided.
{page_text}

Return JSON:
{{
  "documents": [
    {{
      "document_type": "coi|licence|registration|authority|w9|notice_of_assignment|voided_check|equipment_photos|setup|ein|lease|other",
      "pages": [1],
      "quality": "readable|degraded|unreadable",
      "fields": {{
        "certificate_holder": {{"value": null, "status": "blank", "page": 1, "evidence": ""}},
        "named_insured": {{"value": "", "status": "present", "page": 1, "evidence": ""}},
        "auto_limit": {{"value": 1000000, "status": "present", "page": 1, "evidence": ""}},
        "cargo_limit": {{"value": 100000, "status": "present", "page": 3, "evidence": ""}},
        "vin": {{"value": null, "status": "unreadable", "page": 1, "evidence": ""}},
        "usdot": {{"value": "", "status": "present", "page": 1, "evidence": ""}},
        "mc_number": {{"value": "", "status": "present", "page": 1, "evidence": ""}},
        "legal_name": {{"value": "", "status": "present", "page": 1, "evidence": ""}}
      }}
    }}
  ],
  "notes": ""
}}
"""


def enabled() -> bool:
    if (os.getenv("DOC_REVIEW_GEMINI") or "on").strip().lower() in {"off", "0", "none"}:
        return False
    return gemini.is_configured()


def doc_model() -> str:
    return (
        os.getenv("GEMINI_DOC_MODEL")
        or os.getenv("GEMINI_CHAT_MODEL")
        or os.getenv("GEMINI_MODEL")
        or "gemini-3.5-flash"
    ).strip()


def _mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".pdf":
        return "application/pdf"
    return "image/jpeg"


def _parse(content: str) -> dict:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        content = content[start : end + 1]
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _clean_field(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or FIELD_NOT_LOCATED).lower()
    if status not in OUTCOMES:
        status = FIELD_NOT_LOCATED
    value = raw.get("value")
    if status != FIELD_PRESENT:
        value = None
    page = raw.get("page")
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    return {
        "value": value,
        "status": status,
        "page": page,
        "evidence": str(raw.get("evidence") or "")[:240],
        "source": "gemini",
        "confidence": "uncalibrated",
    }


def normalize(payload: dict | None) -> dict:
    payload = payload or {}
    documents = []
    for item in payload.get("documents") or []:
        if not isinstance(item, dict):
            continue
        fields = {}
        for key, raw in (item.get("fields") or {}).items():
            cleaned = _clean_field(raw)
            if cleaned:
                fields[str(key)] = cleaned
        pages = []
        for num in item.get("pages") or []:
            try:
                pages.append(int(num))
            except (TypeError, ValueError):
                continue
        documents.append(
            {
                "document_type": str(item.get("document_type") or "other").lower(),
                "pages": pages or [1],
                "quality": str(item.get("quality") or "readable").lower(),
                "fields": fields,
            }
        )
    return {"documents": documents, "notes": str(payload.get("notes") or "")[:400], "source": "gemini"}


def review_visual(
    pages: list[dict],
    *,
    filename: str = "",
    suggested: str | None = None,
    arrangement: str | None = None,
    legal_carrier: str | None = None,
    images: list[Path] | None = None,
    timeout: float = 45.0,
) -> dict | None:
    """Structured Gemini pass. Caller applies rules; this only proposes fields and types."""
    if not enabled():
        return None
    key = gemini.api_key()
    if not key:
        return None
    snippets = []
    for row in pages[:24]:
        text = (row.get("text") or "").strip()
        snippets.append(f"--- page {row.get('page')} ({row.get('method')}) ---\n{text[:2500]}")
    prompt = PROMPT.format(
        arrangement=arrangement or "unknown",
        legal_carrier=legal_carrier or "(not recorded)",
        filename=filename or "",
        suggested=suggested or "unknown",
        page_text="\n".join(snippets) or "(no extracted text)",
    )
    parts: list[dict] = [{"text": prompt}]
    for image in (images or [])[:8]:
        path = Path(image)
        if not path.exists() or path.stat().st_size > 4_000_000:
            continue
        import base64

        parts.append(
            {
                "inline_data": {
                    "mime_type": _mime(path),
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            }
        )
    url = f"{gemini.BASE_URL}/models/{doc_model()}:generateContent?key={key}"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0,
            "maxOutputTokens": int(os.getenv("GEMINI_DOC_MAX_OUTPUT", "4096")),
        },
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        log.warning("document Gemini review failed: %s", type(exc).__name__)
        return None
    candidates = payload.get("candidates") or []
    content = ""
    for part in (candidates[0].get("content") or {}).get("parts") or [] if candidates else []:
        if "text" in part:
            content += part["text"]
    try:
        return normalize(_parse(content))
    except (json.JSONDecodeError, ValueError, TypeError):
        log.warning("document Gemini review returned invalid JSON")
        return None


def merge_fields(base: dict, proposed: dict | None) -> dict:
    """Prefer unreadable over a guessed value. Keep a heuristic blank when the region was seen empty."""
    if not proposed:
        return base
    merged = dict(base)
    for name, incoming in proposed.items():
        current = merged.get(name) or {}
        incoming_status = incoming.get("status")
        current_status = current.get("status")
        if incoming_status == FIELD_UNREADABLE:
            merged[name] = {**incoming, "raw_value": None}
            continue
        if current_status == FIELD_BLANK and incoming_status == FIELD_PRESENT:
            # Visible empty box beats a possible hallucination.
            continue
        if current_status in {None, FIELD_NOT_LOCATED} and incoming_status in {
            FIELD_PRESENT,
            FIELD_BLANK,
            FIELD_UNREADABLE,
        }:
            merged[name] = incoming
            continue
        if current_status == FIELD_PRESENT and incoming_status == FIELD_PRESENT and not current.get("value"):
            merged[name] = incoming
    return merged
