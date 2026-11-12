"""Exercise the public upload/queue path through the actual CRM request builder."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app import db, docreport, requirements, zoho


class DeliveryFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db_patch = patch.object(db, "DB_PATH", self.root / "test.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init()
        self.session = db.create_session({"mcOwnership": {"value": "own_mc", "status": "user_stated"}})
        self.case = db.upsert_case({
            "session_id": self.session["id"], "opportunity_id": self.session["opportunity_id"],
            "task": "setup_packet", "status": "under_review", "facts": self.session["facts"],
            "documents": [],
        })
        self.session["case_id"] = self.case["id"]
        db.save_session(self.session)
        requirements.issue(self.case["id"], "setup_packet", facts=self.case["facts"])
        db.upsert_mirror({
            "id": "DEAL_TEST", "opportunity_id": self.case["opportunity_id"],
            "case_id": self.case["id"], "stage": "Onboarding", "human_version": 3, "data": {},
        })
        self.upload = self.root / "carrier-packet.pdf"
        self.upload.write_bytes(b"%PDF-1.7\noriginal test document bytes")
        self.calls = []

    def post(self, url, **kwargs):
        if url.endswith("/Deals/DEAL_TEST/Attachments"):
            name, handle, mime = kwargs["files"]["file"]
            self.calls.append(("attachment", name, handle.read()))
            remote = "ATTACHMENT_TEST"
        elif url.endswith("/Deals/DEAL_TEST/Notes"):
            self.calls.append(("report", kwargs["json"]["data"][0]))
            remote = "NOTE_TEST"
        elif url.endswith("/Tasks"):
            self.calls.append(("task", kwargs["json"]["data"][0]))
            remote = "TASK_TEST"
        else:
            raise AssertionError(f"Unexpected endpoint: {url}")
        return httpx.Response(200, json={"data": [{
            "status": "success", "code": "SUCCESS", "details": {"id": remote},
        }]}, request=httpx.Request("POST", url))


class DeliveryIntegration(DeliveryFixture, unittest.TestCase):
    def test_public_queue_sends_files_notes_and_tasks_without_writing_the_deal(self):
        zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        report = docreport.build(self.case["id"])
        zoho.publish_document_review(self.case["id"], report)
        with patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post), \
             patch.object(zoho, "_submit_live", side_effect=AssertionError("Document delivery must not write the Deal")):
            result = zoho.drain()
            zoho.drain()  # A successful retry must not POST the same deliveries again.
        self.assertEqual([call[0] for call in self.calls], ["attachment", "report", "task"])
        self.assertEqual(self.calls[0][1:], (self.upload.name, self.upload.read_bytes()))
        self.assertEqual(self.calls[1][1]["Note_Content"], report["text"])
        self.assertEqual(self.calls[2][1]["What_Id"], {"id": "DEAL_TEST"})
        self.assertTrue(all(row["status"] == "synced" for row in result))
        self.assertEqual(db.get_mirror(self.case["opportunity_id"])["human_version"], 3)

    def test_malformed_legacy_event_cannot_fall_back_to_a_deal_write(self):
        payload = zoho.record("fit_update", self.session, {})
        payload["scenario"] = "document_attachment"
        db.enqueue_outbox("legacy", "document_attachment", payload)
        with patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "_submit_live") as write:
            result = zoho.drain()
        self.assertEqual(result[0]["status"], "failed")
        write.assert_not_called()

    def test_reupload_repairs_an_old_event_marked_synced_as_a_deal(self):
        first = zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        old = db.loads(first["payload_json"], {})
        old.pop("crm_delivery", None)
        old.pop("automated", None)
        db.execute("UPDATE outbox SET payload_json=?,status='synced',zoho_id='DEAL_TEST' WHERE action_id=?",
                   (db.dumps(old), first["action_id"]))
        repaired = zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        self.assertEqual(repaired["action_id"], first["action_id"])
        self.assertEqual(repaired["status"], "queued")
        self.assertIsNone(repaired["zoho_id"])
        with patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post):
            zoho.drain()
        self.assertEqual(self.calls[0][0], "attachment")

    def test_document_delivery_does_not_expire_while_analysis_runs(self):
        event = zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        db.execute("UPDATE outbox SET created_at='2000-01-01T00:00:00+00:00' WHERE action_id=?", (event["action_id"],))
        with patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post):
            result = zoho.drain()
        self.assertEqual(result[0]["status"], "synced")
        self.assertEqual(self.calls[0][0], "attachment")

    def test_failed_attachment_prevents_a_verified_status_even_after_a_note_succeeds(self):
        attachment = zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        publication = zoho.publish_document_review(self.case["id"])
        db.mark_outbox(attachment["action_id"], "failed", "Network error")
        for event in [publication["note"], publication["task"]]:
            db.mark_outbox(event["action_id"], "synced")
            db.set_outbox_zoho(event["action_id"], "REMOTE_TEST")
        status = zoho.sync_status(case_id=self.case["id"])
        self.assertFalse(status["verified"])

    def test_attachment_record_error_with_an_id_is_not_a_delivery_receipt(self):
        zoho.queue_file_delivery(self.case["id"], str(self.upload), self.upload.name, "fixture-digest")
        rejected = httpx.Response(200, json={"data": [{
            "status": "error", "code": "AUTHORIZATION_ERROR", "message": "Denied", "details": {"id": "IGNORED"},
        }]}, request=httpx.Request("POST", "https://example.test"))
        with patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", return_value=rejected):
            result = zoho.drain()
        self.assertEqual(result[0]["status"], "failed")


class UploadDispatch(DeliveryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_reupload_preserves_a_reviewed_requirement_and_reuses_its_file(self):
        from app import main, media

        row = db.add_case_file(self.case["id"], {
            "doc_type": "coi", "filename": self.upload.name, "status": "received", "findings": [],
        }, str(self.upload))
        requirements.receive(self.case["id"], "coi", row["id"], "awaiting_review")
        requirements.decide(self.case["id"], "coi", "approve", reviewer="Test staff", file_id=row["id"])
        with patch.object(main, "ROOT", self.root), patch.object(media, "ROOT", self.root / "stored"), \
             patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post):
            media.store_stub(self.upload, self.session["id"], self.case["id"], self.upload.name)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                response = await api.post(f"/v1/session/{self.session['id']}/attachment",
                                          data={"doc_type": "coi"},
                                          files={"file": (self.upload.name, self.upload.read_bytes(), "application/pdf")})
        self.assertEqual(response.status_code, 200)
        current = db.get_requirement(self.case["id"], "coi")
        self.assertEqual(current["status"], "approved")
        self.assertEqual(current["current_file_id"], row["id"])
        self.assertEqual(len(db.list_case_files(self.case["id"])), 1)

    async def test_http_upload_delivers_original_even_if_analysis_fails(self):
        from app import main, media

        with patch.object(main, "ROOT", self.root), patch.object(media, "ROOT", self.root / "stored"), \
             patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post), \
             patch.object(main.docworker, "run_review_job", side_effect=RuntimeError("Test review failure")):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False), base_url="http://test") as api:
                response = await api.post(f"/v1/session/{self.session['id']}/attachment",
                                          files={"file": (self.upload.name, self.upload.read_bytes(), "application/pdf")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call[0] for call in self.calls], ["attachment"])
        self.assertEqual(self.calls[0][1:], (self.upload.name, self.upload.read_bytes()))

    async def test_http_upload_delivers_a_completed_report_without_another_turn(self):
        from app import docreview, docworker, main, media

        def review_job(job_id):
            job = db.get_review_job(job_id)
            result = docreview.review_pages([{
                "page": 1, "text": "CERTIFICATE OF LIABILITY INSURANCE\nCERTIFICATE HOLDER\n\nCANCELLATION\nSHOULD ANY",
                "method": "test", "unreadable": False,
            }], filename=self.upload.name, suggested="coi", facts=self.case["facts"])
            return docworker._link_review(self.case["id"], result, job["path"])

        with patch.object(main, "ROOT", self.root), patch.object(media, "ROOT", self.root / "stored"), \
             patch.object(zoho, "mode", return_value="live"), patch.object(zoho, "access_token", return_value="test"), \
             patch.object(zoho.httpx, "post", side_effect=self.post), patch.object(docworker, "run_review_job", side_effect=review_job):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                response = await api.post(f"/v1/session/{self.session['id']}/attachment",
                                          files={"file": (self.upload.name, self.upload.read_bytes(), "application/pdf")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call[0] for call in self.calls], ["attachment", "report", "task"])
