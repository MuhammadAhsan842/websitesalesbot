"""Classify, extract, and evaluate onboarding documents. Humans still approve."""

from __future__ import annotations

import re
from pathlib import Path

from app.docschema import (
    AUTHORITY_EVIDENCE,
    FIELD_BLANK,
    FIELD_NOT_LOCATED,
    FIELD_PRESENT,
    FIELD_UNREADABLE,
    LEASE_AUTO_MIN,
    LEASE_CARGO_MIN,
    STATUS_AWAITING_REVIEW,
    STATUS_CLEARER_COPY,
    arrangement_of,
    driver_summary,
    field,
    finding,
    legal_carrier_for,
    manager_summary,
    requirement_of,
    status_from_findings,
)

VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
USDOT_RE = re.compile(r"\bUSDOT[\s\-#:]*([0-9]{5,8})\b", re.I)
MC_RE = re.compile(r"\bMC[\s\-#:]*([0-9]{4,8})\b", re.I)
MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
HOLDER_BLOCK = re.compile(
    r"CERTIFICATE\s+HOLDER(.*?)(?:CANCELLATION|SHOULD ANY OF THE ABOVE|ACORD\s*25|$)",
    re.I | re.S,
)

PAGE_SIGNALS = (
    ("coi", re.compile(r"certificate of liability|acord\s*25", re.I)),
    ("coi_remarks", re.compile(r"acord\s*101|description of operations|motor truck cargo", re.I)),
    ("notice_of_assignment", re.compile(r"notice of assignment|change of payee", re.I)),
    ("w9", re.compile(r"form w-9|request for taxpayer identification", re.I)),
    ("authority", re.compile(
        r"motor carrier of property|operating authority registration|mc authority|fmcsa",
        re.I,
    )),
    ("authority_report", re.compile(r"\bcab\b report|carrier snapshot|safer snapshot|third[- ]party", re.I)),
    ("ein", re.compile(r"we assigned you ein|cp\s*575|employer identification number", re.I)),
    ("licence", re.compile(r"driver('?s)? licen[cs]e|commercial driver", re.I)),
    ("registration", re.compile(r"motor vehicle registration|cab card|certificate of title", re.I)),
    ("lease", re.compile(r"lease agreement|owner[- ]operator", re.I)),
    ("setup", re.compile(r"dispatch(?:er)? agreement|setup packet", re.I)),
    ("voided_check", re.compile(r"void(?:ed)? check", re.I)),
)

PHOTO_HINT = re.compile(r"\.(jpe?g|png|webp|jfif)$", re.I)
DOC_NAME = re.compile(r"coi|w-?9|noa|lease|packet|licen[cs]e|regist|authority|acord", re.I)


def _blob(pages: list[dict]) -> str:
    return "\n".join((row.get("text") or "") for row in pages)


def classify_page(text: str, filename: str = "") -> str:
    blob = f"{filename}\n{text or ''}"
    for doc_type, pattern in PAGE_SIGNALS:
        if pattern.search(blob):
            return doc_type
    name = (filename or "").lower()
    if "lease" in name:
        return "lease"
    if "packet" in name or "setup" in name:
        return "setup"
    if re.search(r"licen[cs]e", name):
        return "licence"
    if "regist" in name:
        return "registration"
    if "authority" in name or "usdot" in name or "fmcsa" in name:
        return "authority"
    if PHOTO_HINT.search(name) and not DOC_NAME.search(name):
        return "equipment_photos"
    return "unknown"


def split_components(pages: list[dict], filename: str = "", suggested: str | None = None) -> list[dict]:
    """One original file → one or more document components with page ranges."""
    if not pages:
        guessed = (suggested or "").strip().lower() or classify_page("", filename)
        return [{"document_type": guessed or "unknown", "pages": [], "text": ""}]
    if len(pages) == 1:
        page = pages[0]
        guessed = classify_page(page.get("text") or "", filename)
        if suggested and suggested not in {"", "unknown", "null", "none", "not_sure"}:
            if guessed in {"unknown", "setup"} or requirement_of(suggested) == requirement_of(guessed):
                guessed = suggested
        if guessed == "unknown" and PHOTO_HINT.search(filename or "") and not DOC_NAME.search(filename or ""):
            guessed = "equipment_photos"
        return [
            {
                "document_type": guessed,
                "pages": [page.get("page") or 1],
                "text": page.get("text") or "",
                "page_rows": [page],
            }
        ]
    labelled = []
    for page in pages:
        labelled.append(
            {
                "document_type": classify_page(page.get("text") or "", filename),
                "page": page.get("page"),
                "text": page.get("text") or "",
                "page_row": page,
            }
        )
    groups: list[dict] = []
    for row in labelled:
        kind = row["document_type"]
        if kind == "coi_remarks" and groups and groups[-1]["document_type"] in {"coi", "coi_remarks"}:
            groups[-1]["pages"].append(row["page"])
            groups[-1]["text"] += "\n" + row["text"]
            groups[-1]["page_rows"].append(row["page_row"])
            groups[-1]["document_type"] = "coi"
            groups[-1]["linked"] = "coi_remarks"
            continue
        if groups and groups[-1]["document_type"] == kind and kind != "unknown":
            groups[-1]["pages"].append(row["page"])
            groups[-1]["text"] += "\n" + row["text"]
            groups[-1]["page_rows"].append(row["page_row"])
            continue
        groups.append(
            {
                "document_type": kind,
                "pages": [row["page"]],
                "text": row["text"],
                "page_rows": [row["page_row"]],
            }
        )
    if suggested and len(groups) == 1 and groups[0]["document_type"] in {"unknown", "setup"}:
        groups[0]["document_type"] = suggested
    return groups


def _money(text: str) -> list[int]:
    values = []
    for match in MONEY_RE.finditer(text or ""):
        try:
            values.append(int(float(match.group(1).replace(",", ""))))
        except ValueError:
            continue
    return values


def _first_present(*candidates: dict) -> dict:
    for item in candidates:
        if item and item.get("status") == FIELD_PRESENT and item.get("value") not in (None, ""):
            return item
    for item in candidates:
        if item:
            return item
    return field(FIELD_NOT_LOCATED)


def extract_holder(text: str, page: int | None = None) -> dict:
    match = HOLDER_BLOCK.search(text or "")
    if not match:
        if re.search(r"certificate holder", text or "", re.I):
            return field(FIELD_BLANK, page=page, evidence="CERTIFICATE HOLDER", confidence="medium")
        return field(FIELD_NOT_LOCATED, page=page)
    region = match.group(1) or ""
    skip = re.compile(
        r"^(certificate holder|cancellation|acord.*|should any.*|the acord name.*|authorized representative.*)$",
        re.I,
    )
    lines = []
    for raw in region.splitlines():
        line = " ".join(raw.split()).strip(" .")
        if not line or skip.match(line) or len(line) < 3:
            continue
        if re.search(r"should any of the above", line, re.I):
            continue
        lines.append(line)
    if not lines:
        return field(FIELD_BLANK, page=page, evidence="CERTIFICATE HOLDER", confidence="high")
    name = lines[0]
    return field(FIELD_PRESENT, name, page=page, evidence=name, confidence="high")


def extract_coi_fields(text: str, pages: list[dict] | None = None) -> dict:
    blob = text or ""
    page = (pages or [{}])[0].get("page") if pages else 1
    insured = None
    insured_match = re.search(
        r"INSURED\s+([A-Z][A-Z0-9&.,'\- ]{3,80}(?:LLC|INC|CO|LTD|LP)?)",
        blob,
        re.I,
    )
    if insured_match:
        insured = field(FIELD_PRESENT, insured_match.group(1).strip(), page=page, evidence=insured_match.group(1).strip())
    else:
        insured = field(FIELD_NOT_LOCATED, page=page)
    auto = field(FIELD_NOT_LOCATED, page=page)
    cargo = field(FIELD_NOT_LOCATED, page=page)
    amounts = _money(blob)
    if re.search(r"automobile liability|any auto|combined single limit", blob, re.I) and amounts:
        auto_val = max(amounts)
        auto = field(FIELD_PRESENT, auto_val, page=page, evidence=str(auto_val), confidence="medium")
    cargo_match = re.search(
        r"(?:motor truck cargo|cargo(?:\s+liability)?)\s*\$\s*([\d,]+)",
        blob,
        re.I,
    )
    if cargo_match:
        try:
            cargo_val = int(cargo_match.group(1).replace(",", ""))
            cargo_page = page
            for row in pages or []:
                if re.search(r"cargo", row.get("text") or "", re.I):
                    cargo_page = row.get("page") or page
                    break
            cargo = field(FIELD_PRESENT, cargo_val, page=cargo_page, evidence=str(cargo_val), confidence="medium")
        except ValueError:
            cargo = field(FIELD_NOT_LOCATED, page=page)
    vin_match = VIN_RE.search(blob.upper())
    vin = (
        field(FIELD_PRESENT, vin_match.group(0), page=page, evidence=vin_match.group(0))
        if vin_match
        else field(FIELD_NOT_LOCATED, page=page)
    )
    additional = field(
        FIELD_NOT_LOCATED if not re.search(r"additional insured", blob, re.I) else FIELD_BLANK,
        page=page,
        evidence="additional insured",
        confidence="low",
    )
    if re.search(r"additional insured.{0,40}(yes|x\b|checked)", blob, re.I):
        additional = field(FIELD_PRESENT, True, page=page, evidence="additional insured marked")
    return {
        "certificate_holder": extract_holder(blob, page),
        "named_insured": insured,
        "auto_limit": auto,
        "cargo_limit": cargo,
        "vin": vin,
        "additional_insured": additional,
        "form": field(FIELD_PRESENT, "ACORD 25", page=page) if re.search(r"acord", blob, re.I) else field(FIELD_NOT_LOCATED),
    }


def extract_authority_fields(text: str, page: int | None = None) -> dict:
    blob = text or ""
    usdot = USDOT_RE.search(blob)
    mc = MC_RE.search(blob)
    name = re.search(
        r"(?:LLC|INC)\s*$|(^[A-Z][A-Z0-9&.,'\- ]{3,60}(?:LLC|INC))",
        blob,
        re.M,
    )
    legal = None
    legal_match = re.search(
        r"([A-Z][A-Z0-9&.,'\- ]{2,60}(?:LLC|INC|CO|LTD))",
        blob,
    )
    if legal_match:
        legal = legal_match.group(1).strip()
    return {
        "usdot": field(FIELD_PRESENT, usdot.group(1), page=page, evidence=usdot.group(0))
        if usdot
        else field(FIELD_NOT_LOCATED, page=page),
        "mc_number": field(FIELD_PRESENT, mc.group(1), page=page, evidence=mc.group(0))
        if mc
        else field(FIELD_NOT_LOCATED, page=page),
        "legal_name": field(FIELD_PRESENT, legal, page=page, evidence=legal)
        if legal
        else field(FIELD_NOT_LOCATED, page=page),
        "authority_status": field(FIELD_NOT_LOCATED, page=page, evidence="appearance is not current status"),
    }


def extract_licence_fields(text: str, page: int | None = None, unreadable: bool = False) -> dict:
    if unreadable or len((text or "").strip()) < 20:
        return {
            "licence_number": field(FIELD_UNREADABLE, page=page, confidence="high"),
            "expiry": field(FIELD_UNREADABLE, page=page, confidence="high"),
            "class": field(FIELD_UNREADABLE, page=page, confidence="medium"),
        }
    expiry = re.search(r"expir(?:es|ation)[:\s]*([0-9]{2}[/-][0-9]{2}[/-][0-9]{2,4})", text or "", re.I)
    klass = re.search(r"class\s*[:#]?\s*([A-D])\b", text or "", re.I)
    return {
        "licence_number": field(FIELD_NOT_LOCATED, page=page)
        if not re.search(r"\b[A-Z0-9]{6,}\b", text or "")
        else field(FIELD_PRESENT, "***", page=page, evidence="licence number present", confidence="low"),
        "expiry": field(FIELD_PRESENT, expiry.group(1), page=page, evidence=expiry.group(0))
        if expiry
        else field(FIELD_NOT_LOCATED, page=page),
        "class": field(FIELD_PRESENT, klass.group(1).upper(), page=page, evidence=klass.group(0))
        if klass
        else field(FIELD_NOT_LOCATED, page=page),
        "real_id_note": field(
            FIELD_PRESENT,
            "not_for_federal_identification",
            page=page,
            evidence="NOT FOR FEDERAL IDENTIFICATION",
        )
        if re.search(r"not for federal identification", text or "", re.I)
        else field(FIELD_NOT_LOCATED, page=page),
    }


def extract_registration_fields(text: str, page: int | None = None, unreadable: bool = False) -> dict:
    if unreadable or len((text or "").strip()) < 25:
        return {
            "vin": field(FIELD_UNREADABLE, page=page, confidence="high"),
            "owner": field(FIELD_UNREADABLE, page=page, confidence="high"),
            "body": field(FIELD_UNREADABLE, page=page, confidence="medium"),
        }
    vin_match = VIN_RE.search((text or "").upper())
    body = re.search(r"\b(BOX|VAN|FLAT|PK|PICKUP|TRUCK)\b", text or "", re.I)
    year = re.search(r"\b(19|20)\d{2}\b", text or "")
    return {
        "vin": field(FIELD_PRESENT, vin_match.group(0), page=page, evidence=vin_match.group(0))
        if vin_match
        else field(FIELD_NOT_LOCATED, page=page),
        "body": field(FIELD_PRESENT, body.group(1).upper(), page=page, evidence=body.group(0))
        if body
        else field(FIELD_NOT_LOCATED, page=page),
        "year": field(FIELD_PRESENT, year.group(0), page=page, evidence=year.group(0))
        if year
        else field(FIELD_NOT_LOCATED, page=page),
        "owner": field(FIELD_NOT_LOCATED, page=page),
    }


def extract_w9_fields(text: str, page: int | None = None) -> dict:
    name = re.search(r"name\s*\(as shown[^\)]*\)\s*([A-Z][^\n]{2,60})", text or "", re.I)
    signed = bool(re.search(r"signature of u\.s\. person|signed", text or "", re.I))
    return {
        "legal_name": field(FIELD_PRESENT, name.group(1).strip(), page=page)
        if name
        else field(FIELD_NOT_LOCATED, page=page),
        "signed": field(FIELD_PRESENT, True, page=page) if signed else field(FIELD_BLANK, page=page),
    }


def extract_lease_fields(text: str, page: int | None = None) -> dict:
    blank_pct = bool(re.search(r"paid _{2,}%|____%|paid\s+% of", text or "", re.I))
    vin_blank = bool(re.search(r"VIN#_{3,}|VIN#\s*$", text or "", re.M))
    signed = bool(re.search(r"signature", text or "", re.I)) and not bool(
        re.search(r"_{6,}", text or "")
    )
    notice_30 = bool(re.search(r"\[?30\]?\s*days", text or "", re.I))
    notice_2 = bool(re.search(r"upon 2 days|2 days['’] notice", text or "", re.I))
    return {
        "compensation": field(FIELD_BLANK, page=page, evidence="____%") if blank_pct else field(FIELD_NOT_LOCATED, page=page),
        "vin": field(FIELD_BLANK, page=page, evidence="VIN#") if vin_blank else field(FIELD_NOT_LOCATED, page=page),
        "signed": field(FIELD_BLANK, page=page, evidence="signature") if not signed else field(FIELD_PRESENT, True, page=page),
        "termination_30": field(FIELD_PRESENT, 30, page=page) if notice_30 else field(FIELD_NOT_LOCATED, page=page),
        "termination_2": field(FIELD_PRESENT, 2, page=page) if notice_2 else field(FIELD_NOT_LOCATED, page=page),
    }


def extract_fields(doc_type: str, text: str, page_rows: list[dict] | None = None) -> dict:
    rows = page_rows or []
    unreadable = bool(rows) and all(row.get("unreadable") for row in rows)
    page = rows[0].get("page") if rows else 1
    kind = requirement_of(doc_type)
    if kind == "coi":
        return extract_coi_fields(text, rows)
    if kind == "authority" or doc_type in AUTHORITY_EVIDENCE:
        return extract_authority_fields(text, page)
    if kind == "licence":
        return extract_licence_fields(text, page, unreadable=unreadable)
    if kind == "registration":
        return extract_registration_fields(text, page, unreadable=unreadable)
    if kind == "w9":
        return extract_w9_fields(text, page)
    if kind == "lease":
        return extract_lease_fields(text, page)
    if kind == "equipment_photos":
        return {"views": field(FIELD_PRESENT, "photo", page=page, evidence="equipment photo")}
    return {"raw_len": field(FIELD_PRESENT, len(text or ""), page=page)}


def _names_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    token = re.compile(r"[a-z0-9]+")
    stop = {"llc", "inc", "co", "the", "of", "and", "corp", "ltd"}
    a = {t for t in token.findall(left.lower()) if t not in stop}
    b = {t for t in token.findall(right.lower()) if t not in stop}
    if not a or not b:
        return False
    return a == b or a <= b or b <= a


def evaluate_component(
    component: dict,
    *,
    facts: dict | None = None,
    arrangement: str | None = None,
    related: list[dict] | None = None,
) -> list[dict]:
    facts = facts or {}
    arrangement = arrangement or arrangement_of(facts)
    legal = legal_carrier_for(facts)
    doc_type = component.get("document_type") or "unknown"
    req = requirement_of(doc_type)
    fields = component.get("fields") or {}
    pages = component.get("pages") or [1]
    page = pages[0]
    findings: list[dict] = []

    def add(**kwargs):
        findings.append(finding(document=doc_type, page=kwargs.get("page", page), **kwargs))

    quality_unread = all((row.get("unreadable") for row in component.get("page_rows") or [])) and component.get(
        "page_rows"
    )
    if req == "equipment_photos":
        return findings
    if req in {"licence", "registration"} and quality_unread:
        add(
            code="clearer_copy_needed",
            why=(
                "Required fields cannot be read reliably from this image. "
                "Please upload the original scan or a close, straight-on photo with all four corners visible."
            ),
            field_name="document",
            outcome=FIELD_UNREADABLE,
            severity="blocking",
            next_action="request_clearer_image",
            actor="driver",
            confidence="high",
        )
        return findings

    holder = fields.get("certificate_holder") or {}
    if req == "coi":
        if holder.get("status") == FIELD_UNREADABLE:
            add(
                code="holder_unreadable",
                why="The certificate-holder area cannot be read reliably. A clearer copy is needed.",
                field_name="certificate_holder",
                outcome=FIELD_UNREADABLE,
                severity="blocking",
                next_action="request_clearer_image",
                actor="driver",
            )
        elif holder.get("status") == FIELD_BLANK:
            add(
                code="required_holder_missing",
                why=(
                    "Certificate-holder box appears blank. "
                    "Request an insurer-issued revision naming the approved legal carrier and address."
                    if arrangement == "lease_on"
                    else "Certificate-holder box appears blank. Onboarding still needs the holder named on the form."
                ),
                field_name="certificate_holder",
                expected=legal or "approved legal carrier",
                outcome=FIELD_BLANK,
                severity="blocking",
                next_action="request_revised_coi",
                actor="driver" if arrangement == "lease_on" else "reviewer",
            )
        elif holder.get("status") == FIELD_PRESENT and arrangement == "lease_on" and legal:
            if not _names_match(str(holder.get("value") or ""), legal):
                add(
                    code="holder_mismatch",
                    why="Certificate holder does not match the legal carrier selected for this inquiry.",
                    field_name="certificate_holder",
                    expected=legal,
                    observed=holder.get("value"),
                    outcome=FIELD_PRESENT,
                    severity="blocking",
                    next_action="request_revised_coi",
                    actor="driver",
                )
        auto = fields.get("auto_limit") or {}
        cargo = fields.get("cargo_limit") or {}
        if arrangement == "lease_on" and auto.get("status") == FIELD_PRESENT:
            try:
                if int(auto.get("value") or 0) < LEASE_AUTO_MIN:
                    add(
                        code="coverage_below_minimum",
                        why=f"Automobile liability on the face of the certificate is below ${LEASE_AUTO_MIN:,}.",
                        field_name="auto_limit",
                        expected=str(LEASE_AUTO_MIN),
                        observed=auto.get("value"),
                        outcome=FIELD_PRESENT,
                        severity="blocking",
                        actor="driver",
                    )
            except (TypeError, ValueError):
                pass
        if arrangement == "lease_on" and cargo.get("status") in {FIELD_NOT_LOCATED, FIELD_BLANK}:
            add(
                code="cargo_not_evidenced",
                why="Cargo coverage is not evidenced in this upload (it may be on a linked remarks page).",
                field_name="cargo_limit",
                expected=str(LEASE_CARGO_MIN),
                outcome=cargo.get("status"),
                severity="review",
                actor="reviewer",
            )
        elif arrangement == "lease_on" and cargo.get("status") == FIELD_PRESENT:
            try:
                if int(cargo.get("value") or 0) < LEASE_CARGO_MIN:
                    add(
                        code="coverage_below_minimum",
                        why=f"Cargo coverage on the face of the certificate is below ${LEASE_CARGO_MIN:,}.",
                        field_name="cargo_limit",
                        expected=str(LEASE_CARGO_MIN),
                        observed=cargo.get("value"),
                        outcome=FIELD_PRESENT,
                        severity="blocking",
                        actor="driver",
                    )
            except (TypeError, ValueError):
                pass
        additional = fields.get("additional_insured") or {}
        if arrangement == "lease_on" and additional.get("status") != FIELD_PRESENT:
            add(
                code="additional_insured_not_evidenced",
                why="Additional-insured evidence is not established by this certificate. Being holder is not enough.",
                field_name="additional_insured",
                outcome=additional.get("status") or FIELD_NOT_LOCATED,
                severity="review",
                actor="reviewer",
            )
        add(
            code="coi_is_evidence",
            why="A COI is evidence, not a contract. Coverage still needs verification. Not approved.",
            field_name="form",
            severity="info",
            actor="reviewer",
            next_action="await_review",
        )

    if req == "authority" or doc_type in AUTHORITY_EVIDENCE:
        usdot = fields.get("usdot") or {}
        mc = fields.get("mc_number") or {}
        if usdot.get("status") == FIELD_PRESENT or mc.get("status") == FIELD_PRESENT:
            add(
                code="authority_identifiers_present",
                why="Carrier identifiers were read from the document. Current operating authority still needs verification.",
                field_name="usdot" if usdot.get("status") == FIELD_PRESENT else "mc_number",
                observed=usdot.get("value") or mc.get("value"),
                outcome=FIELD_PRESENT,
                severity="review",
                actor="reviewer",
                next_action="authority_lookup",
            )
        else:
            add(
                code="authority_identifiers_missing",
                why="No USDOT or MC number could be read. This is not yet operating-authority evidence.",
                field_name="usdot",
                outcome=FIELD_NOT_LOCATED,
                severity="blocking",
                actor="driver",
                next_action="request_authority_evidence",
            )
        add(
            code="authority_verification_outstanding",
            why="USDOT registration status and operating-authority status must be verified from an official source. This file does not establish that the authority is currently active.",
            field_name="authority_status",
            outcome=FIELD_NOT_LOCATED,
            severity="review",
            actor="reviewer",
            next_action="authority_lookup",
        )

    if req == "lease":
        if (fields.get("compensation") or {}).get("status") == FIELD_BLANK:
            add(
                code="blank_lease_terms",
                why="Lease compensation is blank. Do not insert a dispatch fee into the owner-operator share.",
                field_name="compensation",
                outcome=FIELD_BLANK,
                severity="review",
                actor="company",
            )
        if (fields.get("signed") or {}).get("status") == FIELD_BLANK:
            add(
                code="unsigned_agreement",
                why="The attached lease looks unsigned. A completed, signed return is required.",
                field_name="signed",
                outcome=FIELD_BLANK,
                severity="blocking",
                actor="driver",
            )
        if (fields.get("termination_30") or {}).get("status") == FIELD_PRESENT and (
            fields.get("termination_2") or {}
        ).get("status") == FIELD_PRESENT:
            add(
                code="clause_conflict_company",
                why="Termination notice is 30 days in one section and 2 days in another. Company reviewer resolves this — not the driver.",
                field_name="termination",
                outcome=FIELD_PRESENT,
                severity="review",
                actor="company",
            )

    related = related or []
    if req == "registration":
        body = (fields.get("body") or {}).get("value")
        photo_bodies = []
        for other in related:
            if requirement_of(other.get("document_type")) == "equipment_photos":
                photo_bodies.append("photo")
        vin = (fields.get("vin") or {}).get("value")
        other_vins = [
            (other.get("fields") or {}).get("vin", {}).get("value")
            for other in related
            if (other.get("fields") or {}).get("vin", {}).get("status") == FIELD_PRESENT
        ]
        other_vins = [item for item in other_vins if item and vin and item != vin]
        if other_vins:
            add(
                code="possible_equipment_mismatch",
                why="Related files list a different VIN. One carrier can have multiple trucks — ask which unit this onboarding is for.",
                field_name="vin",
                observed=vin,
                outcome=FIELD_PRESENT,
                severity="review",
                actor="driver",
                next_action="clarify_equipment",
            )
        elif body and photo_bodies:
            # Photos are not OCR'd to a body class here; manager reviews views.
            pass

    return findings


def review_pages(
    pages: list[dict],
    *,
    filename: str = "",
    facts: dict | None = None,
    suggested: str | None = None,
    kind: str | None = None,
    gemini_payload: dict | None = None,
) -> dict:
    """Deterministic review. Optional Gemini payload may fill unreadable/not_located fields."""
    from app import docai

    facts = facts or {}
    arrangement = arrangement_of(facts)
    if kind == "photo" and not suggested:
        suggested = suggested or "equipment_photos"
    components = split_components(pages, filename, suggested)
    if gemini_payload:
        by_type = {item.get("document_type"): item for item in gemini_payload.get("documents") or []}
        for component in components:
            incoming = by_type.get(component["document_type"]) or {}
            if incoming.get("pages") and component["document_type"] in {"unknown", "other"}:
                component["document_type"] = incoming.get("document_type") or component["document_type"]
            extracted = extract_fields(component["document_type"], component.get("text") or "", component.get("page_rows"))
            component["fields"] = docai.merge_fields(extracted, incoming.get("fields"))
            if incoming.get("quality") == "unreadable":
                for row in component.get("page_rows") or []:
                    row["unreadable"] = True
    else:
        for component in components:
            component["fields"] = extract_fields(
                component["document_type"],
                component.get("text") or "",
                component.get("page_rows"),
            )
    all_findings = []
    for component in components:
        component["findings"] = evaluate_component(
            component, facts=facts, arrangement=arrangement, related=components
        )
        all_findings.extend(component["findings"])
        photo = requirement_of(component["document_type"]) == "equipment_photos" or kind == "photo"
        component["status"] = status_from_findings(component["findings"], photo=photo)
        component["requirement"] = requirement_of(component["document_type"])
    primary = components[0] if components else {}
    status = primary.get("status") or STATUS_AWAITING_REVIEW
    if any(row.get("status") == STATUS_CLEARER_COPY for row in components):
        # Mixed packet: do not mark the whole upload clearer-copy unless every component is.
        if all(row.get("status") == STATUS_CLEARER_COPY for row in components):
            status = STATUS_CLEARER_COPY
        else:
            status = primary.get("status") or status
    extracted = {
        "components": [
            {
                "document_type": row["document_type"],
                "requirement": row.get("requirement"),
                "pages": row.get("pages"),
                "fields": row.get("fields"),
                "status": row.get("status"),
                "linked": row.get("linked"),
            }
            for row in components
        ],
        "fields": primary.get("fields") or {},
        "_verification": "extracted_unverified",
        "_approved": False,
        "_driver_summary": driver_summary(all_findings),
        "_manager_summary": manager_summary(all_findings, arrangement),
    }
    return {
        "doc_type": primary.get("document_type") or suggested or "unknown",
        "components": components,
        "extracted": extracted,
        "flags": all_findings,
        "findings": all_findings,
        "status": status,
        "approved": False,
        "verified": False,
        "filename": filename,
    }


def review_path(
    path: Path,
    *,
    facts: dict | None = None,
    suggested: str | None = None,
    kind: str | None = None,
    fallback_text: str = "",
    filename: str | None = None,
) -> dict:
    from app import ocr

    path = Path(path)
    read = {"pages": [], "text": "", "method": "unread", "confidence": None, "ocr_used": False, "unreadable": True}
    if path.exists():
        read = ocr.read_pages(path)
    if not any((row.get("text") or "").strip() for row in read.get("pages") or []) and fallback_text:
        read = {
            "pages": [
                {
                    "page": 1,
                    "text": fallback_text,
                    "method": "fallback_text",
                    "confidence": None,
                    "ocr_used": False,
                    "unreadable": len(fallback_text.strip()) < 20,
                }
            ],
            "text": fallback_text,
            "method": "fallback_text",
            "confidence": None,
            "ocr_used": False,
            "unreadable": len(fallback_text.strip()) < 20,
        }
    gemini_payload = None
    visual = (kind == "photo") or path.suffix.lower() in {".jpg", ".jpeg", ".png", ".jfif", ".webp"}
    unread = bool(read.get("unreadable"))
    try:
        from app import docai

        if docai.enabled() and (visual or unread or (read.get("page_count") or 0) > 1):
            images = [path] if visual and path.exists() else None
            gemini_payload = docai.review_visual(
                read.get("pages") or [],
                filename=filename or path.name,
                suggested=suggested,
                arrangement=arrangement_of(facts or {}),
                legal_carrier=legal_carrier_for(facts or {}),
                images=images,
            )
    except Exception:
        gemini_payload = None
    result = review_pages(
        read.get("pages") or [],
        filename=filename or path.name,
        facts=facts,
        suggested=suggested,
        kind=kind,
        gemini_payload=gemini_payload,
    )
    result["method"] = read.get("method")
    result["ocr_confidence"] = read.get("confidence")
    result["pages"] = read.get("pages") or []
    result["ocr_used"] = read.get("ocr_used")
    return result
