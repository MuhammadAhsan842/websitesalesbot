"""Regression: lease-on chat failures from scientific review (prefer→reefer, chips, weekday, fee, COI)."""

from __future__ import annotations

import unittest

from app import fees, knowledge, playbook, requirements, rules, zoho
from app.schema import chip_options, length_chip_labels


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class PreferedDoesNotBecomeReefer(unittest.TestCase):
    def test_prefered_time_keeps_box_truck(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts(
            "sorry my number : 03124567497 time zone : Chicago (GMT-5) , prefered time you can call is 4pm"
        )}
        self.assertNotEqual(items.get("equipment"), "reefer")
        self.assertNotIn("equipment", items)
        self.assertEqual(items.get("phone"), "03124567497")
        self.assertEqual(items.get("callbackTimezone"), "America/Chicago")
        self.assertIn("4", str(items.get("callbackTime") or ""))
        self.assertNotEqual(items.get("operatingArea"), "chicago")


class LengthChipsByEquipment(unittest.TestCase):
    def test_box_truck_only_24_26_28(self):
        labels = length_chip_labels("box_truck")
        self.assertEqual(labels, ["24 ft", "26 ft", "28 ft"])
        opts = chip_options("trailerLength", facts(equipment="box_truck"))
        self.assertEqual([o["label"] for o in opts], ["24 ft", "26 ft", "28 ft"])

    def test_flatbed_48_53(self):
        self.assertEqual(length_chip_labels("flatbed"), ["48 ft", "53 ft"])

    def test_hotshot_30_40(self):
        self.assertEqual(length_chip_labels("hotshot"), ["30 ft", "40 ft"])


class LocalQualifyOrder(unittest.TestCase):
    def test_after_local_miles_asks_weekday(self):
        ask = playbook.next_ask(
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
                operatingMode="local",
                milesPerDay="500-600",
            )
        )
        self.assertEqual(ask, "weekdaySchedule")

    def test_after_weekday_asks_city(self):
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


class FeeAndReadyInsurance(unittest.TestCase):
    def test_fee_lease_needs_insurance_does_not_claim_unknown_arrangement(self):
        text = fees.live_quote("lease_on", insurance="needs_insurance")
        low = text.lower()
        self.assertIn("lease", low)
        self.assertIn("insurance", low)
        self.assertNotIn("once we know", low)
        self.assertNotIn("own-mc or lease-on", low.replace(" ", "").replace("-", ""))

    def test_ready_lease_skips_coi_when_needs_insurance(self):
        text, _, _ = playbook.compose(
            "onboard",
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
                operatingMode="local",
            ),
            [],
            "lease_on",
            False,
            None,
            None,
            {},
            plan={
                "answer_topics": ["onboarding"],
                "next_question_id": None,
                "conversation_move": "offer_handoff",
            },
            user_text="I'm ready to start",
        )
        low = text.lower()
        self.assertIn("insurance", low)
        self.assertNotIn("coi with the proper holder", low)
        self.assertIn("once the applicable coverage", low)

    def test_fit_summary_includes_length_insurance_callback(self):
        summary = playbook.fit_summary(
            facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
                operatingMode="local",
                milesPerDay="500-600",
                phone="03124567497",
                callbackTime="4pm",
                callbackTimezone="America/Chicago",
            ),
            "lease_on",
        )
        self.assertIn("26ft", summary.replace(" ", ""))
        self.assertIn("insurance", summary.lower())
        self.assertIn("callback", summary.lower())
        self.assertIn("Chicago", summary)


class ShortAnswersTommy(unittest.TestCase):
    def test_yours_means_lease_on(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("Yours", {"last_question_id": "mcOwnership"})
        }
        self.assertEqual(items.get("mcOwnership"), "no_own_mc")

    def test_open_means_unclear_mode(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("Open", {"last_question_id": "operatingMode"})
        }
        self.assertEqual(items.get("operatingMode"), "unclear")

    def test_your_insurance_selects_route(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("Your insurance", {"last_question_id": "insurance"})
        }
        self.assertEqual(items.get("insurance"), "needs_insurance")
        self.assertEqual(items.get("insuranceRoute"), "company_arranged")

    def test_no_do_not_on_coverage_is_unclear(self):
        items = {
            i["key"]: i["value"]
            for i in rules._short_answer_facts("No do not", {"last_question_id": "coverageTypes"})
        }
        self.assertEqual(items.get("coverageTypes"), "unclear")
        self.assertEqual(items.get("insurance"), "needs_insurance")

    def test_expired_auto_policy_not_present(self):
        items = {i["key"]: i["value"] for i in rules.extract_facts(
            "My commercial auto policy has expired"
        )}
        self.assertEqual(items.get("autoLiabilityCoverage"), "expired")
        self.assertNotEqual(items.get("autoLiabilityCoverage"), "present")
        self.assertEqual(items.get("insurance"), "needs_insurance")


class UngroundedGotIt(unittest.TestCase):
    def test_align_strips_invented_26_box(self):
        text, ask, chips = playbook.align_delivery(
            "Got it—a 26-foot box truck. Will you run under your own MC or lease on? What type of truck do you have?",
            "equipment",
            {},
        )
        self.assertEqual(ask, "equipment")
        self.assertNotRegex(text, r"(?i)26.?foot box")
        self.assertIn("truck", text.lower())


class RequirementsInsuranceQuote(unittest.TestCase):
    def test_needs_insurance_skips_coi(self):
        rows = requirements.catalog_for(
            "lease_agreement",
            facts(insurance="needs_insurance", mcOwnership="no_own_mc"),
        )
        types = [doc for doc, _ in rows]
        self.assertIn("licence", types)
        self.assertIn("registration", types)
        self.assertNotIn("coi", types)

    def test_task_for_insurance_quote(self):
        task = rules.task_for(
            "lease_on",
            "onboard",
            facts(insurance="needs_insurance"),
        )
        self.assertEqual(task, "insurance_quote")


class ZohoHandoffPayload(unittest.TestCase):
    def test_crm_carries_insurance_length_callback(self):
        session = {
            "id": "s1",
            "opportunity_id": "opp_test_12345678",
            "state_version": 1,
            "channel": "chat",
            "facts": facts(
                equipment="box_truck",
                trailerLength="26ft",
                mcOwnership="no_own_mc",
                insurance="needs_insurance",
                operatingMode="local",
                milesPerDay="500-600",
                phone="03124567497",
                callbackTime="4pm",
                callbackTimezone="America/Chicago",
            ),
        }
        payload = zoho.record(
            "manager_requested",
            session,
            {"task": "insurance_quote", "status": "manager_requested", "next_action": "Confirm insurance program and charges; complete callback"},
        )
        crm = payload["crm"]
        desc = payload["zoho"]["Description"]
        self.assertEqual(crm["trailer_length"], "26ft")
        self.assertEqual(crm["insurance"], "needs_insurance")
        self.assertEqual(crm["miles_per_day"], "500-600")
        self.assertEqual(crm["callback_timezone"], "America/Chicago")
        self.assertIn("insurance", (crm.get("needs_summary") or "").lower())
        self.assertIn("26", desc)
        self.assertIn("Reason for review", desc)
        self.assertIn("Next Step", desc)
        self.assertIn("timezone", desc.lower())
        self.assertNotIn("Closing_Date", payload["zoho"])
        self.assertIn("Lease-on review", payload["zoho"]["Deal_Name"])
        self.assertIn("Insurance", payload["zoho"]["Deal_Name"])


class KnowledgeCopy(unittest.TestCase):
    def test_fee_route_says_review_not_best_fitting(self):
        text = knowledge.lookup("fee_route_manager").lower()
        self.assertIn("review your request", text)
        self.assertNotIn("best-fitting", text)


if __name__ == "__main__":
    unittest.main()
