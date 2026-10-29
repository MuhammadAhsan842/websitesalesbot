"""End-to-end turn contract: wording, chips, memory, and next answer agree."""

from __future__ import annotations

import unittest

from app import graph, knowledge, playbook, rules
from app.schema import CHIPS, QUESTIONS


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class MoneyFilter(unittest.TestCase):
    def test_coverage_question_with_limits_does_not_leak(self):
        # Legacy wording with dollars must not become unknown.
        text = (
            "What coverage does your policy include — commercial auto "
            "(often around $750k–$1M), cargo (often around $100k), or both?"
        )
        self.assertFalse(graph._leaks(text))

    def test_earnings_promise_still_leaks(self):
        self.assertTrue(graph._leaks("We can help you make $5000 a week."))

    def test_attributed_counteroffer_percent_ok(self):
        self.assertFalse(graph._leaks("You're proposing 6%. That hasn't been approved."))


class ChipAndAgeParsing(unittest.TestCase):
    def test_about_five_months_chip(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("About 5 months", {"last_question_id": "authorityAgeMonths"})
        }
        self.assertEqual(items.get("authorityAgeMonths"), 5)

    def test_one_year_plus_chip(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("1 year+", {"last_question_id": "authorityAgeMonths"})
        }
        self.assertEqual(items.get("authorityAgeMonths"), 12)

    def test_my_mc_about_five_months_free_text(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts("my mc is about 5 months")}
        self.assertEqual(items.get("authorityAgeMonths"), 5)
        self.assertEqual(items.get("mcOwnership"), "own_mc")

    def test_miles_chip(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("400-500", {"last_question_id": "milesPerDay"})
        }
        self.assertEqual(items.get("milesPerDay"), "400-500")

    def test_auto_cargo_chip(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("Auto + cargo", {"last_question_id": "coverageTypes"})
        }
        self.assertEqual(items.get("coverageTypes"), "auto_and_cargo")


class AlignDelivery(unittest.TestCase):
    def test_replaces_fit_purchase_loop_with_pending_question(self):
        text, ask, chips = playbook.align_delivery(
            "Got it—a 30 ft hotshot. Since fit depends on lanes and own-MC vs lease-on, "
            "what's your current setup? Do you have a fit already, or are you planning a future purchase?",
            "coverageTypes",
            facts(equipment="hotshot", trailerLength="30ft"),
        )
        self.assertEqual(ask, "coverageTypes")
        self.assertIn("coverage", text.lower())
        self.assertNotIn("future purchase", text.lower())
        self.assertEqual(chips, CHIPS["coverageTypes"])

    def test_insurance_answer_advances_to_coverage_question(self):
        state = facts(
            equipment="hotshot",
            trailerLength="30ft",
            mcOwnership="own_mc",
            insurance="own_insurance",
            equipmentSupport="in_scope",
        )
        ask = playbook.next_ask(
            state,
            {"answered": ["equipment", "trailerLength", "mcOwnership", "insurance"]},
        )
        self.assertEqual(ask, "coverageTypes")
        text, delivered, chips = playbook.align_delivery(
            "I don't have that answer. I can note it for our onboarding manager instead of guessing.",
            ask,
            state,
        )
        self.assertEqual(delivered, "coverageTypes")
        self.assertIn("coverage", text.lower())
        self.assertNotIn("don't have that answer", text.lower())
        self.assertIn("Auto + cargo", chips)

    def test_local_chip_vs_mc_status_mismatch_fixed(self):
        text, ask, chips = playbook.align_delivery(
            "Got it—a 53ft dry van with your own insurance. What's your current MC status?",
            "milesPerDay",
            facts(equipment="dry_van", trailerLength="53ft", insurance="own_insurance", operatingMode="local"),
        )
        self.assertEqual(ask, "milesPerDay")
        self.assertIn("miles", text.lower())
        self.assertEqual(chips, CHIPS["milesPerDay"])


class HotshotReplay(unittest.TestCase):
    """Controlled replay of the failing hotshot conversation without a live model."""

    def test_sequence_fills_and_asks_one_aligned_question(self):
        mem = {"answered": [], "follow_up": "assistant", "explained": []}
        state = {}

        def apply(text):
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
            wording = (
                "Got it—a 30 ft hotshot. Since fit depends on lanes and own-MC vs lease-on, "
                "what's your current setup? Do you have a fit already, or are you planning a future purchase?"
            )
            text_out, delivered, chips = playbook.align_delivery(wording, ask, state)
            mem["last_question_id"] = delivered
            return text_out, delivered, chips, ask

        apply("30 ft hotshot")
        self.assertEqual(state["equipment"]["value"], "hotshot")
        self.assertEqual(state["trailerLength"]["value"], "30ft")

        text, delivered, chips, ask = apply("I have my own mc")
        self.assertEqual(state["mcOwnership"]["value"], "own_mc")
        self.assertEqual(ask, "insurance")
        self.assertEqual(delivered, "insurance")
        self.assertIn("insurance", text.lower())
        self.assertEqual(chips, CHIPS["insurance"])

        text, delivered, chips, ask = apply("I have my own insurance")
        self.assertEqual(state["insurance"]["value"], "own_insurance")
        self.assertEqual(ask, "coverageTypes")
        self.assertEqual(delivered, "coverageTypes")
        self.assertIn("coverage", text.lower())
        self.assertNotIn("don't have that answer", text.lower())
        self.assertNotIn("future purchase", text.lower())

        text, delivered, chips, ask = apply("Auto + cargo")
        self.assertEqual(state["coverageTypes"]["value"], "auto_and_cargo")
        self.assertIn(ask, {"authorityAgeMonths", "operatingMode"})
        self.assertEqual(delivered, ask)
        self.assertTrue(playbook._asks_about(text, ask))

        text, delivered, chips, ask = apply("About 5 months")
        self.assertEqual(state.get("authorityAgeMonths", {}).get("value"), 5)
        self.assertNotEqual(delivered, "authorityAgeMonths")  # age filled; next slot
        self.assertTrue(playbook._asks_about(text, delivered) or delivered is None)

        text, delivered, chips, ask = apply("I want local loads")
        # free text should set local when extract runs
        ruled = rules.propose("I want local loads", state, mem)
        for item in ruled["facts"]:
            state[item["key"]] = {"value": item["value"], "status": "user_stated"}
        self.assertEqual(state.get("operatingMode", {}).get("value"), "local")


class DryVanReplay(unittest.TestCase):
    def test_local_then_miles_aligned(self):
        state = facts(
            equipment="dry_van",
            trailerLength="53ft",
            mcOwnership="no_own_mc",
            insurance="own_insurance",
            coverageTypes="auto_and_cargo",
            operatingMode="local",
            equipmentSupport="in_scope",
        )
        mem = {
            "answered": [
                "equipment",
                "trailerLength",
                "mcOwnership",
                "insurance",
                "coverageTypes",
                "operatingMode",
            ],
            "follow_up": "assistant",
            "last_question_id": "milesPerDay",
        }
        ask = playbook.next_ask(state, mem)
        self.assertEqual(ask, "milesPerDay")
        text, delivered, chips = playbook.align_delivery(
            "Got it—a 53ft dry van with your own insurance. What's your current MC status?",
            ask,
            state,
        )
        self.assertEqual(delivered, "milesPerDay")
        self.assertIn("miles", text.lower())
        self.assertEqual(chips, ["400-500", "500-600", "I don't know yet"])
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("400-500", {"last_question_id": "milesPerDay"})
        }
        self.assertEqual(items["milesPerDay"], "400-500")


class TypedChips(unittest.TestCase):
    def test_chip_options_include_field_values(self):
        from app.schema import chip_options

        opts = chip_options("authorityAgeMonths")
        labels = {row["label"] for row in opts}
        self.assertIn("About 5 months", labels)
        about = next(row for row in opts if row["label"] == "About 5 months")
        self.assertEqual(about["field"], "authorityAgeMonths")
        self.assertEqual(about["value"], 5)

    def test_facts_from_chip_authoritative(self):
        items = {
            i["key"]: i["value"]
            for i in rules.facts_from_chip(
                {"label": "About 5 months", "field": "authorityAgeMonths", "value": 5}
            )
        }
        self.assertEqual(items.get("authorityAgeMonths"), 5)

    def test_api_chips_helper(self):
        from app.graph import _api_chips

        rows = _api_chips("milesPerDay", ["400-500"])
        self.assertEqual(rows[0]["field"], "milesPerDay")
        self.assertEqual(rows[0]["value"], "400-500")


class QualifyOrder(unittest.TestCase):
    def test_model_cannot_skip_trailer_length(self):
        from app import plan

        session = {
            "facts": facts(equipment="hotshot", equipmentSupport="in_scope"),
            "memory": {"answered": ["equipment", "equipmentSupport"], "follow_up": "assistant"},
        }
        validated = plan.validate_plan(
            "hotshot",
            session,
            {
                "intent": "general",
                "answer_topics": [],
                "next_question_id": "mcOwnership",
                "action": "none",
                "facts": [],
            },
        )
        self.assertEqual(validated["next_question_id"], "trailerLength")
        self.assertIn("qualify_order", validated["fallbacks"])

    def test_insurance_yes_chip_normalizes(self):
        items = {
            i["key"]: i["value"]
            for i in rules.facts_from_chip(
                {"label": "Yes, I have insurance", "field": "insurance", "value": "yes"}
            )
        }
        self.assertEqual(items.get("insurance"), "own_insurance")

    def test_authority_alias_chip(self):
        items = {
            i["key"]: i["value"]
            for i in rules.facts_from_chip(
                {"label": "I have my own MC", "field": "authority", "value": "own_mc"}
            )
        }
        self.assertEqual(items.get("mcOwnership"), "own_mc")

    def test_polluted_mc_draft_replaced(self):
        text, ask, chips = playbook.align_delivery(
            "Got it—a hotshot. That's a 30 or 40-foot box truck. I can't set up a case for that yet. "
            "Do you currently have your own MC, or are you looking to lease on?",
            "trailerLength",
            facts(equipment="hotshot", equipmentSupport="in_scope"),
        )
        self.assertEqual(ask, "trailerLength")
        self.assertIn("length", text.lower())
        self.assertNotIn("box truck", text.lower())
        self.assertNotIn("can't set up", text.lower())
        self.assertEqual(chips, ["30 ft", "40 ft"])


class RegisterVersion(unittest.TestCase):
    def test_v12(self):
        self.assertEqual(knowledge.REGISTER["version"], "ayyan_sales_v12")
        self.assertNotIn("$", QUESTIONS["coverageTypes"])


if __name__ == "__main__":
    unittest.main()
