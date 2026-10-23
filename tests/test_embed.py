"""MiniLM cache + BM25/RRF; live Ollama is not required."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, embed, examples


def fake_vec(text: str) -> list[float]:
    tokens = set((text or "").lower().split())
    vocab = ["sign", "insurance", "week", "truck", "fee", "local", "box", "mc"]
    return [1.0 if word in tokens else 0.0 for word in vocab]


class EmbedCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init()
        embed._cache.clear()

    def test_rrf_prefers_shared_top_ranks(self):
        fused = embed.rrf({"a": 0, "b": 1}, {"a": 1, "c": 0}, ["a", "b", "c"])
        self.assertEqual(fused[0][0], "a")

    def test_unchanged_text_is_not_reembedded(self):
        calls = []

        def infer(text):
            calls.append(text)
            return fake_vec(text)

        with patch.object(embed, "_infer", infer):
            first = embed.upsert("example", "moses_wont_sign", "I don't want to sign for nothing")
            second = embed.upsert("example", "moses_wont_sign", "I don't want to sign for nothing")
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(embed.get_cached("example", "moses_wont_sign"), first)

    def test_changed_text_is_reembedded(self):
        with patch.object(embed, "_infer", fake_vec):
            embed.upsert("example", "doc", "waiting on insurance")
            embed.upsert("example", "doc", "postpone until next week")
        self.assertEqual(embed.get_cached("example", "doc"), fake_vec("postpone until next week"))


class HybridExamples(unittest.TestCase):
    def test_bm25_still_finds_objections_without_vectors(self):
        embed._cache.clear()
        self.assertEqual(examples.search("I don't wanna sign for nothing")[0]["id"], "moses_wont_sign")
        self.assertEqual(examples.search("Let's see about next week")[0]["id"], "union_pause_next_week")
        self.assertEqual(examples.search("still getting insurance quotes")[0]["id"], "jason_waiting_insurance")

    def test_hybrid_keeps_sign_objection_with_fake_vectors(self):
        embed._cache.clear()
        with patch.object(embed, "embed", fake_vec):
            for row in examples.BANK:
                embed._cache[("example", row["id"])] = fake_vec(f"{row['user']} {row['context']}")
            hits = examples.search("hesitant to sign if you cannot get me loads")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "moses_wont_sign")
