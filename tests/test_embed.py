"""Pinecone-only text vectors; live Ollama is not required in unit tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, embed, examples


def fake_vec(text: str) -> list[float]:
    tokens = set((text or "").lower().split())
    vocab = ["sign", "insurance", "week", "truck", "fee", "local", "box", "mc"]
    return [1.0 if word in tokens else 0.0 for word in vocab]


class EmbedPineconeOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._prev_db = db.DB_PATH
        self.addCleanup(lambda: setattr(db, "DB_PATH", self._prev_db))
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init()

    def test_rrf_prefers_shared_top_ranks(self):
        fused = embed.rrf({"a": 0, "b": 1}, {"a": 1, "c": 0}, ["a", "b", "c"])
        self.assertEqual(fused[0][0], "a")

    def test_unchanged_text_is_not_reembedded(self):
        calls = []

        def infer(text):
            calls.append(text)
            return fake_vec(text)

        with (
            patch.object(embed, "_infer", infer),
            patch("app.vectorstore.enabled", return_value=True),
            # After first upsert, hash matches and Pinecone already has the id.
            patch("app.vectorstore.has_vector", return_value=True),
            patch("app.vectorstore.upsert_vector", return_value=True) as up,
        ):
            first = embed.upsert("example", "moses_wont_sign", "I don't want to sign for nothing")
            second = embed.upsert("example", "moses_wont_sign", "I don't want to sign for nothing")
        self.assertEqual(first, fake_vec("I don't want to sign for nothing"))
        self.assertIsNone(second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(up.call_count, 1)
        self.assertIsNone(embed.get_cached("example", "moses_wont_sign"))

    def test_changed_text_is_reembedded(self):
        with (
            patch.object(embed, "_infer", fake_vec),
            patch("app.vectorstore.enabled", return_value=True),
            patch("app.vectorstore.has_vector", return_value=False),
            patch("app.vectorstore.upsert_vector", return_value=True) as up,
        ):
            embed.upsert("example", "doc", "waiting on insurance")
            embed.upsert("example", "doc", "postpone until next week")
        self.assertEqual(up.call_count, 2)

    def test_upsert_requires_pinecone(self):
        with patch("app.vectorstore.enabled", return_value=False):
            self.assertIsNone(embed.upsert("example", "x", "hello"))


class HybridExamples(unittest.TestCase):
    def test_bm25_still_finds_objections_without_vectors(self):
        with patch.object(embed, "query_similar", return_value=[]):
            self.assertEqual(examples.search("I don't wanna sign for nothing")[0]["id"], "moses_wont_sign")
            self.assertEqual(examples.search("Let's see about next week")[0]["id"], "union_pause_next_week")
            self.assertEqual(examples.search("still getting insurance quotes")[0]["id"], "jason_waiting_insurance")

    def test_hybrid_keeps_sign_objection_with_pinecone_hits(self):
        ranked = [("moses_wont_sign", 0.9), ("union_pause_next_week", 0.2)]
        with patch.object(embed, "query_similar", return_value=ranked):
            hits = examples.search("hesitant to sign if you cannot get me loads")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "moses_wont_sign")
