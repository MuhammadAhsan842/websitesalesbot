"""Rule-based model pick; no extra LLM call."""

import os
import unittest
from unittest.mock import patch

from app import router


class Router(unittest.TestCase):
    def test_qualify_stays_on_qwen(self):
        with patch.dict(os.environ, {"MODEL_ROUTER": "auto"}):
            choice = router.pick("I run one hotshot with my own MC", "mc", None, {}, gemma_ready=True)
        self.assertEqual(choice["family"], "qwen")
        self.assertEqual(choice["reason"], "qualify_extract")

    def test_fee_and_objection_use_gemma(self):
        with patch.dict(os.environ, {"MODEL_ROUTER": "auto"}):
            fee = router.pick("What do you charge?", "fee", "topic_fee", {}, gemma_ready=True)
            self.assertEqual(fee["family"], "gemma")
            self.assertEqual(fee["model"], router.GEMMA_MODEL)
            commit = router.pick("I don't want to sign for nothing", "commit", None, {}, gemma_ready=True)
            self.assertEqual(commit["family"], "gemma")

    def test_missing_gemma_stays_on_qwen(self):
        choice = router.pick("What do you charge?", "fee", None, {}, gemma_ready=False)
        self.assertEqual(choice["family"], "qwen")
        self.assertEqual(choice["reason"], "gemma_unavailable")

    def test_forced_gemma(self):
        with patch.dict(os.environ, {"MODEL_ROUTER": "gemma"}):
            choice = router.pick("Own MC", "mc", None, {}, gemma_ready=True)
            self.assertEqual(choice["family"], "gemma")
            self.assertEqual(choice["reason"], "forced_gemma")
