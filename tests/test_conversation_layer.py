"""Moves, extra facts, repair edges, example bank, and session restore."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app import db, examples, graph, main, memory, playbook, qwen, retrieve, rules, variants, zoho
from app.graph import build_graph


def facts(**values):
    return {key: {"value": value, "status": "user_stated"} for key, value in values.items()}


class ExtraFacts(unittest.TestCase):
    def test_union_local_box_stores_first_class_fields(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "26 foot box, liftgate, local New Jersey, need to roll Monday"
        )}
        self.assertEqual(items["equipment"], "box_truck")
        self.assertEqual(items["trailerLength"], "26ft")
        self.assertEqual(items["liftgate"], "yes")
        self.assertEqual(items["operatingMode"], "local")
        self.assertEqual(items["operatingArea"], "nj")
        self.assertEqual(items["deadline"], "monday")
        self.assertNotIn("union", items)

    def test_wont_sign_and_payload(self):
        items = {item["key"]: item["value"] for item in rules.extract_facts(
            "I need 10,000 lb payload and I don't want to sign for nothing"
        )}
        self.assertEqual(items["payload"], "10000")
        self.assertEqual(items["commitmentStance"], "wont_sign")

    def test_deadline_unblocks_mc_not_start_date(self):
        state = facts(equipment="box_truck", deadline="monday", operatingArea="nj", startDate="monday")
        self.assertEqual(playbook.next_ask(state, memory.empty()), "mcOwnership")
        self.assertEqual(playbook.next_ask(state, memory.empty(), "fee"), "mcOwnership")
        self.assertIsNone(playbook.next_ask(state, memory.empty(), "existing_customer", "leave_sales"))


class RepairEdges(unittest.TestCase):
    def test_authority_ready_is_unclear_not_own_mc(self):
        proposal = rules.propose("My authority is ready", {}, None)
        self.assertEqual(proposal["repair"], "authority_uncertain")
        self.assertEqual(proposal["intent"], "mc_new")
        self.assertEqual(proposal["action"], "none")
        values = {item["key"]: item["value"] for item in proposal["facts"]}
        self.assertEqual(values["mcOwnership"], "unclear")

    def test_meant_the_fee(self):
        proposal = rules.propose("No, I meant the fee", {}, None)
        self.assertEqual(proposal["repair"], "topic_fee")
        self.assertEqual(proposal["intent"], "fee")

    def test_need_to_get_paid_leaves_sales(self):
        proposal = rules.propose("Forget onboarding, I need to get paid", {}, None)
        self.assertEqual(proposal["repair"], "leave_sales")
        self.assertEqual(proposal["intent"], "existing_customer")
        self.assertEqual(proposal["task"], "operations_support")
        self.assertEqual(proposal["action"], "create_case")

    def test_i_have_everything_does_not_verify_docs(self):
        proposal = rules.propose("I have everything", facts(equipment="box_truck"), None)
        self.assertEqual(proposal["repair"], "repetition_unverified")
        text, _, _ = playbook.compose(
            "general",
            facts(equipment="box_truck"),
            [],
            None,
            False,
            None,
            "fleetSize",
            memory.empty(),
            repair="repetition_unverified",
        )
        self.assertIn("cannot see documents staff have not received", text.lower())
        self.assertNotIn("approved", text.lower())


class ExampleBank(unittest.TestCase):
    def test_retrieves_approved_ids_with_rewritten_reply(self):
        hits = examples.search("My authority is ready")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "authority_ready")
        self.assertEqual(hits[0]["move"], "clarify")
        self.assertIn("own-MC", hits[0]["reply"])
        self.assertTrue(all(examples.allowed(row) for row in examples.BANK))


class MovesAndWording(unittest.TestCase):
    def test_default_move_and_variant(self):
        self.assertEqual(variants.default_move("mc_new", "authority_uncertain", None, "mcOwnership"), "clarify")
        self.assertEqual(variants.default_variant("clarify", None, "mc_new", "authority_uncertain"), "clarify_mc")
        self.assertEqual(variants.default_move("existing_customer", "leave_sales", None, None), "offer_handoff")

    def test_wording_with_percent_is_dropped(self):
        parsed = qwen.parse_content(json.dumps({"intent": "fee", "wording": "Staff quote is 8%"}))
        self.assertIsNone(parsed.wording)
        parsed = qwen.parse_content(json.dumps({"intent": "fee", "wording": "Own-MC path is on file"}))
        self.assertEqual(parsed.wording, "Own-MC path is on file")

    def test_examples_and_last_blocker_reach_qwen_payload(self):
        payload = qwen.request_payload(
            "My authority is ready",
            {},
            "discover_needs",
            memory={"last_blocker": "waiting_insurance", "follow_up": "assistant"},
            examples=examples.search("My authority is ready"),
        )
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(user["memory"]["last_blocker"], "waiting_insurance")
        self.assertEqual(user["examples"][0]["id"], "authority_ready")
        self.assertIn("conversation_move", payload["format"]["properties"])
        self.assertIn("reply_variant_id", payload["format"]["properties"])

    def test_episodic_line_only_when_blocker_is_stale(self):
        mem = {"last_blocker": "waiting_insurance"}
        self.assertIn("waiting on insurance", memory.episodic_line(mem, "What do you charge?").lower())
        self.assertIsNone(memory.episodic_line(mem, "Still waiting on insurance"))
        self.assertIsNone(memory.episodic_line({"last_blocker": "waiting_packet"}, "Dallas. Local only"))
        self.assertIn("packet", memory.episodic_line({"last_blocker": "waiting_packet"}, "I'm back. What's my status?").lower())


class SessionRestore(unittest.IsolatedAsyncioTestCase):
    async def test_repair_paths_and_history_endpoint(self):
        def handler(request):
            payload = json.loads(request.content)
            text = json.loads(payload["messages"][1]["content"])["text"]
            body = {"intent": "general"}
            if "charge" in text.lower() or "fee" in text.lower():
                body = {"intent": "fee", "conversation_move": "answer", "reply_variant_id": "answer_fee"}
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
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                    opened = await api.post("/v1/session", json={})
                    sid = opened.json()["session_id"]

                    ready = await api.post("/v1/turn", json={"session_id": sid, "text": "My authority is ready"})
                    self.assertEqual(ready.status_code, 200)
                    body = ready.json()
                    plan = next(t for t in body["traces"] if t["stage"] == "plan")
                    self.assertEqual(plan["repair"], "authority_uncertain")
                    self.assertEqual(plan["action"], "none")
                    self.assertIsNone(body.get("case_id"))
                    self.assertNotIn("approved", body["text"].lower())
                    stored = db.get_session(sid)
                    self.assertEqual(stored["facts"]["mcOwnership"]["value"], "unclear")
                    self.assertIn("Will you run under your own MC", body["text"])

                    paid = await api.post("/v1/turn", json={"session_id": sid, "text": "Forget onboarding, I need to get paid"})
                    self.assertEqual(paid.json()["traces"][-1]["stage"], "reply")
                    plan = next(t for t in paid.json()["traces"] if t["stage"] == "plan")
                    self.assertEqual(plan["repair"], "leave_sales")
                    self.assertEqual(plan["task"], "operations_support")
                    self.assertEqual(plan["action"], "create_case")
                    self.assertIn("operations", paid.json()["text"].lower())

                    opened2 = await api.post("/v1/session", json={})
                    sid2 = opened2.json()["session_id"]
                    await api.post("/v1/turn", json={"session_id": sid2, "text": "I run one box truck in Atlanta"})
                    docs = await api.post("/v1/turn", json={"session_id": sid2, "text": "I have everything"})
                    self.assertIn("cannot see documents staff have not received", docs.json()["text"].lower())
                    self.assertIsNone(docs.json().get("case_id") or db.get_session(sid2).get("case_id"))

                    fee = await api.post("/v1/turn", json={"session_id": sid2, "text": "No, I meant the fee"})
                    plan = next(t for t in fee.json()["traces"] if t["stage"] == "plan")
                    self.assertEqual(plan["repair"], "topic_fee")
                    self.assertNotIn("You're looking for support", fee.json()["text"])

                    history = await api.get(f"/v1/session/{sid2}")
                    self.assertEqual(history.status_code, 200)
                    messages = history.json()["messages"]
                    self.assertGreaterEqual(len(messages), 4)
                    self.assertEqual(messages[0]["role"], "user")
                    self.assertIn("next_step", history.json()["desk"])
                    first = await api.post(
                        "/v1/turn",
                        json={"session_id": sid2, "text": "Call me at 469-555-0199", "turn_id": "turn-replay-1"},
                    )
                    replay = await api.post(
                        "/v1/turn",
                        json={"session_id": sid2, "text": "Call me at 469-555-0199", "turn_id": "turn-replay-1"},
                    )
                    self.assertEqual(first.json()["text"], replay.json()["text"])
                    missing = await api.get("/v1/session/does-not-exist")
                    self.assertEqual(missing.status_code, 404)


class MergeRepair(unittest.TestCase):
    def test_qwen_cannot_promote_authority_ready_to_own_mc(self):
        ruled = rules.propose("My authority is ready", {}, None)
        merged = graph._from_qwen(
            {"intent": "mc", "facts": [{"key": "mcOwnership", "value": "own_mc"}], "action": "create_case", "task": "setup_packet"},
            ruled,
            "My authority is ready",
        )
        self.assertEqual(merged["intent"], "mc_new")
        self.assertEqual(merged["action"], "none")
        values = {item["key"]: item["value"] for item in merged["facts"]}
        self.assertEqual(values["mcOwnership"], "unclear")


if __name__ == "__main__":
    unittest.main()
