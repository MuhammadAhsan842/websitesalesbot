"""Verify that the hardware benchmark rejects faster settings with failed canaries."""

import argparse
from contextlib import redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

import httpx
from scripts import benchmark_cpu


class Benchmark(unittest.IsolatedAsyncioTestCase):
    async def test_failed_canary_disqualifies_setting(self):
        calls = []
        def handler(request):
            if request.url.path == "/api/show":
                return httpx.Response(200, json={"details": {"quantization_level": "synthetic"}})
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test-model", "digest": "synthetic-digest"}]})
            payload = json.loads(request.content)
            calls.append(payload)
            text = json.loads(payload["messages"][1]["content"])["text"]
            case = next((case for case in benchmark_cpu.CASES if case.text == text), None)
            proposal = {"intent": "general"}
            if case:
                proposal["facts"] = [{"key": key, "value": value} for key, value in case.facts.items()]
                proposal["knowledge_keys"] = list(case.keys)
                proposal["blocked"] = ["guarantee"] if case.name == "guarantee_freight" else []
                if case.name == "guarantee_freight" and payload["options"]["num_thread"] == 2:
                    proposal["knowledge_keys"] = []
            return httpx.Response(200, json={"message": {"content": json.dumps(proposal)}, "eval_count": 20})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        args = argparse.Namespace(url="http://test", model="test-model", threads=[1, 2], repeats=1, timeout=1)
        with patch.object(benchmark_cpu.httpx, "AsyncClient", return_value=client), redirect_stderr(io.StringIO()):
            result = await benchmark_cpu.run(args)
        self.assertEqual(result["suggested_threads"], 1)
        self.assertEqual(result["metadata"]["digest"], "synthetic-digest")
        self.assertEqual(result["results"][0]["summary"]["canaries_passed"], 5)
        self.assertEqual(result["results"][1]["summary"]["canaries_passed"], 4)
        self.assertEqual(len(calls), 12)  # Two warmups, five measured requests per setting.
        self.assertTrue(all(payload["options"]["num_gpu"] == 0 for payload in calls))


if __name__ == "__main__":
    unittest.main()
