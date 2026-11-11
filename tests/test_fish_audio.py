"""Fish Audio TTS wiring; network calls mocked."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app import fish_audio
from app.main import app


class FishAudioTts(unittest.IsolatedAsyncioTestCase):
    async def test_capabilities_and_tts_endpoint(self):
        with patch.object(fish_audio, "is_configured", return_value=True), patch.object(
            fish_audio, "status", return_value={"configured": True, "model": "s2.1-pro-free", "reference_id": None, "clone_mode": "oneshot_owner_reference"}
        ), patch.object(fish_audio, "generate_speech", return_value=b"ID3fake-mp3") as generate:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                caps = await client.get("/v1/tts/capabilities")
                self.assertEqual(caps.status_code, 200)
                self.assertTrue(caps.json()["available"])
                spoken = await client.post("/v1/tts", json={"text": "Hello from Ayyan.", "format": "mp3"})
                self.assertEqual(spoken.status_code, 200)
                self.assertEqual(spoken.headers["content-type"], "audio/mpeg")
                self.assertEqual(spoken.content, b"ID3fake-mp3")
                generate.assert_called_once()

    def test_reference_checksum_gate(self):
        with patch.object(fish_audio, "_manifest", return_value={
            "reference_audio": {"path": "assets/voices/owner/reference-24k.wav", "sha256": "deadbeef"},
            "reference_transcript": "hello",
        }):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                fish_audio.owner_reference_bytes()
