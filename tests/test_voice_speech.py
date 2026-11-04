"""Speech API format/error contracts; engines stubbed, not acoustic evaluation."""
import importlib.util
import io
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

import httpx
from app.voice_speech import app, owner_reference

@unittest.skipUnless(importlib.util.find_spec('av'), 'Install speech/voice extras for audio decoding')
class SpeechAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        self.wav = io.BytesIO()
        with wave.open(self.wav, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b'\0\0' * 1600)
        app.state.gate = asyncio.Semaphore(1)
        app.state.tts = SimpleNamespace(profile='owner', generate=lambda text: self.wav.getvalue())
        app.state.asr = SimpleNamespace(transcribe=lambda audio, **kwargs: ([SimpleNamespace(text='A 26 foot box truck')], None))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://speech')
        self.addAsyncCleanup(self.client.aclose)

    async def test_reference_is_private_and_checksum_verified(self):
        self.assertTrue(owner_reference().name.endswith('.wav'))
        with patch('pathlib.Path.read_bytes', return_value=b'changed recording'):
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                owner_reference()

    async def test_profile_cannot_silently_substitute_a_demo_speaker(self):
        response = await self.client.post('/v1/audio/speech', json={'input':'Hello', 'voice':'demo'})
        self.assertEqual(response.status_code, 422)
        response = await self.client.post('/v1/audio/speech', json={'input':'Hello', 'voice':'owner'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:4], b'RIFF')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_audio_decoding_returns_recognized_text(self):
        response = await self.client.post('/v1/audio/transcriptions', files={'file': ('audio.wav', self.wav.getvalue(), 'audio/wav')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['text'], 'A 26 foot box truck')

    async def test_bad_or_empty_audio_is_rejected(self):
        response = await self.client.post('/v1/audio/transcriptions', files={'file': ('bad.wav', b'not audio')})
        self.assertEqual(response.status_code, 422)
        response = await self.client.post('/v1/audio/transcriptions', files={'file': ('empty.wav', b'')})
        self.assertEqual(response.status_code, 413)
