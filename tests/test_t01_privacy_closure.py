"""Case T01: expired demand, existing dispatcher, privacy boundary."""

import unittest

from app import examples, graph, knowledge, memory, plan, playbook


class T01Concerns(unittest.TestCase):
    def test_expired_demand(self):
        self.assertEqual(
            memory.detect_concern("Not anymore. That was for last Friday.", "general"),
            "expired_demand",
        )

    def test_existing_dispatcher(self):
        self.assertEqual(
            memory.detect_concern("Already hired a dispatcher.", "general"),
            "existing_dispatcher",
        )

    def test_privacy_boundary(self):
        self.assertEqual(
            memory.detect_concern("I don't know you, and that's private business information.", "general"),
            "privacy_boundary",
        )


class T01Compose(unittest.TestCase):
    def test_expired_closes_without_qualify(self):
        text = "Not anymore. That was for last Friday."
        reply, chips, _ = playbook.compose(
            "general",
            {},
            [],
            None,
            False,
            None,
            "equipment",
            {"concern": "expired_demand", "follow_up": "driver_initiates"},
            wording="",
            plan={"answer_topics": ["expired_demand"], "next_question_id": None, "conversation_move": "pause"},
            user_text=text,
        )
        self.assertIn("won't treat that old request", reply.lower())
        self.assertNotIn("What are you running", reply)
        self.assertEqual(chips, [])

    def test_hired_dispatcher_no_fee_probe(self):
        reply, chips, _ = playbook.compose(
            "general",
            {},
            [],
            None,
            False,
            None,
            "mcOwnership",
            {"concern": "existing_dispatcher"},
            wording="",
            plan={"answer_topics": ["existing_dispatcher"], "next_question_id": None},
            user_text="Already hired a dispatcher.",
        )
        self.assertIn("hope the arrangement", reply.lower())
        self.assertNotIn("charge", reply.lower())
        self.assertNotIn("%", reply)
        self.assertEqual(chips, [])

    def test_privacy_apology_no_pitch(self):
        reply, chips, _ = playbook.compose(
            "general",
            {},
            [],
            None,
            False,
            None,
            "equipment",
            {"concern": "privacy_boundary"},
            wording="",
            plan={"answer_topics": ["privacy_boundary"], "next_question_id": None},
            user_text="That's private business information.",
        )
        low = reply.lower()
        self.assertTrue("sorry" in low or "overstep" in low)
        self.assertNotIn("weekly", low)
        self.assertNotIn("consistent load", low)
        self.assertEqual(chips, [])

    def test_plan_stops_next_question(self):
        validated = plan.validate_plan(
            "Already hired a dispatcher.",
            {"facts": {}, "memory": {"concern": "existing_dispatcher"}},
            {"intent": "general", "answer_topics": ["existing_dispatcher"], "action": "none"},
        )
        self.assertIsNone(validated["next_question_id"])


class T01RetrievalAndHygiene(unittest.TestCase):
    def test_examples_include_t01(self):
        examples.reload_index()
        ids = {row["id"] for row in examples.published()}
        self.assertIn("t01_expired_requirement", ids)
        self.assertIn("t01_privacy_boundary", ids)
        self.assertEqual(examples.VERSION, "ayyan_examples_v6")
        hits = examples.search("Already hired a dispatcher.")
        self.assertTrue(any("dispatcher" in (h.get("id") or "") or "dispatcher" in (h.get("strategy") or "").lower() for h in hits))

    def test_formatting_debris_leaks(self):
        self.assertTrue(graph._leaks("7)Hey! Still looking for loads?"))
        self.assertTrue(graph._leaks("We can provide consistent loads every week."))
        self.assertFalse(graph._leaks(knowledge.lookup("expired_demand")))

    def test_register_v9_keys(self):
        self.assertEqual(knowledge.REGISTER["version"], "ayyan_sales_v11")
        for key in ("expired_demand", "existing_dispatcher", "privacy_boundary", "apology_no_pitch"):
            self.assertIn(key, knowledge.REGISTER)


if __name__ == "__main__":
    unittest.main()
