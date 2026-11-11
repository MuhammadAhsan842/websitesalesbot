"""Case-wide review, repeat-safe jobs, and Zoho document delivery."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DOC_REVIEW_GEMINI"] = "off"

from app import db, docworker, requirements, zoho

COI = """
CERTIFICATE OF LIABILITY INSURANCE
INSURED FREIGHT FUSION LLC
CERTIFICATE HOLDER

CANCELLATION
SHOULD ANY OF THE ABOVE DESCRIBED POLICIES BE CANCELLED
"""


def _case(task="lease_agreement"):
    session = db.create_session()
    return db.upsert_case(
        {
            "session_id": session["id"],
            "opportunity_id": session["opportunity_id"],
            "status": "collecting_documents",
            "task": task,
            "owner": "Unassigned desk",
            "facts": {"mcOwnership": {"value": "no_own_mc", "status": "user_stated"}},
            "documents": [],
        }
    )


class CaseWideReport(unittest.TestCase):
    def test_clean_photo_does_not_clear_a_blank_holder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case()
                requirements.issue(case["id"], "lease_agreement", facts=case["facts"])
                coi = root / "insurance.pdf"
                coi.write_bytes(b"coi")
                photo = root / "truck.jpg"
                photo.write_bytes(b"photo")
                docworker.ingest_upload(
                    case["id"],
                    coi,
                    {"filename": "insurance.pdf", "path": str(coi), "ocr_text": COI},
                    suggested_doc_type="coi",
                )
                docworker.ingest_upload(
                    case["id"],
                    photo,
                    {"filename": "truck.jpg", "path": str(photo), "ocr_text": ""},
                    suggested_doc_type="equipment_photos",
                )
                current = db.get_case(case["id"])
                action = (current.get("next_action") or "").lower()
                self.assertIn("information_missing", action)
                self.assertIn("certificate of insurance", action)
                self.assertNotIn("no configured issue", action)
                req = db.get_requirement(case["id"], "coi")
                self.assertEqual(req["status"], "information_missing")


class RepeatSafeJobs(unittest.TestCase):
    def test_replaying_a_job_does_not_create_another_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case()
                upload = root / "insurance.pdf"
                upload.write_bytes(COI.encode())
                job = db.add_review_job(
                    {
                        "case_id": case["id"],
                        "path": str(upload),
                        "suggested_doc_type": "coi",
                        "status": "queued",
                    }
                )
                with patch.object(docworker.ocr, "read_pages", return_value={"pages": [{"page": 1, "text": COI, "method": "test", "unreadable": False}], "text": COI, "method": "test", "confidence": 90, "ocr_used": False, "unreadable": False}):
                    first = docworker.run_review_job(job["id"])
                    second = docworker.run_review_job(job["id"])
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(len(db.list_case_files(case["id"])), 1)
                self.assertEqual(first["version"], 1)


class ComponentApproval(unittest.TestCase):
    def test_packet_component_can_be_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case("setup_packet")
                requirements.issue(case["id"], "setup_packet", facts={})
                packet = root / "packet.pdf"
                packet.write_text("placeholder")
                file_row = db.add_case_file(
                    case["id"],
                    {"doc_type": "w9", "filename": "packet.pdf", "status": "received", "flags": [], "extracted": {}},
                    str(packet),
                )
                db.add_document_component(
                    file_row["id"],
                    case["id"],
                    {"document_type": "coi", "pages": [2], "fields": {}, "findings": [], "status": "awaiting_review"},
                )
                requirements.receive(case["id"], "coi", file_row["id"], "awaiting_review")
                decided = requirements.decide(case["id"], "coi", "approve", reviewer="Manager", file_id=file_row["id"])
                self.assertEqual(decided["status"], "approved")


class LeaseRequirement(unittest.TestCase):
    def test_four_uploads_do_not_clear_lease_on_without_the_agreement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case()
                requirements.issue(case["id"], "lease_agreement", facts=case["facts"])
                types = [doc for doc, _ in requirements.catalog_for("lease_agreement", case["facts"])]
                self.assertIn("lease", types)
                for doc_type in types:
                    if doc_type == "lease":
                        continue
                    upload = root / f"{doc_type}.pdf"
                    upload.write_bytes(b"%PDF")
                    row = db.add_case_file(
                        case["id"],
                        {"doc_type": doc_type, "filename": upload.name, "status": "received", "flags": [], "extracted": {}},
                        str(upload),
                    )
                    requirements.receive(case["id"], doc_type, row["id"], "awaiting_review")
                    requirements.decide(case["id"], doc_type, "approve", reviewer="Manager")
                ready, blockers = requirements.ready_for_handoff(case["id"])
                self.assertFalse(ready)
                self.assertTrue(any(item.startswith("lease:") for item in blockers))


class ZohoDelivery(unittest.TestCase):
    def test_review_queues_report_and_original_without_confirming_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"), patch.object(zoho, "mode", return_value="offline"):
                db.init()
                case = _case()
                upload = root / "insurance.pdf"
                upload.write_bytes(b"coi-bytes")
                docworker.ingest_upload(
                    case["id"],
                    upload,
                    {"filename": "insurance.pdf", "path": str(upload), "ocr_text": COI},
                    suggested_doc_type="coi",
                )
                zoho.drain()
                rows = db.list_outbox(case_id=case["id"])
                kinds = {row["kind"] for row in rows}
                self.assertIn("document_report", kinds)
                self.assertIn("document_attachment", kinds)
                self.assertIn("document_task", kinds)
                self.assertTrue(all(row["status"] == "local_only" for row in rows))
                status = zoho.sync_status(case_id=case["id"])
                self.assertFalse(status["verified"])

    def test_failed_delivery_can_be_queued_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case()
                first = zoho.queue_file_delivery(case["id"], str(root / "insurance.pdf"), "insurance.pdf", "abc123")
                db.mark_outbox(first["action_id"], "failed", "timeout")
                second = zoho.queue_file_delivery(case["id"], str(root / "insurance.pdf"), "insurance.pdf", "abc123")
                self.assertEqual(second["action_id"], first["action_id"])
                self.assertEqual(second["status"], "queued")


if __name__ == "__main__":
    unittest.main()
