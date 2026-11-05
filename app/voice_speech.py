"""Optional, loopback-only local speech service; independent of inference/media.

Demo: faster-whisper + an explicitly selected Piper voice.
Owner: faster-whisper + Chatterbox using the private owner reference.
Models are loaded before health reports ready. No raw audio is retained.
"""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
MAX_AUDIO_BYTES = 4 * 1024 * 1024


def owner_reference() -> Path:
    manifest = json.loads((ROOT / "config/voice.json").read_text())
    path = (ROOT / manifest["reference_audio"]["path"]).resolve()
    if not path.is_relative_to(ROOT / "assets/voices/owner"):
        raise RuntimeError("Owner reference must remain inside private voice assets")
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["reference_audio"]["sha256"]:
        raise RuntimeError("Owner reference checksum mismatch")
    return path


class PiperSpeech:
    profile = "demo"
    def __init__(self):
        from piper import PiperVoice
        self.voice = PiperVoice.load(os.environ["PIPER_MODEL"])

    def generate(self, text):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            self.voice.synthesize_wav(text, wav)
        return output.getvalue()


class OwnerSpeech:
    profile = "owner"
    def __init__(self):
        from chatterbox.tts import ChatterboxTTS
        self.reference = owner_reference()
        self.voice = ChatterboxTTS.from_pretrained(device=os.getenv("VOICE_TTS_DEVICE", "cpu"))
        self.voice.prepare_conditionals(str(self.reference))

    def generate(self, text):
        import torchaudio
        wav = self.voice.generate(text)
        output = io.BytesIO()
        torchaudio.save(output, wav.cpu(), self.voice.sr, format="wav")
        return output.getvalue()


class GeminiSpeech:
    profile = "gemini"
    def __init__(self):
        from app import gemini
        if not gemini.is_configured():
            raise RuntimeError("GEMINI_API_KEY is not configured for Gemini speech")
        self.gemini = gemini

    def generate(self, text):
        return self.gemini.generate_speech(text)


class FishSpeech:
    """Owner WhatsApp voice via Fish Audio one-shot (or FISH_REFERENCE_ID)."""
    profile = "fish"
    def __init__(self):
        from app import fish_audio
        if not fish_audio.is_configured():
            raise RuntimeError("FISH_API_KEY is not configured for Fish speech")
        self.fish = fish_audio

    def generate(self, text):
        return self.fish.generate_speech(text, format="wav")


@asynccontextmanager
async def lifespan(app):
    from faster_whisper import WhisperModel
    profile = os.getenv("VOICE_PROFILE", "owner")
    if profile not in {"owner", "demo", "gemini", "fish"}:
        raise RuntimeError("Unknown voice profile")
    if profile == "gemini":
        app.state.tts = GeminiSpeech()
    elif profile == "fish":
        app.state.tts = FishSpeech()
    elif profile == "owner":
        app.state.tts = OwnerSpeech()
    else:
        app.state.tts = PiperSpeech()
    app.state.asr = WhisperModel(os.getenv("VOICE_WHISPER_MODEL", "tiny.en"), device="cpu", compute_type="int8",
                                cpu_threads=int(os.getenv("VOICE_SPEECH_THREADS", "2")))
    app.state.gate = asyncio.Semaphore(1)
    yield


app = FastAPI(title="Ayyan local speech", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ready": hasattr(app.state, "asr") and hasattr(app.state, "tts"),
            "profile": app.state.tts.profile if hasattr(app.state, "tts") else None}


class SpeechIn(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    voice: str
    model: str = "local"
    response_format: str = "wav"
    speed: float = 1.0


@app.post("/v1/audio/speech")
async def speech(body: SpeechIn):
    if body.voice != app.state.tts.profile or body.response_format != "wav" or body.speed != 1.0:
        raise HTTPException(422, "Use the configured profile, WAV format and speed 1.0")
    async with app.state.gate:
        wav = await asyncio.to_thread(app.state.tts.generate, body.input)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)):
    import av
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio must be nonempty and at most 4 MiB")
    def recognize():
        # Bound decoded samples while decoding, including files with no duration header.
        import av
        import numpy as np
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks, samples = [], 0
        with av.open(io.BytesIO(data)) as container:
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples += converted.samples
                    if samples > 16000 * 60:
                        raise ValueError("Maximum utterance duration is 60 seconds")
                    chunks.append(converted.to_ndarray().flatten())
            for converted in resampler.resample(None):
                samples += converted.samples
                if samples > 16000 * 60:
                    raise ValueError("Maximum utterance duration is 60 seconds")
                chunks.append(converted.to_ndarray().flatten())
        if not chunks:
            raise ValueError("No audio")
        audio = np.concatenate(chunks).astype(np.float32) / 32768.0
        segments, _ = app.state.asr.transcribe(audio, language="en", beam_size=1,
                                               condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments).strip()
    try:
        async with app.state.gate:
            text = await asyncio.to_thread(recognize)
    except (ValueError, EOFError, av.error.FFmpegError) as exc:
        raise HTTPException(422, "Invalid or overlong audio") from exc
    return {"text": text}
