"""CPU helpers + Gemini LLM admission queue (no local chat model)."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from app import cpu, llm


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


class AdmissionQueue(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = replace(llm.CONFIG, parallel=1, max_waiting=1, queue_timeout=0.05)
        self.old_gate = llm._gate
        llm._gate = llm.Admission(self.cfg)

    async def asyncTearDown(self):
        llm._gate = self.old_gate

    async def test_queue_full_raises(self):
        llm._gate.pending = self.cfg.parallel + self.cfg.max_waiting
        with self.assertRaises(llm.InferenceBusy):
            async with llm._gate.enter():
                pass

    async def test_propose_is_gemini_only(self):
        with patch.object(llm, "_infer", new=AsyncMock(return_value={"intent": "general", "_source": "gemini"})):
            result = await llm.propose("Own MC", {}, "fit_check")
        self.assertEqual(result.get("_source"), "gemini")
        self.assertEqual(llm.last_route.get("family"), "gemini")


if __name__ == "__main__":
    unittest.main()
