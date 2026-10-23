"""Bounded response-plan: model proposes, playbook validates, records supply claims."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app import db, examples, fees, graph, main, memory, plan, playbook, qwen, retrieve, zoho
from app.graph import build_graph


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class PlanContract(unittest.TestCase):
    def test_fee_and_commitment_stay_together(self):
        text = "I have my own MC. What do you charge, and do I have to sign now?"
        self.assertEqual(plan.detect_topics(text, "fee"), ["dispatch_fee", "commitment"])
        validated = plan.validate_plan(
            text,
            {
                "facts": facts(mcOwnership="own_mc"),
                "memory": {"answered": ["mcOwnership"], "follow_up": "assistant"},
            },
            {
                "intent": "fee",
                "facts": [{"key": "mcOwnership", "value": "own_mc"}],
                "answer_topics": ["dispatch_fee"],
                "conversation_move": "answer",
                "next_question_id": "supportNeed",
                "action": "none",
                "wording": "Own MC is on file.",
            },
        )
        self.assertEqual(validated["answer_topics"], ["dispatch_fee", "commitment"])
        self.assertIsNone(validated["next_question_id"])
        reply, _, _ = playbook.compose(
            "fee",
            facts(mcOwnership="own_mc", equipment="hotshot"),
            ["Staff-approved own-MC dispatch fee is 8% of gross."],
            "dispatch_service",
            False,
            None,
            "supportNeed",
            {"concern": "total_fees", "answered": ["mcOwnership", "equipment"], "follow_up": "assistant"},
            wording="Own MC is on file.",
            plan=validated,
            user_text=text,
        )
        self.assertIn("8%", reply)
        self.assertTrue("not committing" in reply.lower() or "does not guarantee" in reply.lower())
        self.assertNotIn("What support matters most", reply)

    def test_repeat_question_and_invalid_packet_are_dropped(self):
        validated = plan.validate_plan(
            "Box truck, Dallas",
            {"facts": facts(equipment="box_truck", operatingArea="Dallas"), "memory": {"answered": ["equipment", "operatingArea"]}},
            {
                "intent": "onboard",
                "next_question_id": "equipment",
                "action": "create_case",
                "task": "setup_packet",
            },
        )
        self.assertIsNone(validated["next_question_id"])
        self.assertEqual(validated["proposed_action"], "none")
        self.assertIn("underspecified_packet", validated["fallbacks"])

    def test_action_message_only_after_success(self):
        self.assertFalse(plan.allow_action_message("Packet emailed and booked.", saved=False))
        self.assertTrue(plan.allow_action_message("Human-owned setup packet is saved locally.", saved=True))
        text, _, _ = playbook.compose(
            "onboard",
            facts(equipment="box_truck"),
            [],
            None,
            False,
            "Packet emailed.",
            None,
            memory.empty(),
            wording="Ready is recorded.",
        )
        self.assertNotIn("emailed", text.lower())
        self.assertNotIn("booked", text.lower())

    def test_invalid_plan_does_not_copy_example_reply(self):
        parsed = qwen.parse_content(json.dumps({
            "intent": "general",
            "answer_topics": ["dispatch_fee"],
            "wording": "Packet emailed, you're booked Friday",
        }))
        self.assertIsNone(parsed.wording)
        merged = graph._from_qwen(
            {"intent": "general", "wording": None, "action": "none"},
            {"intent": "general", "knowledge_keys": [], "blocked": [], "facts": []},
            "I run reefer Friday",
        )
        self.assertIsNone(merged.get("wording"))


class RetrievalJourneys(unittest.TestCase):
    def tearDown(self):
        examples.INDEX = examples._index_rows(list(examples.BANK))

    def test_friday_reefer_does_not_retrieve_monday_box(self):
        examples.reload_index()
        hits = examples.search("I run reefer. Need to roll Friday with produce.")
        ids = [hit["id"] for hit in hits]
        self.assertIn("reefer_friday", ids)
        self.assertNotIn("union_nj_monday", ids)

    def test_rejected_examples_stay_out_of_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "test.db"):
                db.init()
                db.save_example({
                    "id": "leaked_monday_box",
                    "user_text": "Reefer Friday produce confidential box truck Monday NJ",
                    "context": "Should never retrieve",
                    "reply": "Box truck Monday is on file.",
                    "tags": ["reefer", "friday"],
                    "status": "rejected",
                })
                examples.reload_index()
                ids = [hit["id"] for hit in examples.search("Reefer Friday produce")]
                self.assertNotIn("leaked_monday_box", ids)
                self.assertEqual(db.get_example("leaked_monday_box")["status"], "withdrawn")
                examples.reload_index()

    def test_withdrawn_seed_is_not_republished(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "test.db"):
                db.init()
                db.save_example({
                    "id": "union_nj_monday",
                    "user_text": "Monday box",
                    "reply": "Withdrawn copy.",
                    "status": "withdrawn",
                    "reviewed_by": "Staff desk",
                })
                from app import ingest

                ingest.seed_reviewed_bank()
                self.assertEqual(db.get_example("union_nj_monday")["status"], "withdrawn")
                examples.reload_index()
                ids = [row["id"] for row in examples.published()]
                self.assertNotIn("union_nj_monday", ids)

    def test_prompt_examples_are_strategy_not_case_facts(self):
        hits = examples.search("I run reefer. Need to roll Friday with produce.")
        prompt = examples.prompt_examples(hits)
        blob = json.dumps(prompt).lower()
        self.assertNotIn("monday", blob)
        self.assertNotIn("26-ft", blob)
        self.assertNotIn("liftgate", blob)
        self.assertIn("strategy", prompt[0])
        self.assertTrue(all("user" not in row for row in prompt))
        self.assertEqual(examples.search("thanks"), [])
        self.assertTrue(all(row["id"] != "weak_insurance_restart" for row in examples.BANK))


class MemoryJourneys(unittest.TestCase):
    def test_otr_keeps_stated_home_time_and_asks(self):
        session = {
            "facts": facts(operatingMode="local", supportNeed="daily_home_time"),
            "memory": {"hard_constraint": "home_every_night", "goal": "local_work", "answered": ["operatingMode", "supportNeed"]},
            "channel": "chat",
        }
        session["facts"]["operatingMode"] = {"value": "otr", "status": "corrected"}
        state = memory.update(session, {"intent": "general", "conversation_move": "acknowledge"}, "OTR")
        self.assertEqual(state["hard_constraint"], "home_every_night")
        self.assertEqual(state["goal"], "otr")
        self.assertTrue(any(row["key"] == "home_time_vs_otr" and row["status"] == "active" for row in state["records"]))
        self.assertIn("daily home time", memory.episodic_line(state, "OTR").lower())

    def test_otr_clears_local_only_inference(self):
        session = {
            "facts": facts(operatingMode="otr"),
            "memory": {"hard_constraint": "home_every_night", "goal": "local_work", "answered": ["operatingMode"]},
            "channel": "chat",
        }
        state = memory.update(session, {"intent": "general"}, "I'm switching to OTR")
        self.assertIsNone(state["hard_constraint"])
        self.assertEqual(state["goal"], "otr")

    def test_insurance_blocker_clears_when_resolved(self):
        session = {
            "facts": facts(equipment="box_truck"),
            "memory": {"last_blocker": "waiting_insurance", "blocker": "waiting_insurance", "records": [{"kind": "blocker", "key": "waiting_insurance", "status": "active"}]},
            "channel": "chat",
        }
        state = memory.update(session, {"intent": "general"}, "I got my insurance, COI is ready")
        self.assertIsNone(state["blocker"])
        self.assertIsNone(state["last_blocker"])
        self.assertTrue(any(row["key"] == "waiting_insurance" and row["status"] == "superseded" for row in state["records"]))
        self.assertIsNone(memory.episodic_line(state, "I got my insurance, COI is ready"))

    def test_pause_and_return(self):
        paused = memory.update(
            {"facts": {}, "memory": memory.empty(), "channel": "chat"},
            {"intent": "general"},
            "I'm pretty busy this week, let's see about next week",
        )
        self.assertEqual(paused["follow_up"], "driver_initiates")
        self.assertEqual(paused["concern"], "pause")
        text, chips, _ = playbook.compose("general", {}, [], None, False, None, "equipment", paused)
        self.assertIn("whenever you're ready", text.lower())
        self.assertEqual(chips, [])
        resumed = memory.update(
            {"facts": {}, "memory": paused, "channel": "chat"},
            {"intent": "general"},
            "I'm back. Ready to talk.",
        )
        self.assertEqual(resumed["follow_up"], "assistant")


class FeeCommitGraph(unittest.IsolatedAsyncioTestCase):
    async def test_plan_answers_both_questions_and_blocks_false_success(self):
        def handler(request):
            payload = json.loads(request.content)
            user = json.loads(payload["messages"][1]["content"])
            text = user["text"]
            body = {"intent": "general", "action": "none"}
            if "own MC" in text and "charge" in text.lower():
                body = {
                    "intent": "fee",
                    "facts": [{"key": "mcOwnership", "value": "own_mc"}],
                    "answer_topics": ["dispatch_fee", "commitment"],
                    "conversation_move": "answer",
                    "next_question_id": None,
                    "action": "none",
                    "wording": "Own MC is on file.",
                }
            elif "ready to start" in text.lower():
                body = {"intent": "onboard", "action": "create_case", "task": "setup_packet", "wording": "Packet emailed."}
            self.assertIn("answer_topics", payload["format"]["properties"])
            self.assertIn("next_question_id", payload["format"]["properties"])
            return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model_client:
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch.object(db, "DB_PATH", Path(temporary) / "test.db"),
                patch.object(zoho, "access_token", return_value=None),
                patch.object(retrieve, "search", return_value=[]),
                patch.object(qwen, "_client", model_client),
                patch.object(qwen, "_gate", qwen.Admission(qwen.CONFIG)),
                patch.object(main.app.state, "graph", build_graph(InMemorySaver()), create=True),
            ):
                db.init()
                fees.publish("dispatch_service", 8, "Staff")
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                    opened = await api.post("/v1/session", json={})
                    sid = opened.json()["session_id"]
                    reply = await api.post(
                        "/v1/turn",
                        json={"session_id": sid, "text": "I have my own MC. What do you charge, and do I have to sign now?"},
                    )
                    self.assertEqual(reply.status_code, 200)
                    body = reply.json()
                    self.assertIn("8%", body["text"])
                    self.assertTrue("not committing" in body["text"].lower() or "does not guarantee" in body["text"].lower())
                    self.assertNotIn("What support matters most", body["text"])
                    plan_trace = next(item for item in body["traces"] if item["stage"] == "plan")
                    self.assertIn("dispatch_fee", plan_trace["answer_topics"])
                    self.assertIn("commitment", plan_trace["answer_topics"])
                    self.assertIsNone(plan_trace["next_question_id"])
                    self.assertNotIn("emailed", body["text"].lower())

                    blocked = await api.post("/v1/turn", json={"session_id": sid, "text": "I'm ready to start"})
                    self.assertIsNone(blocked.json().get("case_id"))
                    self.assertNotIn("emailed", blocked.json()["text"].lower())
                    self.assertNotIn("booked", blocked.json()["text"].lower())


class AfterHoursJourney(unittest.IsolatedAsyncioTestCase):
    async def test_complete_dallas_box_onboarding(self):
        def handler(request):
            payload = json.loads(request.content)
            user = json.loads(payload["messages"][1]["content"])
            text = user["text"].lower()
            blob = json.dumps(user.get("examples") or []).lower()
            self.assertNotIn("26-ft", blob)
            self.assertNotIn("liftgate", blob)
            self.assertNotIn("e-track", blob)
            body = {"intent": "general", "action": "none"}
            if "box truck" in text and "dallas" in text:
                body = {
                    "intent": "dispatch_inquiry",
                    "facts": [
                        {"key": "equipment", "value": "box_truck", "evidence": "box truck"},
                        {"key": "operatingArea", "value": "Dallas", "evidence": "Dallas"},
                        {"key": "mcOwnership", "value": "own_mc", "evidence": "own MC"},
                    ],
                    "conversation_move": "acknowledge",
                    "wording": "Dallas box truck, own MC on file.",
                }
            elif "charge" in text and "sign" in text:
                body = {
                    "intent": "fee",
                    "answer_topics": ["dispatch_fee", "commitment"],
                    "conversation_move": "answer",
                    "wording": "Both questions noted.",
                }
            elif "busy this week" in text:
                body = {"intent": "general", "conversation_move": "pause", "answer_topics": ["pause"]}
            elif "back from last week" in text:
                body = {"intent": "general", "conversation_move": "acknowledge", "wording": "Welcome back."}
            elif "comparing quotes" in text:
                body = {"intent": "general", "conversation_move": "acknowledge", "wording": "Insurance delay is on file."}
            elif "insurance is active" in text:
                body = {"intent": "general", "conversation_move": "acknowledge", "wording": "You report coverage arranged."}
            elif "ready to start" in text:
                body = {"intent": "onboard", "action": "create_case", "task": "setup_packet", "wording": "Ready is recorded."}
            return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model_client:
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch.object(db, "DB_PATH", Path(temporary) / "test.db"),
                patch.object(zoho, "access_token", return_value=None),
                patch.object(retrieve, "search", return_value=[]),
                patch.object(qwen, "_client", model_client),
                patch.object(qwen, "_gate", qwen.Admission(qwen.CONFIG)),
                patch.object(main.app.state, "graph", build_graph(InMemorySaver()), create=True),
            ):
                db.init()
                fees.publish("dispatch_service", 8, "Staff")
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                    sid = (await api.post("/v1/session", json={})).json()["session_id"]
                    fit = await api.post("/v1/turn", json={"session_id": sid, "text": "I run one box truck in Dallas with my own MC"})
                    self.assertIn("box", fit.json()["text"].lower())
                    fee = await api.post(
                        "/v1/turn",
                        json={"session_id": sid, "text": "What do you charge, and do I have to sign now?"},
                    )
                    self.assertIn("8%", fee.json()["text"])
                    self.assertTrue("not committing" in fee.json()["text"].lower() or "talking here is not" in fee.json()["text"].lower())
                    pause = await api.post(
                        "/v1/turn",
                        json={"session_id": sid, "text": "I'm pretty busy this week, let's see about next week"},
                    )
                    self.assertIn("ready", pause.json()["text"].lower())
                    self.assertNotIn("What are you running", pause.json()["text"])
                    back = await api.post("/v1/turn", json={"session_id": sid, "text": "Hey, I'm back from last week."})
                    self.assertEqual(back.status_code, 200)
                    quotes = await api.post("/v1/turn", json={"session_id": sid, "text": "Not yet. I'm still comparing quotes."})
                    self.assertNotIn("What are you running", quotes.json()["text"])
                    arranged = await api.post("/v1/turn", json={"session_id": sid, "text": "Insurance is active now."})
                    desk = (await api.get(f"/v1/session/{sid}")).json()["desk"]
                    self.assertTrue(any(row.get("status") == "superseded" for row in desk.get("records") or []))
                    ready = await api.post("/v1/turn", json={"session_id": sid, "text": "I'm ready to start"})
                    self.assertIsNotNone(ready.json().get("case_id"))
                    self.assertIn("saved locally", ready.json()["text"].lower())
                    self.assertNotIn("emailed", ready.json()["text"].lower())
                    self.assertNotIn("booked", ready.json()["text"].lower())
