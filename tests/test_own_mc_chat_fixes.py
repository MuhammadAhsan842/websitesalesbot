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

    def test_otr_goes_straight_to_start_no_weekday_or_miles(self):
        state = facts(
            equipment="hotshot",
            trailerLength="30ft",
            mcOwnership="own_mc",
            authorityAgeMonths=12,
            operatingMode="otr",
            equipmentSupport="in_scope",
        )
        ask = playbook.next_ask(state)
        self.assertEqual(ask, "startDate")
        missing = playbook.missing_core(state)
        self.assertNotIn("weekdaySchedule", missing)
        self.assertNotIn("stayOutDuration", missing)
        self.assertNotIn("milesPerDay", missing)

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
    def test_freight_topic_never_asks_city_on_own_mc(self):
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
        self.assertIsNone(validated["next_question_id"])
        self.assertNotEqual(validated["next_question_id"], "operatingArea")

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

    def test_period_ended_insurance_plus_age_keeps_only_age(self):
        text, ask, _ = playbook.align_delivery(
            "Got it—you're running under your own MC. Do you currently have active commercial insurance, "
            "or do you need help getting set up. About how old is your MC or authority?",
            "authorityAgeMonths",
            facts(equipment="hotshot", trailerLength="40ft", mcOwnership="own_mc"),
        )
        self.assertEqual(ask, "authorityAgeMonths")
        low = text.lower()
        self.assertIn("how old", low)
        self.assertNotIn("insurance", low)
        self.assertEqual(low.count("?"), 1)

    def test_city_plus_start_keeps_only_start(self):
        text, ask, _ = playbook.align_delivery(
            "Got it—Monday through Friday. What city or ZIP will you be starting from. When would you like to start?",
            "startDate",
            facts(
                equipment="hotshot",
                trailerLength="40ft",
                mcOwnership="own_mc",
                operatingMode="local",
                weekdaySchedule="monday_friday",
            ),
        )
        self.assertEqual(ask, "startDate")
        low = text.lower()
        self.assertIn("when would you like to start", low)
        self.assertNotIn("city", low)
        self.assertNotIn("zip", low)

    def test_otr_strips_weekday_and_miles_when_start_pending(self):
        text, ask, _ = playbook.align_delivery(
            "Got it, OTR. Do you normally run Monday through Friday, or are you open to weekends too?",
            "startDate",
            facts(
                equipment="reefer",
                trailerLength="53ft",
                mcOwnership="own_mc",
                authorityAgeMonths=5,
                operatingMode="otr",
                equipmentSupport="in_scope",
            ),
        )
        self.assertEqual(ask, "startDate")
        low = text.lower()
        self.assertIn("when would you like to start", low)
        self.assertNotIn("monday through friday", low)
        self.assertNotIn("miles", low)

        text2, ask2, _ = playbook.align_delivery(
            "Got it, OTR. How many miles can you cover in a day?",
            "startDate",
            facts(
                equipment="reefer",
                trailerLength="53ft",
                mcOwnership="own_mc",
                operatingMode="otr",
                equipmentSupport="in_scope",
            ),
        )
        self.assertEqual(ask2, "startDate")
        self.assertIn("when would you like to start", text2.lower())
        self.assertNotIn("miles", text2.lower())

    def test_standalone_city_ask_stripped_when_no_pending(self):
        text, ask, _ = playbook.align_delivery(
            "Got it, starting today. What city or ZIP will you be heading out from?",
            None,
            facts(
                equipment="hotshot",
                trailerLength="40ft",
                mcOwnership="own_mc",
                startDate="today",
                equipmentSupport="in_scope",
            ),
        )
        self.assertIsNone(ask)
        self.assertNotIn("city", text.lower())
        self.assertNotIn("zip", text.lower())


class DocsBeatStickyFee(unittest.TestCase):
    def test_what_did_you_need_is_docs_not_fee(self):
        topics = plan.detect_topics(
            "What did youneed from me to start?",
            intent="general",
            concern="total_fees",
        )
        self.assertIn("docs_status", topics)
        self.assertNotIn("dispatch_fee", topics)

    def test_compose_docs_not_fee_paragraph(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(
                equipment="hotshot",
                trailerLength="40ft",
                mcOwnership="own_mc",
                startDate="today",
                equipmentSupport="in_scope",
            ),
            [],
            "dispatch_service",
            False,
            None,
            None,
            {"answered": [], "concern": "total_fees", "follow_up": "assistant"},
            plan={
                "answer_topics": ["docs_status"],
                "next_question_id": None,
                "proposed_action": "none",
            },
            user_text="What did youneed from me to start?",
            wording="For this arrangement, the current own-MC dispatch fee is 8% of gross.",
        )
        low = reply.lower()
        self.assertTrue("w-9" in low or "authority" in low)
        self.assertNotIn("8%", low)


class ReadyComposeOneRoute(unittest.TestCase):
    def test_ready_after_start_is_brief(self):
        reply, chips, _ = playbook.compose(
            "onboard",
            facts(
                equipment="hotshot",
                trailerLength="40ft",
                mcOwnership="own_mc",
                authorityAgeMonths=5,
                operatingMode="local",
                milesPerDay="500-600",
                weekdaySchedule="monday_friday",
                startDate="today",
                equipmentSupport="in_scope",
            ),
            [],
            "dispatch_service",
            False,
            None,
            None,
            {"answered": [], "follow_up": "assistant"},
            plan={"answer_topics": ["onboarding"], "next_question_id": None},
            user_text="I'm ready to start",
        )
        low = reply.lower()
        self.assertIn("setup review", low)
        self.assertNotIn("box truck 24/26/28", low)
        self.assertNotIn("dry van", low)
        self.assertEqual(chips, CHIPS["handoff"])

    def test_saved_own_mc_single_docs_list(self):
        reply, _, _ = playbook.compose(
            "general",
            facts(equipment="hotshot", trailerLength="40ft", mcOwnership="own_mc", equipmentSupport="in_scope"),
            [],
            "dispatch_service",
            True,
            knowledge.lookup("own_mc_review_saved"),
            None,
            {"answered": [], "follow_up": "assistant"},
            plan={"answer_topics": [], "next_question_id": None, "proposed_action": "create_case"},
            user_text="today",
            wording="Got it, next week. What's the best email to send the packet to?",
        )
        low = reply.lower()
        self.assertIn("setup review is saved", low)
        self.assertIn("w-9", low)
        self.assertIn("coi", low)
        self.assertNotIn("email", low)
        self.assertNotIn("licence", low)
        self.assertNotIn("we only dispatch these types", low)
        self.assertEqual(low.count("setup review is saved"), 1)


class FreightOwnMcNoCity(unittest.TestCase):
    def test_freight_does_not_ask_city_for_own_mc(self):
        validated = plan.validate_plan(
            "what load options do you have near me?",
            {
                "facts": facts(
                    equipment="hotshot",
                    trailerLength="40ft",
                    mcOwnership="own_mc",
                    startDate="today",
                ),
                "memory": {"answered": [], "follow_up": "assistant"},
            },
            {
                "intent": "freight",
                "facts": [],
                "answer_topics": ["freight"],
                "next_question_id": None,
                "action": "none",
                "wording": "Where should we look?",
            },
        )
        self.assertIsNone(validated["next_question_id"])
        self.assertIn("freight", validated["answer_topics"])


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


class LengthBeforeReject(unittest.TestCase):
    def test_flatbed_without_length_asks_length(self):
        state = facts(equipment="flatbed", equipmentSupport="out_of_scope")
        self.assertEqual(playbook.next_ask(state), "trailerLength")
        reply, _, _ = playbook.compose(
            "dispatch_inquiry",
            state,
            [],
            None,
            False,
            None,
            "trailerLength",
            {"answered": ["equipment"], "follow_up": "assistant"},
            plan={"answer_topics": [], "next_question_id": "trailerLength"},
            user_text="Flatbed",
            wording=knowledge.lookup("equip_unsupported"),
        )
        low = reply.lower()
        self.assertIn("length", low)
        self.assertIn("flatbed", low)
        self.assertNotIn("outside what we dispatch", low)

    def test_merge_blocks_model_out_of_scope_before_length(self):
        from app import graph

        merged = graph._merge_facts(
            [{"key": "equipmentSupport", "value": "out_of_scope", "evidence": "outside"}],
            [{"key": "equipment", "value": "flatbed", "status": "user_stated"},
             {"key": "equipmentSupport", "value": "in_scope", "status": "user_stated"}],
            "Flatbed",
            {},
        )
        by_key = {item["key"]: item["value"] for item in merged}
        self.assertEqual(by_key.get("equipment"), "flatbed")
        self.assertEqual(by_key.get("equipmentSupport"), "in_scope")

    def test_box_truck_without_length_asks_length(self):
        text, ask, _ = playbook.align_delivery(
            knowledge.lookup("equip_unsupported"),
            None,
            facts(equipment="box_truck", equipmentSupport="in_scope"),
        )
        self.assertEqual(ask, "trailerLength")
        low = text.lower()
        self.assertIn("box", low)
        self.assertIn("length", low)
        self.assertNotIn("outside what we dispatch", low)


class ExclusiveLengthAsk(unittest.TestCase):
    def test_double_length_phrasing_collapses_to_one(self):
        text, ask, _ = playbook.align_delivery(
            "What is the length of your reefer. What length trailer or box are you running?",
            "trailerLength",
            facts(equipment="reefer", equipmentSupport="in_scope"),
        )
        self.assertEqual(ask, "trailerLength")
        self.assertEqual(text.count("?"), 1)
        low = text.lower()
        self.assertIn("reefer", low)
        self.assertNotIn("trailer or box", low)
        self.assertLessEqual(playbook._info_request_count(text), 1)


class NoRepeatedEquipAck(unittest.TestCase):
    def test_after_own_mc_age_ask_does_not_restamp_truck(self):
        text, ask, _ = playbook.align_delivery(
            "Got it — 48ft reefer. About how old is your MC or authority?",
            "authorityAgeMonths",
            facts(
                equipment="reefer",
                trailerLength="48ft",
                mcOwnership="own_mc",
                equipmentSupport="in_scope",
            ),
        )
        self.assertEqual(ask, "authorityAgeMonths")
        low = text.lower()
        self.assertIn("how old", low)
        self.assertNotIn("48ft reefer", low.replace(" ", ""))
        self.assertNotIn("48 ft reefer", low)
        # One short question — no truck stamp lead-in.
        self.assertFalse(low.startswith("got it — 48"))

    def test_length_and_mc_turns_still_ack_once(self):
        length_text, _, _ = playbook.align_delivery(
            "That equipment is outside what we dispatch.",
            "trailerLength",
            facts(equipment="flatbed", equipmentSupport="in_scope"),
        )
        self.assertIn("flatbed", length_text.lower())
        mc_text, _, _ = playbook.align_delivery(
            "random",
            "mcOwnership",
            facts(equipment="flatbed", trailerLength="53ft", equipmentSupport="in_scope"),
        )
        self.assertRegex(mc_text.lower(), r"got it.*,?\s*53\s*ft\s*flatbed")
        self.assertIn("own mc", mc_text.lower())


class StartDateTomorrow(unittest.TestCase):
    def test_tommorow_fills_start_when_pending(self):
        items = rules._short_answer_facts("tommorow", {"last_question_id": "startDate"})
        self.assertTrue(any(i["key"] == "startDate" and i["value"] == "tomorrow" for i in items))

    def test_tomorrow_in_free_text(self):
        ruled = rules.propose("tommorow", {}, {"last_question_id": "startDate", "answered": [], "follow_up": "assistant"})
        keys = {i["key"]: i["value"] for i in ruled["facts"] if i["key"] != "_unknown"}
        self.assertEqual(keys.get("startDate"), "tomorrow")


class HandoffCopy(unittest.TestCase):
    def test_no_nobody_has_accepted(self):
        self.assertNotIn("nobody has accepted", knowledge.lookup("handoff_requested").lower())
        self.assertIn("callback", knowledge.lookup("handoff_requested").lower())


if __name__ == "__main__":
    unittest.main()
