"""Background document worker. Reads and flags. Never approves."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app import db, ocr, requirements
from app.diffing import clause_diff

PACKET_DIR = Path(__file__).resolve().parent.parent / "data" / "packets"

SAMPLE = {
    "lease": Path("/home/muhammad/Downloads/2026 SAL Lease Agreement (2).pdf"),
    "setup": Path("/home/muhammad/Downloads/Setup Packet for ATL Fast Freight LLC.pdf"),
    "registration": Path("/home/muhammad/Downloads/Truck Registration.jfif"),
    "coi": Path("/home/muhammad/Downloads/COI.jfif"),
}


def _flag(code: str, evidence: str, message: str, severity: str = "blocking", source: str = "") -> dict:
    start = source.find(evidence) if source and evidence else -1
    return {
        "code": code,
        "severity": severity,
        "evidence": evidence,
        "span": evidence,
        "start": start if start >= 0 else None,
        "end": (start + len(evidence)) if start >= 0 else None,
        "message": message,
    }


def _locate(text: str, needle: str) -> tuple[int, int]:
    if not text or not needle:
        return -1, -1
    start = text.find(needle)
    if start < 0:
        start = text.lower().find(needle.lower())
    if start < 0:
        return -1, -1
    return start, start + len(needle)


def _bind_spans(flags: list[dict], text: str) -> list[dict]:
    for flag in flags:
        evidence = flag.get("evidence") or ""
        start, end = _locate(text, evidence)
        if start < 0:
            for part in re.split(r"\s+", evidence):
                if len(part) < 4:
                    continue
                start, end = _locate(text, part)
                if start >= 0:
                    evidence = text[start:end]
                    break
        flag["span"] = evidence
        flag["start"] = start if start >= 0 else None
        flag["end"] = end if start >= 0 else None
    return flags


def _pdf_text(path: Path) -> str:
    try:
        out = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True, timeout=20)
        return out
    except Exception:
        return ""


def _ocr_text(path: Path) -> str:
    try:
        return subprocess.check_output(["tesseract", str(path), "stdout"], text=True, timeout=40)
    except Exception:
        return ""


def extract_lease(text: str) -> tuple[dict, list[dict]]:
    extracted = {
        "carrier": "Silver Arrow Logistics, LLC" if "Silver Arrow" in text else None,
        "owner_operator": None if re.search(r"between,\s*_{3,}", text) else "filled",
        "compensation": "blank" if re.search(r"paid _{2,}%|paid ____%", text) else "stated",
        "term_notice_days": 30 if "[30] days" in text else None,
        "termination_days": 2 if "upon 2 days" in text else None,
        "vin": "blank" if re.search(r"VIN#_{3,}|VIN#\s*$", text, re.M) else "stated",
        "signed": False,
    }
    flags = [
        _flag("blank_percent", "____%", "Lease compensation is blank. Do not invent a %.", source=text),
        _flag("clause_conflict", "[30] days", "Two termination periods. Human picks which clause controls.", source=text),
        _flag("blank_party", "Owner Operator", "Lease party is not the prospect until a human fills it.", source=text),
        _flag("blank_vin", "VIN#", "No vehicle is bound.", source=text),
        _flag("unsigned", "Signature", "Unsigned draft. Not an agreement.", source=text),
        _flag("title_mismatch", "Silver Arrow", "Entity on the file is not auto-merged.", source=text),
    ]
    if "____%" not in text and "_{2,}%" not in text and not re.search(r"paid _{2,}%", text):
        flags = [f for f in flags if f["code"] != "blank_percent"]
        if re.search(r"(\d+)\s*%", text):
            extracted["compensation"] = re.search(r"(\d+)\s*%", text).group(1)
            flags.append(_flag("draft_percent", f"{extracted['compensation']}% in draft", "Draft % is not Ayyan’s live quote until staff publish it."))
    return extracted, flags


def extract_setup(text: str) -> tuple[dict, list[dict]]:
    extracted = {
        "dispatcher": "LEO DISPATCH INC." if "LEO DISPATCH" in text else None,
        "carrier": "ATL Fast Freight LLC" if "ATL Fast Freight" in text else None,
        "sample_fee": "6" if re.search(r"pay 6%", text) else None,
        "payment_at_invoice": "Payment is due to the DISPATCHER at the time of the invoice" in text,
        "payment_after_broker": "only after the CARRIER has received payment" in text,
    }
    flags = [
        _flag("wrong_company", "LEO DISPATCH", "This is not an Ayyan packet. Do not treat 6% as our fee.", source=text),
        _flag("sample_fee", "6%", "Sample fee from another dispatcher. Blocked until a human publishes Ayyan’s schedule.", source=text),
        _flag("payment_conflict", "Payment is due to the DISPATCHER", "Invoice-now vs pay-after-broker. Human picks the live sentence.", source=text),
        _flag("load_promise", "keep truck(s) loaded", "Load-promise language. Bot must not repeat it as a guarantee.", source=text),
        _flag("sign_authority", "signature for rate confirmation", "Dispatcher signature authority is a human decision.", source=text),
    ]
    return extracted, flags


def extract_coi(text: str, name_hint: str | None = None) -> tuple[dict, list[dict]]:
    text_u = text.upper()
    extracted = {
        "form": "ACORD 25" if "ACORD" in text_u or "CERTIFICATE OF LIABILITY" in text_u else None,
        "holder": "Silver Arrow Logistics LLC" if "SILVER ARROW" in text_u else None,
        "insured": "MANNING" if "MANNING" in text_u else None,
        "certificate_number": None if not re.search(r"CERTIFICATE NUMBER:\s*[A-Z0-9]", text_u) else "present",
        "vin_listed": bool(re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", text_u)),
        "additional_insured": "UNCHECKED" if "ADDITIONAL" in text_u else "unknown",
    }
    flags = [
        _flag("coi_no_rights", "CERTIFICATE OF LIABILITY", "A COI is evidence, not a contract. Not approved.", source=text),
        _flag("blank_cert_number", "CERTIFICATE NUMBER", "Cannot verify the certificate id.", source=text),
        _flag("no_vin", "DESCRIPTION OF OPERATIONS", "Unit on the COI is not tied to a VIN.", source=text),
        _flag("additional_insured", "ADDITIONAL", "Lease requires Carrier as additional insured. Unresolved.", source=text),
        _flag("not_ayyan_holder", "SILVER ARROW", "Ayyan is not the holder. Arrangement must match the file.", source=text),
    ]
    if name_hint and extracted["insured"] and name_hint.split()[0].upper() not in text_u:
        flags.append(_flag("name_mismatch", f"COI insured vs {name_hint}", "Names do not clearly match. Abstain on entity resolution."))
    return extracted, flags


def extract_registration(text: str) -> tuple[dict, list[dict]]:
    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", text.upper())
    extracted = {
        "owner": "Andez Manning" if re.search(r"ANDEZ MANNING", text, re.I) else None,
        "year": "2007" if "2007" in text else None,
        "make": "STRG" if "STRG" in text.upper() else None,
        "body": "BOX" if re.search(r"\bBOX\b", text.upper()) else None,
        "vin": vin.group(0) if vin else None,
        "plate": "70J6KE" if "70J6KE" in text.upper() else None,
    }
    flags = [
        _flag("equipment_conflict", "BOX", "Do not bind a truck until cab card matches photos.", "blocking", source=text),
        _flag("name_form", "ANDEZ MANNING", "Same person is likely; do not auto-merge.", "info", source=text),
    ]
    return extracted, flags


def classify(path: Path, ocr_text: str = "") -> str:
    name = path.name.lower()
    blob = f"{name} {(ocr_text or '').lower()}"
    if "w-9" in blob or re.search(r"\bw9\b", blob) or "request for taxpayer" in blob:
        return "w9"
    if "notice of assignment" in blob or re.search(r"\bnoa\b", blob):
        return "notice_of_assignment"
    if "voided" in blob and "check" in blob:
        return "voided_check"
    if "lease" in name:
        return "lease"
    if "setup" in name or "packet" in name:
        return "setup"
    if "coi" in name or "insurance" in name or "certificate of liability" in blob:
        return "coi"
    if "regist" in name or "cab" in name:
        return "registration"
    if "licence" in name or "license" in name or "driver license" in blob:
        return "licence"
    if "authority" in name or "mc authority" in blob:
        return "authority"
    if path.suffix.lower() == ".pdf":
        text = (_pdf_text(path) or ocr_text or "").lower()
        if "lease" in text:
            return "lease"
        if "certificate of" in text or "liability" in text:
            return "coi"
        return "setup"
    return "unknown"


def extract_path(path: Path, facts: dict | None = None, read: dict | None = None) -> dict:
    read = read or ocr.read_document(path)
    doc_type = classify(path, read.get("text") or "")
    text = read.get("text") or ""
    flags: list[dict] = []
    if read.get("unreadable"):
        flags.append(
            _flag(
                "unreadable",
                path.name,
                "Original stored. Text/OCR did not yield a readable page. A person must view the file. Extracted fields stay unverified.",
                source=path.name,
            )
        )
    if ocr.low_confidence(read):
        flags.append(
            _flag(
                "ocr_low_confidence",
                path.name,
                f"OCR confidence {read.get('confidence')} is below {ocr.LOW_CONF}. Do not treat names or VINs as confirmed.",
                "info",
                source=path.name,
            )
        )
    if doc_type == "lease":
        extracted, extra = extract_lease(text)
    elif doc_type == "setup":
        extracted, extra = extract_setup(text)
    elif doc_type == "coi":
        name = None
        if facts and facts.get("name"):
            name = facts["name"].get("value")
        extracted, extra = extract_coi(text, name)
    elif doc_type == "registration":
        extracted, extra = extract_registration(text or path.name)
    else:
        extracted, extra = {"raw_len": len(text)}, [_flag("unclassified", path.name, "Staff must label this file.")]
    flags.extend(extra)
    extracted["_verification"] = "extracted_unverified"
    extracted["_method"] = read.get("method")
    extracted["_ocr_used"] = bool(read.get("ocr_used"))
    extracted["_approved"] = False
    flags = _bind_spans(flags, text)
    return {
        "doc_type": doc_type,
        "filename": path.name,
        "extracted": extracted,
        "flags": flags,
        "method": read.get("method"),
        "ocr_confidence": read.get("confidence"),
        "status": "flagged" if any(f["severity"] == "blocking" for f in flags) else "received",
        "approved": False,
        "verified": False,
    }


def _link_review(case_id: str, review: dict, original_path: str, *, sample: bool = False) -> dict:
    case = db.get_case(case_id) or {}
    doc_type = review.get("doc_type") or "unknown"
    prior = db.latest_file(case_id, doc_type)
    review["version"] = (prior.get("version") or 0) + 1 if prior else 1
    review["original_path"] = original_path
    if prior:
        review["diff"] = clause_diff(prior.get("extracted"), review.get("extracted"))
        requirements.reopen(case_id, doc_type, "replacement file")
    req = requirements.receive(case_id, doc_type, None, review.get("status") or "received")
    if req:
        review["requirement_id"] = req["id"]
    row = db.add_case_file(case_id, review, original_path)
    requirements.receive(case_id, doc_type, row["id"], row["status"])
    docs = list(case.get("documents") or [])
    if "returned" not in docs:
        docs.append("returned")
    db.upsert_case(
        {
            "id": case_id,
            "status": "under_review",
            "next_action": (
                "Sample packet linked for demo review only — not a driver upload."
                if sample
                else "Human review of returned file — received is not approved. OCR is unverified."
            ),
            "documents": docs,
            "facts": case.get("facts") or {},
            "session_id": case.get("session_id"),
            "opportunity_id": case.get("opportunity_id"),
            "task": case.get("task"),
            "summary": case.get("summary"),
            "owner": case.get("owner"),
        }
    )
    return row


def ingest_upload(case_id: str, path: Path, attachment: dict | None = None) -> dict:
    """Link a real chat/staff upload to the case checklist. Never approves."""
    case = db.get_case(case_id)
    if not case:
        raise FileNotFoundError("unknown case")
    path = Path(path)
    requirements.issue(case_id, case.get("task"), facts=case.get("facts") or {})
    ocr_text = (attachment or {}).get("ocr_text") or ""
    read = {
        "text": ocr_text,
        "confidence": (attachment or {}).get("ocr_confidence"),
        "method": "chat_upload",
        "ocr_used": bool(ocr_text),
    }
    if not ocr_text and path.exists():
        read = ocr.read_document(path)
    review = extract_path(path, case.get("facts") or {}, read=read)
    review["doc_type"] = classify(path, read.get("text") or "")
    if attachment:
        review["filename"] = attachment.get("filename") or path.name
        review["attachment_id"] = attachment.get("id")
    original_path = str((attachment or {}).get("path") or path)
    row = _link_review(case_id, review, original_path, sample=False)
    db.add_event(
        "Chat upload linked to case",
        {
            "caseId": case_id,
            "fileId": row["id"],
            "docType": row.get("doc_type"),
            "attachmentId": (attachment or {}).get("id"),
        },
    )
    return row


def ingest_sample(case_id: str) -> list[dict]:
    """DEMO ONLY: hard-coded sample files. Real driver uploads must use ingest_upload."""
    case = db.get_case(case_id)
    if not case:
        raise FileNotFoundError("unknown case")
    requirements.issue(case_id, case.get("task"), facts=case.get("facts") or {})
    saved = []
    for _kind, source in SAMPLE.items():
        if not source.exists():
            continue
        doc_type = classify(source)
        prior = db.latest_file(case_id, doc_type)
        prior_path = Path(prior["original_path"]) if prior and prior.get("original_path") else None
        if prior_path and ocr.same_file(source, prior_path):
            saved.append({**prior, "duplicate": True, "sample": True})
            continue
        original = ocr.store_original(case_id, source)
        read = ocr.read_document(Path(original["original_path"]))
        review = extract_path(source, case.get("facts") or {}, read=read)
        review.update(
            {
                "original_path": original["original_path"],
                "method": read.get("method"),
                "ocr_confidence": read.get("confidence"),
                "sample": True,
            }
        )
        row = _link_review(case_id, review, original["original_path"], sample=True)
        saved.append({**row, "sample": True})
    db.add_event("Sample document worker ran (demo only)", {"caseId": case_id, "files": len(saved)})
    return saved
