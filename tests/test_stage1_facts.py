"""Stage 1: structured facts, direct-question priority, explanation memory."""

import unittest

from app import knowledge, memory, plan, playbook, rules
from app.schema import EQUIP_LABELS


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class FactMeanings(unittest.TestCase):
    def test_liftgate_load_preference_is_not_installed(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I need loads that do not require a liftgate."
        )}
        self.assertEqual(items.get("liftgateLoadPreference"), "not_required")
        self.assertNotEqual(items.get("liftgate"), "yes")

    def test_liftgate_and_pallet_jack_installed(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I have a liftgate and a pallet jack."
        )}
        self.assertEqual(items.get("liftgate"), "yes")
        self.assertEqual(items.get("palletJack"), "yes")

    def test_hotshot_accessories(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I have straps, chains, binders and tarps."
        )}
        self.assertEqual(items.get("accessories"), "straps,chains,binders,tarps")

    def test_partial_insurance_coverages(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I have cargo insurance but no commercial auto liability."
        )}
        self.assertEqual(items.get("cargoCoverage"), "present")
        self.assertEqual(items.get("autoLiabilityCoverage"), "absent")

    def test_factoring_is_payment_arrangement(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts("I use factoring.")}
        self.assertEqual(items.get("paymentArrangement"), "factoring")
        self.assertNotEqual(items.get("primaryProblem"), "paperwork")

    def test_mc_age_recorded_without_eligibility(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts("My MC is two months old.")}
        self.assertEqual(items.get("mcOwnership"), "own_mc")
        self.assertEqual(items.get("authorityAgeMonths"), 2)

    def test_sprinter_and_cargo_van_are_out_of_scope(self):
        for text in ("Spriter van.", "Sprintervan", "Do you support Sprinter?", "cargo van"):
            items = {item["key"]: item["value"] for item in rules.extract_facts(text)}
            self.assertIn(items.get("equipment"), {"sprinter_van", "cargo_van"}, text)
            self.assertEqual(items.get("equipmentSupport"), "out_of_scope", text)

    def test_short_box_is_out_of_scope(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts("I have a 22 foot box truck")}
        self.assertEqual(items.get("equipment"), "box_truck")
        self.assertEqual(items.get("trailerLength"), "22ft")
        self.assertEqual(items.get("equipmentSupport"), "out_of_scope")

    def test_catalog_lengths_only(self):
        cases = [
            ("I have a 26 foot box truck", "box_truck", "26ft", "in_scope"),
            ("I have a 30 foot box truck", "box_truck", "30ft", "out_of_scope"),
            ("I run a 40 ft hotshot", "hotshot", "40ft", "in_scope"),
            ("I run a 20 ft hotshot", "hotshot", "20ft", "out_of_scope"),
            ("I have a 53 ft dry van", "dry_van", "53ft", "in_scope"),
            ("I have a 45 ft dry van", "dry_van", "45ft", "out_of_scope"),
            ("I run a 48 ft reefer", "reefer", "48ft", "in_scope"),
            ("I run a 40 ft flatbed", "flatbed", "40ft", "out_of_scope"),
            ("I have a 53 ft step deck", "step_deck", "53ft", "in_scope"),
        ]
        for text, eq, length, support in cases:
            items = {item["key"]: item["value"] for item in rules.extract_facts(text)}
            self.assertEqual(items.get("equipment"), eq, text)
            self.assertEqual(items.get("trailerLength"), length, text)
            self.assertEqual(items.get("equipmentSupport"), support, text)

    def test_regional_operating_mode(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I only want regional work."
        )}
        self.assertEqual(items.get("operatingMode"), "regional")


class DirectQuestions(unittest.TestCase):
    def test_commercial_cargo_question_answers_insurance(self):
        text = "Do you need commercial and cargo insurance?"
        topics = plan.detect_topics(text)
        self.assertIn("insurance", topics)
        validated = plan.validate_plan(
            text,
            {
                "facts": facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", insurance="own_insurance"),
                "memory": {"answered": ["equipment", "trailerLength", "mcOwnership", "insurance"], "follow_up": "assistant"},
            },
            {"intent": "general", "answer_topics": ["insurance"], "action": "none"},
        )
        self.assertEqual(validated["answer_topics"], ["insurance"])
        self.assertIsNone(validated["next_question_id"])
        self.assertEqual(validated["conversation_move"], "answer")
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", trailerLength="26ft", mcOwnership="own_mc", insurance="own_insurance"),
            [knowledge.lookup("insurance")],
            "dispatch_service",
            False,
            None,
            "operatingMode",
            {"answered": ["equipment", "trailerLength", "mcOwnership", "insurance"], "follow_up": "assistant", "explained": ["equip_box_truck"]},
            plan=validated,
            user_text=text,
        )
        low = reply.lower()
        self.assertIn("commercial auto", low)
        self.assertIn("cargo", low)
        self.assertNotIn("otr", low)
        self.assertNotIn("box truck is in scope", low)

    def test_dallas_bundle_skips_known_slots(self):
        state = facts(
            equipment="box_truck",
            trailerLength="26ft",
            liftgate="yes",
            mcOwnership="own_mc",
            insurance="own_insurance",
            operatingArea="dallas",
            operatingMode="regional",
        )
        mem = memory.empty()
        mem["answered"] = list(state.keys())
        ask = playbook.next_ask(state, mem)
        self.assertNotIn(ask, {"equipment", "trailerLength", "mcOwnership", "insurance", "operatingMode", "operatingArea"})


class ExplanationMemory(unittest.TestCase):
    def test_equip_line_not_repeated_on_mc_turn(self):
        state = facts(equipment="box_truck", trailerLength="26ft")
        mem = {"answered": ["equipment", "trailerLength"], "follow_up": "assistant", "explained": ["equip_box_truck"]}
        reply, _, _ = playbook.compose(
            "mc",
            state,
            [],
            None,
            False,
            None,
            "mcOwnership",
            mem,
            user_text="I have MC.",
            plan={"answer_topics": [], "next_question_id": "mcOwnership", "conversation_move": "qualify", "wording": None},
        )
        self.assertNotIn("Box truck is in scope", reply)
        self.assertIn("own MC", reply)

    def test_first_box_truck_gets_short_focus(self):
        state = facts(equipment="box_truck", trailerLength="26ft")
        mem = {"answered": ["equipment", "trailerLength"], "follow_up": "assistant", "explained": []}
        reply, _, _ = playbook.compose(
            "general",
            state,
            [],
            None,
            False,
            None,
            "mcOwnership",
            mem,
            user_text="I have a 26-foot box truck.",
            plan={"answer_topics": [], "next_question_id": "mcOwnership", "conversation_move": "qualify", "wording": None},
        )
        self.assertRegex(reply.lower(), r"26ft box truck|26-foot box truck|26 foot box truck")
        self.assertIn("equip_box_truck", mem.get("explained") or [])
        self.assertNotIn("Box truck is in scope", reply)

    def test_sprinter_support_copy(self):
        self.assertIn("Sprinter", EQUIP_LABELS["sprinter_van"])
        line = knowledge.lookup("equip_sprinter_van")
        self.assertIn("don't provide dispatch", line.lower())
        self.assertIn("sprinter", line.lower())

    def test_model_wording_is_delivered_without_register_dump(self):
        state = facts(equipment="box_truck", trailerLength="26ft")
        mem = {"answered": ["equipment", "trailerLength"], "follow_up": "assistant", "explained": []}
        wording = "Got it—a 26-foot box truck. Will you run under your own MC or lease on?"
        reply, _, _ = playbook.compose(
            "general",
            state,
            [knowledge.lookup("equip_box_truck")],
            None,
            False,
            None,
            "mcOwnership",
            mem,
            wording=wording,
            user_text="26 ft",
            plan={
                "answer_topics": [],
                "next_question_id": "mcOwnership",
                "conversation_move": "qualify",
                "wording": wording,
            },
        )
        self.assertEqual(reply, wording)
        self.assertNotIn("Box truck is in scope", reply)


if __name__ == "__main__":
    unittest.main()
