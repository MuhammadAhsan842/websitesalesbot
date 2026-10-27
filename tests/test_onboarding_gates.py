"""Conditional requirements, upload→checklist link, approve completeness gate."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, docworker, requirements


def _case(facts=None, task="setup_packet"):
    return db.upsert_case(
        {
            "session_id": "s1",
            "status": "collecting_documents",
            "task": task,
            "owner": "Unassigned desk",
            "facts": facts or {},
            "documents": [],
        }
    )


class ConditionalCatalog(unittest.TestCase):
    def test_noa_only_when_factoring(self):
        types = {doc for doc, _ in requirements.catalog_for("setup_packet", {})}
        self.assertIn("coi", types)
        self.assertNotIn("notice_of_assignment", types)
        self.assertNotIn("voided_check", types)
        factored = {
            "paymentArrangement": {"value": "factoring", "status": "user_stated"},
        }
        types = {doc for doc, _ in requirements.catalog_for("setup_packet", factored)}
        self.assertIn("notice_of_assignment", types)
        self.assertIn("voided_check", types)
        quick = {"paymentArrangement": {"value": "quick_pay", "status": "user_stated"}}
        types = {doc for doc, _ in requirements.catalog_for("setup_packet", quick)}
        self.assertIn("voided_check", types)
        self.assertNotIn("notice_of_assignment", types)


class ApproveGate(unittest.TestCase):
    def test_empty_packet_cannot_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                case = _case()
                requirements.issue(case["id"], "setup_packet", facts={})
                ready, blockers = requirements.ready_for_handoff(case["id"])
                self.assertFalse(ready)
                self.assertTrue(any(b.startswith("coi:") for b in blockers))
                self.assertTrue(any(b.startswith("w9:") for b in blockers))

    def test_ack_is_not_approve_and_decide_unblocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                case = _case()
                requirements.issue(case["id"], "setup_packet", facts={})
                for doc_type, _ in requirements.catalog_for("setup_packet", {}):
                    requirements.receive(case["id"], doc_type, f"file_{doc_type}", "received")
                db.acknowledge_case_files(case["id"])
                ready, _ = requirements.ready_for_handoff(case["id"])
                self.assertFalse(ready)
                for doc_type, _ in requirements.catalog_for("setup_packet", {}):
                    requirements.decide(case["id"], doc_type, "approve", reviewer="Staff desk", file_id=f"file_{doc_type}")
                ready, blockers = requirements.ready_for_handoff(case["id"])
                self.assertTrue(ready)
                self.assertEqual(blockers, [])


class UploadLinksChecklist(unittest.TestCase):
    def test_ingest_upload_creates_case_file_and_marks_received(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = _case()
                requirements.issue(case["id"], "setup_packet", facts={})
                upload = root / "coi-driver.jpeg"
                upload.write_bytes(b"fake-image")
                attachment = {
                    "id": "att1",
                    "filename": "coi-driver.jpeg",
                    "path": str(upload),
                    "ocr_text": "Certificate of Liability Insurance",
                    "ocr_confidence": 0.5,
                }
                row = docworker.ingest_upload(case["id"], upload, attachment)
                self.assertEqual(row["doc_type"], "coi")
                files = db.list_case_files(case["id"])
                self.assertEqual(len(files), 1)
                req = db.get_requirement(case["id"], "coi")
                self.assertIn(req["status"], {"received", "flagged"})
                self.assertEqual(req["current_file_id"], row["id"])
                snap = requirements.snapshot(case["id"])
                self.assertNotIn("coi", snap["outstanding"])
                self.assertIn("coi", snap["awaiting_review"])
                self.assertFalse(snap["ready_for_handoff"])


if __name__ == "__main__":
    unittest.main()
