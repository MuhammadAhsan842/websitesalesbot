"""Replay accepted local uploads onto one verified Deal, then read back the related lists.

Run in the server's Python environment, from its repository. No credentials are printed.
Without --send this only describes the local recovery plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import httpx

from app import db, ingest, zoho


def plan(inquiry_id: str, deal_id: str) -> dict:
    if not db.DB_PATH.is_file():
        raise ValueError("Server database not found. Run from the server's repository/environment.")
    cases = db.execute("SELECT id FROM cases WHERE opportunity_id=?", (inquiry_id,), fetch="all") or []
    if len(cases) != 1:
        raise ValueError("Expected exactly one onboarding case for this inquiry; no files were sent.")
    case = db.get_case(cases[0]["id"])
    mirror = db.get_mirror(inquiry_id) or {}
    stored_deal = str(mirror.get("id") or "")
    if stored_deal and not stored_deal.startswith("zcrm_local_") and stored_deal != deal_id:
        raise ValueError("The saved Deal ID differs from --deal-id; resolve the mapping before sending files.")
    sources = db.list_attachments(case_id=case["id"])
    if case.get("session_id"):
        sources += [row for row in db.list_attachments(session_id=case["session_id"])
                    if row.get("case_id") in {None, case["id"]}]
    files, missing, seen = [], [], set()
    for row in sources:
        path = Path(row.get("path") or "")
        filename = str(row.get("filename") or path.name).replace("\\", "/").rsplit("/", 1)[-1]
        if not path.is_file():
            if filename not in missing:
                missing.append(filename)
            continue
        digest = ingest.sha256_file(path)
        if digest in seen:
            continue
        seen.add(digest)
        files.append({"path": str(path), "filename": filename, "sha256": digest})
    if not files:
        raise ValueError("No accepted local uploads found for this inquiry. Check the database and stored file paths.")
    return {"inquiry_id": inquiry_id, "deal_id": deal_id, "case_id": case["id"], "files": files, "missing_files": missing}


def _related(deal_id: str, relationship: str, headers: dict) -> list[dict]:
    rows = []
    for page in range(1, 101):
        response = httpx.get(f"{zoho.api_base()}/Deals/{deal_id}/{relationship}", headers=headers,
                             params={"page": page, "per_page": 200}, timeout=30)
        response.raise_for_status()
        if response.status_code == 204:
            return rows
        payload = response.json()
        if "data" not in payload:
            raise RuntimeError(f"Zoho did not return a readable {relationship} list.")
        rows.extend(payload.get("data") or [])
        if not (payload.get("info") or {}).get("more_records"):
            return rows
    raise RuntimeError("Related-list pagination did not finish; verification is incomplete.")


def _event(action_id: str) -> dict:
    return db.execute("SELECT * FROM outbox WHERE action_id=?", (action_id,), fetch="one") or {}


def _requeue(event: dict) -> None:
    # The operator requested replay and a read-back did not confirm this receipt.
    db.execute("UPDATE outbox SET status='queued',zoho_id=NULL,last_error=NULL,updated_at=? WHERE action_id=?",
               (db.now(), event["action_id"]))


def send(recovery: dict) -> dict:
    token = zoho.access_token()
    if not token:
        raise ValueError("Zoho is not connected in this server environment; local uploads have not been sent.")
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    inquiry, deal_id, case_id = recovery["inquiry_id"], recovery["deal_id"], recovery["case_id"]
    response = httpx.get(f"{zoho.api_base()}/Deals/{deal_id}", headers=headers, timeout=30)
    response.raise_for_status()
    records = response.json().get("data") or []
    if len(records) != 1 or str(records[0].get("id")) != deal_id:
        raise ValueError("Zoho did not confirm the selected Deal; no documents were queued.")
    mentioned = set(re.findall(r"\bopp_[A-Za-z0-9_-]+\b", str(records[0].get("Description") or "")))
    if mentioned and inquiry not in mentioned:
        raise ValueError("The Deal description identifies a different inquiry; no documents were queued.")
    mirror = db.get_mirror(inquiry) or {}
    if str(mirror.get("id") or "") != deal_id:
        if inquiry not in mentioned:
            raise ValueError("Cannot verify this inquiry's Deal mapping. No documents were queued.")
        db.upsert_mirror({"id": deal_id, "opportunity_id": inquiry, "case_id": case_id,
                          "module": "Deals", "stage": records[0].get("Stage"),
                          "human_version": mirror.get("human_version") or 0, "data": mirror.get("data") or {}})
    before = _related(deal_id, "Attachments", headers)
    present_ids = {str(row.get("id")) for row in before}
    actions = []
    for item in recovery["files"]:
        queued = zoho.queue_file_delivery(case_id, item["path"], item["filename"], item["sha256"])
        if not queued:
            raise ValueError("Could not associate a file with the selected inquiry.")
        actions.append((item["filename"], queued["action_id"]))
        if queued.get("status") == "synced" and str(queued.get("zoho_id")) in present_ids:
            continue
        # A lost POST response can leave a real file behind. Reuse it only after comparing bytes.
        adopted = None
        for remote in before:
            if remote.get("File_Name") != item["filename"] or not remote.get("id"):
                continue
            original = httpx.get(f"{zoho.api_base()}/Deals/{deal_id}/Attachments/{remote['id']}",
                                 headers=headers, timeout=60)
            original.raise_for_status()
            if hashlib.sha256(original.content).hexdigest() == item["sha256"]:
                adopted = str(remote["id"])
                break
        if adopted:
            db.mark_outbox(queued["action_id"], "synced")
            db.set_outbox_zoho(queued["action_id"], adopted)
            db.add_event("Document recovery confirmed existing attachment bytes", {"caseId": case_id, "attachmentId": adopted})
        else:
            _requeue(queued)
    # Send originals first; report publication must not block their delivery.
    zoho.drain(opportunity_id=inquiry)
    publication = zoho.publish_document_review(case_id)
    if not publication:
        raise ValueError("Original delivery attempted, but a review report could not be queued.")
    notes_before = _related(deal_id, "Notes", headers)
    note = _event(publication["note"]["action_id"])
    if note.get("status") != "synced" or str(note.get("zoho_id")) not in {str(row.get("id")) for row in notes_before}:
        _requeue(note)
    task = publication.get("task")
    if task and task.get("status") in {"local_only", "failed", "timeout"}:
        _requeue(task)
    zoho.drain(opportunity_id=inquiry)
    attached = {str(row.get("id")) for row in _related(deal_id, "Attachments", headers)}
    notes = {str(row.get("id")) for row in _related(deal_id, "Notes", headers)}
    outcomes = []
    for filename, action in actions:
        event = _event(action)
        remote_id = event.get("zoho_id")
        confirmed = event.get("status") == "synced" and str(remote_id) in attached
        outcomes.append({"filename": filename, "confirmed": confirmed, "attachment_id": remote_id,
                         "status": event.get("status"), "error": event.get("last_error")})
    note = _event(publication["note"]["action_id"])
    report_confirmed = note.get("status") == "synced" and str(note.get("zoho_id")) in notes
    verified = all(row["confirmed"] for row in outcomes) and report_confirmed and not recovery["missing_files"]
    return {"inquiry_id": inquiry, "deal_id": deal_id, "attachments": outcomes,
            "report_confirmed": report_confirmed, "report_id": note.get("zoho_id"),
            "missing_files": recovery["missing_files"], "verified": verified,
            "note": "Confirmed by reading this Deal's related lists. This is delivery, not document approval."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inquiry", required=True)
    parser.add_argument("--deal-id", required=True)
    parser.add_argument("--send", action="store_true", help="Send stored documents using this server's Zoho connection")
    args = parser.parse_args(argv)
    try:
        recovery = plan(args.inquiry, args.deal_id)
        if args.send:
            result = send(recovery)
            print(json.dumps(result, indent=2))
            return 0 if result["verified"] else 1
        print(json.dumps({**recovery, "send": False}, indent=2))
        return 0
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        # HTTP exception strings may include sensitive request details. Print only structured API errors.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Zoho request failed; inspect the server's CRM connection and access."
        print(json.dumps({"verified": False, "error": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
