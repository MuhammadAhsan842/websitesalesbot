"""LiveKit media worker. Run: python -m app.voice_agent dev.

No independent sales prompt/tools: completed speech goes through the same graph
as chat. Both speech endpoints may be local OpenAI-compatible services.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import httpx
from livekit.agents import Agent, AgentServer, AgentSession, APIConnectOptions, JobContext, cli, llm, room_io
from livekit.plugins import openai, silero

log = logging.getLogger("ayyan.voice")


def configuration():
    required = ("VOICE_API_URL", "VOICE_WORKER_SECRET", "VOICE_STT_BASE_URL", "VOICE_STT_MODEL",
                "VOICE_TTS_BASE_URL", "VOICE_TTS_MODEL", "VOICE_TTS_VOICE", "VOICE_SPEECH_HEALTH_URL")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing voice configuration: " + ", ".join(missing))
    if len(os.environ["VOICE_WORKER_SECRET"]) < 32:
        raise RuntimeError("VOICE_WORKER_SECRET must contain at least 32 characters")
    profile = os.getenv("VOICE_PROFILE", "owner")
    if profile not in {"owner", "demo"}:
        raise RuntimeError("Select the owner or explicit demo profile")
    return profile


class Bridge:
    def __init__(self, connection_id, token, client):
        self.connection_id, self.token, self.client = connection_id, token, client
        self.sequence = 0
        self.event_lock = asyncio.Lock()
        self.pending = set()

    async def request(self, suffix, body):
        response = await self.client.post("/v1/voice/" + self.connection_id + suffix,
                                          json=body, headers={"X-Voice-Token": self.token})
        response.raise_for_status()
        return response.json()

    async def event(self, event, **extra):
        async with self.event_lock:
            self.sequence += 1
            return await self.request("/events", {"sequence": self.sequence, "event": event, **extra})

    async def committed(self, utterance_id, text):
        # Retain the request when playback generation is interrupted. Its user turn
        # was committed; cancellation must not silently discard an accepted action.
        async def submit():
            started = time.monotonic()
            for attempt in range(90):
                try:
                    reply = await self.request("/turn", {"utterance_id": utterance_id, "text": text})
                    log.info("voice_turn_completed latency_ms=%d", (time.monotonic() - started) * 1000)
                    return reply
                except httpx.HTTPStatusError as error:
                    if error.response.status_code != 409 or attempt == 89:
                        raise
                    # Distinguish busy turn admission from a disconnected/taken-over call.
                    state = await self.event("heartbeat")
                    if not state["connected"]:
                        raise
                    await asyncio.sleep(1)
        task = asyncio.create_task(submit())
        self.pending.add(task)
        def finished(done):
            self.pending.discard(done)
            if not done.cancelled():
                done.exception()  # Retrieve failures even if speech generation was interrupted.
        task.add_done_callback(finished)
        return await asyncio.shield(task)


class GraphStream(llm.LLMStream):
    async def _run(self):
        message = next((item for item in reversed(self._chat_ctx.items) if getattr(item, "role", None) == "user"), None)
        if not message or not message.text_content.strip():
            return
        bridge = self._llm.bridge
        try:
            reply = await bridge.committed(message.id, message.text_content)
            if reply["speak"]:
                self._event_ch.send_nowait(llm.ChatChunk(id=message.id, delta=llm.ChoiceDelta(
                    role="assistant", content=reply["text"])))
        except (httpx.HTTPError, TimeoutError):
            log.warning("Shared inquiry request failed; ending voice")
            await bridge.event("failed")
            raise


class GraphLLM(llm.LLM):
    """SDK-compatible response source; delegates exclusively to our validated graph."""
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def chat(self, *, chat_ctx, tools=None, **kwargs):
        return GraphStream(self, chat_ctx=chat_ctx, tools=[],
                           conn_options=APIConnectOptions(max_retry=0, timeout=185))


class InquiryAgent(Agent):
    def __init__(self, bridge):
        super().__init__(instructions="Continue the shared inquiry. All responses come from its validated graph.",
                         llm=GraphLLM(bridge))


server = AgentServer(port=8081, num_idle_processes=1, load_threshold=1.0, initialize_process_timeout=60)


def prewarm(process):
    process.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm
_heartbeat_task = None


@server.on("worker_registered")
def registered(*_):
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        return
    async def heartbeat():
        profile = configuration()
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    # Only advertise availability when speech dependencies also report ready.
                    worker_health = await client.get("http://127.0.0.1:8081/")
                    worker_health.raise_for_status()
                    health = await client.get(os.environ["VOICE_SPEECH_HEALTH_URL"])
                    health.raise_for_status()
                    status = health.json()
                    if status.get("ready") and status.get("profile") == profile:
                        response = await client.post(os.environ["VOICE_API_URL"].rstrip('/') + "/v1/voice/worker/heartbeat",
                            headers={"Authorization": "Bearer " + os.environ["VOICE_WORKER_SECRET"]})
                        response.raise_for_status()
                except httpx.HTTPError:
                    log.warning("Voice dependencies unavailable; admission will close")
                await asyncio.sleep(10)
    _heartbeat_task = asyncio.create_task(heartbeat())


@server.rtc_session(agent_name="ayyan-voice")
async def entrypoint(ctx: JobContext):
    configuration()
    metadata = json.loads(ctx.job.metadata)
    connection_id, token = metadata["connection_id"], metadata["worker_token"]
    expected_room = "ayyan-" + connection_id
    if ctx.job.room.name != expected_room:
        raise RuntimeError("Dispatch room does not match connection")
    async with httpx.AsyncClient(base_url=os.environ["VOICE_API_URL"], timeout=185,
                               headers={"Authorization": "Bearer " + os.environ["VOICE_WORKER_SECRET"]}) as client:
        bridge = Bridge(connection_id, token, client)
        await ctx.connect()
        async with asyncio.timeout(50):
            participant = await ctx.wait_for_participant(identity="visitor-" + connection_id)
            # A joined websocket alone is not an active microphone/media track.
            from livekit import rtc
            while not any(track.source == rtc.TrackSource.SOURCE_MICROPHONE for track in participant.track_publications.values()):
                await asyncio.sleep(0.1)
        session = AgentSession(
            vad=ctx.proc.userdata["vad"], turn_detection="vad", preemptive_generation=False,
            min_endpointing_delay=0.6, max_endpointing_delay=2.0,
            min_interruption_duration=0.4, min_interruption_words=1,
            stt=openai.STT(model=os.environ["VOICE_STT_MODEL"], base_url=os.environ["VOICE_STT_BASE_URL"],
                           api_key=os.getenv("VOICE_STT_API_KEY", "local"), use_realtime=False),
            tts=openai.TTS(model=os.environ["VOICE_TTS_MODEL"], voice=os.environ["VOICE_TTS_VOICE"],
                           base_url=os.environ["VOICE_TTS_BASE_URL"], api_key=os.getenv("VOICE_TTS_API_KEY", "local"),
                           response_format="wav"),
        )
        ended = asyncio.Event()
        tasks = set()
        def spawn(coro):
            task = asyncio.create_task(coro)
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return task

        @session.on("close")
        def closed(_):
            ended.set()

        async def record_playback(event_name, **data):
            try:
                await bridge.event(event_name, **data)
            except httpx.HTTPError:
                log.debug("Playback receipt arrived after connection ended")

        @session.on("conversation_item_added")
        def delivered(event):
            item = event.item
            if getattr(item, "role", None) == "assistant":
                spawn(record_playback("playback_interrupted" if item.interrupted else "playback_completed",
                                   speech_id=item.id, spoken_text=item.text_content))

        async def guard():
            while not ended.is_set():
                try:
                    state = await bridge.event("heartbeat")
                    if not state["connected"]:
                        break
                except httpx.HTTPError:
                    break
                await asyncio.sleep(5)
            await session.aclose()
            ended.set()

        try:
            await session.start(agent=InquiryAgent(bridge), room=ctx.room,
                                room_options=room_io.RoomOptions(text_input=False, video_input=False,
                                    participant_identity="visitor-" + connection_id, delete_room_on_close=True))
            await bridge.event("connected")
            spawn(guard())
            profile = os.getenv("VOICE_PROFILE", "owner")
            intro = "I'm Ayyan Group's AI assistant. We can continue your existing inquiry here."
            if profile == "demo":
                intro += " This is the demonstration voice, not the owner's selected voice."
            await session.say(intro, allow_interruptions=True)
            await ended.wait()
        finally:
            await session.aclose()
            try:
                await bridge.event("disconnected")
            except httpx.HTTPError:
                pass
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if bridge.pending:
                await asyncio.gather(*bridge.pending, return_exceptions=True)


if __name__ == "__main__":
    cli.run_app(server)
