"""Committed speech -> shared graph -> persisted facts. No real network or audio."""
import asyncio
import importlib.util
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from app import db, examples, graph, main, llm, retrieve, voice, zoho


class BrowserVoice(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(db, 'DB_PATH', root / 'test.db'))
        self.stack.enter_context(patch.object(zoho, 'drain', return_value=[]))
        self.stack.enter_context(patch.object(zoho, 'access_token', return_value=None))
        self.stack.enter_context(patch.object(examples, 'search', return_value=[]))
        self.stack.enter_context(patch.object(retrieve, 'search', return_value=[]))
        self.model = self.stack.enter_context(patch.object(llm, 'propose', new=AsyncMock(return_value={
            'intent': 'general', 'facts': [], 'action': 'none'})))
        self.stack.enter_context(patch.object(main.app.state, 'graph', graph.build_graph(InMemorySaver()), create=True))
        self.stack.enter_context(patch.dict(os.environ, {'VOICE_WORKER_SECRET': 's' * 40, 'VOICE_ENABLED': '0'}))
        db.init()
        self.session = db.create_session({'equipment': {'value': 'box_truck', 'status': 'user_stated'}})
        self.sid = self.session['id']
        self.access = voice.issue_access(self.sid)
        self.connection_id = 'voice-test'
        db.execute('INSERT INTO voice_connections(id,session_id,room,token_hash,status,expires,heartbeat) VALUES (?,?,?,?,?,?,?)',
                   (self.connection_id, self.sid, 'ayyan-voice-test', voice.digest('lease-secret'), 'connecting', time.time()+60, time.time()))
        self.worker = {'Authorization': 'Bearer ' + 's'*40, 'X-Voice-Token': 'lease-secret'}
        self.visitor = {'X-Inquiry-Token': self.access}
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)

    async def event(self, name, sequence=1):
        return await self.client.post('/v1/voice/voice-test/events', headers=self.worker,
                                      json={'event': name, 'sequence': sequence})

    async def say(self, text, utterance='first'):
        return await self.client.post('/v1/voice/voice-test/turn', headers=self.worker,
                                      json={'text': text, 'utterance_id': utterance})

    async def test_voice_requires_both_session_and_worker_capabilities(self):
        response = await self.client.get('/v1/voice/voice-test')
        self.assertEqual(response.status_code, 403)
        response = await self.client.post('/v1/voice/voice-test/events', headers=self.visitor,
                                          json={'event': 'connected', 'sequence': 1})
        self.assertEqual(response.status_code, 403)
        response = await self.client.get('/v1/voice/voice-test', headers=self.visitor)
        self.assertFalse(response.json()['connected'])

    async def test_other_inquiry_cannot_read_or_end_voice(self):
        other = db.create_session()
        token = voice.issue_access(other['id'])
        for method in ('get', 'delete'):
            response = await getattr(self.client, method)('/v1/voice/voice-test', headers={'X-Inquiry-Token': token})
            self.assertEqual(response.status_code, 403)

    async def test_only_ready_media_commits_turn_and_identity_is_unchanged(self):
        self.assertEqual((await self.say('26 ft')).status_code, 409)
        self.assertEqual(self.model.await_count, 0)
        await self.event('connected')
        response = await self.say('26 ft')
        self.assertEqual(response.status_code, 200, response.text)
        saved = db.get_session(self.sid)
        self.assertEqual(saved['facts']['equipment']['value'], 'box_truck')
        self.assertIn('26', saved['facts']['trailerLength']['value'])
        self.assertFalse(saved['identity_confirmed'])
        history = (await self.client.get('/v1/session/' + self.sid)).json()
        self.assertTrue(history['workflows']['browser_voice']['connected'])
        self.assertEqual(history['messages'][0]['text'], '26 ft')

    async def test_duplicate_utterance_does_not_repeat_action_or_transcript(self):
        await self.event('connected')
        first = await self.say('26 ft')
        again = await self.say('26 ft')
        self.assertEqual(first.json(), again.json())
        self.assertEqual(len(db.list_messages(self.sid)), 2)
        self.assertEqual(self.model.await_count, 1)

    async def test_stale_event_cannot_resurrect_connection(self):
        await self.event('connected', 2)
        await self.event('heartbeat', 1)
        self.assertEqual(voice.connection(self.connection_id)['event_seq'], 2)
        await self.client.delete('/v1/voice/voice-test', headers=self.visitor)
        self.assertEqual((await self.event('connected', 3)).status_code, 409)
        self.assertFalse((await self.client.get('/v1/voice/voice-test', headers=self.visitor)).json()['connected'])
        self.assertEqual((await self.say('Call me')).status_code, 409)
        self.assertEqual(self.model.await_count, 0)

    async def test_takeover_stops_future_voice_turns(self):
        await self.event('connected')
        session = db.get_session(self.sid)
        session['manager_accepted'] = True
        db.save_session(session)
        self.assertEqual((await self.say('Call me')).status_code, 409)
        self.assertEqual(self.model.await_count, 0)

    async def test_disconnect_during_inference_suppresses_speech_but_keeps_committed_turn(self):
        await self.event('connected')
        async def disconnect(*args, **kwargs):
            db.execute("UPDATE voice_connections SET status='ended',expires=0 WHERE id=?", (self.connection_id,))
            return {'intent': 'general', 'facts': [], 'action': 'none'}
        self.model.side_effect = disconnect
        reply = await self.say('26 ft')
        self.assertFalse(reply.json()['speak'])
        self.assertEqual(len(db.list_messages(self.sid)), 2)

    async def test_text_and_voice_turns_cannot_race(self):
        async with voice.conversation_lock(self.sid):
            response = await self.client.post('/v1/turn', json={'session_id': self.sid, 'text': '40 ft'})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.model.await_count, 0)

    async def test_expired_media_and_worker_do_not_claim_readiness(self):
        db.execute('UPDATE voice_connections SET expires=0 WHERE id=?', (self.connection_id,))
        self.assertEqual((await self.say('26 ft')).status_code, 409)
        self.assertFalse((await self.client.get('/v1/voice/capabilities')).json()['available'])

    async def test_partial_transcripts_are_not_an_action_endpoint(self):
        response = await self.client.post('/v1/voice/voice-test/events', headers=self.worker,
                                          json={'event': 'utterance.partial', 'sequence': 1})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(db.list_messages(self.sid)), 0)

    async def test_voice_access_is_not_returned_by_history(self):
        response = await self.client.get('/v1/session/' + self.sid)
        self.assertNotIn(self.access, response.text)
        self.assertNotIn('voice_access_token', response.json())

    async def test_session_creation_issues_private_capability(self):
        response = await self.client.post('/v1/session', json={})
        self.assertEqual(response.status_code, 200)
        value = response.json()
        voice.verify_access(value['session_id'], value['voice_access_token'])

    async def test_expired_writer_lease_can_be_recovered(self):
        db.execute('INSERT INTO conversation_locks VALUES (?,?,?)', (self.sid, 'crashed', 0))
        async with voice.conversation_lock(self.sid):
            pass
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM conversation_locks').fetchone()[0], 0)

    @unittest.skipUnless(importlib.util.find_spec("livekit"), "Install voice extras for grant SDK checks")
    async def test_grant_has_room_scope_and_no_worker_secret(self):
        from livekit import api
        import jwt
        await self.client.delete('/v1/voice/voice-test', headers=self.visitor)
        service = AsyncMock()
        service.__aenter__.return_value = service
        with patch.dict(os.environ, {'VOICE_ENABLED': '1', 'LIVEKIT_URL': 'ws://127.0.0.1:7880',
                                     'LIVEKIT_API_KEY': 'devkey', 'LIVEKIT_API_SECRET': 'test-secret-that-is-at-least-32-bytes'}), \
             patch.object(voice, 'capabilities', return_value={'available': True}), \
             patch.object(api, 'LiveKitAPI', return_value=service):
            response = await self.client.post('/v1/voice/connect', headers=self.visitor, json={'session_id': self.sid})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        claims = jwt.decode(payload['token'], options={'verify_signature': False})
        self.assertEqual(claims['video']['room'], 'ayyan-' + payload['connection_id'])
        self.assertTrue(claims['video']['roomJoin'])
        self.assertFalse(claims['video']['canPublishData'])
        self.assertNotIn('roomConfig', claims)
        self.assertNotIn('worker_token', response.text)
        self.assertNotIn('s' * 40, response.text)
        service.agent_dispatch.create_dispatch.assert_awaited_once()

    @unittest.skipUnless(importlib.util.find_spec("livekit"), "Install voice extras for grant SDK checks")
    async def test_failed_dispatch_does_not_hold_capacity_or_claim_connection(self):
        from livekit import api
        await self.client.delete('/v1/voice/voice-test', headers=self.visitor)
        service = AsyncMock()
        service.__aenter__.return_value = service
        service.room.create_room.side_effect = RuntimeError('Injected unavailable media')
        with patch.object(voice, 'capabilities', return_value={'available': True}), \
             patch.object(api, 'LiveKitAPI', return_value=service):
            response = await self.client.post('/v1/voice/connect', headers=self.visitor, json={'session_id': self.sid})
        self.assertEqual(response.status_code, 503)
        with db.connect() as conn:
            active = conn.execute("SELECT id FROM voice_connections WHERE status IN ('connecting','connected') AND expires>?", (time.time(),)).fetchall()
        self.assertEqual(active, [])
