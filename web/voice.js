import { Room, RoomEvent, Track } from 'livekit-client';

// No provider credentials or reference recordings are shipped to the browser.
export class VoiceClient {
  constructor({sessionId, accessToken, onStatus, onHistory, fetcher = fetch,
               roomFactory = () => new Room({adaptiveStream: true}), audioRoot = document.body}) {
    Object.assign(this, {sessionId, accessToken, onStatus, onHistory, fetcher, roomFactory, audioRoot});
    this.generation = 0;
    this.audio = new Set();
  }
  async request(path, options = {}) {
    const response = await this.fetcher('/v1/voice' + path, {
      ...options, headers: {'Content-Type': 'application/json', 'X-Inquiry-Token': this.accessToken, ...options.headers}
    });
    if (!response.ok) throw new Error(response.status === 403 ? 'Start a new chat to enable voice securely.' :
      response.status === 409 ? 'Voice is busy or the inquiry has changed. Continue in chat.' : 'Voice is unavailable. Continue in chat.');
    return response.json();
  }
  async start() {
    if (this.room) return;
    const generation = ++this.generation;
    const room = this.room = this.roomFactory();
    this.onStatus('connecting');
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind !== Track.Kind.Audio) return;
      const audio = track.attach();
      this.audio.add(audio);
      this.audioRoot.append(audio);
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach(audio => { audio.remove(); this.audio.delete(audio); });
    });
    room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (!room.canPlaybackAudio) this.onStatus('playback_blocked', 'Click Enable audio to hear the assistant.');
    });
    room.on(RoomEvent.Disconnected, () => { if (this.room === room) void this.stop(); });
    try {
      const grant = await this.request('/connect', {method: 'POST', body: JSON.stringify({session_id: this.sessionId})});
      // Stop/reset may happen while the grant is in flight. Release it as well.
      if (generation !== this.generation) {
        await this.request('/' + grant.connection_id, {method: 'DELETE'});
        return;
      }
      this.connectionId = grant.connection_id;
      await room.connect(grant.url, grant.token);
      if (generation !== this.generation) { await room.disconnect(); return; }
      await room.localParticipant.setMicrophoneEnabled(true, {echoCancellation: true, noiseSuppression: true});
      if (generation !== this.generation) { await room.disconnect(); return; }
      try { await room.startAudio(); }
      catch { this.onStatus('playback_blocked', 'Click Enable audio to hear the assistant.'); }
      if (generation !== this.generation) { await room.disconnect(); return; }
      const deadline = Date.now() + 45000;
      this.poller = setInterval(async () => {
        if (this.polling || generation !== this.generation) return;
        this.polling = true;
        try {
          const state = await this.request('/' + this.connectionId);
          if (generation !== this.generation) return;
          if (state.status === 'ended' || Date.now() > deadline && !state.connected) {
            await this.stop();
            this.onStatus('error', 'Voice disconnected. Your inquiry is still available in chat.');
            return;
          }
          this.onStatus(state.connected ? (room.canPlaybackAudio ? 'connected' : 'playback_blocked') : 'connecting');
          await this.onHistory();
        } catch (error) {
          await this.stop();
          this.onStatus('error', error.message);
        } finally { this.polling = false; }
      }, 1500);
    } catch (error) {
      if (generation === this.generation) {
        await this.stop();
        this.onStatus('error', error.message || 'Microphone unavailable. Continue in chat.');
      }
    }
  }
  async enableAudio() { await this.room?.startAudio(); }
  async mute(muted) { await this.room?.localParticipant.setMicrophoneEnabled(!muted); }
  async stop() {
    ++this.generation;
    clearInterval(this.poller);
    const room = this.room;
    const connectionId = this.connectionId;
    this.room = null;
    this.connectionId = null;
    // Release the microphone and stop audio immediately, even if the API is down.
    if (room) await room.disconnect();
    this.audio.forEach(audio => { audio.pause(); audio.srcObject = null; audio.remove(); });
    this.audio.clear();
    if (connectionId) await this.request('/' + connectionId, {method: 'DELETE'}).catch(() => {});
    this.onStatus('idle');
    await this.onHistory();
  }
}
