"""Opt-in localhost-only WebRTC smoke: real grants, dispatch and PCM transport.

Uses a temporary application DB and an injected worker-readiness fixture. It does
NOT run ASR, TTS, a model, CRM or an actual media worker. No paid provider calls.
Start a local LiveKit server first; set LIVEKIT_URL/KEY/SECRET in this shell.
"""
import asyncio
import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

import numpy as np
from livekit import api, rtc
from app import db, voice


async def main():
    url = os.environ.get('LIVEKIT_URL', 'ws://127.0.0.1:7880')
    if urlsplit(url).hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('This smoke test is restricted to localhost')
    with tempfile.TemporaryDirectory(prefix='ayyan-rtc-') as temporary, \
         patch.object(db, 'DB_PATH', Path(temporary) / 'smoke.db'), \
         patch.dict(os.environ, {'VOICE_ENABLED': '1', 'VOICE_WORKER_SECRET': secrets.token_urlsafe(32)}):
        db.init()
        session = db.create_session()
        access = voice.issue_access(session['id'])
        # Isolate transport from acoustic readiness. This is never the production DB.
        voice.worker_heartbeat('Bearer ' + os.environ['VOICE_WORKER_SECRET'])
        grant = await voice.connect(voice.GrantIn(session_id=session['id']), access)
        row = voice.connection(grant['connection_id'])
        publisher, subscriber = rtc.Room(), rtc.Room()
        audio_received = asyncio.Event()
        streams = []
        tasks = []
        @subscriber.on('track_subscribed')
        def subscribed(track, *_):
            async def receive():
                stream = rtc.AudioStream.from_track(track=track, sample_rate=16000, num_channels=1)
                streams.append(stream)
                async for event in stream:
                    if np.abs(np.frombuffer(event.frame.data, dtype=np.int16)).max() > 50:
                        audio_received.set()
                        break
            tasks.append(asyncio.create_task(receive()))
        receiver_token = (api.AccessToken().with_identity('transport-test-receiver')
                          .with_grants(api.VideoGrants(room_join=True, room=row['room'], can_publish=False))).to_jwt()
        try:
            async with asyncio.timeout(20):
                await subscriber.connect(url, receiver_token)
                await publisher.connect(url, grant['token'])
                source = rtc.AudioSource(16000, 1)
                track = rtc.LocalAudioTrack.create_audio_track('test-microphone', source)
                await publisher.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
                for index in range(100):
                    frame = rtc.AudioFrame.create(16000, 1, 160)
                    samples = np.sin(2 * np.pi * 440 * (np.arange(160) + index*160)/16000) * 8000
                    np.copyto(np.frombuffer(frame.data, dtype=np.int16), samples.astype(np.int16))
                    await source.capture_frame(frame)
                await audio_received.wait()
                await source.aclose()
                print('PASS: real room creation, agent dispatch, scoped visitor JWT and received WebRTC PCM audio')
                print('Scope: localhost transport only; speech models and conversational quality NOT tested')
        finally:
            await publisher.disconnect()
            await subscriber.disconnect()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for stream in streams:
                await stream.aclose()
            async with api.LiveKitAPI() as client:
                await client.room.delete_room(api.DeleteRoomRequest(room=row['room']))


if __name__ == '__main__':
    asyncio.run(main())
