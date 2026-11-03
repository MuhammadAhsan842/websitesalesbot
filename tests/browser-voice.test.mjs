import test from 'node:test';
import assert from 'node:assert/strict';
import {VoiceClient} from '../web/voice.js';

function fixture(fetcher, microphone = async () => {}) {
  let disconnected = 0;
  const statuses = [];
  const room = {on() {}, async connect() {}, async startAudio() {},
    async disconnect() { disconnected++; }, localParticipant: {setMicrophoneEnabled: microphone}};
  const client = new VoiceClient({sessionId: 'one', accessToken: 'private', fetcher,
    roomFactory: () => room, audioRoot: {append() {}}, onStatus: (...args) => statuses.push(args), onHistory: async () => {}});
  return {client, statuses, disconnected: () => disconnected};
}
const ok = value => ({ok: true, json: async () => value});

test('permission failure releases connection and returns to chat', async () => {
  const calls = [];
  const f = fixture(async (path, options) => { calls.push([path, options]); return ok({connection_id: 'room', url: 'ws://local', token: 'scoped'}); },
    async () => { throw new Error('Permission denied'); });
  await f.client.start();
  assert.equal(f.client.room, null);
  assert.equal(f.disconnected(), 1);
  assert.equal(calls.at(-1)[1].method, 'DELETE');
  assert.equal(f.statuses.at(-1)[0], 'error');
  assert.equal(calls[0][1].headers['X-Inquiry-Token'], 'private');
});

test('stopping while grant is in flight releases the late grant', async () => {
  let grant;
  let released = false;
  const f = fixture(async (_, options) => {
    if (options.method === 'DELETE') { released = true; return ok({}); }
    return new Promise(resolve => { grant = resolve; });
  });
  const starting = f.client.start();
  await f.client.stop();
  grant(ok({connection_id: 'room'}));
  await starting;
  assert.equal(released, true);
  assert.equal(f.client.room, null);
});

test('a failed grant does not leave a microphone or room active', async () => {
  let captures = 0;
  const f = fixture(async () => ({ok: false, status: 503}), async () => { captures++; });
  await f.client.start();
  assert.equal(captures, 0);
  assert.equal(f.client.room, null);
  assert.equal(f.disconnected(), 1);
});

test('stopping during media connection disconnects a late connection', async () => {
  let connected;
  let captures = 0;
  const f = fixture(async () => ok({connection_id:'room', url:'ws://local', token:'scoped'}),
    async () => { captures++; });
  const original = f.client.roomFactory;
  f.client.roomFactory = () => {
    const room = original();
    room.connect = () => new Promise(resolve => { connected = resolve; });
    return room;
  };
  const starting = f.client.start();
  while (!connected) await new Promise(resolve => setImmediate(resolve));
  await f.client.stop();
  connected();
  await starting;
  assert.equal(captures, 0);
  assert.equal(f.client.room, null);
  assert.equal(f.disconnected(), 2);
});

test('autoplay refusal keeps the microphone session available for explicit audio enable', async () => {
  let captures = 0;
  const f = fixture(async () => ok({connection_id:'room', url:'ws://local', token:'scoped'}),
    async () => { captures++; });
  const original = f.client.roomFactory;
  f.client.roomFactory = () => {
    const room = original();
    room.startAudio = async () => { throw new Error('Autoplay blocked'); };
    return room;
  };
  try {
    await f.client.start();
    assert.equal(captures, 1);
    assert.notEqual(f.client.room, null);
    assert.equal(f.statuses.at(-1)[0], 'playback_blocked');
  } finally { await f.client.stop(); }
});
