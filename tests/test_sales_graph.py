"""Real graph/database regressions with schema-valid, synthetic Qwen responses."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app import db, main, qwen, retrieve, zoho
from app.graph import build_graph
from scripts.five_scenarios import SCENARIOS


PROPOSALS = {
    "I need dispatch": {"intent": "dispatch_inquiry"},
    "I run one hotshot with my own MC in Texas, paperwork, start next week": {
        "intent": "mc",
        "facts": [
            {"key": "equipment", "value": "hotshot"},
            {"key": "fleetSize", "value": 1},
            {"key": "mcOwnership", "value": "own_mc"},
            {"key": "operatingArea", "value": "Texas"},
            {"key": "supportNeed", "value": "paperwork"},
            {"key": "startDate", "value": "next week"},
        ],
    },
    "I'm ready to start": {"intent": "onboard"},
    "What do you charge? Can you do 6% like Leo Dispatch?": {
        "intent": "fee",
        "knowledge_keys": ["fee", "competitor"],
        "blocked": ["invented_fee"],
    },
    "I have my own MC": {"intent": "mc", "facts": [{"key": "mcOwnership", "value": "own_mc"}]},
    "Can you guarantee $10,000 a week and keep me loaded?": {
        "intent": "guarantee",
        "knowledge_keys": ["guarantee", "freight"],
        "blocked": ["guarantee"],
    },
    "Call me at 469-555-0199": {"intent": "call_me", "facts": [{"key": "phone", "value": "469-555-0199"}]},
    "What's my status?": {"intent": "status"},
    "I want to lease on. I have to be home every night.": {
        "intent": "hometime",
        "facts": [{"key": "mcOwnership", "value": "no_own_mc"}, {"key": "supportNeed", "value": "daily_home_time"}],
    },
    "One box truck, Atlanta, start next week": {
        "intent": "dispatch_inquiry",
        "facts": [
            {"key": "fleetSize", "value": 1},
            {"key": "equipment", "value": "box_truck"},
            {"key": "operatingArea", "value": "Atlanta"},
            {"key": "startDate", "value": "next week"},
        ],
    },
}


class SalesGraph(unittest.IsolatedAsyncioTestCase):
    async def test_five_flows_keep_qwen_and_correct_case_branch(self):
        calls = []

        def model(request):
            payload = json.loads(request.content)
            text = json.loads(payload["messages"][1]["content"])["text"]
            calls.append(text)
            return httpx.Response(200, json={"message": {"content": json.dumps(PROPOSALS[text])}, "eval_count": 32})

        async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as model_client:
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch.object(db, "DB_PATH", Path(temporary) / "test.db"),
                patch.object(zoho, "access_token", return_value=None),
                patch.object(retrieve, "search", return_value=[{"key": "unknown", "text": "Ask the team", "hybrid": 0}]),
                patch.object(qwen, "_client", model_client),
                patch.object(qwen, "_gate", qwen.Admission(qwen.CONFIG)),
                patch.object(main.app.state, "graph", build_graph(InMemorySaver()), create=True),
            ):
                db.init()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                    for number, (_, lines) in enumerate(SCENARIOS, 1):
                        with self.subTest(scenario=number):
                            opened = await api.post("/v1/session", json={})
                            self.assertEqual(opened.status_code, 200)
                            sid = opened.json()["session_id"]
                            outputs = []
                            for line in lines:
                                reply = await api.post("/v1/turn", json={"session_id": sid, "text": line})
                                self.assertEqual(reply.status_code, 200)
                                output = reply.json()
                                outputs.append(output)
                                trace = next(t for t in output["traces"] if t["stage"] == "propose")
                                self.assertIn(trace["source"], {"qwen", "gemma"})
                                self.assertIn("request_ms", trace["timing"])
                                self.assertNotIn("6%", output["text"])
                                self.assertNotIn("$10,000", output["text"])
                            stored = db.get_session(sid)
                            case = db.get_case(stored["case_id"]) if stored.get("case_id") else None
                            if number == 1:
                                self.assertEqual(case["task"], "setup_packet")
                                self.assertEqual(stored["facts"]["fleetSize"]["value"], 1)
                            elif number == 2:
                                self.assertEqual(stored["facts"]["mcOwnership"]["value"], "own_mc")
                                self.assertEqual(stored["channel"], "chat")
                            elif number == 3:
                                keys = next(t["keys"] for t in outputs[-1]["traces"] if t["stage"] == "knowledge")
                                self.assertTrue({"guarantee", "freight"}.issubset(keys))
                            elif number == 4:
                                self.assertEqual(case["task"], "callback")
                                self.assertIn("callback_requested", outputs[-1]["text"])
                            elif number == 5:
                                self.assertEqual(case["task"], "lease_agreement")
                                self.assertEqual(stored["facts"]["fleetSize"]["value"], 1)
                                self.assertEqual(stored["facts"]["supportNeed"]["value"], "daily_home_time")
                    self.assertEqual(len(calls), sum(len(lines) for _, lines in SCENARIOS))


if __name__ == "__main__":
    unittest.main()
