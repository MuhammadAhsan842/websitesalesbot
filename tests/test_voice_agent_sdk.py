import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

SDK_AVAILABLE = bool(importlib.util.find_spec('livekit') and importlib.util.find_spec('livekit.agents'))

@unittest.skipUnless(SDK_AVAILABLE, 'Install requirements-voice.txt for SDK contract tests')
class VoiceSDK(unittest.IsolatedAsyncioTestCase):
    async def test_actual_agent_session_uses_shared_graph_without_a_second_model(self):
        from livekit.agents import AgentSession
        from app.voice_agent import InquiryAgent
        bridge = SimpleNamespace(committed=AsyncMock(return_value={'text': 'What length is the trailer?', 'speak': True}))
        session = AgentSession()
        try:
            await session.start(agent=InquiryAgent(bridge))
            await session.run(user_input='I have a reefer')
            replies = [item for item in session.history.items if getattr(item, 'role', None) == 'assistant']
            self.assertEqual([item.text_content for item in replies], ['What length is the trailer?'])
            bridge.committed.assert_awaited_once()
        finally:
            await session.aclose()

    async def test_suppressed_speech_is_not_added_as_delivered_reply(self):
        from livekit.agents import AgentSession
        from app.voice_agent import InquiryAgent
        bridge = SimpleNamespace(committed=AsyncMock(return_value={'text': 'Obsolete reply', 'speak': False}))
        session = AgentSession()
        try:
            await session.start(agent=InquiryAgent(bridge))
            await session.run(user_input='I have a reefer')
            self.assertFalse([item for item in session.history.items if getattr(item, 'role', None) == 'assistant'])
        finally:
            await session.aclose()
