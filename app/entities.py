"""Case-level entity resolution. Same / different / abstain. Never auto-merge."""

from __future__ import annotations

import re

from app import db

TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"llc", "inc", "co", "the", "of", "and", "corp"}
# Distinct roles on the same inquiry. Holder, insured, driver, and payee may differ.
ROLE_BUCKETS = {
    "insured": ("insured", "named_insured"),
    "carrier": ("carrier", "legal_name", "dispatcher"),
    "holder": ("holder", "certificate_holder"),
    "driver": ("driver", "licence_name"),
    "owner": ("owner", "owner_operator"),
    "payee": ("payee", "factor"),
}


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").lower().replace(",", " ").split())


def _tokens(value: str | None) -> set[str]:
    return {tok for tok in TOKEN.findall(_norm(value)) if tok not in STOP and len(tok) > 1}


def _jaccard(a: str | None, b: str | None) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _pair(left: dict, right: dict, kind: str) -> dict:
    score = _jaccard(left["value"], right["value"])
    entities = [left["value"], right["value"]]
    files = [left["file"], right["file"]]
    if _norm(left["value"]) == _norm(right["value"]) or score >= 0.99:
        return {
            "decision": "same",
            "entities": entities,
            "files": files,
            "score": round(score, 3),
            "reason": f"Exact {kind} match after normalize. Still not auto-merged.",
        }
    if left.get("field") and right.get("field") and left.get("field") != right.get("field"):
        return {
            "decision": "abstain",
            "entities": entities,
            "files": files,
            "score": round(score, 3),
            "reason": f"{left.get('field')} and {right.get('field')} are different roles. Different names can be legitimate.",
        }
    if score >= 0.4:
        return {
            "decision": "abstain",
            "entities": entities,
            "files": files,
            "score": round(score, 3),
            "reason": f"Similar {kind} strings (overlap {score:.2f}). Abstain until a person associates them.",
        }
    return {
        "decision": "different",
        "entities": entities,
        "files": files,
        "score": round(score, 3),
        "reason": f"{kind.capitalize()} strings do not match (overlap {score:.2f}).",
    }


def _unique(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = (_norm(row["value"]), row["file"], row.get("field"))
        if key in seen or not row.get("value"):
            continue
        seen.add(key)
        out.append(row)
    return out


def _extracted_value(raw):
    if isinstance(raw, dict):
        return raw.get("value") if raw.get("status") == "present" else None
    return raw


def resolve(case_id: str) -> dict:
    files = db.list_case_files(case_id)
    people = []
    companies = []
    vins = []
    for item in files:
        extracted = item.get("extracted") or {}
        fields = extracted.get("fields") if isinstance(extracted.get("fields"), dict) else extracted
        insured = _extracted_value(fields.get("insured") or fields.get("named_insured"))
        if insured:
            companies.append({"value": insured, "file": item["filename"], "field": "insured"})
        owner = _extracted_value(fields.get("owner"))
        if owner:
            people.append({"value": owner, "file": item["filename"], "field": "owner"})
        owner_op = _extracted_value(fields.get("owner_operator"))
        if owner_op and owner_op not in {"filled", "blank"}:
            people.append({"value": owner_op, "file": item["filename"], "field": "owner_operator"})
        for key in ("carrier", "dispatcher", "holder", "certificate_holder", "legal_name", "payee"):
            value = _extracted_value(fields.get(key))
            if value:
                role = "holder" if "holder" in key else "payee" if key == "payee" else "carrier"
                companies.append({"value": value, "file": item["filename"], "field": role})
        vin = _extracted_value(fields.get("vin"))
        if vin and vin not in {"blank", None}:
            vins.append({"value": vin, "file": item["filename"]})

    people = _unique(people)
    companies = _unique(companies)
    same, different, abstain = [], [], []

    def collect(rows: list[dict], kind: str):
        for i, left in enumerate(rows):
            for right in rows[i + 1 :]:
                if _norm(left["value"]) == _norm(right["value"]) and left["file"] == right["file"]:
                    continue
                verdict = _pair(left, right, kind)
                bucket = {"same": same, "different": different, "abstain": abstain}[verdict["decision"]]
                bucket.append(verdict)

    collect(people, "person")
    collect(companies, "company")

    distinct_vins = {row["value"] for row in vins}
    if len(distinct_vins) > 1:
        different.append(
            {
                "decision": "different",
                "entities": sorted(distinct_vins),
                "reason": "More than one VIN on the case. Do not bind a single truck.",
            }
        )
    elif any((item.get("extracted") or {}).get("vin") == "blank" for item in files) and vins:
        abstain.append(
            {
                "decision": "abstain",
                "entities": ["blank VIN", next(iter(distinct_vins))],
                "reason": "A file has a VIN and another does not. Abstain on equipment association.",
            }
        )

    if not files:
        abstain.append({"decision": "abstain", "entities": [], "reason": "No files on the case yet."})
    elif len(people) == 1:
        abstain.append(
            {
                "decision": "abstain",
                "entities": [people[0]["value"]],
                "reason": "A single name on file is not identity confirmation. Do not auto-merge.",
            }
        )
    elif not same and not different and not abstain:
        abstain.append({"decision": "abstain", "entities": [], "reason": "Nothing to associate yet. Abstain."})

    return {
        "same": same,
        "different": different,
        "abstain": abstain,
        "people": people,
        "companies": companies,
        "vins": vins,
        "auto_merged": False,
    }
