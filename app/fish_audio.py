"""Fish Audio TTS with one-shot cloning from the owner WhatsApp reference.

Persistent model creation requires Fish API credit. This adapter therefore
clones from the private owner reference on each request via MessagePack.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any

import httpx
import msgpack

log = logging.getLogger("ayyan.fish_audio")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DEFAULT_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
_reference_cache: tuple[str, bytes, str] | None = None
_client: httpx.Client | None = None


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def api_key() -> str:
    return (os.getenv("FISH_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def tts_model() -> str:
    return (os.getenv("FISH_TTS_MODEL") or DEFAULT_MODEL).strip()


def base_url() -> str:
    return (os.getenv("FISH_API_BASE") or DEFAULT_BASE).rstrip("/")


def status() -> dict:
    return {
        "configured": is_configured(),
        "model": tts_model(),
        "reference_id": (os.getenv("FISH_REFERENCE_ID") or "").strip() or None,
        "clone_mode": "reference_id" if (os.getenv("FISH_REFERENCE_ID") or "").strip() else "oneshot_owner_reference",
        "latency": os.getenv("FISH_TTS_LATENCY", "balanced"),
    }


def _manifest() -> dict:
    return json.loads((ROOT / "config" / "voice.json").read_text())


def owner_reference_bytes() -> tuple[bytes, str]:
    """Return (audio_bytes, transcript) for one-shot cloning."""
    global _reference_cache
    manifest = _manifest()
    path = (ROOT / manifest["reference_audio"]["path"]).resolve()
    if not path.is_relative_to(ROOT / "assets/voices/owner"):
        raise RuntimeError("Owner reference must remain inside private voice assets")
    expected = manifest["reference_audio"]["sha256"]
    transcript = (manifest.get("reference_transcript") or "").strip()
    if not transcript:
        raise RuntimeError("config/voice.json is missing reference_transcript for Fish cloning")
    if _reference_cache and _reference_cache[0] == expected:
        return _reference_cache[1], _reference_cache[2]
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("Owner reference checksum mismatch")
    _reference_cache = (expected, data, transcript)
    return data, transcript


def _http() -> httpx.Client:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), http2=False)
    return _client


def _mp3_to_wav(mp3: bytes) -> bytes:
    try:
        completed = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
            input=mp3,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to convert Fish Audio MP3 to WAV") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed converting Fish Audio output: {exc.stderr[:200]!r}") from exc
    if not completed.stdout.startswith(b"RIFF"):
        raise RuntimeError("ffmpeg did not return a WAV payload")
    return completed.stdout


def generate_speech(text: str, *, format: str = "mp3", timeout: float = 60.0) -> bytes:
    """Synthesize speech in the owner voice. format is mp3 or wav."""
    key = api_key()
    if not key:
        raise RuntimeError("FISH_API_KEY is not configured")
    spoken = (text or "").strip()
    if not spoken:
        raise ValueError("text is required")
    if len(spoken) > 4000:
        raise ValueError("text exceeds 4000 characters")

    reference_id = (os.getenv("FISH_REFERENCE_ID") or "").strip()
    payload: dict[str, Any] = {
        "text": spoken,
        "format": "mp3",
        "normalize": True,
        # balanced is faster than normal for interactive chat replies.
        "latency": os.getenv("FISH_TTS_LATENCY", "balanced"),
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "model": tts_model(),
    }
    if reference_id:
        payload["reference_id"] = reference_id
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    else:
        audio, transcript = owner_reference_bytes()
        payload["references"] = [{"audio": audio, "text": transcript}]
        headers["Content-Type"] = "application/msgpack"
        body = msgpack.packb(payload, use_bin_type=True)

    response = _http().post(f"{base_url()}/v1/tts", content=body, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"Fish Audio TTS HTTP {response.status_code}: {response.text[:400]}")
    mp3 = response.content
    if not mp3:
        raise RuntimeError("Fish Audio returned empty audio")
    if format == "mp3":
        return mp3
    if format == "wav":
        return _mp3_to_wav(mp3)
    raise ValueError("format must be mp3 or wav")
