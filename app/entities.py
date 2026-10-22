"""Case-level entity resolution. Same / different / abstain. Never auto-merge."""

from __future__ import annotations

import re

from app import db

TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"llc", "inc", "co", "the", "of", "and", "corp"}
KNOWN_SPLIT = (
    ({"silver", "arrow"}, {"leo", "dispatch"}),
    ({"silver", "arrow"}, {"atl", "fast", "freight"}),
)


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
    left_tok, right_tok = _tokens(left["value"]), _tokens(right["value"])
    for first, second in KNOWN_SPLIT:
        if (first <= left_tok and second <= right_tok) or (second <= left_tok and first <= right_tok):
            return {
                "decision": "different",
                "entities": entities,
                "files": files,
                "score": round(score, 3),
                "reason": "Known distinct companies on this packet. Do not merge.",
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


def resolve(case_id: str) -> dict:
    files = db.list_case_files(case_id)
    people = []
    companies = []
    vins = []
    for item in files:
        extracted = item.get("extracted") or {}
        if extracted.get("insured"):
            people.append({"value": extracted["insured"], "file": item["filename"], "field": "insured"})
        if extracted.get("owner"):
            people.append({"value": extracted["owner"], "file": item["filename"], "field": "owner"})
        owner_op = extracted.get("owner_operator")
        if owner_op and owner_op not in {"filled", "blank"}:
            people.append({"value": owner_op, "file": item["filename"], "field": "owner_operator"})
        for key in ("carrier", "dispatcher", "holder"):
            if extracted.get(key):
                companies.append({"value": extracted[key], "file": item["filename"], "field": key})
        if extracted.get("vin") and extracted["vin"] not in {"blank", None}:
            vins.append({"value": extracted["vin"], "file": item["filename"]})

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

    if any(item.get("doc_type") == "registration" for item in files):
        reg = next(item for item in files if item["doc_type"] == "registration")
        if (reg.get("extracted") or {}).get("body") == "BOX":
            abstain.append(
                {
                    "decision": "abstain",
                    "entities": ["registration BOX/STRG 2007", "hotshot/flatbed photos"],
                    "reason": "Equipment association is unresolved. Do not bind a truck.",
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
