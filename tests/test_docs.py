"""Packet PDFs stay off personality RAG. Checklists and missing items are register copy."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, docs, ingest, knowledge, plan, requirements, retrieve, rules


class PacketGate(unittest.TestCase):
    def test_sample_packets_are_not_chats(self):
        self.assertEqual(ingest.classify("W9(2).pdf"), "packet")
        self.assertEqual(ingest.classify("Carroll Transport - COI - Leo Dispatch.pdf"), "packet")
        self.assertEqual(ingest.classify("NOA - 2026-09-08T143520.312(2).pdf"), "packet")
        self.assertEqual(ingest.classify("ATL Fast Freight LLC Carrier Setup Packet (1).pdf"), "packet")


class Checklist(unittest.TestCase):
    def test_which_papers_uses_own_mc_list(self):
        self.assertIn("docs_own", docs.keys_for("Which papers do I send?"))
        topics = plan.detect_topics("Which papers do I send?")
        self.assertIn("docs_status", topics)
        keys = rules.knowledge_for("general", [], None, "Which papers do I send?")
        self.assertIn("docs_own", keys)
        self.assertIn("W-9", knowledge.lookup("docs_own"))
        self.assertIn("notice of assignment", knowledge.lookup("docs_own").lower())

    def test_named_templates_do_not_approve(self):
        self.assertEqual(docs.keys_for("I sent the W-9")[0], "docs_w9")
        self.assertIn("docs_coi", docs.keys_for("is my COI enough"))
        self.assertIn("unverified", knowledge.lookup("docs_coi").lower())
        self.assertIn("not filed", knowledge.lookup("docs_noa").lower())
        self.assertIn("email it from chat", knowledge.lookup("docs_packet").lower())

    def test_missing_line_uses_issued_requirements(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                session = {"id": "s1", "facts": {}, "case_id": None}
                line = docs.missing_line(session)
                self.assertIn("hasn't sent a packet", line)
                case = db.upsert_case(
                    {
                        "id": "c1",
                        "session_id": "s1",
                        "status": "awaiting_human_action",
                        "task": "setup_packet",
                        "owner": "Unassigned desk",
                        "facts": {},
                        "documents": [],
                    }
                )
                requirements.issue(case["id"], "setup_packet")
                session["case_id"] = case["id"]
                missing = docs.missing_line(session)
                self.assertIn("Still outstanding", missing)
                self.assertIn("W-9", missing)
                self.assertIn("unverified", missing.lower())
                self.assertNotIn("approved", missing.lower().replace("not approved", ""))


class RegisterRetrieve(unittest.TestCase):
    def test_lexical_finds_w9_template_not_a_packet_file(self):
        from app import embed

        with (
            patch.object(embed, "ensure", return_value={}),
            patch.object(embed, "embed", return_value=None),
            patch.object(embed, "get_cached", return_value=None),
        ):
            retrieve.build_index()
            self.assertFalse(retrieve.status()["packets_indexed"])
            hits = retrieve.search("taxpayer ID form signature TIN")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["key"], "docs_w9")
