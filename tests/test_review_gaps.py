"""Regression tests for post-3e9cdaf review findings."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import graph, knowledge, memory, playbook, requirements, rules


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class UploadSessionCaseLink(unittest.TestCase):
    def test_upload_persists_session_case_id(self):
        import app.db as dbmod

        tmp = tempfile.TemporaryDirectory()
        db_file = Path(tmp.name) / "ayyan.db"

        def connect():
            import sqlite3

            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            return conn

        with mock.patch.object(dbmod, "connect", connect):
            dbmod.init()
            created = dbmod.create_session(facts(equipment="box_truck", mcOwnership="own_mc"))
            from app.main import _ensure_onboarding_case

            loaded = dbmod.get_session(created["id"])
            case = _ensure_onboarding_case(loaded)
            self.assertTrue(case["id"])
            again = dbmod.get_session(created["id"])
            self.assertEqual(again.get("case_id"), case["id"])
        tmp.cleanup()


class ApprovalFileBinding(unittest.TestCase):
    def test_rejects_nonexistent_file(self):
        import app.db as dbmod

        tmp = tempfile.TemporaryDirectory()
        db_file = Path(tmp.name) / "ayyan.db"

        def connect():
            import sqlite3

            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            return conn

        with mock.patch.object(dbmod, "connect", connect):
            dbmod.init()
            case = dbmod.upsert_case(
                {
                    "session_id": "s1",
                    "opportunity_id": "o1",
                    "task": "setup_packet",
                    "status": "under_review",
                    "facts": {},
                    "summary": "t",
                    "next_action": "review",
                }
            )
            requirements.issue(case["id"], "setup_packet", facts=facts(mcOwnership="own_mc"))
            with self.assertRaises(ValueError):
                requirements.decide(case["id"], "coi", "approve", "Reviewer", file_id="file_missing")
        tmp.cleanup()

    def test_rejects_stale_file_when_newer_exists(self):
        import app.db as dbmod

        tmp = tempfile.TemporaryDirectory()
        db_file = Path(tmp.name) / "ayyan.db"

        def connect():
            import sqlite3

            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            return conn

        with mock.patch.object(dbmod, "connect", connect):
            dbmod.init()
            case = dbmod.upsert_case(
                {
                    "session_id": "s2",
                    "opportunity_id": "o2",
                    "task": "setup_packet",
                    "status": "under_review",
                    "facts": {},
                    "summary": "t",
                    "next_action": "review",
                }
            )
            requirements.issue(case["id"], "setup_packet", facts=facts(mcOwnership="own_mc"))
            old = dbmod.add_case_file(
                case["id"],
                {"doc_type": "coi", "filename": "old.pdf", "flags": [], "extracted": {}, "status": "received"},
                "/tmp/old.pdf",
            )
            new = dbmod.add_case_file(
                case["id"],
                {"doc_type": "coi", "filename": "new.pdf", "flags": [], "extracted": {}, "status": "received"},
                "/tmp/new.pdf",
            )
            dbmod.update_requirement(
                dbmod.get_requirement(case["id"], "coi")["id"],
                {"current_file_id": new["id"], "status": "received"},
            )
            with self.assertRaises(ValueError):
                requirements.decide(case["id"], "coi", "approve", "Reviewer", file_id=old["id"])
        tmp.cleanup()


class WordingConsistency(unittest.TestCase):
    def test_privacy_blocks_fee_probe_in_model_wording(self):
        reply, _, _ = playbook.compose(
            "general",
            {},
            [],
            None,
            False,
            None,
            None,
            {"concern": "privacy_boundary", "follow_up": "driver_initiates"},
            wording="Sorry about that. What percentage does your dispatcher charge?",
            plan={"answer_topics": ["privacy_boundary"], "next_question_id": None, "conversation_move": "pause"},
            user_text="That's private business information.",
        )
        self.assertNotIn("percentage", reply.lower())
        self.assertNotIn("charge", reply.lower())

    def test_rejects_reask_truck_when_equipment_known(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", trailerLength="26ft", equipmentSupport="in_scope"),
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"answered": ["equipment", "trailerLength"], "explained": ["equip_box_truck"]},
            wording="Understood. What type of truck do you need?",
            plan={
                "answer_topics": [],
                "next_question_id": "mcOwnership",
                "conversation_move": "qualify",
                "wording": "Understood. What type of truck do you need?",
            },
            user_text="I run regional.",
        )
        self.assertNotIn("what type of truck", reply.lower())

    def test_short_box_refusal_copy(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", trailerLength="20ft", equipmentSupport="out_of_scope"),
            [],
            None,
            False,
            None,
            None,
            {"answered": ["equipment", "trailerLength"]},
            wording="Box truck is in scope.",
            plan={"answer_topics": [], "next_question_id": None, "conversation_move": "answer"},
            user_text="I have a 20 ft box truck",
        )
        self.assertIn("24", reply)
        self.assertRegex(reply, r"24.*26.*28|24, 26, or 28")

    def test_noncatalog_dry_van_length_refusal(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="dry_van", trailerLength="45ft", equipmentSupport="out_of_scope"),
            [],
            None,
            False,
            None,
            None,
            {"answered": ["equipment", "trailerLength"]},
            wording="Dry van is in scope.",
            plan={"answer_topics": [], "next_question_id": None, "conversation_move": "answer"},
            user_text="I have a 45 ft dry van",
        )
        self.assertRegex(reply.lower(), r"catalog|outside our current service|standard sizes")


class CrossTurnSupport(unittest.TestCase):
    def test_length_only_reevaluates_box_support(self):
        state = {
            "session": {
                "id": "s",
                "channel": "web",
                "state_version": 1,
                "facts": facts(equipment="box_truck", equipmentSupport="in_scope"),
                "memory": {},
                "conversation_state": "discover_needs",
                "takeover": False,
                "handed_over": False,
                "opportunity_id": "o",
            },
            "proposal": {
                "facts": [{"key": "trailerLength", "value": "20ft", "status": "user_stated"}],
                "repair": None,
            },
            "user_text": "20 ft",
        }
        with mock.patch("app.graph.zoho.queue_fit", return_value=None):
            out = graph.node_reduce_facts(state)
        self.assertEqual(fact_value(out["session"]["facts"], "equipmentSupport"), "out_of_scope")
        self.assertEqual(fact_value(out["session"]["facts"], "trailerLength"), "20ft")


def fact_value(facts, key):
    from app.tasks import fact_value as fv

    return fv(facts, key)


class ReactivationAndHistory(unittest.TestCase):
    def test_reactivation_after_expired(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="dry_van"),
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"concern": "expired_demand", "follow_up": "driver_initiates", "answered": ["equipment"]},
            wording="",
            plan={"answer_topics": ["pause"], "next_question_id": None, "conversation_move": "pause"},
            user_text="My situation changed. I'm ready to start.",
        )
        self.assertNotIn("whenever you're ready", reply.lower())
        self.assertTrue("changed" in reply.lower() or "looking for" in reply.lower() or "own mc" in reply.lower())

    def test_last_friday_not_start_date(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("Not anymore. That was for last Friday.")}
        self.assertNotIn("startDate", items)
        self.assertNotIn("deadline", items)

    def test_weight_range_not_miles(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("I want 7000 to 7500 lb")}
        self.assertNotIn("milesPerDay", items)
        self.assertIn("preferredPayload", items)


class LeakGuaranteeRefusal(unittest.TestCase):
    def test_approved_guarantee_refusal_allowed(self):
        self.assertFalse(graph._leaks(knowledge.lookup("guarantee")))
        self.assertTrue(graph._leaks("We can provide consistent loads every week."))


if __name__ == "__main__":
    unittest.main()
