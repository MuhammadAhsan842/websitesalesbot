"""Compact memory must change asking, pause, and concern replies."""

import unittest

from app import memory, playbook


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class MemoryState(unittest.TestCase):
    def test_hard_constraint_and_answered_survive_later_turns(self):
        session = {
            "facts": facts(equipment="box_truck", fleetSize=1, supportNeed="daily_home_time", operatingArea="Atlanta"),
            "handed_over": False,
        }
        first = memory.update(session, {"intent": "hometime", "arrangement": "lease_on"}, "Home every night, local work")
        self.assertEqual(first["hard_constraint"], "home_every_night")
        self.assertEqual(first["goal"], "local_work")
        self.assertIn("equipment", first["answered"])
        session["facts"]["mcOwnership"] = {"value": "no_own_mc", "status": "user_stated"}
        later = memory.update(session, {"intent": "mc", "arrangement": "lease_on"}, "I want to lease on")
        self.assertEqual(later["hard_constraint"], "home_every_night")
        self.assertEqual(later["goal"], "local_work")
        self.assertIn("mcOwnership", later["answered"])

    def test_pause_stops_follow_up_until_the_driver_returns(self):
        session = {"facts": facts(equipment="hotshot"), "handed_over": False}
        paused = memory.update(session, {"intent": "general"}, "I'll let you know when I'm ready")
        self.assertEqual(paused["concern"], "pause")
        self.assertEqual(paused["follow_up"], "driver_initiates")
        self.assertIsNone(playbook.next_ask(session["facts"], paused))
        resumed = memory.update(session, {"intent": "fee"}, "What do you charge?")
        self.assertEqual(resumed["follow_up"], "assistant")
        self.assertEqual(resumed["concern"], "total_fees")

    def test_own_mc_aliases_normalize(self):
        self.assertEqual(memory.normalize_mc("own MC"), "own_mc")
        self.assertEqual(memory.normalize_mc("lease-on"), "no_own_mc")


class KnowledgeScope(unittest.TestCase):
    def test_fee_question_does_not_pull_equipment_or_guarantee(self):
        from app.rules import knowledge_for
        from app.memory import scoped_knowledge

        keys = knowledge_for(
            "fee",
            ["invented_fee"],
            "hotshot",
            "What do you charge? Can you do 6% like Leo Dispatch?",
            [{"key": "equipment", "value": "hotshot"}],
        )
        self.assertIn("fee", keys)
        self.assertIn("competitor", keys)
        self.assertNotIn("equip_hotshot", keys)
        self.assertNotIn("guarantee", keys)
        kept, bits = scoped_knowledge(
            ["guarantee", "fee", "competitor", "equip_hotshot"],
            ["no weekly", "8% of gross", "Leo is not Ayyan", "Hotshot is in scope"],
            "total_fees",
            "What do you charge?",
        )
        self.assertEqual(kept, ["fee"])
        self.assertEqual(bits, ["8% of gross"])
        named, named_bits = scoped_knowledge(
            ["fee", "competitor"],
            ["8% of gross", "Leo is not Ayyan"],
            "total_fees",
            "Can you do 6% like Leo Dispatch?",
        )
        self.assertEqual(named, ["fee"])
        self.assertEqual(named_bits, ["8% of gross"])


class MemoryCompose(unittest.TestCase):
    def test_fee_concern_answers_without_fit_recap_or_second_question(self):
        state = facts(equipment="hotshot", fleetSize=1, operatingArea="Texas", mcOwnership="own_mc")
        mem = {
            "goal": "dispatch",
            "hard_constraint": None,
            "concern": "total_fees",
            "answered": ["equipment", "fleetSize", "operatingArea", "mcOwnership"],
            "blocker": "reviewing_terms",
            "follow_up": "assistant",
        }
        text, chips, summary = playbook.compose(
            "fee",
            state,
            ["Staff-approved own-MC dispatch fee is 8% of gross."],
            "dispatch_service",
            False,
            None,
            "supportNeed",
            mem,
        )
        self.assertIn("8%", text)
        self.assertNotIn("You're looking for support", text)
        self.assertNotIn("What support matters most", text)
        self.assertIsNone(summary)
        self.assertEqual(text.count("?"), 0)

    def test_repetition_reads_this_session_only(self):
        state = facts(equipment="box_truck", operatingArea="Atlanta")
        mem = memory.empty()
        mem.update(concern="repetition", answered=["equipment", "operatingArea"], follow_up="assistant")
        text, _, _ = playbook.compose("general", state, [], None, False, None, "fleetSize", mem)
        self.assertIn("box_truck", text)
        self.assertIn("Atlanta", text)
        self.assertIn("can't see papers onboarding hasn't received", text)

    def test_pause_has_no_next_question(self):
        mem = memory.empty()
        mem.update(concern="pause", follow_up="driver_initiates")
        text, chips, _ = playbook.compose("general", {}, [], None, False, None, "equipment", mem)
        self.assertIn("whenever you're ready", text.lower())
        self.assertNotIn("What are you running", text)
        self.assertEqual(chips, [])

    def test_commitment_answers_before_any_qualification(self):
        mem = memory.empty()
        mem.update(concern="commitment", follow_up="assistant")
        text, _, _ = playbook.compose("commit", {}, [], None, False, None, "equipment", mem)
        self.assertIn("guarantee a load", text)
        self.assertNotIn("What are you running", text)

    def test_wording_does_not_stack_register_paragraphs(self):
        state = facts(equipment="hotshot", mcOwnership="own_mc")
        mem = {
            "goal": "dispatch",
            "concern": "total_fees",
            "answered": ["equipment", "mcOwnership"],
            "follow_up": "assistant",
        }
        text, _, _ = playbook.compose(
            "fee",
            state,
            ["Staff-approved own-MC dispatch fee is 8% of gross.", "Leo, ATL, and Silver Arrow are not Ayyan."],
            "dispatch_service",
            False,
            None,
            "supportNeed",
            mem,
            wording="Own-MC is on file.",
        )
        self.assertIn("8%", text)
        self.assertIn("Own-MC is on file", text)
        self.assertNotIn("Silver Arrow", text)
        self.assertEqual(text.count("?"), 0)

    def test_desk_card_names_next_step_for_staff(self):
        session = {
            "facts": facts(equipment="box_truck", mcOwnership="own_mc", operatingArea="Dallas", supportNeed="daily_home_time"),
            "memory": {
                "goal": "local_work",
                "hard_constraint": "home_every_night",
                "concern": "commitment",
                "last_blocker": "reviewing_terms",
                "follow_up": "assistant",
            },
            "takeover": False,
            "handed_over": False,
        }
        card = playbook.desk_card(session)
        self.assertEqual(card["goal"], "local_work")
        self.assertIn("signature", card["next_step"].lower())
        self.assertEqual(card["owner"], "assistant")
        self.assertIn("box truck", card["line"].lower())

    def test_home_time_skips_reasking_support(self):
        state = facts(equipment="box_truck", fleetSize=1, operatingArea="Atlanta", supportNeed="daily_home_time", trailerLength="26ft")
        mem = {
            "goal": "local_work",
            "hard_constraint": "home_every_night",
            "concern": "home_time",
            "answered": ["equipment", "fleetSize", "operatingArea", "supportNeed", "primaryProblem", "trailerLength"],
            "blocker": None,
            "follow_up": "assistant",
        }
        self.assertEqual(playbook.next_ask(state, mem), "mcOwnership")
        self.assertNotIn("primaryProblem", playbook.missing_core(state, mem))
