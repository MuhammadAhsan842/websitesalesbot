import pytest
from app import embed, gemini, qwen, router


def test_gemini_configured():
    assert gemini.is_configured()
    assert gemini.api_key() != ""
    assert gemini.chat_model() == "gemini-3.5-flash-lite"
    assert gemini.embed_model() == "gemini-embedding-2"
    assert gemini.tts_model() == "gemini-3.8-flash-lite-tts"


def test_router_gemini_mode(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "gemini")
    assert router.mode() == "gemini"
    choice = router.pick("Hello I have a truck")
    assert choice["family"] == "gemini"
    assert choice["model"] == "gemini-3.5-flash-lite"


def test_gemini_embed():
    vec = gemini.embed("test box truck load dispatch", dims=768)
    assert vec is not None
    assert len(vec) == 768


def test_embed_module_gemini():
    vec = embed.embed("flatbed 48ft OTR")
    assert vec is not None
    assert len(vec) == 768


def test_gemini_speech_generation():
    audio = gemini.generate_speech("Testing voice synthesis.")
    assert isinstance(audio, bytes)
    assert len(audio) > 1000
    assert audio[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_qwen_propose_with_gemini(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "gemini")
    res = await qwen.propose(
        user_text="I have a 26ft box truck in Dallas looking for loads under my own MC.",
        facts={},
        conversation_state="qualify",
    )
    assert res is not None
    assert res.get("_source") == "gemini"
    assert res.get("intent") in qwen.INTENTS or res.get("intent") == "general"
    assert "wording" in res
