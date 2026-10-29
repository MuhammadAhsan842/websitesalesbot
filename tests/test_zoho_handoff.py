"""Zoho handoff lifecycle: one Deal per inquiry, real ID persistence, actionable briefs."""

from __future__ import annotations

import uuid
import unittest
from unittest import mock

from app import db, playbook, tasks, zoho


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class MirrorIdPersistence(unittest.TestCase):
    def setUp(self):
        db.init()
        self.opp = _uid("opp_mirror")
        self.real_id = _uid("ZOHO")

    def test_real_id_replaces_synthetic_and_is_kept(self):
        db.upsert_mirror(
            {
                "id": f"zcrm_local_{self.opp}",
                "opportunity_id": self.opp,
                "module": "Deals",
                "stage": "Qualification",
                "data": {},
            }
        )
        db.upsert_mirror(
            {
                "id": self.real_id,
                "opportunity_id": self.opp,
                "module": "Deals",
                "stage": "Onboarding",
                "data": {"zoho_id": self.real_id},
            }
        )
        stored = db.get_mirror(self.opp)
        self.assertEqual(stored["id"], self.real_id)
        # Synthetic must not overwrite the real id.
        db.upsert_mirror(
            {
                "id": f"zcrm_local_{self.opp}",
                "opportunity_id": self.opp,
                "module": "Deals",
                "stage": "Qualification",
                "data": {},
            }
        )
        stored = db.get_mirror(self.opp)
        self.assertEqual(stored["id"], self.real_id)
        self.assertEqual(stored["stage"], "Qualification")  # stage may update; id must not regress


class DuplicateCreatePrevention(unittest.TestCase):
    def setUp(self):
        db.init()

    def test_second_live_event_puts_not_posts(self):
        opp = _uid("opp_dup")
        real_id = _uid("ZOHO_REAL")
        session = {
            "id": _uid("sess_dup"),
            "opportunity_id": opp,
            "state_version": 1,
            "channel": "chat",
            "facts": facts(equipment="box_truck", trailerLength="26ft", mcOwnership="no_own_mc"),
        }
        db.upsert_mirror(
            {
                "id": f"zcrm_local_{opp}",
                "opportunity_id": opp,
                "module": "Deals",
                "stage": "Qualification",
                "data": {},
            }
        )
        fake_post = mock.Mock()
        fake_post.raise_for_status = mock.Mock()
        fake_post.json.return_value = {
            "data": [{"code": "SUCCESS", "status": "success", "details": {"id": real_id}}]
        }
        fake_put = mock.Mock()
        fake_put.raise_for_status = mock.Mock()
        fake_put.json.return_value = {
            "data": [{"code": "SUCCESS", "status": "success", "details": {"id": real_id}}]
        }

        zoho.queue_inquiry(session)
        with mock.patch.object(zoho, "mode", return_value="live"), mock.patch.object(
            zoho, "access_token", return_value="tok"
        ), mock.patch("app.zoho.httpx.post", return_value=fake_post) as post, mock.patch(
            "app.zoho.httpx.put", return_value=fake_put
        ) as put:
            results = zoho.drain()
            self.assertTrue(any(r.get("zoho_id") == real_id for r in results))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(db.get_mirror(opp)["id"], real_id)

            session["state_version"] = 2
            zoho.queue_handoff(session, "insurance_quote", "manager_requested", "Review insurance options")
            zoho.drain()
            self.assertEqual(put.call_count, 1)
            self.assertEqual(post.call_count, 1)  # no second create
            self.assertEqual(db.get_mirror(opp)["id"], real_id)


class PerRecordValidation(unittest.TestCase):
    def setUp(self):
        db.init()

    def test_http_200_with_record_error_fails_sync(self):
        opp = _uid("opp_reject")
        session = {
            "id": _uid("sess_rej"),
            "opportunity_id": opp,
            "state_version": 1,
            "facts": facts(equipment="box_truck"),
        }
        zoho.queue_inquiry(session)
        bad = mock.Mock()
        bad.raise_for_status = mock.Mock()
        bad.json.return_value = {
            "data": [{"code": "INVALID_DATA", "status": "error", "message": "Stage invalid"}]
        }
        with mock.patch.object(zoho, "mode", return_value="live"), mock.patch.object(
            zoho, "access_token", return_value="tok"
        ), mock.patch("app.zoho.httpx.post", return_value=bad):
            results = zoho.drain()
        self.assertTrue(results)
        self.assertEqual(results[0]["status"], "failed")
        rows = db.list_outbox(opportunity_id=opp)
        self.assertTrue(any(r["status"] == "failed" for r in rows))


class StageNoRegression(unittest.TestCase):
    def setUp(self):
        db.init()

    def test_fit_update_keeps_onboarding_stage(self):
        opp = _uid("opp_stage")
        db.upsert_mirror(
            {
                "id": _uid("ZOHO_STAGE"),
                "opportunity_id": opp,
                "module": "Deals",
                "stage": "Onboarding",
                "data": {},
            }
        )
        session = {
            "id": _uid("sess_stage"),
            "opportunity_id": opp,
            "state_version": 3,
            "facts": facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
            ),
        }
        payload = zoho.record("fit_update", session, {})
        self.assertEqual(payload["zoho"]["Stage"], "Onboarding")


class HandoffBriefContent(unittest.TestCase):
    def test_brief_for_lease_insurance_callback_conversation(self):
        f = facts(
            equipment="box_truck",
            trailerLength="26ft",
            equipmentSupport="in_scope",
            mcOwnership="no_own_mc",
            insurance="needs_insurance",
            operatingMode="local",
            milesPerDay="500-600",
            phone="03124567497",
            callbackTime="4pm",
            callbackTimezone="America/Chicago",
        )
        brief = playbook.handoff_brief(
            f,
            "lease_on",
            task="insurance_quote",
            status="manager_requested",
            next_action="Confirm insurance program and applicable charges; complete callback scheduling.",
            related_tasks=["callback"],
            opportunity_id="opp_abcdef12",
            reason="Driver explicitly requested an onboarding manager after asking about lease-on charges.",
        )
        low = brief.lower()
        self.assertIn("26ft", brief.replace(" ", ""))
        self.assertIn("lease", low)
        self.assertIn("insurance", low)
        self.assertIn("500-600", brief)
        self.assertIn("callback", low)
        self.assertIn("timezone", low)
        self.assertNotIn("operating from chicago", low)
        self.assertIn("monday", low)  # outstanding weekday
        self.assertIn("opp_abcdef12", brief)

    def test_fit_summary_no_inscope_without_equipment(self):
        text = playbook.fit_summary({}, None)
        self.assertNotIn("In scope", text)
        self.assertIn("unconfirmed", text.lower())


class RelatedTasksPreserved(unittest.TestCase):
    def setUp(self):
        db.init()

    def test_callback_does_not_replace_insurance_purpose(self):
        session = db.create_session(
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
            )
        )
        with mock.patch.object(zoho, "queue_handoff", return_value=None):
            tasks.persist_human_task(
                session,
                "insurance_quote",
                "manager_requested",
                "Review insurance options",
                "Manager handoff requested",
            )
            tasks.persist_human_task(
                session,
                "callback",
                "callback_requested",
                "Return the call at 4pm America/Chicago",
                "Callback recorded",
            )
        case = db.get_case(session["case_id"])
        self.assertEqual(case["task"], "insurance_quote")
        self.assertIn("callback", case.get("related_tasks") or [])


class LiveSubmitUsesPutAfterIdKnown(unittest.TestCase):
    def test_submit_live_put_when_real_id(self):
        payload = {"zoho": {"Deal_Name": "x", "Stage": "Onboarding", "Description": "y"}}
        ok = mock.Mock()
        ok.raise_for_status = mock.Mock()
        ok.json.return_value = {"data": [{"status": "success", "details": {"id": "ABC"}}]}
        with mock.patch.object(zoho, "access_token", return_value="tok"), mock.patch(
            "app.zoho.httpx.put", return_value=ok
        ) as put, mock.patch("app.zoho.httpx.post") as post:
            zoho_id = zoho._submit_live(payload, "ABC")
        self.assertEqual(zoho_id, "ABC")
        put.assert_called_once()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
