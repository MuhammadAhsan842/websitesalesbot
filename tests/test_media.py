"""OCR + CLIP image index stay separate from MiniLM. Vision never auto-approves."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, embed, media, vision


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def clip_vec(label: str) -> list[float]:
    tokens = set((label or "").lower().replace("/", " ").split())
    vocab = ["reefer", "box", "truck", "friday", "coi", "quote"]
    return [1.0 if word in tokens else 0.0 for word in vocab]


class AttachmentPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init()
        media.ROOT = Path(self.tmp.name) / "att"
        self.photo = Path(self.tmp.name) / "reefer.jpg"
        self.photo.write_bytes(PNG)

    def test_duplicate_hash_is_not_reprocessed(self):
        with patch.object(media.ocr, "read_document", return_value={"text": "", "confidence": None, "ocr_used": False}):
            first = media.process(self.photo, session_id="s1", look=False)
            second = media.process(self.photo, session_id="s1", look=False)
        self.assertEqual(first["status"], "processed")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(first["id"], second["id"])

    def test_screenshot_skips_vision_and_keeps_ocr(self):
        text = "Not yet. I'm still comparing quotes. Thanks buddy let's see about next week. What do you charge?"
        with (
            patch.object(media.ocr, "read_document", return_value={"text": text, "confidence": 80.0, "ocr_used": True}),
            patch.object(media, "interpret") as look,
        ):
            shot = Path(self.tmp.name) / "chat.png"
            shot.write_bytes(PNG)
            result = media.process(shot, session_id="s2", look=True)
        self.assertEqual(result["kind"], "screenshot")
        row = db.get_attachment(result["id"])
        self.assertEqual(row["vision_status"], "skipped")
        look.assert_not_called()
        hits = media.search("comparing quotes", session_id="s2")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], result["id"])

    def test_vision_facts_are_cached_not_approved(self):
        with (
            patch.object(media.ocr, "read_document", return_value={"text": "", "confidence": None}),
            patch("app.qwen.look", return_value={"kind": "equipment_photo", "description": "A reefer trailer. Approved and insured.", "proposed_facts": [{"key": "equipment", "value": "reefer", "evidence": "reefer"}]}),
            patch("app.qwen.vision_enabled", return_value=True),
        ):
            result = media.process(self.photo, session_id="s3", look=True)
        row = db.get_attachment(result["id"])
        self.assertEqual(row["vision_status"], "cached")
        self.assertTrue(row["vision"].get("unverified"))
        self.assertNotIn("approved", (row["vision"].get("description") or "").lower())
        self.assertIsNone(db.get_session("s3"))

    def test_session_evidence_only_on_visual_turns(self):
        with patch.object(media.ocr, "read_document", return_value={"text": "", "confidence": None}):
            media.process(self.photo, session_id="s5", look=False)
        self.assertEqual(media.session_evidence("s5", "what do you charge"), [])
        lines = media.session_evidence("s5", "this is my truck")
        self.assertTrue(lines)
        self.assertIn("unverified", lines[0].lower())

    def test_same_bytes_do_not_move_another_session(self):
        with patch.object(media.ocr, "read_document", return_value={"text": "", "confidence": None}):
            first = media.process(self.photo, session_id="s6", look=False)
            second = media.process(self.photo, session_id="s7", look=False)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(db.get_attachment(first["id"])["session_id"], "s6")
        self.assertEqual(db.get_attachment(second["id"])["session_id"], "s7")

    def test_clip_query_does_not_use_minilm_space(self):
        with patch.object(media.ocr, "read_document", return_value={"text": "box truck", "confidence": 70}):
            media.process(self.photo, session_id="s4", look=False)
        att = db.list_attachments("s4")[0]
        db.execute(
            """INSERT INTO embeddings (id, kind, doc_id, model, dims, sha256, vec, updated_at)
               VALUES (?, 'image', ?, 'clip-test', 6, 'x', ?, ?)""",
            (f"image:{att['id']}:clip-test", att["id"], embed.pack(clip_vec("reefer truck")), db.now()),
        )
        with (
            patch.dict("os.environ", {"IMAGE_EMBED_MODEL": "clip-test"}),
            patch.object(vision, "enabled", return_value=True),
            patch.object(vision, "embed_text", return_value=clip_vec("reefer friday")),
            patch.object(vision, "get_image_vec", return_value=clip_vec("reefer truck")),
            patch.object(embed, "embed", side_effect=AssertionError("MiniLM must not encode CLIP queries")),
        ):
            hits = media.search("reefer", session_id="s4")
        self.assertTrue(hits)
        self.assertGreater(hits[0]["image"], 0)


class LookSanitizer(unittest.TestCase):
    def test_look_drops_approval_claims(self):
        from app.qwen import _sanitize_look

        cleaned = _sanitize_look(
            {
                "kind": "equipment_photo",
                "description": "COI is valid insurance. Driver is approved.",
                "proposed_facts": [{"key": "equipment", "value": "box_truck", "evidence": "box"}],
            }
        )
        self.assertNotIn("approved", cleaned["description"].lower())
        self.assertTrue(cleaned["unverified"])
        self.assertEqual(cleaned["proposed_facts"][0]["key"], "equipment")


class AttachmentApi(unittest.IsolatedAsyncioTestCase):
    async def test_upload_is_unverified_and_does_not_touch_chat_inference(self):
        import httpx
        from langgraph.checkpoint.memory import InMemorySaver

        from app import main, qwen, retrieve, zoho
        from app.graph import build_graph

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(db, "DB_PATH", Path(temporary) / "test.db"),
            patch.object(media, "ROOT", Path(temporary) / "att"),
            patch.object(zoho, "access_token", return_value=None),
            patch.object(retrieve, "search", return_value=[]),
            patch.object(qwen, "look", side_effect=AssertionError("vision is not on the upload path")),
            patch.object(qwen, "propose", side_effect=AssertionError("chat inference is not for uploads")),
            patch.object(main.app.state, "graph", build_graph(InMemorySaver()), create=True),
            patch.object(media.ocr, "read_document", return_value={"text": "", "confidence": None}),
        ):
            db.init()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
                opened = await api.post("/v1/session", json={})
                sid = opened.json()["session_id"]
                health = await api.get("/v1/health")
                self.assertEqual(health.json()["image_embed"]["space"], "clip")
                self.assertFalse(health.json()["vision"]["enabled"])
                uploaded = await api.post(
                    f"/v1/session/{sid}/attachment",
                    files={"file": ("reefer.jpg", PNG, "image/jpeg")},
                )
                self.assertEqual(uploaded.status_code, 200)
                body = uploaded.json()
                self.assertTrue(body["unverified"])
                self.assertTrue(body["not_approval"])
                self.assertFalse(body["queued_vision"])
                self.assertIn("unverified", (body.get("text") or "").lower())
                listed = await api.get(f"/v1/session/{sid}/attachments")
                self.assertEqual(len(listed.json()["attachments"]), 1)
