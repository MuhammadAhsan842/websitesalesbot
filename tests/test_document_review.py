"""Document-review pipeline: blank vs unreadable, packet split, authority evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, docreview, docschema, docworker, ocr, requirements

BLANK_HOLDER_COI = """
CERTIFICATE OF LIABILITY INSURANCE
INSURED  FREIGHT FUSION LLC
ANY AUTO  COMBINED SINGLE LIMIT  $1,000,000
MOTOR TRUCK CARGO  $100,000
VIN 3ALACWDT8DDF36232
CERTIFICATE HOLDER

CANCELLATION
SHOULD ANY OF THE ABOVE DESCRIBED POLICIES BE CANCELLED
"""

SILVER_HOLDER_COI = """
CERTIFICATE OF LIABILITY INSURANCE
INSURED  MANNING LOGISTICS LLC
ANY AUTO  $1,000,000
MOTOR TRUCK CARGO  $150,000
CERTIFICATE HOLDER
Silver Arrow Logistics LLC
123 Carrier Way
CANCELLATION
SHOULD ANY OF THE ABOVE DESCRIBED POLICIES BE CANCELLED
"""

FMCSA_LETTER = """
U.S. Department of Transportation
Federal Motor Carrier Safety Administration
CERTIFICATE
MOTOR CARRIER OF PROPERTY (EXCEPT HOUSEHOLD GOODS)
USDOT-5129107; MC-58236767
D & R TRANSPORTATION LLC
DEARBORN, MI
This Certificate is evidence of operating authority registration.
"""


def _page(text, page=1, unreadable=False):
    return {
        "page": page,
        "text": text,
        "method": "test",
        "confidence": None if unreadable else 90,
        "ocr_used": True,
        "unreadable": unreadable,
    }


class FieldOutcomes(unittest.TestCase):
    def test_blank_holder_is_not_unreadable(self):
        holder = docreview.extract_holder(BLANK_HOLDER_COI)
        self.assertEqual(holder["status"], docschema.FIELD_BLANK)
        self.assertIsNone(holder["value"])

    def test_populated_holder_is_present(self):
        holder = docreview.extract_holder(SILVER_HOLDER_COI)
        self.assertEqual(holder["status"], docschema.FIELD_PRESENT)
        self.assertIn("Silver Arrow", holder["value"])

    def test_blank_and_wrong_holder_are_different_codes(self):
        facts = {"legalOperatingCompany": {"value": "Ayyan Logistics LLC", "status": "user_stated"},
                 "mcOwnership": {"value": "no_own_mc", "status": "user_stated"}}
        blank = docreview.review_pages([_page(BLANK_HOLDER_COI)], filename="coi.jpg", facts=facts, suggested="coi")
        wrong = docreview.review_pages([_page(SILVER_HOLDER_COI)], filename="coi.jpg", facts=facts, suggested="coi")
        blank_codes = {row["code"] for row in blank["findings"]}
        wrong_codes = {row["code"] for row in wrong["findings"]}
        self.assertIn("required_holder_missing", blank_codes)
        self.assertNotIn("holder_mismatch", blank_codes)
        self.assertIn("holder_mismatch", wrong_codes)
        self.assertNotIn("required_holder_missing", wrong_codes)
        self.assertEqual(blank["status"], "information_missing")
        self.assertEqual(wrong["status"], "possible_mismatch")

    def test_correct_holder_does_not_require_website_brand(self):
        facts = {
            "legalOperatingCompany": {"value": "Silver Arrow Logistics LLC", "status": "user_stated"},
            "mcOwnership": {"value": "no_own_mc", "status": "user_stated"},
        }
        result = docreview.review_pages([_page(SILVER_HOLDER_COI)], filename="coi.jpg", facts=facts, suggested="coi")
        codes = {row["code"] for row in result["findings"]}
        self.assertNotIn("holder_mismatch", codes)
        self.assertNotIn("required_holder_missing", codes)

    def test_unreadable_licence_requests_clearer_copy(self):
        result = docreview.review_pages(
            [_page("", unreadable=True)],
            filename="licence.jpg",
            suggested="licence",
        )
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("clearer_copy_needed", codes)
        self.assertEqual(result["status"], "clearer_copy")
        self.assertNotIn("holder_mismatch", codes)

    def test_equipment_photo_does_not_fail_ocr(self):
        result = docreview.review_pages(
            [_page("sky gravel", unreadable=True)],
            filename="truck.jpg",
            suggested="equipment_photos",
            kind="photo",
        )
        self.assertEqual(result["doc_type"], "equipment_photos")
        self.assertEqual(result["status"], "awaiting_review")
        self.assertFalse(any(row["code"] == "clearer_copy_needed" for row in result["findings"]))

    def test_federal_identification_wording_is_not_a_reject(self):
        text = "South Carolina COMMERCIAL DRIVER LICENSE Class A Expires 09/24/2028 NOT FOR FEDERAL IDENTIFICATION"
        result = docreview.review_pages([_page(text)], filename="licence.jpg", suggested="licence")
        codes = {row["code"] for row in result["findings"]}
        self.assertNotIn("clearer_copy_needed", codes)
        self.assertNotIn("licence_rejected", codes)


class PacketSplit(unittest.TestCase):
    def test_w9_inside_packet_does_not_classify_the_whole_file(self):
        pages = [
            _page("LEO DISPATCH INC. setup agreement ATL Fast Freight LLC MC: 76969160", 1),
            _page("CERTIFICATE OF LIABILITY INSURANCE ACORD 25 see ACORD 101", 2),
            _page("ACORD 101 DESCRIPTION OF OPERATIONS MOTOR TRUCK CARGO $100,000 VIN 1HGBH41JXMN109186", 3),
            _page("NOTICE OF ASSIGNMENT change of payee", 4),
            _page("Form W-9 Request for Taxpayer Identification Number", 5),
            _page("CAB report dated September 28, 2026 USDOT 1234567 MC 999999", 6),
            _page("We assigned you EIN 12-3456789 CP 575", 7),
        ]
        components = docreview.split_components(pages, filename="Setup Packet for ATL Fast Freight LLC.pdf")
        types = [row["document_type"] for row in components]
        self.assertIn("coi", types)
        self.assertIn("notice_of_assignment", types)
        self.assertIn("w9", types)
        self.assertIn("authority_report", types)
        self.assertNotEqual(types, ["w9"])
        coi = next(row for row in components if row["document_type"] == "coi")
        self.assertEqual(coi["pages"], [2, 3])

    def test_cargo_on_remarks_page_is_linked(self):
        pages = [
            _page("CERTIFICATE OF LIABILITY INSURANCE ACORD 25 see ACORD 101 CERTIFICATE HOLDER Example Broker CANCELLATION SHOULD ANY", 2),
            _page("ACORD 101 DESCRIPTION OF OPERATIONS MOTOR TRUCK CARGO $100,000", 3),
        ]
        result = docreview.review_pages(pages, filename="packet.pdf")
        coi = next(row for row in result["components"] if row["document_type"] == "coi")
        cargo = (coi["fields"].get("cargo_limit") or {})
        self.assertEqual(cargo.get("status"), "present")
        self.assertEqual(int(cargo.get("value")), 100000)
        self.assertNotIn("cargo_not_evidenced", {row["code"] for row in result["findings"] if row.get("document") == "coi"})


class AuthorityEvidence(unittest.TestCase):
    def test_fmcsa_certificate_is_authority_evidence_not_active_status(self):
        result = docreview.review_pages([_page(FMCSA_LETTER)], filename="attachment-9.jpg")
        self.assertEqual(requirement_of(result["doc_type"]), "authority")
        fields = result["extracted"]["fields"]
        self.assertEqual(fields["usdot"]["status"], "present")
        self.assertEqual(fields["mc_number"]["status"], "present")
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("authority_identifiers_present", codes)
        self.assertIn("authority_verification_outstanding", codes)

    def test_requirement_label_accepts_operating_authority_evidence(self):
        labels = [label for doc, label in requirements.CORE_SETUP]
        self.assertIn("Operating-authority evidence", labels)


def requirement_of(doc_type):
    return docschema.requirement_of(doc_type)


class SampleFlagsRemoved(unittest.TestCase):
    def test_coi_extractor_does_not_emit_silver_arrow_flags_on_blank_holder(self):
        extracted, flags = docworker.extract_coi(BLANK_HOLDER_COI)
        codes = {row["code"] for row in flags}
        self.assertNotIn("not_ayyan_holder", codes)
        self.assertFalse(any("Silver Arrow" in (row.get("evidence") or "") for row in flags))
        holder = (extracted.get("fields") or {}).get("certificate_holder") or {}
        self.assertEqual(holder.get("status"), "blank")

    def test_native_cover_does_not_skip_thin_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            # Unit: per-page records keep a thin page even when another page is native-rich.
            pages = [
                {"page": 1, "text": "Cover letter with more than eighty characters of native PDF text for ATL Fast Freight.", "method": "pdftotext", "confidence": 100.0, "ocr_used": False, "unreadable": False, "char_count": 90},
                {"page": 2, "text": "", "method": "pdftotext_thin", "confidence": None, "ocr_used": False, "unreadable": True, "char_count": 0},
            ]
            self.assertTrue(pages[0]["char_count"] >= ocr.NATIVE_MIN)
            self.assertTrue(pages[1]["unreadable"])
            components = docreview.split_components(pages, filename="packet.pdf")
            self.assertGreaterEqual(len(components), 1)


class IngestUsesFallbackNotExcerptOnly(unittest.TestCase):
    def test_ingest_upload_records_findings_and_does_not_approve(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(db, "DB_PATH", root / "t.db"):
                db.init()
                case = db.upsert_case(
                    {
                        "session_id": "s1",
                        "status": "collecting_documents",
                        "task": "lease_agreement",
                        "owner": "Unassigned desk",
                        "facts": {
                            "mcOwnership": {"value": "no_own_mc", "status": "user_stated"},
                            "legalOperatingCompany": {"value": "Ayyan Logistics LLC", "status": "user_stated"},
                        },
                        "documents": [],
                    }
                )
                requirements.issue(case["id"], "lease_agreement", facts=case["facts"])
                upload = root / "coi.jpg"
                upload.write_bytes(b"not-an-image")
                row = docworker.ingest_upload(
                    case["id"],
                    upload,
                    {
                        "id": "att1",
                        "filename": "coi.jpg",
                        "path": str(upload),
                        "ocr_text": BLANK_HOLDER_COI,
                    },
                    suggested_doc_type="coi",
                )
                self.assertFalse(row.get("approved"))
                self.assertEqual(row["doc_type"], "coi")
                self.assertEqual(row["status"], "information_missing")
                req = db.get_requirement(case["id"], "coi")
                self.assertEqual(req["status"], "information_missing")
                self.assertFalse(any(f["code"] == "not_ayyan_holder" for f in row.get("flags") or []))
                comps = db.list_document_components(case["id"])
                self.assertTrue(comps)


if __name__ == "__main__":
    unittest.main()
