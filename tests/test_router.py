"""Gemini-only router."""

from __future__ import annotations

import unittest

from app import router


class RouterGeminiOnly(unittest.TestCase):
    def test_mode_is_gemini(self):
        self.assertEqual(router.mode(), "gemini")

    def test_pick_always_gemini(self):
        choice = router.pick("I need dispatch", intent="dispatch_inquiry")
        self.assertEqual(choice["family"], "gemini")
        self.assertEqual(choice["reason"], "gemini_only")
        self.assertTrue(str(choice["model"]).startswith("gemini") or "gemini" in str(choice["model"]))


if __name__ == "__main__":
    unittest.main()
