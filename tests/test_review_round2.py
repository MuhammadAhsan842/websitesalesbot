"""Regression tests for review round 2: OOS execution, factoring files, reactivation, multi-equip."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import db as dbmod
from app import graph, memory, plan, playbook, requirements, rules
from app.tasks import fact_value


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class OutOfScopeBlocksOnboarding(unittest.TestCase):
    def test_rules_do_not_create_case_for_short_box(self):
        state = facts(
            equipment="box_truck",
            trailerLength="20ft",
            equipmentSupport="out_of_scope",
            mcOwnership="own_mc",
            operatingArea="dallas",
        )
        out = rules.propose("I'm ready to start", state, {})
        self.assertNotEqual(out.get("action"), "create_case")

    def test_plan_blocks_setup_packet_when_out_of_scope(self):
        session = {
            "facts": facts(
                equipment="box_truck",
                trailerLength="20ft",
                equipmentSupport="out_of_scope",
                mcOwnership="own_mc",
                operatingArea="dallas",
            ),
            "memory": {"answered": ["equipment", "trailerLength", "mcOwnership", "operatingArea"]},
        }
        validated = plan.validate_plan(
            "I'm ready to start",
            session,
            {
                "intent": "onboard",
                "action": "create_case",
                "task": "setup_packet",
                "answer_topics": [],
                "next_question_id": None,
                "wording": "Your truck is outside scope. I've asked onboarding to send a packet.",
            },
        )
        self.assertEqual(validated["proposed_action"], "none")
        self.assertIn("out_of_scope_equipment", validated.get("fallbacks") or [])

    def test_execute_refuses_packet_for_out_of_scope(self):
        session = {
            "id": "s-oos",
            "channel": "web",
            "state_version": 1,
            "takeover": False,
            "handed_over": False,
            "facts": facts(
                equipment="box_truck",
                trailerLength="20ft",
                equipmentSupport="out_of_scope",
                mcOwnership="own_mc",
                operatingArea="dallas",
            ),
            "memory": {},
        }
        with mock.patch("app.graph.persist_human_task") as persist:
            out = graph.node_execute(
                {
                    "session": session,
                    "proposal": {"action": "create_case", "task": "setup_packet", "intent": "onboard"},
                }
            )
        persist.assert_not_called()
        self.assertFalse(out["action_result"].get("saved"))
        self.assertEqual(out["traces"][-1].get("blocked"), "out_of_scope_equipment")

    def test_compose_does_not_claim_onboarding_when_out_of_scope(self):
        reply, _, _ = playbook.compose(
            "onboard",
            facts(
                equipment="box_truck",
                trailerLength="20ft",
                equipmentSupport="out_of_scope",
                mcOwnership="own_mc",
                operatingArea="dallas",
            ),
            [],
            None,
            True,
            "I've asked our onboarding manager to take the setup packet from here.",
            None,
            {"answered": ["equipment", "trailerLength", "mcOwnership", "operatingArea"]},
            wording="That length is outside our current service.",
            plan={"answer_topics": ["services"], "next_question_id": None, "conversation_move": "answer", "task": "setup_packet"},
            user_text="I'm ready to start",
        )
        self.assertRegex(reply.lower(), r"outside|24|catalog|current service")
        self.assertNotRegex(reply.lower(), r"asked our onboarding|setup packet from here")


class FactoringNeedsEvidence(unittest.TestCase):
    def test_cannot_approve_noa_without_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(dbmod, "DB_PATH", Path(temporary) / "t.db"):
                dbmod.init()
                case = dbmod.upsert_case(
                    {
                        "session_id": "s1",
                        "status": "collecting_documents",
                        "task": "setup_packet",
                        "owner": "desk",
                        "facts": facts(paymentArrangement="factoring", mcOwnership="own_mc"),
                        "documents": [],
                    }
                )
                requirements.issue(
                    case["id"],
                    "setup_packet",
                    facts=facts(paymentArrangement="factoring", mcOwnership="own_mc"),
                )
                with self.assertRaises(ValueError):
                    requirements.decide(case["id"], "notice_of_assignment", "approve", "Reviewer")
                with self.assertRaises(ValueError):
                    requirements.decide(case["id"], "voided_check", "approve", "Reviewer")
                with self.assertRaises(ValueError):
                    requirements.decide(case["id"], "notice_of_assignment", "waive", "Reviewer", reason="")
                requirements.decide(
                    case["id"],
                    "notice_of_assignment",
                    "waive",
                    "Reviewer",
                    reason="Authorized: factoring not used after all",
                )
                row = dbmod.get_requirement(case["id"], "notice_of_assignment")
                self.assertEqual(row["status"], "waived")


class ReactivationAllowsOnboard(unittest.TestCase):
    def test_ready_to_start_after_pause_keeps_create_case(self):
        session = {
            "facts": facts(
                equipment="box_truck",
                trailerLength="26ft",
                equipmentSupport="in_scope",
                mcOwnership="own_mc",
                operatingArea="dallas",
            ),
            "memory": {
                "follow_up": "driver_initiates",
                "concern": "pause",
                "answered": ["equipment", "trailerLength", "mcOwnership", "operatingArea"],
            },
        }
        validated = plan.validate_plan(
            "My situation changed. I'm ready to start.",
            session,
            {
                "intent": "onboard",
                "action": "create_case",
                "task": "setup_packet",
                "answer_topics": [],
                "next_question_id": None,
                "wording": "Of course. I'll ask onboarding for the setup packet.",
            },
        )
        self.assertEqual(validated["proposed_action"], "create_case")
        self.assertNotIn("pause", validated.get("fallbacks") or [])

    def test_memory_clears_pause_on_return(self):
        session = {
            "id": "s",
            "channel": "web",
            "facts": facts(equipment="box_truck"),
            "memory": {"follow_up": "driver_initiates", "concern": "expired_demand"},
        }
        memory.update(session, {"intent": "onboard", "action": "create_case", "task": "setup_packet"}, "I'm ready to start")
        self.assertEqual(session["memory"]["follow_up"], "assistant")
        self.assertIsNone(session["memory"]["concern"])


class MultiVehicleAndNumbers(unittest.TestCase):
    def test_cargo_then_box_prefers_box(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("Cargo van. I also have a 26-ft box truck.")}
        self.assertEqual(items.get("equipment"), "box_truck")
        self.assertEqual(items.get("equipmentSupport"), "in_scope")
        self.assertIn("cargo_van", (items.get("secondaryEquipment") or ""))

    def test_comma_weight_range(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("I want 7,000 to 7,500 lbs")}
        self.assertEqual(items.get("preferredPayload"), "7000-7500")
        self.assertNotIn("milesPerDay", items)

    def test_unitless_rejected_weight(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("18000 is too much for my truck")}
        self.assertEqual(items.get("rejectedLoadWeight"), "18000")

    def test_miles_range(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("I can cover 400-500 miles a day")}
        self.assertEqual(items.get("milesPerDay"), "400-500")


if __name__ == "__main__":
    unittest.main()
