"""HTTP/graph/database regressions; no live model, CRM, audio or production data."""

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app import db, examples, graph, main, qwen, requirements, retrieve, tasks, workflows, zoho


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class InquiryWorkflows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(db, "DB_PATH", root / "test.db"))
        self.stack.enter_context(patch.object(zoho, "access_token", return_value=None))
        self.stack.enter_context(patch.object(zoho, "drain", return_value=[]))
        self.stack.enter_context(patch.object(examples, "search", return_value=[]))
        self.stack.enter_context(patch.object(retrieve, "search", return_value=[]))
        self.model = self.stack.enter_context(patch.object(qwen, "propose", new=AsyncMock(
            return_value={"intent": "general", "facts": [], "action": "none"})))
        self.stack.enter_context(patch.object(main.app.state, "graph", graph.build_graph(InMemorySaver()), create=True))
        db.init()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.session = db.create_session(facts(
            equipment="box_truck", trailerLength="26ft", mcOwnership="no_own_mc", insurance="needs_insurance",
            operatingMode="local", milesPerDay="500-600", weekdaySchedule="monday_friday", operatingArea="Phoenix"))
        self.sid = self.session["id"]

    async def say(self, text, **extra):
        response = await self.client.post("/v1/turn", json={"session_id": self.sid, "text": text, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def request_complete_callback(self):
        return await self.say("Call me at +1 469-555-0199, preferred time 4pm, timezone America/Chicago on 2030-12-15")

    async def test_callback_survives_reloaded_graph_and_separate_contact_turns(self):
        first = await self.say("Call me")
        self.assertEqual(first["workflows"]["callback"]["status"], "collecting")
        self.assertEqual(first["channel"], "chat")
        # A new graph has no previous checkpoint; pending work comes from SQLite.
        main.app.state.graph = graph.build_graph(InMemorySaver())
        phone = await self.say("+1 469-555-0199")
        self.assertEqual(phone["workflows"]["callback"]["next_field"], "callbackTime")
        when = await self.say("4pm")
        self.assertEqual(when["workflows"]["callback"]["next_field"], "callbackTimezone")
        zone = await self.say("Chicago")
        self.assertEqual(zone["workflows"]["callback"]["next_field"], "callbackDate")
        done = await self.say("2030-12-15")
        self.assertEqual(done["workflows"]["callback"]["status"], "requested")
        self.assertEqual(done["workflows"]["callback"]["local_time"], "16:00")
        self.assertIn("not confirmed", done["text"])
        saved = db.get_session(self.sid)
        self.assertEqual(saved["channel"], "chat")
        self.assertFalse(saved["identity_confirmed"])
        self.assertEqual(saved["facts"]["equipment"]["value"], "box_truck")
        self.assertEqual(saved["facts"]["trailerLength"]["value"], "26ft")
        self.assertEqual(saved["facts"]["operatingArea"]["value"], "Phoenix")
        self.assertEqual(self.model.await_count, 5)

    async def test_request_includes_date_and_requires_phone_country(self):
        reply = await self.say("Call me, my number is 03124567497, timezone Chicago, preferred time 4pm")
        self.assertEqual(reply["workflows"]["callback"]["status"], "collecting")
        self.assertEqual(reply["workflows"]["callback"]["next_field"], "phone")
        self.assertIn("country code", reply["text"])
        self.assertIsNone(db.get_session(self.sid)["case_id"])
        self.assertEqual(db.get_workflow(self.sid, "callback")["data"]["phone_raw"], "03124567497")

    async def test_combined_details_and_http_retry_are_duplicate_safe(self):
        first = await self.request_complete_callback()
        self.assertEqual(first["workflows"]["callback"]["status"], "requested")
        repeated = await self.say("Call me", turn_id="callback_retry")
        count = len(db.list_cases())
        again = await self.say("Call me", turn_id="callback_retry")
        self.assertEqual(repeated, again)
        self.assertEqual(len(db.list_cases()), count)
        self.assertEqual(first["workflows"]["callback"]["version"], again["workflows"]["callback"]["version"])

    async def test_turn_retry_key_is_scoped_to_session(self):
        first = await self.say("Call me", turn_id="same-client-key")
        other = db.create_session()
        self.sid = other["id"]
        second = await self.say("Talk here", turn_id="same-client-key")
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertNotIn("callback", second["workflows"])
        self.assertIn("browser_voice", second["workflows"])

    async def test_number_correction_updates_existing_callback(self):
        first = await self.request_complete_callback()
        corrected = await self.say("Sorry, my number is +1 214-555-0123")
        self.assertEqual(first["case_id"], corrected["case_id"])
        self.assertEqual(corrected["workflows"]["callback"]["phone_last4"], "0123")
        self.assertEqual(corrected["workflows"]["callback"]["status"], "requested")
        self.assertEqual(db.get_session(self.sid)["facts"]["equipment"]["value"], "box_truck")

    async def test_invalid_corrected_time_reopens_collection(self):
        await self.request_complete_callback()
        reply = await self.say("Preferred time 29:90")
        self.assertEqual(reply["workflows"]["callback"]["status"], "collecting")
        self.assertEqual(reply["workflows"]["callback"]["next_field"], "callbackTime")

    async def test_new_request_after_cancellation_needs_new_date(self):
        await self.request_complete_callback()
        await self.say("Cancel my callback")
        reply = await self.say("Call me")
        self.assertEqual(reply["workflows"]["callback"]["status"], "collecting")
        self.assertEqual(reply["workflows"]["callback"]["next_field"], "callbackDate")

    async def test_history_keeps_callback_progress_and_does_not_offer_qualification_chips(self):
        await self.say("Call me")
        history = await self.client.get(f"/v1/session/{self.sid}")
        self.assertEqual(history.json()["workflows"]["callback"]["next_field"], "phone")
        self.assertEqual(history.json()["chips"], [])

    async def test_model_name_does_not_silently_disable_examples(self):
        with patch.dict("os.environ", {"QWEN_MODEL": "agoc-qwen4b-test", "AGOC_SKIP_EXAMPLES": "0"}):
            await self.say("What equipment do you support?")
            examples.search.assert_called_once()

    async def test_fee_question_interrupts_and_collection_resumes(self):
        await self.say("Call me")
        reply = await self.say("What is the fee?")
        self.assertNotIn("What number", reply["text"])
        self.assertEqual(reply["workflows"]["callback"]["status"], "collecting")
        reply = await self.say("+1 469-555-0199")
        self.assertEqual(reply["workflows"]["callback"]["next_field"], "callbackTime")

    async def test_callback_preserves_insurance_review_case_and_stage(self):
        session = db.get_session(self.sid)
        tasks.persist_human_task(session, "insurance_quote", "manager_requested", "Review insurance options", "Review requested")
        case_id = session["case_id"]
        reply = await self.request_complete_callback()
        case = db.get_case(case_id)
        self.assertEqual(reply["case_id"], case_id)
        self.assertEqual(case["task"], "insurance_quote")
        self.assertEqual(case["status"], "manager_requested")
        self.assertEqual(case["next_action"], "Review insurance options")
        self.assertIn("callback", case["related_tasks"])

    async def test_cancel_keeps_purpose_and_is_truthful_after_takeover(self):
        await self.request_complete_callback()
        session = db.get_session(self.sid)
        session["manager_accepted"] = True
        db.save_session(session)
        reply = await self.say("Cancel my callback")
        self.assertEqual(reply["workflows"]["callback"]["status"], "cancelled")
        self.assertIn("cancelled", reply["text"])
        status = zoho.record("fit_update", db.get_session(self.sid), {})["zoho"]["Description"]
        self.assertIn("Do not call", status)

    async def test_negated_cancellation_does_not_cancel(self):
        await self.request_complete_callback()
        reply = await self.say("Please don't cancel my callback")
        self.assertEqual(reply["workflows"]["callback"]["status"], "requested")

    async def test_human_takeover_prevents_collecting_automatic_callback(self):
        await self.say("Call me")
        session = db.get_session(self.sid)
        session["manager_accepted"] = True
        db.save_session(session)
        reply = await self.say("+1 469-555-0199")
        self.assertEqual(reply["workflows"]["callback"]["status"], "collecting")
        self.assertIn("stay out of the way", reply["text"])

    async def test_voice_request_never_claims_audio_or_identity_connected(self):
        reply = await self.say("Talk here")
        self.assertEqual(reply["channel"], "chat")
        self.assertEqual(reply["workflows"]["browser_voice"]["status"], "unavailable")
        self.assertFalse(reply["workflows"]["browser_voice"]["connected"])
        self.assertFalse(db.get_session(self.sid)["identity_confirmed"])
        self.assertEqual(reply["text"].count("?"), 0)

    async def test_readiness_routes_to_quote_and_cannot_be_approved(self):
        reply = await self.say("I'm ready to start")
        case = db.get_case(reply["case_id"])
        self.assertEqual(case["task"], "insurance_quote")
        self.assertEqual({r["doc_type"] for r in db.list_requirements(case["id"])}, {"licence", "registration"})
        for row in db.list_requirements(case["id"]):
            requirements.decide(case["id"], row["doc_type"], "waive", "Test reviewer", "Test quote intake waiver")
        ready, blockers = requirements.ready_for_handoff(case["id"])
        self.assertFalse(ready)
        self.assertIn("insurance_quote_only", blockers)
        self.assertIn("insurance_not_approved", blockers)
        for act in ("approve", "production"):
            response = await self.client.post(f"/v1/cases/{case['id']}/act", json={"act": act})
            self.assertEqual(response.status_code, 409)

    async def test_fit_update_preserves_review_context(self):
        session = db.get_session(self.sid)
        tasks.persist_human_task(session, "insurance_quote", "manager_requested", "Confirm insurance options and charges", "Review requested")
        description = zoho.record("fit_update", session, {})["zoho"]["Description"]
        self.assertIn("insurance_quote", description)
        self.assertIn("Confirm insurance options and charges", description)
        self.assertIn("500-600", description)
        self.assertIn("26ft", description.replace(" ", ""))

    async def test_full_contact_number_is_not_exposed_in_progress(self):
        reply = await self.request_complete_callback()
        progress = reply["workflows"]["callback"]
        self.assertEqual(progress["phone_last4"], "0199")
        self.assertNotIn("phone_raw", progress)
        self.assertNotIn("phone_e164_candidate", progress)

    async def test_public_assets_are_served_but_project_files_are_private(self):
        for path in ("/", "/widget.js", "/staff.html"):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        for path in ("/app/main.py", "/.git/config", "/.env", "/data/zoho_token.json", "/requirements.txt"):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    async def test_retry_reconciles_a_workflow_saved_before_case_creation(self):
        with patch.object(graph, "persist_human_task", side_effect=RuntimeError("Injected handoff failure")):
            with self.assertRaises(RuntimeError):
                await self.request_complete_callback()
        self.assertEqual(db.get_workflow(self.sid, "callback")["status"], "requested")
        reply = await self.request_complete_callback()
        self.assertTrue(reply["case_id"])
        self.assertEqual(db.get_case(reply["case_id"])["task"], "callback")
        self.assertEqual(len(db.list_cases()), 1)


class WorkflowRepository(unittest.TestCase):
    def test_stale_writer_rejected_without_losing_saved_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", Path(tmp) / "test.db"):
            db.init()
            session = db.create_session()
            row = db.save_workflow(session["id"], "callback", "collecting", {})
            updated = db.save_workflow(session["id"], "callback", "requested", {"test": True}, row["version"])
            with self.assertRaises(ValueError):
                db.save_workflow(session["id"], "callback", "collecting", {}, row["version"])
            self.assertEqual(db.get_workflow(session["id"], "callback")["version"], updated["version"])
            db.init()  # Migration is additive and repeatable.
            self.assertEqual(db.get_workflow(session["id"], "callback")["status"], "requested")

    def test_invalid_timezone_date_and_time_do_not_complete_request(self):
        self.assertIsNone(workflows._zone("Mars/Office"))
        self.assertIsNone(workflows._date("2030-02-31", workflows._zone("UTC")))
        data = {"phone_raw": "+14695550199", "local_time": "29:90", "timezone": "UTC", "local_date": "2030-12-15"}
        self.assertEqual(workflows.next_callback_field(data), "callbackTime")
        data["local_time"] = "16:00"
        data["timezone"] = "Mars/Office"
        self.assertEqual(workflows.next_callback_field(data), "callbackTimezone")

    def test_old_quote_checklist_cannot_be_reused_after_promotion(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", Path(tmp) / "test.db"):
            db.init()
            case = db.upsert_case({"task": "insurance_quote", "status": "under_review", "facts": facts(insurance="needs_insurance")})
            requirements.issue(case["id"], "insurance_quote")
            for row in db.list_requirements(case["id"]):
                requirements.decide(case["id"], row["doc_type"], "waive", "Reviewer", "Quote intake waiver")
            db.upsert_case({"id": case["id"], "task": "lease_agreement", "facts": facts(insurance="own_insurance")})
            ready, blockers = requirements.ready_for_handoff(case["id"])
            self.assertFalse(ready)
            self.assertIn("lease:not_issued", blockers)
            self.assertIn("coi:not_issued", blockers)

    def test_local_mirror_is_neither_verified_crm_sync_nor_assignment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", Path(tmp) / "test.db"), patch.object(zoho, "mode", return_value="offline"):
            db.init()
            session = db.create_session()
            zoho.queue_inquiry(session)
            zoho.drain()
            state = zoho.sync_status(session_id=session["id"])
            self.assertFalse(state["verified"])
            self.assertFalse(state["assigned"])

    def test_offline_update_with_existing_real_id_is_not_remote_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", Path(tmp) / "test.db"), patch.object(zoho, "mode", return_value="offline"):
            db.init()
            session = db.create_session()
            db.upsert_mirror({"id": "real-record-id", "opportunity_id": session["opportunity_id"], "module": "Deals", "stage": "Qualification", "data": {}})
            zoho.queue_inquiry(session)
            zoho.drain()
            state = zoho.sync_status(session_id=session["id"])
            self.assertEqual(state["latest"]["status"], "local_only")
            self.assertFalse(state["verified"])
            self.assertFalse(state["assigned"])


if __name__ == "__main__":
    unittest.main()
