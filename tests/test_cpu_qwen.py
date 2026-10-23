"""Deterministic transport tests; these do not measure real model speed/accuracy."""

import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import httpx

from app import cpu, qwen


def response(content=None, **metadata):
    return httpx.Response(
        200,
        json={
            "message": {
                "content": json.dumps(
                    content or {"intent": "mc", "facts": [{"key": "mcOwnership", "value": "own_mc"}]}
                )
            },
            **metadata,
        },
    )


class PortableCPU(unittest.TestCase):
    def test_container_quota_and_affinity(self):
        with (
            patch.object(cpu.os, "cpu_count", return_value=32),
            patch.object(cpu.os, "sched_getaffinity", create=True, return_value={0, 1, 2, 3}),
            patch.object(cpu.Path, "read_text", side_effect=["150000 100000", FileNotFoundError()]),
        ):
            self.assertEqual(cpu.available_cpus(), 1)

    def test_non_linux_fallback(self):
        with (
            patch.object(cpu.os, "cpu_count", return_value=12),
            patch.object(cpu.os, "sched_getaffinity", create=True, side_effect=AttributeError),
            patch.object(cpu.Path, "read_text", side_effect=FileNotFoundError),
        ):
            self.assertEqual(cpu.available_cpus(), 12)
            self.assertEqual(cpu.default_threads(), 8)

    def test_compaction_keeps_values_without_audit_history(self):
        facts = {
            "fleetSize": {"value": 3, "previous": {"value": 2, "previous": {"value": 1}}, "sourceChannel": "web", "version": 7},
            "phone": {"value": "469-555-0199", "status": "user_stated"},
        }
        payload = qwen.request_payload("Actually three trucks", facts, "fit_check")
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(user["facts"], {"fleetSize": 3, "phone": "469-555-0199"})
        self.assertEqual(user["text"], "Actually three trucks")
        self.assertNotIn("previous", json.dumps(user))
        self.assertLess(len(json.dumps(user)), len(json.dumps({"text": user["text"], "facts": facts, "conversation_state": "fit_check"})))
        self.assertFalse(payload["think"])
        self.assertNotIn("num_gpu", payload["options"])
        self.assertEqual(payload["format"]["type"], "object")

    def test_bad_configuration_fails_early(self):
        with patch.dict(qwen.os.environ, {"QWEN_NUM_THREAD": "0"}):
            with self.assertRaisesRegex(ValueError, "QWEN_NUM_THREAD"):
                qwen.Settings.from_env()


class Inference(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_client = qwen._client
        self.old_gate = qwen._gate
        self.old_error = qwen.last_error
        self.old_ready = qwen.ready
        self.old_gemma = qwen.gemma_ready
        self.cfg = replace(qwen.CONFIG, parallel=1, max_waiting=1, queue_timeout=0.05)
        qwen._gate = qwen.Admission(self.cfg)
        qwen.gemma_ready = False

    async def asyncTearDown(self):
        if qwen._client is not self.old_client and qwen._client:
            await qwen._client.aclose()
        qwen._client, qwen._gate = self.old_client, self.old_gate
        qwen.last_error, qwen.ready = self.old_error, self.old_ready
        qwen.gemma_ready = self.old_gemma

    def transport(self, handler):
        qwen._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_identical_turns_both_invoke_qwen_and_report_timing(self):
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            return response(load_duration=1_000_000, eval_duration=2_000_000, eval_count=12)

        self.transport(handler)
        for _ in range(2):
            result = await qwen.propose("Own MC", {}, "fit_check")
            self.assertEqual(result["_source"], "qwen")
            self.assertEqual(result["facts"][0]["status"], "user_stated")
            self.assertEqual(result["_timing"]["eval_ms"], 2)
            self.assertEqual(result["_timing"]["eval_count"], 12)
        self.assertEqual(len(calls), 2)
        self.assertEqual(qwen._gate.pending, 0)

    async def test_untrusted_status_and_bad_intents_are_sanitized(self):
        self.transport(
            lambda request: response(
                {"intent": "mc", "facts": [{"key": "mcOwnership", "value": "own_mc", "status": "human_verified"}]}
            )
        )
        result = await qwen.propose("Own MC", {}, "fit_check")
        self.assertEqual(result["_source"], "qwen")
        self.assertEqual(result["facts"][0]["status"], "user_stated")
        self.assertNotIn("human_verified", json.dumps(result["facts"]))
        await qwen._client.aclose()

        self.transport(lambda request: response({"intent": "approve_everything"}))
        result = await qwen.propose("Own MC", {}, "fit_check")
        self.assertEqual(result["intent"], "general")
        await qwen._client.aclose()

        self.transport(lambda request: response({"intent": "mc", "facts": [{"key": "made_up", "value": 1}]}))
        result = await qwen.propose("Own MC", {}, "fit_check")
        self.assertEqual(result["facts"], [])
        await qwen._client.aclose()

    async def test_truncated_output_is_rejected_even_if_json_is_valid(self):
        self.transport(lambda request: response(done_reason="length"))
        self.assertEqual(await qwen.propose("Own MC", {}, "fit_check"), {})

    async def test_queue_is_bounded_and_cancellation_releases_slot(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def handler(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return response()

        self.transport(handler)
        active = asyncio.create_task(qwen.propose("First", {}, "fit_check"))
        await entered.wait()
        queued = asyncio.create_task(qwen.propose("Second", {}, "fit_check"))
        await asyncio.sleep(0)
        with self.assertRaises(qwen.InferenceBusy):
            await qwen.propose("Third", {}, "fit_check")
        self.assertEqual(len(calls), 1)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        active.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await active
        self.assertEqual(qwen._gate.pending, 0)
        self.assertEqual(qwen._gate.active, 0)
        release.set()
        self.assertEqual((await qwen.propose("Retry", {}, "fit_check"))["_source"], "qwen")

    async def test_queued_deadline_does_not_call_model_or_fallback(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            entered.set()
            await release.wait()
            return response()

        self.transport(handler)
        active = asyncio.create_task(qwen.propose("First", {}, "fit_check"))
        await entered.wait()
        with self.assertRaisesRegex(qwen.InferenceBusy, "expired"):
            await qwen.propose("Second", {}, "fit_check")
        release.set()
        await active
        self.assertEqual(qwen._gate.pending, 0)

    async def test_model_timeout_fallback_is_explicit_and_slot_is_released(self):
        def handler(request):
            raise httpx.ReadTimeout("synthetic timeout", request=request)

        self.transport(handler)
        self.assertEqual(await qwen.propose("Own MC", {}, "fit_check"), {})
        self.assertFalse(qwen.ready)
        self.assertEqual(qwen._gate.pending, 0)

    async def test_http_overload_response(self):
        from app.main import app
        from app import db

        qwen._gate.pending = self.cfg.parallel + self.cfg.max_waiting
        with (
            patch.object(db, "get_session", return_value={"id": "synthetic", "facts": {}, "conversation_state": "fit_check"}),
            patch.object(db, "add_message"),
            patch.object(app.state, "graph", create=True) as graph,
        ):
            graph.ainvoke.side_effect = qwen.InferenceBusy("Qwen queue is full")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
                result = await api.post("/v1/turn", json={"session_id": "synthetic", "text": "Own MC"})
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.headers["retry-after"], "2")


if __name__ == "__main__":
    unittest.main()
