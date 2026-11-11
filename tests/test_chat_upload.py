"""Chat document upload options and validation helpers."""

from __future__ import annotations

import unittest

from app import requirements
from app.main import _doc_label, _upload_magic_ok


def facts(**kwargs):
    return {key: {"value": value, "status": "user_stated"} for key, value in kwargs.items()}


class UploadOptions(unittest.TestCase):
    def test_needs_insurance_excludes_coi(self):
        options = requirements.customer_upload_options(
            "insurance_quote",
            facts(mcOwnership="no_own_mc", insurance="needs_insurance"),
        )
        values = [row["value"] for row in options]
        self.assertIn("licence", values)
        self.assertIn("registration", values)
        self.assertIn("unknown", values)
        self.assertNotIn("coi", values)

    def test_lease_own_insurance_includes_coi(self):
        options = requirements.customer_upload_options(
            "lease_agreement",
            facts(mcOwnership="no_own_mc", insurance="own_insurance"),
        )
        values = [row["value"] for row in options]
        self.assertIn("coi", values)
        self.assertIn("unknown", values)

    def test_status_labels(self):
        self.assertEqual(requirements.customer_status_label("received"), "Received / checking")
        self.assertEqual(requirements.customer_status_label("clearer_copy"), "Clearer copy needed")
        self.assertEqual(requirements.customer_status_label("information_missing"), "Information missing")
        self.assertEqual(requirements.customer_status_label("possible_mismatch"), "Possible mismatch")
        self.assertEqual(requirements.customer_status_label("awaiting_review"), "Automated checks passed / awaiting review")
        self.assertEqual(requirements.customer_status_label("approved"), "Approved by authorized reviewer")


class UploadValidation(unittest.TestCase):
    def test_magic_bytes(self):
        self.assertTrue(_upload_magic_ok(b"%PDF-1.4", ".pdf"))
        self.assertTrue(_upload_magic_ok(b"\xff\xd8\xff\xe0rest", ".jpg"))
        self.assertTrue(_upload_magic_ok(b"\x89PNG\r\n\x1a\nrest", ".png"))
        self.assertFalse(_upload_magic_ok(b"not-a-pdf", ".pdf"))
        self.assertFalse(_upload_magic_ok(b"", ".png"))

    def test_doc_label(self):
        self.assertIn("certificate of insurance", _doc_label("coi").lower())
        self.assertEqual(_doc_label("unknown"), "document")


if __name__ == "__main__":
    unittest.main()
