"""Reviewed example pipeline: chats in, packets out, duplicates skipped, leaks blocked."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import db, examples, ingest, ocr


class ClassifyAndPii(unittest.TestCase):
    def test_packets_and_ids_are_not_chats(self):
        self.assertEqual(ingest.classify("ATL Fast Freight LLC Carrier Setup Packet (1).pdf"), "packet")
        self.assertEqual(ingest.classify("W9(2).pdf"), "packet")
        self.assertEqual(ingest.classify("Carroll Transport - COI - Leo Dispatch.pdf"), "packet")
        self.assertEqual(ingest.classify("NOA - 2026-09-08T143520.312(2).pdf"), "packet")
        self.assertEqual(ingest.classify("Union moving.pdf"), "chat")
        self.assertEqual(ingest.classify("Jason Chats.1.pdf"), "chat")
        self.assertEqual(ingest.classify("conversation document.docx"), "chat")
        self.assertEqual(
            ingest.classify("export.txt", "Message from you, Ready?\nMessage from 469-555-0199, Si."),
            "chat",
        )

    def test_export_turns_keep_driver_then_sales(self):
        text = (
            "Message from 801 928 4726, I run a hotshot out of Utah, Sunday, October 18 2026, 9:43 PM.\n"
            "more_vert\n"
            "Message from you, Own MC or lease-on?, Sunday, October 18 2026, 9:57 PM.\n"
        )
        turns = ingest.extract_turns(text)
        self.assertEqual(turns[0]["role"], "driver")
        self.assertIn("hotshot", turns[0]["text"].lower())
        self.assertEqual(turns[1]["role"], "sales")

    def test_short_driver_answers_are_kept(self):
        text = (
            "Message from you, Still waiting on insurance?, Sunday, October 18 2026, 9:57 PM.\n"
            "Message from 469-555-0199, Si., Sunday, October 18 2026, 9:58 PM.\n"
            "Message from 469-555-0199, 26 pies, Sunday, October 18 2026, 9:59 PM.\n"
        )
        turns = ingest.extract_turns(text)
        bodies = [row["text"].lower() for row in turns if row["role"] == "driver"]
        self.assertTrue(any(body.startswith("si") for body in bodies))
        self.assertTrue(any("26 pies" in body for body in bodies))

    def test_strip_phone_email_and_dot(self):
        text = ingest.strip_pii("Call (561) 909-8184 or Unionmovingmass@gmail.com DOT 9703143")
        self.assertNotIn("561", text)
        self.assertNotIn("gmail", text.lower())
        self.assertIn("[redacted]", text)


class Bank(unittest.TestCase):
    def test_every_seed_is_leak_free_and_searchable(self):
        self.assertGreaterEqual(len(examples.BANK), 20)
        self.assertTrue(all(examples.allowed(row) for row in examples.BANK))
        hits = examples.search("NJ by Monday 26 box liftgate")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "union_nj_monday")
        self.assertIn("reply", hits[0])
        self.assertNotIn("6%", hits[0]["reply"])
        pause = examples.search("Let's see about next week")
        self.assertEqual(pause[0]["id"], "union_pause_next_week")
        truck = examples.search("I'm picking up my truck tomorrow morning. I'll send the registration after.")
        self.assertTrue(truck)
        self.assertEqual(truck[0]["id"], "moses_truck_tomorrow")
        mailbox = examples.search("Tell him to send again mailbox")
        self.assertEqual(mailbox[0]["move"], "acknowledge")


class DuplicateIngest(unittest.TestCase):
    def test_same_bytes_are_duplicate_not_new_experience(self):
        with tempfile.TemporaryDirectory() as temporary:
            db_path = Path(temporary) / "t.db"
            with patch.object(db, "DB_PATH", db_path):
                db.init()
                first = Path(temporary) / "Union moving.pdf"
                first.write_bytes(b"%PDF-1.4 fake chat bytes")
                copy = Path(temporary) / "Union moving again.pdf"
                copy.write_bytes(first.read_bytes())
                with patch.object(ocr, "read_document", return_value={"text": "Let's see about next week", "method": "test"}):
                    one = ingest.ingest_path(first)
                    two = ingest.ingest_path(copy)
                self.assertEqual(two["status"], "duplicate")
                self.assertEqual(one["source"]["sha256"], hashlib.sha256(first.read_bytes()).hexdigest())

    def test_w9_is_rejected_kind(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                path = Path(temporary) / "W9(2).pdf"
                path.write_bytes(b"%PDF-1.4 Form W-9 Request for Taxpayer")
                with patch.object(ocr, "read_document", return_value={"text": "Form W-9", "method": "test"}):
                    result = ingest.ingest_path(path)
                self.assertEqual(result["status"], "rejected_kind")
                self.assertEqual(result["kind"], "packet")
                self.assertEqual(result["examples"], [])


class Seed(unittest.TestCase):
    def test_seed_publishes_rewritten_bank(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "t.db"):
                db.init()
                out = ingest.seed_reviewed_bank()
                self.assertGreaterEqual(out["published"], 20)
                self.assertGreaterEqual(out["index"], 20)
                row = db.get_example("union_pause_next_week")
                self.assertEqual(row["status"], "published")
                self.assertIn("next week", row["reply"].lower())


if __name__ == "__main__":
    unittest.main()
