"""Background document worker. Reads and flags. Never approves."""

from __future__ import annotations

from pathlib import Path

from app import db, ocr, requirements
from app.diffing import clause_diff
from app.docreview import classify_page, review_pages, review_path
from app.docschema import requirement_of

PACKET_DIR = Path(__file__).resolve().parent.parent / "data" / "packets"

SAMPLE = {
    "lease": Path("/home/muhammad/Downloads/2026 SAL Lease Agreement (2).pdf"),
    "setup": Path("/home/muhammad/Downloads/Setup Packet for ATL Fast Freight LLC.pdf"),
    "registration": Path("/home/muhammad/Downloads/Truck Registration.jfif"),
    "coi": Path("/home/muhammad/Downloads/COI.jfif"),
}

CHAT_EXCERPT_MAX = 4000


def classify(path: Path, ocr_text: str = "") -> str:
    """Compatibility wrapper. Packets must use page-level split_components."""
    return classify_page(ocr_text or "", path.name)


def extract_lease(text: str) -> tuple[dict, list[dict]]:
    result = review_pages([{"page": 1, "text": text, "method": "test", "unreadable": False}], filename="lease.pdf")
    return result.get("extracted") or {}, result.get("flags") or []


def extract_setup(text: str) -> tuple[dict, list[dict]]:
    result = review_pages([{"page": 1, "text": text, "method": "test", "unreadable": False}], filename="setup.pdf")
    return result.get("extracted") or {}, result.get("flags") or []


def extract_coi(text: str, name_hint: str | None = None) -> tuple[dict, list[dict]]:
    result = review_pages(
        [{"page": 1, "text": text, "method": "test", "unreadable": False}],
        filename="coi.pdf",
        suggested="coi",
        facts={"name": {"value": name_hint, "status": "user_stated"}} if name_hint else None,
    )
    return result.get("extracted") or {}, result.get("flags") or []


def extract_registration(text: str) -> tuple[dict, list[dict]]:
    result = review_pages(
        [{"page": 1, "text": text, "method": "test", "unreadable": False}],
        filename="registration.pdf",
        suggested="registration",
    )
    return result.get("extracted") or {}, result.get("flags") or []


def extract_path(path: Path, facts: dict | None = None, read: dict | None = None) -> dict:
    path = Path(path)
    pages = (read or {}).get("pages")
    if not pages:
        text = (read or {}).get("text") or ""
        pages = [
            {
                "page": 1,
                "text": text,
                "method": (read or {}).get("method") or "unread",
                "confidence": (read or {}).get("confidence"),
                "ocr_used": bool((read or {}).get("ocr_used")),
                "unreadable": bool((read or {}).get("unreadable")),
            }
        ]
    result = review_pages(pages, filename=path.name, facts=facts)
    result["method"] = (read or {}).get("method") or result.get("method")
    result["ocr_confidence"] = (read or {}).get("confidence")
    return result


def _link_review(case_id: str, review: dict, original_path: str, *, sample: bool = False) -> dict:
    case = db.get_case(case_id) or {}
    doc_type = requirement_of(review.get("doc_type") or "unknown")
    review["doc_type"] = doc_type
    prior = db.latest_file(case_id, doc_type)
    review["version"] = (prior.get("version") or 0) + 1 if prior else 1
    review["original_path"] = original_path
    if prior:
        review["diff"] = clause_diff(prior.get("extracted"), review.get("extracted"))
        requirements.reopen(case_id, doc_type, "replacement file")
    status = review.get("status") or "received"
    req = requirements.receive(case_id, doc_type, None, status)
    if req:
        review["requirement_id"] = req["id"]
    row = db.add_case_file(case_id, review, original_path)
    for component in review.get("components") or []:
        db.add_document_component(row["id"], case_id, component)
    identifiers = (review.get("extracted") or {}).get("fields") or {}
    if requirement_of(doc_type) == "authority" or any(
        requirement_of(item.get("document_type")) == "authority" for item in review.get("components") or []
    ):
        db.add_verification_record(
            case_id,
            kind="authority_lookup",
            source="document_identifiers",
            status="pending",
            identifiers={
                "usdot": (identifiers.get("usdot") or {}).get("value"),
                "mc_number": (identifiers.get("mc_number") or {}).get("value"),
                "legal_name": (identifiers.get("legal_name") or {}).get("value"),
            },
        )
    for component in review.get("components") or []:
        comp_req = requirement_of(component.get("document_type") or doc_type)
        if comp_req in {doc_type, "unknown"}:
            continue
        requirements.receive(case_id, comp_req, row["id"], component.get("status") or status)
    requirements.receive(case_id, doc_type, row["id"], row["status"])
    docs = list(case.get("documents") or [])
    if "returned" not in docs:
        docs.append("returned")
    summary = (review.get("extracted") or {}).get("_manager_summary")
    db.upsert_case(
        {
            "id": case_id,
            "status": "under_review",
            "next_action": (
                "Sample packet linked for demo review only — not a driver upload."
                if sample
                else (summary or "Human review of returned file — received is not approved. OCR is unverified.")
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


def ingest_upload(
    case_id: str,
    path: Path,
    attachment: dict | None = None,
    *,
    suggested_doc_type: str | None = None,
) -> dict:
    """Link a real chat/staff upload to the case checklist. Never approves."""
    case = db.get_case(case_id)
    if not case:
        raise FileNotFoundError("unknown case")
    path = Path(path)
    requirements.issue(case_id, case.get("task"), facts=case.get("facts") or {})
    fallback = ""
    # Chat stores a short redacted excerpt. Re-read the original; excerpt is last resort only.
    excerpt = (attachment or {}).get("ocr_text") or ""
    if excerpt and len(excerpt) < CHAT_EXCERPT_MAX:
        fallback = excerpt
    suggested = (suggested_doc_type or "").strip().lower() or None
    if suggested in {"null", "none", "not_sure"}:
        suggested = None
    review = review_path(
        path,
        facts=case.get("facts") or {},
        suggested=suggested,
        kind=(attachment or {}).get("kind"),
        fallback_text=fallback,
        filename=(attachment or {}).get("filename") or path.name,
    )
    guessed = review.get("doc_type") or "unknown"
    if suggested:
        review["suggested_doc_type"] = suggested
        review["guessed_doc_type"] = guessed
        if not review.get("components") or len(review.get("components") or []) <= 1:
            review["doc_type"] = suggested
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
            "suggestedDocType": suggested,
            "components": len(review.get("components") or []),
        },
    )
    return row


def run_review_job(job_id: str) -> dict | None:
    job = db.get_review_job(job_id)
    if not job:
        return None
    db.update_review_job(job_id, {"status": "running", "attempts": int(job.get("attempts") or 0) + 1})
    try:
        from app import ingest, media

        path = Path(job["path"])
        attachment = db.get_attachment(job["attachment_id"]) if job.get("attachment_id") else None
        if not attachment:
            processed = media.process(path, job.get("session_id"), job.get("case_id"), False)
            attachment = processed.get("attachment") or {}
        else:
            read = ocr.read_pages(path) if path.exists() else {"text": "", "confidence": None, "pages": []}
            excerpt = ingest.strip_pii(read.get("text") or "")[:CHAT_EXCERPT_MAX]
            attachment = db.save_attachment(
                {
                    **attachment,
                    "ocr_text": excerpt,
                    "ocr_confidence": read.get("confidence"),
                    "kind": attachment.get("kind") or media.classify_kind(path.name, read.get("text") or ""),
                }
            )
            try:
                from app import vision

                vision.upsert_image(attachment["id"], path)
            except Exception:
                pass
        row = ingest_upload(
            job["case_id"],
            Path(attachment.get("path") or path),
            attachment,
            suggested_doc_type=job.get("suggested_doc_type"),
        )
        db.update_review_job(job_id, {"status": "done", "file_id": row.get("id"), "error": None})
        return row
    except Exception as exc:
        db.update_review_job(job_id, {"status": "error", "error": type(exc).__name__})
        raise


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
        prior = db.latest_file(case_id, classify(source))
        prior_path = Path(prior["original_path"]) if prior and prior.get("original_path") else None
        if prior_path and ocr.same_file(source, prior_path):
            saved.append({**prior, "duplicate": True, "sample": True})
            continue
        original = ocr.store_original(case_id, source)
        review = review_path(Path(original["original_path"]), facts=case.get("facts") or {}, filename=source.name)
        review.update({"original_path": original["original_path"], "sample": True})
        row = _link_review(case_id, review, original["original_path"], sample=True)
        saved.append({**row, "sample": True})
    db.add_event("Sample document worker ran (demo only)", {"caseId": case_id, "files": len(saved)})
    return saved
