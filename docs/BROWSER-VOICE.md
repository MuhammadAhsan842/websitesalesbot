# Browser voice: local pilot implementation

This branch now contains a LiveKit worker, browser microphone controls, a shared
conversation bridge and optional local speech adapters. It does not implement
telephone calling. Its tests are not evidence of acceptable voice similarity,
recognition accuracy, interruption timing or conversational latency.

## Processes and state

```
Browser microphone -> LiveKit -> VAD -> ASR -> committed transcript
  -> FastAPI shared turn handler -> existing graph / retrieval / model
  -> validated reply -> TTS -> interruptible LiveKit playback
```

Run the application, LiveKit, the media worker and speech service as separate
processes. LiveKit and recognition/synthesis can stay entirely local. The
conversation model remains the existing Ollama adapter. No additional sales LLM
or tool-executing agent is introduced by the voice worker.

The operational DB remains SQLite. A new browser session receives a random voice
capability, stored in sessionStorage, with only its SHA-256 hash in SQLite. History
never returns that capability. Old sessions can continue chatting; start a new
chat for voice. Browser grants last five minutes and are restricted to one room.
Dispatch capabilities stay in server-side dispatch metadata, outside browser
JWTs. Worker requests need both the worker secret and connection capability.

Browser voice has its own connection state. Legacy `session.channel` and customer
identity flags are not rewritten by media events. A microphone connection does
not verify a carrier's identity. Public progress reports the media connection
separately. No audio is stored by this application; committed text and playback
events are retained under the existing application's data handling.

One active/connecting voice session is admitted at a time. Connection setup
expires after 60 seconds; worker events renew a 45-second lease. Late events
cannot revive an ended connection. A healthy registered worker and matching
speech-service health are required before the UI offers a connection.

All chat and voice turns, plus staff case actions, share SQLite-backed turn
admission. An overlapping request gets HTTP 409 instead of writing stale facts.
The invocation deadline is 180 seconds, with a 190-second crash-recovery lease.
This is admission and bounded recovery, not distributed exactly-once execution;
existing outbox reconciliation requirements still apply.

Partial recognition never enters the graph. Preemptive generation is disabled.
A committed HTTP request survives interruption of speech generation. A later
correction is a subsequent committed turn. The worker queues/retries admission
using the original utterance ID, never a new action ID. On disconnect or takeover,
the server suppresses the result's speech. Already committed business actions
are not silently rolled back. Playback events distinguish completed and
interrupted speech; these are SDK playout reports, not proof a person heard it.

## Install

Use a fresh environment for the API/worker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-voice.txt
npm ci
npm run build:voice
cp .env.voice.example .env.voice
```

Set `VOICE_WORKER_SECRET` to a generated random value of at least 32 characters.
For example, generate it locally with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
and put it into the ignored `.env.voice`. Do not paste it into a public ticket.
Load the same environment in each terminal:

```bash
set -a
source .env.voice
set +a
```

## Speech profiles

The selected profile remains `owner`. Installing the worker does not create a
clone or change `config/voice.json` into an approved speech artifact.

### Owner reference, experimental local synthesis

Create a **separate Python 3.11 environment** for the cloning dependency stack:

```bash
python3.11 -m venv .venv-owner-speech
.venv-owner-speech/bin/pip install -r requirements-owner-voice.txt
# Load .env.voice here as above: VOICE_PROFILE=owner, VOICE_TTS_VOICE=owner.
.venv-owner-speech/bin/uvicorn app.voice_speech:app --host 127.0.0.1 --port 8011
```

This adapter uses Chatterbox speaker conditioning from the existing owner's
private WAV after verifying its manifest checksum. It does not play the WhatsApp
recording as a response. Model initialization may download large weights.
CPU mode is available as an experiment, not a practical-latency claim. Set
`VOICE_TTS_DEVICE=cuda` only on a compatible installation. The Chatterbox adapter
has not been acoustically validated in this workspace; dependency compatibility,
model access, voice similarity and speed remain acceptance gates. Review engine
and model terms for deployment. Never silently fall back to the demo voice.

Alternatively, point `VOICE_TTS_BASE_URL` at an evaluated OpenAI-compatible
cloning service, with its registered owner voice ID in `VOICE_TTS_VOICE`. Provide
a readiness endpoint at `VOICE_SPEECH_HEALTH_URL` returning
`{"ready":true,"profile":"owner"}` only when both speech dependencies are ready.
Speech provider API keys, when needed, stay on the worker, never in the browser.

### Explicit demo voice for transport tests

To test transport independently of owner cloning, deliberately set both
`VOICE_PROFILE=demo` and `VOICE_TTS_VOICE=demo` in all three process environments.
The UI labels this as a demo and the spoken introduction identifies it.

```bash
python3 -m venv .venv-speech
.venv-speech/bin/pip install -r requirements-speech.txt
mkdir -p data/voice-models
.venv-speech/bin/python -m piper.download_voices \
  --download-dir data/voice-models en_US-lessac-medium
# Set PIPER_MODEL to the absolute path of the downloaded .onnx file.
.venv-speech/bin/uvicorn app.voice_speech:app --host 127.0.0.1 --port 8011
```

The matching `.onnx.json` must be beside the model. Check each downloaded voice's
model card/license. ASR uses faster-whisper tiny.en on CPU by default. Test larger
recognizers separately if critical terms/numbers are not reliable. The speech
service is intentionally unauthenticated and **must remain loopback-only**;
use an authenticated private service boundary before remote hosting.

## Start LiveKit, the API and worker

For local development only, run a pinned LiveKit server with its development
credentials. Bind published ports to loopback. Keep RTC advertised ports equal
to the host ports when using Docker:

```bash
docker run --rm --name ayyan-livekit \
  -p 127.0.0.1:7880:7880 -p 127.0.0.1:7881:7881 \
  -p 127.0.0.1:7882:7882/udp \
  livekit/livekit-server:v1.9.9 \
  --dev --bind 0.0.0.0 --node-ip 127.0.0.1 --udp-port 7882
```

With the environment loaded, use separate terminals:

```bash
# Terminal 1: your existing Ollama service/model must also be running.
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765

# Terminal 2: fetch VAD assets once, then start the media worker.
.venv/bin/python -m app.voice_agent download-files
.venv/bin/python -m app.voice_agent dev
```

Open `http://127.0.0.1:8765/`, start a new inquiry, and choose **Talk here**.
Microphone access requires localhost or HTTPS. Approve microphone access, speak,
interrupt, mute, then use **Return to chat**. Closing the widget also stops the
microphone. No automatic dialing or switch to voice occurs.

The build checks health on opening the widget. If dependencies were started
later, close/reopen it. A missing worker, failed model load or missing microphone
permission keeps/falls back to chat. An unavailable pipeline must never claim to
be connected.

## Verification and release boundary

```bash
.venv/bin/python -m scripts.test_isolated
npm run test:voice
npm run build:voice
```

SDK contract tests exercise the actual AgentSession response pipeline with a
stubbed business bridge. Integration tests exercise voice authentication,
connection events, committed speech, graph/database continuity, idempotency,
human takeover and disconnect suppression. JS tests cover failed/late grants
and microphone refusal cleanup. These do not simulate real acoustic recognition
or prove barge-in latency.

Before a supervised pilot, record chat -> voice -> chat, a spoken correction,
interrupted playback, uncertain contact-number confirmation, microphone refusal,
network loss, expired tokens and human takeover. Measure first audible response,
recognition errors, p95 interruption stop time and CPU use. Review the owner
voice against your recording before enabling it for visitors. Fix critical
business-flow failures in the existing graph before expanding voice traffic.

The legacy demo still exposes unauthenticated chat/staff APIs. New voice
capabilities do not secure those APIs. Do not publish this demo directly on the
internet. Customer authorization, staff authentication, retention controls,
production TURN/TLS and provider/privacy setup remain launch work. Browser
voice is a local pilot implementation, not a production certification.

## Verification recorded in this workspace

- Base environment: 275 tests run, with optional SDK/audio tests skipped when
  those extras are absent.
- Voice environment: 275 tests passed, including the real LiveKit AgentSession
  response-source contract and stubbed speech decoding/API contracts.
- Five JavaScript lifecycle tests passed; the browser bundle builds locally.
- LiveKit v1.9.9 started in a local test container. Actual room creation and agent
  dispatch succeeded through the API; the PCM transport smoke could not establish
  signaling because the workspace proxy returned HTTP 403. Elevated execution
  produced the same result. No successful audio delivery is claimed.
- Piper model download was blocked by HTTP 403, including elevated retry. Owner
  cloning and real ASR/TTS synthesis were not run. Chatterbox adapter method
  signatures were checked against the pinned wheel, not a loaded model.
- No live Zoho write, cloud deployment, paid speech request or telephone call was
  made. Test containers were stopped.

For an independent localhost transport check, use the optional voice environment:

```bash
python -m scripts.smoke_voice_transport
```

This uses a temporary database and a synthetic readiness fixture, then creates a
real room/dispatch and attempts scoped WebRTC PCM delivery between test peers.
It does not test speech models, browser permissions, the media agent or business
outcomes. It rejects remote server URLs and cleans up its test room.
