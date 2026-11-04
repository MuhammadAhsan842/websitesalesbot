# Selected speaking voice reference

The project owner explicitly selected this uploaded recording as the desired
speaking voice for the Ayyan AI assistant on 3 November 2026.

* `source-whatsapp.ogg`: original uploaded WhatsApp voice note, unchanged.
* `reference-24k.wav`: decoded/resampled 24 kHz mono 16-bit PCM reference.
* `../../../config/voice.json`: selected profile, repository-relative asset paths,
  checksums, audio metadata and implementation status.

The recording is approximately five seconds long. It is a reference for an optional
voice-cloning-capable TTS adapter, not a trained model, generated greeting or
verified clone. The conversion does not restore detail lost to WhatsApp
compression. Voice similarity, pronunciation and latency have not been tested.

The optional adapter uses profile `owner` for speaker conditioning to generate
new speech from the graph's validated replies, and preserve the AI introduction.
Do not play the reference as though it answers arbitrary questions, or silently
substitute a stock speaker while representing it as the selected voice.

Standard Kokoro/Piper voice selection alone does not implement arbitrary voice
cloning. Validate the selected engine/model runtime and commercial-use
terms before deployment. Additional clean samples can be added after
evaluation; keep this original as provenance.

These assets are intentionally versioned at the owner's request. The current
public-site allowlist does not expose `assets/voices/` or `config/voice.json` over
HTTP. Keep speaker references server-side when adding the voice runtime.

The optional adapter in `app/voice_speech.py` now supports conditioning from this
reference using Chatterbox. It is experimental: an adapter is not an approved
clone, and no acoustic acceptance is implied. See `docs/BROWSER-VOICE.md`.
