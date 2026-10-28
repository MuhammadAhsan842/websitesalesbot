"""MD behavior pack: success-chat patterns and human compose paths."""

import unittest

from app import behavior, examples, knowledge, memory, plan, playbook, rules


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class BehaviorPackIngest(unittest.TestCase):
    def test_policy_cards_load(self):
        cards = behavior.load_policy_cards()
        self.assertGreaterEqual(len(cards), 17)
        ids = {c["id"] for c in cards}
        self.assertIn("pol01", ids)
        self.assertIn("sc14", ids)

    def test_examples_include_ref_and_cards(self):
        examples.reload_index()
        published = {row["id"] for row in examples.published()}
        self.assertIn("ref_cargo_then_box", published)
        self.assertIn("ref_fuel_blocker", published)
        self.assertIn("card_pol01", published)
        self.assertEqual(examples.VERSION, "ayyan_examples_v6")

    def test_fuel_strategy_retrieves(self):
        examples.reload_index()
        hits = examples.search("Do you offer a fuel advance? I can't start without diesel money.")
        self.assertTrue(hits)
        blob = " ".join(h.get("strategy", "") + h.get("id", "") for h in hits).lower()
        self.assertTrue("fuel" in blob or "ref_fuel" in blob or "sc14" in blob)


class MdSuccessCompose(unittest.TestCase):
    def test_insurance_question_not_concatenated(self):
        wording = (
            "They're separate coverages. Onboarding checks each on the COI for your setup."
        )
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", mcOwnership="own_mc"),
            [knowledge.lookup("insurance"), knowledge.lookup("equip_box_truck")],
            "dispatch_service",
            False,
            None,
            "operatingMode",
            {"answered": ["equipment", "mcOwnership"], "explained": ["equip_box_truck"]},
            wording=wording,
            plan={
                "answer_topics": ["insurance"],
                "next_question_id": None,
                "conversation_move": "answer",
                "wording": wording,
            },
            user_text="Do you need commercial and cargo both?",
        )
        self.assertEqual(reply, wording)

    def test_fuel_blocker_stops_qualify_push(self):
        text = "I need a fuel advance before pickup or I can't start"
        self.assertEqual(memory.detect_concern(text, "general"), "fuel_requirement")
        validated = plan.validate_plan(
            text,
            {"facts": facts(equipment="box_truck"), "memory": {"concern": "fuel_requirement"}},
            {"intent": "general", "answer_topics": ["fuel_requirement"], "action": "none"},
        )
        self.assertIsNone(validated["next_question_id"])
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck"),
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"concern": "fuel_requirement", "answered": ["equipment"]},
            wording="",
            plan=validated,
            user_text=text,
        )
        self.assertIn("funding before pickup", reply.lower())
        self.assertNotIn("own MC or lease", reply)

    def test_insurance_pause_no_extra_question(self):
        text = "The owner says insurance costs too much. He wants to wait."
        reply, chips, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", mcOwnership="own_mc"),
            [],
            "dispatch_service",
            False,
            None,
            "operatingMode",
            {"concern": "insurance_affordability", "answered": ["equipment", "mcOwnership"]},
            wording="",
            plan={"answer_topics": ["pause"], "next_question_id": None, "conversation_move": "pause"},
            user_text=text,
        )
        self.assertIn("holding things up", reply.lower())
        self.assertNotIn("?", reply)

    def test_cargo_van_then_human_refusal(self):
        text = "cargo van"
        items = {item["key"]: item["value"] for item in rules.extract_facts(text)}
        self.assertEqual(items.get("equipmentSupport"), "out_of_scope")
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="cargo_van", equipmentSupport="out_of_scope"),
            [],
            None,
            False,
            None,
            None,
            {"answered": ["equipment"]},
            wording="We don't provide dispatch services for cargo vans.",
            plan={"answer_topics": [], "next_question_id": None, "conversation_move": "answer"},
            user_text=text,
        )
        self.assertIn("don't provide", reply.lower())
        self.assertNotIn("Will you run", reply)


class RegisterTone(unittest.TestCase):
    def test_v8_human_keys(self):
        self.assertEqual(knowledge.REGISTER["version"], "ayyan_sales_v10")
        self.assertIn("Hey", knowledge.lookup("welcome"))
        self.assertIn("fuel_requirement", knowledge.REGISTER)
        self.assertIn("privacy_boundary", knowledge.REGISTER)


if __name__ == "__main__":
    unittest.main()
