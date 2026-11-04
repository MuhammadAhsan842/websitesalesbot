"""Own-MC qualify/review fixes: no insurance questionnaire, branch order, docs + auto review."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, knowledge, plan, playbook, requirements, rules, tasks
from app.schema import CHIPS, QUESTIONS


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class OwnMcAskOrder(unittest.TestCase):
    def test_after_own_mc_asks_authority_age_not_insurance(self):
        ask = playbook.next_ask(
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", equipmentSupport="in_scope")
        )
        self.assertEqual(ask, "authorityAgeMonths")
        self.assertNotIn("insurance", playbook.missing_core(
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc")
        ))

    def test_local_miles_weekday_start_skips_city(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            mcOwnership="own_mc",
            authorityAgeMonths=5,
            operatingMode="local",
            milesPerDay="400-500",
            weekdaySchedule="monday_friday",
            equipmentSupport="in_scope",
        )
        ask = playbook.next_ask(state)
        self.assertEqual(ask, "startDate")
        self.assertNotIn("operatingArea", playbook.missing_core(state))
        self.assertNotIn("stayOutDuration", playbook.missing_core(state))
        self.assertNotIn("insurance", playbook.missing_core(state))

    def test_otr_weekday_then_start_no_stay_out(self):
        state = facts(
            equipment="hotshot",
            trailerLength="30ft",
            mcOwnership="own_mc",
            authorityAgeMonths=12,
            operatingMode="otr",
            equipmentSupport="in_scope",
        )
        ask = playbook.next_ask(state)
        self.assertEqual(ask, "weekdaySchedule")
        state["weekdaySchedule"] = {"value": "monday_friday", "status": "user_stated"}
        ask = playbook.next_ask(state)
        self.assertEqual(ask, "startDate")
        self.assertNotIn("stayOutDuration", playbook.missing_core(state))
        self.assertNotIn("milesPerDay", playbook.missing_core(state))

    def test_lease_on_path_unchanged_after_weekday_asks_city(self):
        ask = playbook.next_ask(
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
                operatingMode="local",
                milesPerDay="500-600",
                weekdaySchedule="monday_friday",
            )
        )
        self.assertEqual(ask, "operatingArea")


class FreightCityOnly(unittest.TestCase):
    def test_freight_topic_asks_city_when_missing(self):
        validated = plan.validate_plan(
            "what load options do you have near me?",
            {
                "facts": facts(
                    equipment="box_truck",
                    trailerLength="26ft",
                    mcOwnership="own_mc",
                    authorityAgeMonths=5,
                    operatingMode="local",
                    milesPerDay="500-600",
                    weekdaySchedule="monday_friday",
                    startDate="next week",
                ),
                "memory": {"answered": [], "follow_up": "assistant"},
            },
            {
                "intent": "freight",
                "facts": [],
                "answer_topics": ["freight"],
                "next_question_id": None,
                "action": "none",
                "task": None,
                "wording": "I can look into freight once we know your city.",
            },
        )
        self.assertIn("freight", validated["answer_topics"])
        self.assertEqual(validated["next_question_id"], "operatingArea")

    def test_missing_city_does_not_block_own_mc_packet(self):
        validated = plan.validate_plan(
            "next week",
            {
                "facts": facts(
                    equipment="box_truck",
                    trailerLength="26ft",
                    mcOwnership="own_mc",
                    authorityAgeMonths=5,
                    operatingMode="otr",
                    weekdaySchedule="monday_friday",
                    startDate="next week",
                    equipmentSupport="in_scope",
                ),
                "memory": {"answered": [], "follow_up": "assistant"},
            },
            {
                "intent": "general",
                "facts": [{"key": "startDate", "value": "next week"}],
                "answer_topics": [],
                "next_question_id": None,
                "action": "create_case",
                "task": "setup_packet",
                "wording": None,
            },
        )
        self.assertEqual(validated["proposed_action"], "create_case")
        self.assertNotIn("underspecified_packet", validated["fallbacks"])


class DocsAlignWithRequirements(unittest.TestCase):
    def test_customer_docs_match_catalog(self):
        labels = requirements.customer_doc_labels("setup_packet", facts(mcOwnership="own_mc"))
        self.assertIn("MC authority sheet", labels)
        self.assertIn("W-9", labels)
        self.assertIn("Certificate of insurance", labels)
        self.assertIn("Truck photos", labels)
        self.assertNotIn("Dispatch setup agreement", labels)
        line = requirements.customer_docs_sentence("setup_packet", facts(mcOwnership="own_mc")).lower()
        self.assertIn("authority", line)
        self.assertIn("w-9", line)
        self.assertIn("truck photos", line)
        self.assertIn("factoring", line)

    def test_factoring_adds_noa_and_voided_check(self):
        labels = requirements.customer_doc_labels(
            "setup_packet", facts(mcOwnership="own_mc", paymentArrangement="factoring")
        )
        self.assertIn("Notice of assignment", labels)
        self.assertIn("Voided check", labels)


class OneQuestionReplace(unittest.TestCase):
    def test_wrong_model_question_is_replaced_not_appended(self):
        text, ask, chips = playbook.align_delivery(
            "Got it — 26 ft box truck. Do you have your own insurance on the truck?",
            "authorityAgeMonths",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc"),
        )
        self.assertEqual(ask, "authorityAgeMonths")
        self.assertEqual(text.count("?"), 1)
        self.assertIn("how old", text.lower())
        self.assertNotIn("insurance", text.lower())
        self.assertEqual(chips, CHIPS["authorityAgeMonths"])


class HandoffBriefOwnMc(unittest.TestCase):
    def test_setup_review_reason_and_no_city_blocker(self):
        brief = playbook.handoff_brief(
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="own_mc",
                authorityAgeMonths=5,
                operatingMode="otr",
                weekdaySchedule="monday_friday",
                startDate="next week",
                equipmentSupport="in_scope",
            ),
            "dispatch_service",
            task="setup_packet",
            status="awaiting_human_action",
            next_action="Review own-MC setup packet",
        )
        low = brief.lower()
        self.assertIn("own-mc setup review", low)
        self.assertIn("own mc", low)
        self.assertIn("authority ~5 months", low)
        self.assertNotIn("starting city/zip", low)
        self.assertIn("document packet", low)


class AutoSaveOnStartDate(unittest.TestCase):
    def test_rules_create_case_when_start_date_completes_own_mc(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            mcOwnership="own_mc",
            authorityAgeMonths=5,
            operatingMode="local",
            milesPerDay="500-600",
            weekdaySchedule="monday_friday",
            equipmentSupport="in_scope",
        )
        mem = {
            "answered": list(state.keys()),
            "follow_up": "assistant",
            "last_question_id": "startDate",
        }
        ruled = rules.propose("Next week", state, mem)
        self.assertEqual(ruled["action"], "create_case")
        self.assertEqual(ruled["task"], "setup_packet")
        self.assertEqual(ruled["arrangement"], "dispatch_service")

    def test_persist_issues_requirements_without_city(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                session = db.create_session(
                    facts(
                        equipment="box_truck",
                        trailerLength="26ft",
                        mcOwnership="own_mc",
                        authorityAgeMonths=5,
                        operatingMode="otr",
                        weekdaySchedule="monday_friday",
                        startDate="next week",
                        equipmentSupport="in_scope",
                    )
                )
                session["opportunity_id"] = session["id"]
                saved = tasks.persist_human_task(
                    session,
                    "setup_packet",
                    "awaiting_human_action",
                    "Own-MC setup review",
                    "Own-MC review queued",
                )
                snap = requirements.snapshot(saved["id"])
                self.assertGreaterEqual(snap["issued"], 4)
                types = {row["doc_type"] for row in snap["requirements"]}
                self.assertIn("authority", types)
                self.assertIn("w9", types)
                self.assertIn("coi", types)
                self.assertIn("equipment_photos", types)
                self.assertIn("setup review", (saved.get("summary") or "").lower())


class OwnMcReplay(unittest.TestCase):
    """API-style qualify replay without a live model."""

    def test_full_local_path_to_docs_follow_up(self):
        mem = {"answered": [], "follow_up": "assistant", "explained": []}
        state = {}

        def step(text):
            nonlocal state, mem
            ruled = rules.propose(text, state, mem)
            for item in ruled["facts"]:
                if item["key"] == "_unknown":
                    continue
                state[item["key"]] = {"value": item["value"], "status": item.get("status") or "user_stated"}
            ask = playbook.next_ask(state, mem)
            for key, item in state.items():
                if item.get("value") not in (None, "", False) and key not in mem["answered"]:
                    mem["answered"].append(key)
            out, delivered, chips = playbook.align_delivery(
                "Got it. What's your current setup?",
                ask,
                state,
            )
            mem["last_question_id"] = delivered
            return out, delivered, chips, ask, ruled

        step("26 ft box truck")
        self.assertEqual(state["equipment"]["value"], "box_truck")
        _, delivered, _, ask, _ = step("I have my own MC")
        self.assertEqual(ask, "authorityAgeMonths")
        self.assertEqual(delivered, "authorityAgeMonths")
        _, delivered, _, ask, _ = step("About 5 months")
        self.assertEqual(ask, "operatingMode")
        _, delivered, _, ask, _ = step("Local work")
        self.assertEqual(state["operatingMode"]["value"], "local")
        self.assertEqual(ask, "milesPerDay")
        _, delivered, _, ask, _ = step("500-600")
        self.assertEqual(ask, "weekdaySchedule")
        _, delivered, _, ask, _ = step("Monday through Friday")
        self.assertEqual(ask, "startDate")
        self.assertNotEqual(ask, "operatingArea")
        out, delivered, chips, ask, ruled = step("Next week")
        self.assertIsNone(ask)
        self.assertEqual(ruled["action"], "create_case")
        self.assertEqual(ruled["task"], "setup_packet")
        reply, reply_chips, summary = playbook.compose(
            "general",
            state,
            [],
            "dispatch_service",
            True,
            knowledge.lookup("own_mc_review_saved"),
            None,
            mem,
            plan={"answer_topics": [], "next_question_id": None, "proposed_action": "create_case", "task": "setup_packet"},
            user_text="Next week",
        )
        low = reply.lower()
        self.assertTrue("own-mc" in low or "own mc" in low or "setup review" in low)
        self.assertTrue("w-9" in low or "authority" in low)
        self.assertIn("truck photos", low)
        self.assertEqual(reply_chips, CHIPS["handoff"])


if __name__ == "__main__":
    unittest.main()
