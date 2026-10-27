"""Release 1: model-authored replies + unsupported equipment stop."""

import unittest

from app import knowledge, plan, playbook, rules


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class UnsupportedEquipment(unittest.TestCase):
    def test_cargo_van_stops_qualification(self):
        text = "I have a cargo van"
        items = {item["key"]: item["value"] for item in rules.extract_facts(text)}
        self.assertEqual(items["equipmentSupport"], "out_of_scope")
        validated = plan.validate_plan(
            text,
            {
                "facts": facts(equipment="cargo_van", equipmentSupport="out_of_scope"),
                "memory": {"answered": ["equipment"], "follow_up": "assistant"},
            },
            {"intent": "general", "answer_topics": [], "action": "none"},
        )
        self.assertIsNone(validated["next_question_id"])
        self.assertEqual(validated["conversation_move"], "answer")
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="cargo_van", equipmentSupport="out_of_scope"),
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"answered": ["equipment"], "follow_up": "assistant", "explained": []},
            wording="We don't provide dispatch services for cargo vans.",
            plan=validated,
            user_text=text,
        )
        self.assertIn("don't provide", reply.lower())
        self.assertNotIn("own MC", reply)
        self.assertNotIn("insurance", reply.lower())


class ModelAuthoredContract(unittest.TestCase):
    def test_full_reply_not_concatenated(self):
        wording = (
            "Onboarding checks commercial auto liability and cargo on your COI. "
            "The team confirms the limits for your setup."
        )
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck", mcOwnership="own_mc", insurance="own_insurance"),
            [knowledge.lookup("insurance"), knowledge.lookup("equip_box_truck")],
            "dispatch_service",
            False,
            None,
            "operatingMode",
            {
                "answered": ["equipment", "mcOwnership", "insurance"],
                "follow_up": "assistant",
                "explained": ["equip_box_truck"],
            },
            wording=wording,
            plan={
                "answer_topics": ["insurance"],
                "next_question_id": None,
                "conversation_move": "answer",
                "wording": wording,
            },
            user_text="Do you need commercial and cargo insurance?",
        )
        self.assertEqual(reply, wording)
        self.assertNotIn("Box truck is in scope", reply)
        self.assertNotIn("OTR", reply)


if __name__ == "__main__":
    unittest.main()
