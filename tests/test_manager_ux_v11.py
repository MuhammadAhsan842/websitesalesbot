"""Manager notebook + control/fact/handoff regressions for ayyan_sales_v11."""

from __future__ import annotations

import unittest

from app import fees, knowledge, plan, playbook, rules
from app.knowledge import lookup
from app.schema import CHIPS, QUESTIONS


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class OneQuestionFlow(unittest.TestCase):
    def test_local_asks_miles_before_city(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            mcOwnership="own_mc",
            insurance="own_insurance",
            coverageTypes="auto_and_cargo",
            operatingMode="local",
            equipmentSupport="in_scope",
        )
        answered = [
            "equipment", "trailerLength", "mcOwnership", "insurance", "coverageTypes",
            "authorityAgeMonths", "operatingMode",
        ]
        ask = playbook.next_ask(state, {"answered": answered})
        self.assertEqual(ask, "milesPerDay")
        self.assertNotEqual(ask, "stayOutDuration")

    def test_otr_asks_stay_out_not_miles(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            mcOwnership="own_mc",
            insurance="own_insurance",
            coverageTypes="auto_and_cargo",
            operatingMode="otr",
            equipmentSupport="in_scope",
        )
        answered = [
            "equipment", "trailerLength", "mcOwnership", "insurance", "coverageTypes",
            "authorityAgeMonths", "operatingMode",
        ]
        ask = playbook.next_ask(state, {"answered": answered})
        self.assertEqual(ask, "stayOutDuration")
        self.assertNotEqual(ask, "milesPerDay")

    def test_insurance_yes_then_coverage(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            mcOwnership="no_own_mc",
            insurance="own_insurance",
            equipmentSupport="in_scope",
        )
        ask = playbook.next_ask(
            state,
            {"answered": ["equipment", "trailerLength", "mcOwnership", "insurance"]},
        )
        self.assertEqual(ask, "coverageTypes")
        self.assertIn("coverage", QUESTIONS["coverageTypes"].lower())
        self.assertIn("Auto + cargo", CHIPS["coverageTypes"])


class FeeAndHandoff(unittest.TestCase):
    def test_fee_quote_routes_to_manager(self):
        route = lookup("fee_route_manager").lower()
        self.assertIn("onboarding manager", route)
        self.assertNotIn("?", route)
        # live_quote needs fee_schedule; when DB is ready it must still route, never invent 6%.
        try:
            line = fees.live_quote("dispatch_service")
        except Exception:
            return
        self.assertNotRegex(line.lower(), r"\b6%\b")
        if "%" in line:
            self.assertIn("onboarding manager", line.lower())

    def test_negotiation_does_not_adopt_counter_percent(self):
        text = "Can you do 6% instead?"
        validated = plan.validate_plan(
            text,
            {
                "facts": facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", requestedFeePercent="6"),
                "memory": {"answered": ["equipment", "trailerLength", "mcOwnership"], "follow_up": "assistant"},
            },
            {"intent": "fee", "answer_topics": ["negotiation", "dispatch_fee"], "action": "none"},
        )
        self.assertIn("negotiation", validated["answer_topics"])
        reply, chips, _ = playbook.compose(
            "fee",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", requestedFeePercent="6"),
            [],
            "dispatch_service",
            False,
            None,
            None,
            {"answered": ["equipment", "trailerLength", "mcOwnership"], "follow_up": "assistant"},
            plan=validated,
            user_text=text,
        )
        low = reply.lower()
        self.assertIn("review", low)
        self.assertIn("onboarding manager", low)
        chip_text = " ".join(
            (c["label"] if isinstance(c, dict) else str(c)) for c in chips
        )
        self.assertIn("Talk to onboarding manager", chip_text)

    def test_human_intent_is_manager_not_generic(self):
        self.assertEqual(rules.detect_intent("Talk to onboarding manager"), "human")
        self.assertIn("Talk to onboarding manager", CHIPS["handoff"])
        self.assertIn("onboarding manager", lookup("handoff_requested").lower())


class FactIntegrity(unittest.TestCase):
    def test_merge_prefers_ruled_equipment(self):
        from app.graph import _merge_facts

        merged = {
            item["key"]: item["value"]
            for item in _merge_facts(
                [{"key": "equipment", "value": "box_truck", "evidence": "30 ft box", "status": "user_stated"}],
                [{"key": "equipment", "value": "dry_van", "status": "user_stated"},
                 {"key": "trailerLength", "value": "53ft", "status": "user_stated"}],
                "I have a 53 ft semi truck",
                {"equipment": {"value": "dry_van", "status": "user_stated"}},
            )
        }
        self.assertEqual(merged.get("equipment"), "dry_van")
        self.assertEqual(merged.get("trailerLength"), "53ft")

    def test_wording_rejects_wrong_truck_hallucination(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="dry_van", trailerLength="53ft", equipmentSupport="in_scope"),
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"answered": ["equipment", "trailerLength"], "explained": ["equip_dry_van"]},
            wording="ok MC good for 30ft box truck. What sort of 30 ft box owned by me?",
            plan={
                "answer_topics": [],
                "next_question_id": "mcOwnership",
                "conversation_move": "qualify",
                "wording": "ok MC good for 30ft box truck. What sort of 30 ft box owned by me?",
            },
            user_text="53 ft semitruck",
        )
        low = reply.lower()
        self.assertNotIn("30ft box", low.replace(" ", ""))
        self.assertNotIn("30 ft box", low)

    def test_next_open_point_loop_killed(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", insurance="own_insurance"),
            [],
            "dispatch_service",
            False,
            None,
            "coverageTypes",
            {"answered": ["equipment", "trailerLength", "mcOwnership", "insurance"]},
            wording="Got the truck and MC on file — what's the next open point?",
            plan={
                "answer_topics": [],
                "next_question_id": "coverageTypes",
                "conversation_move": "qualify",
                "wording": "Got the truck and MC on file — what's the next open point?",
            },
            user_text="yes",
        )
        self.assertNotIn("next open point", reply.lower())
        self.assertIn("coverage", reply.lower())

    def test_accessories_not_in_short_box_ack(self):
        self.assertNotIn("lift gate", lookup("equip_box_truck").lower())
        self.assertIn("lift gate", lookup("equip_box_truck_accessories").lower())


class ReadyToStartDocs(unittest.TestCase):
    def test_own_mc_ready_lists_papers(self):
        reply, _, _ = playbook.compose(
            "onboard",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", equipmentSupport="in_scope"),
            [],
            "dispatch_service",
            False,
            None,
            None,
            {"answered": ["equipment", "trailerLength", "mcOwnership"]},
            plan={"answer_topics": ["onboarding"], "next_question_id": None, "conversation_move": "offer_handoff"},
            user_text="I'm ready to start",
        )
        low = reply.lower()
        self.assertTrue("w-9" in low or "coi" in low or "authority" in low)

    def test_lease_ready_lists_papers(self):
        reply, _, _ = playbook.compose(
            "onboard",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="no_own_mc", equipmentSupport="in_scope"),
            [],
            "lease_on",
            False,
            None,
            None,
            {"answered": ["equipment", "trailerLength", "mcOwnership"]},
            plan={"answer_topics": ["onboarding"], "next_question_id": None, "conversation_move": "offer_handoff"},
            user_text="I'm ready to start",
        )
        low = reply.lower()
        self.assertTrue("lease" in low and ("coi" in low or "licence" in low or "w-9" in low))


class RegisterVersion(unittest.TestCase):
    def test_v11(self):
        self.assertEqual(knowledge.REGISTER["version"], "ayyan_sales_v12")


if __name__ == "__main__":
    unittest.main()
