"""Recover historical uploads and verify their visibility on the intended Deal."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app import db, ingest, recover_document_handoff as recovery, requirements, zoho


class DocumentRecovery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        db_patch = patch.object(db, "DB_PATH", self.root / "server.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        db.init()
        self.session = db.create_session({"mcOwnership": {"value": "own_mc", "status": "user_stated"}})
        self.inquiry = self.session["opportunity_id"]
        self.deal = "DEAL_TEST"
        self.case = db.upsert_case({"session_id": self.session["id"], "opportunity_id": self.inquiry,
                                   "task": "setup_packet", "status": "under_review", "facts": self.session["facts"]})
        requirements.issue(self.case["id"], "setup_packet", facts=self.case["facts"])
        db.upsert_mirror({"id": self.deal, "opportunity_id": self.inquiry, "case_id": self.case["id"],
                          "stage": "Onboarding", "human_version": 3, "data": {}})
        self.files = []
        for index, filename in enumerate(["carrier-packet.pdf", "truck-front.jpg", "truck-side.jpg", "trailer.jpg"]):
            path = self.root / filename
            path.write_bytes(f"original test file {index}".encode())
            digest = ingest.sha256_file(path)
            db.save_attachment({"session_id": self.session["id"], "case_id": self.case["id"], "filename": filename,
                                "path": str(path), "sha256": digest, "kind": "document"})
            # Historical bug: an ordinary Deal payload was saved as a synced attachment.
            payload = zoho.record("fit_update", self.session, {})
            payload["scenario"] = "document_attachment"
            action = f"{self.inquiry}:attachment:{digest}"
            db.enqueue_outbox(action, "document_attachment", payload)
            db.mark_outbox(action, "synced")
            db.set_outbox_zoho(action, self.deal)
            self.files.append((filename, path.read_bytes()))
        self.remote_files = {}
        self.remote_notes = {}
        self.posts = []
        self.hide_files = False
        for name, value in [("access_token", "test"), ("mode", "live"), ("api_base", "https://crm.test/crm/v6")]:
            p = patch.object(zoho, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        for name, method in [("get", self.get), ("post", self.post)]:
            p = patch.object(zoho.httpx, name, side_effect=method)
            p.start()
            self.addCleanup(p.stop)

    def response(self, url, payload=None, content=None):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, **({"content": content} if content is not None else {"json": payload}))

    def get(self, url, **kwargs):
        if url.endswith(f"/Deals/{self.deal}"):
            return self.response(url, {"data": [{"id": self.deal, "Description": f"Inquiry ID: {self.inquiry}."}]})
        if url.endswith("/Attachments"):
            rows = [] if self.hide_files else [{"id": key, "File_Name": value[0]} for key, value in self.remote_files.items()]
            return self.response(url, {"data": rows})
        if "/Attachments/" in url:
            return self.response(url, content=self.remote_files[url.rsplit("/", 1)[-1]][1])
        if url.endswith("/Notes"):
            return self.response(url, {"data": [{"id": key} for key in self.remote_notes]})
        raise AssertionError(f"Unexpected GET: {url}")

    def post(self, url, **kwargs):
        self.posts.append(url)
        if url.endswith(f"/Deals/{self.deal}/Attachments"):
            filename, handle, _ = kwargs["files"]["file"]
            key = f"ATT_{len(self.remote_files) + 1}"
            self.remote_files[key] = (filename, handle.read())
        elif url.endswith(f"/Deals/{self.deal}/Notes"):
            key = f"NOTE_{len(self.remote_notes) + 1}"
            self.remote_notes[key] = kwargs["json"]["data"][0]
        elif url.endswith("/Tasks"):
            key = "TASK_TEST"
        else:
            raise AssertionError(f"Unexpected POST: {url}")
        return self.response(url, {"data": [{"status": "success", "code": "SUCCESS", "details": {"id": key}}]})

    def test_all_originals_and_report_are_visible_after_replaying_legacy_successes(self):
        result = recovery.send(recovery.plan(self.inquiry, self.deal))
        self.assertTrue(result["verified"])
        self.assertTrue(result["report_confirmed"])
        self.assertCountEqual(list(self.remote_files.values()), self.files)
        self.assertTrue(all(row["attachment_id"] != self.deal for row in result["attachments"]))

    def test_repeating_recovery_does_not_create_duplicate_remote_documents(self):
        request = recovery.plan(self.inquiry, self.deal)
        recovery.send(request)
        count = len(self.posts)
        again = recovery.send(request)
        self.assertTrue(again["verified"])
        self.assertEqual(len(self.posts), count)

    def test_existing_original_is_reused_after_matching_remote_bytes(self):
        self.remote_files["ALREADY_PRESENT"] = self.files[0]
        result = recovery.send(recovery.plan(self.inquiry, self.deal))
        self.assertTrue(result["verified"])
        self.assertEqual(len(self.remote_files), 4)
        self.assertEqual(sum(url.endswith("/Attachments") for url in self.posts), 3)

    def test_wrong_saved_deal_mapping_is_rejected_before_sending(self):
        with self.assertRaisesRegex(ValueError, "saved Deal ID differs"):
            recovery.plan(self.inquiry, "ANOTHER_DEAL")
        self.assertFalse(self.posts)

    def test_missing_connection_does_not_claim_delivery(self):
        with patch.object(zoho, "access_token", return_value=None):
            with self.assertRaisesRegex(ValueError, "not connected"):
                recovery.send(recovery.plan(self.inquiry, self.deal))
        self.assertFalse(self.posts)

    def test_post_receipts_alone_do_not_count_as_visible_attachments(self):
        self.hide_files = True
        result = recovery.send(recovery.plan(self.inquiry, self.deal))
        self.assertFalse(result["verified"])
        self.assertTrue(all(not row["confirmed"] for row in result["attachments"]))

    def test_recovery_does_not_send_or_expire_other_inquiries(self):
        other = db.create_session()
        event = zoho.queue_inquiry(other)
        db.execute("UPDATE outbox SET created_at='2000-01-01T00:00:00+00:00' WHERE action_id=?", (event["action_id"],))
        recovery.send(recovery.plan(self.inquiry, self.deal))
        untouched = db.execute("SELECT status FROM outbox WHERE action_id=?", (event["action_id"],), fetch="one")
        self.assertEqual(untouched["status"], "queued")

    def test_offline_local_records_are_replayed_after_connecting(self):
        for item in recovery.plan(self.inquiry, self.deal)["files"]:
            event = zoho.queue_file_delivery(self.case["id"], item["path"], item["filename"], item["sha256"])
            db.mark_outbox(event["action_id"], "local_only")
            db.set_outbox_zoho(event["action_id"], "zcrm_local_attachment")
        result = recovery.send(recovery.plan(self.inquiry, self.deal))
        self.assertTrue(result["verified"])
        self.assertEqual(len(self.remote_files), 4)
