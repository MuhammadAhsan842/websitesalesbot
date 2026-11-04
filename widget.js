(() => {
  const API = "";
  const STORE = "agoc_session_v2";
  let sessionId = sessionStorage.getItem(STORE);
  const VOICE_STORE = "agoc_voice_access_v1";
  let voiceClient = null;
  let voiceRequest = 0;
  let voiceState = "idle";
  let voiceAvailable = false;
  let muted = false;
  let channel = "chat";
  let workflows = {};
  const pageEquipment = () => document.body.dataset.equipment || "";

  function el(tag, attrs = {}, html = "") {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else node.setAttribute(k, v);
    });
    if (html) node.innerHTML = html;
    return node;
  }

  const launcher = el("button", { class: "agoc-launcher", "aria-label": "Open dispatch fit check" }, "Fit");
  const panel = el("div", { class: "agoc-panel", id: "agoc-panel" });
  panel.innerHTML = `
    <div class="agoc-head">
      <div>
        <strong>Dispatch Fit Check</strong>
        <span data-channel>Useful answers first. Papers stay with a person.</span>
      </div>
      <button type="button" data-close>×</button>
    </div>
    <div class="agoc-log" id="agoc-log"></div>
    <div class="agoc-chips" id="agoc-chips"></div>
    <div class="agoc-voice" aria-label="Voice controls">
      <span data-voice-status role="status" aria-live="polite">Checking voice availability…</span>
      <div><button type="button" data-voice-start disabled>Talk here</button>
      <button type="button" data-voice-mute hidden>Mute</button>
      <button type="button" data-voice-audio hidden>Enable audio</button>
      <button type="button" data-voice-end hidden>Return to chat</button></div>
    </div>
    <form class="agoc-form" id="agoc-form">
      <label class="agoc-attach" title="Add a photo. Stored unverified — not approval.">
        <input type="file" name="photo" accept="image/*,.pdf" hidden />
        Photo
      </label>
      <input name="message" autocomplete="off" placeholder="Ask, or choose Talk here / Call me" />
      <button type="submit">Send</button>
    </form>
  `;
  document.body.append(launcher, panel);

  const log = panel.querySelector("#agoc-log");
  const chips = panel.querySelector("#agoc-chips");
  const form = panel.querySelector("#agoc-form");
  const channelLabel = panel.querySelector("[data-channel]");

  function channelText() {
    if (voiceState !== "idle" && voiceState !== "error") return "Voice · same inquiry";
    const callback = workflows.callback;
    if (callback?.status === "collecting") return "Chat · collecting callback details";
    if (callback?.status === "requested") return "Chat · callback requested, time unconfirmed";
    if (callback?.status === "cancelled") return "Chat · callback cancelled";
    return "Chat · " + (voiceAvailable ? "voice available by choice" : "callbacks can be requested");
  }

  function normalizeChip(item) {
    if (item && typeof item === "object") {
      return {
        label: item.label || String(item.value || ""),
        field: item.field || null,
        value: item.value != null ? item.value : item.label,
        autoLiabilityCoverage: item.autoLiabilityCoverage,
        cargoCoverage: item.cargoCoverage,
        requestedArrangement: item.requestedArrangement,
      };
    }
    const label = String(item || "");
    return { label, field: null, value: label };
  }

  function addMsg(role, text, pending = false) {
    const msg = el("div", { class: `agoc-msg ${role}${pending ? " pending" : ""}` });
    msg.textContent = String(text);
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  function renderChips(list) {
    chips.innerHTML = "";
    (list || []).map(normalizeChip).forEach((chip) => {
      if (!chip.label) return;
      const btn = el("button", { type: "button" }, chip.label);
      btn.disabled = !["idle", "error"].includes(voiceState);
      btn.addEventListener("click", () => send(chip.label, chip));
      chips.appendChild(btn);
    });
  }

  function showIntro(text, list) {
    if (log.children.length) return;
    addMsg(
      "bot",
      text ||
        "I'm Ayyan Group's AI sales assistant. I can check dispatch fit; a person handles papers. What are you running?",
    );
    renderChips(
      list && list.length
        ? list
        : ["I need dispatch", "What equipment do you support?", "I'm already a carrier"],
    );
  }

  function renderHistory(data) {
    log.innerHTML = "";
    channel = data.channel || channel;
    workflows = data.workflows || {};
    channelLabel.textContent = channelText();
    (data.messages || []).forEach((item) => {
      addMsg(item.role === "user" ? "user" : "bot", item.text);
    });
    renderChips(data.chips || []);
    if (!log.children.length) showIntro(data.text, data.chips);
  }

  async function restoreSession() {
    const stored = sessionStorage.getItem(STORE);
    if (!stored) return false;
    try {
      const response = await fetch(`${API}/v1/session/${stored}`);
      if (response.status === 404) {
        sessionStorage.removeItem(STORE);
        sessionId = null;
        return false;
      }
      if (!response.ok) throw new Error("session");
      sessionId = stored;
      renderHistory(await response.json());
      return true;
    } catch {
      return false;
    }
  }

  async function ensureSession() {
    if (sessionId && log.children.length) return;
    if (await restoreSession()) return;
    try {
      const response = await fetch(`${API}/v1/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: document.body.dataset.page || "", equipment: pageEquipment() }),
      });
      if (!response.ok) throw new Error("session");
      const data = await response.json();
      sessionId = data.session_id;
      sessionStorage.setItem(STORE, sessionId);
      if (data.voice_access_token) sessionStorage.setItem(VOICE_STORE, JSON.stringify({sessionId, token: data.voice_access_token}));
      showIntro(data.text, data.chips);
    } catch {
      addMsg("bot", "The fit check is not reachable. Start the API, then open this again.");
    }
  }

  async function send(text, chip = null) {
    const value = String(text || "").trim();
    if (value.toLowerCase() === "talk here" && voiceAvailable) return startVoice();
    if (!["idle", "error"].includes(voiceState)) return;
    if (!value) return;
    await ensureSession();
    addMsg("user", value);
    renderChips([]);
    const pending = addMsg("bot", "Listening — keeping this on the same case…", true);
    const turnId = crypto.randomUUID ? crypto.randomUUID() : `turn_${Date.now()}`;
    const payload = {
      session_id: sessionId,
      text: value,
      equipment: pageEquipment(),
      turn_id: turnId,
    };
    if (chip && (chip.field || chip.value != null)) {
      payload.chip = {
        label: chip.label || value,
        field: chip.field || null,
        value: chip.value != null ? chip.value : value,
      };
      if (chip.autoLiabilityCoverage) payload.chip.autoLiabilityCoverage = chip.autoLiabilityCoverage;
      if (chip.cargoCoverage) payload.chip.cargoCoverage = chip.cargoCoverage;
      if (chip.requestedArrangement) payload.chip.requestedArrangement = chip.requestedArrangement;
    }
    const post = () =>
      fetch(`${API}/v1/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    try {
      let response = await post();
      if (response.status === 503) {
        pending.textContent = "Still on this CPU — retrying once…";
        await new Promise((resolve) => setTimeout(resolve, 2000));
        response = await post();
      }
      const data = await response.json();
      pending.classList.remove("pending");
      if (response.status === 503) {
        pending.textContent = "The assistant is still busy. Your message is saved here — send it again in a moment.";
        return;
      }
      channel = data.channel || channel;
      workflows = data.workflows || {};
      channelLabel.textContent = channelText();
      pending.textContent = String(data.text || "I do not have an approved answer for that.");
      if (data.fit_summary) pending.classList.add("fit");
      if (data.thinking) {
        const details = el("details", { class: "agoc-think" });
        details.innerHTML = `<summary>Model thinking</summary><pre></pre>`;
        details.querySelector("pre").textContent = data.thinking;
        if (data.model_wording && data.model_wording !== data.text) {
          const draft = el("div", { class: "agoc-think-draft" });
          draft.textContent = `Model wording (pre-align): ${data.model_wording}`;
          details.appendChild(draft);
        }
        pending.appendChild(details);
      }
      renderChips(data.chips || []);
    } catch {
      pending.classList.remove("pending");
      pending.textContent = "The fit check is not reachable. Start the API, then send again.";
    }
  }

  const voiceStatus = panel.querySelector("[data-voice-status]");
  const startButton = panel.querySelector("[data-voice-start]");
  const muteButton = panel.querySelector("[data-voice-mute]");
  const endButton = panel.querySelector("[data-voice-end]");
  const audioButton = panel.querySelector("[data-voice-audio]");
  function updateVoice(state, message) {
    voiceState = state;
    const active = !["idle", "error"].includes(state);
    startButton.hidden = active;
    startButton.disabled = !voiceAvailable;
    endButton.hidden = !active;
    muteButton.hidden = !["connected", "playback_blocked"].includes(state);
    audioButton.hidden = state !== "playback_blocked";
    form.querySelectorAll("input, button").forEach(node => { node.disabled = active; });
    chips.querySelectorAll("button").forEach(node => { node.disabled = active; });
    voiceStatus.textContent = message || ({connecting: "Connecting microphone…", connected: "AI voice connected · you can interrupt",
      playback_blocked: "Enable audio to hear the AI assistant",
      idle: voiceAvailable ? "Microphone starts only when you choose Talk here." : "Voice unavailable · continue in chat",
      error: "Voice unavailable · continue in chat"}[state] || state);
    channelLabel.textContent = channelText();
  }
  async function checkVoice() {
    try {
      const response = await fetch("/v1/voice/capabilities");
      if (!response.ok) throw new Error("voice");
      const capability = await response.json();
      voiceAvailable = capability.available;
      startButton.textContent = capability.profile === "demo" ? "Talk here · demo voice" : "Talk here";
    } catch { voiceAvailable = false; }
    if (["idle", "error"].includes(voiceState)) updateVoice("idle");
  }
  let sdkPromise;
  function loadVoice() {
    if (!sdkPromise) sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/voice-client.js";
      script.onload = resolve;
      script.onerror = () => { sdkPromise = null; reject(new Error("Voice client could not load. Continue in chat.")); };
      document.head.append(script);
    });
    return sdkPromise;
  }
  async function startVoice() {
    if (!["idle", "error"].includes(voiceState)) return;
    const request = ++voiceRequest;
    updateVoice("connecting");
    await ensureSession();
    if (request !== voiceRequest) return;
    let access;
    try { access = JSON.parse(sessionStorage.getItem(VOICE_STORE) || "null"); } catch {}
    if (!access || access.sessionId !== sessionId) {
      updateVoice("error", "Voice needs a newly started chat in this browser. Your existing chat remains available.");
      return;
    }
    try {
      await loadVoice();
      if (request !== voiceRequest) return;
      voiceClient = new window.AyyanVoice.VoiceClient({sessionId, accessToken: access.token,
        onStatus: updateVoice, onHistory: async () => {
          if (!sessionId) return;
          const response = await fetch(`/v1/session/${sessionId}`);
          if (response.ok) {
            const history = await response.json();
            renderHistory(history);
            if (history.manager_accepted && voiceClient?.room) await voiceClient.stop();
          }
        }});
      await voiceClient.start();
    } catch (error) { updateVoice("error", error.message); }
  }
  startButton.addEventListener("click", startVoice);
  endButton.addEventListener("click", () => { ++voiceRequest; if (voiceClient) void voiceClient.stop(); else updateVoice("idle"); });
  muteButton.addEventListener("click", async () => {
    muted = !muted;
    try { await voiceClient?.mute(muted); muteButton.textContent = muted ? "Unmute" : "Mute"; }
    catch { await voiceClient?.stop(); }
  });
  audioButton.addEventListener("click", () => voiceClient?.enableAudio());
  window.addEventListener("pagehide", () => { void voiceClient?.stop(); });
  void checkVoice();

  window.addEventListener("agoc-reset", async () => {
    ++voiceRequest;
    await voiceClient?.stop();
    sessionStorage.removeItem(VOICE_STORE);
    sessionId = null;
    sessionStorage.removeItem(STORE);
    log.innerHTML = "";
    chips.innerHTML = "";
    channel = "chat";
    workflows = {};
  });
  launcher.addEventListener("click", async () => {
    panel.classList.add("open");
    if (!log.children.length) await ensureSession();
    await checkVoice();
  });
  panel.querySelector("[data-close]").addEventListener("click", async () => {
    ++voiceRequest;
    await voiceClient?.stop();
    if (!voiceClient) updateVoice("idle");
    panel.classList.remove("open");
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(form.message.value);
    form.message.value = "";
  });
  form.photo.addEventListener("change", async () => {
    const file = form.photo.files && form.photo.files[0];
    form.photo.value = "";
    if (!file) return;
    await ensureSession();
    if (!sessionId) return;
    addMsg("user", `Photo: ${file.name}`);
    const pending = addMsg("bot", "Saving the photo in the background. This is not approval.", true);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${API}/v1/session/${sessionId}/attachment`, { method: "POST", body });
      const data = await response.json();
      pending.classList.remove("pending");
      pending.textContent = data.text || "I have the photo on this chat (unverified). Onboarding still needs to look at it.";
    } catch {
      pending.classList.remove("pending");
      pending.textContent = "The photo could not be saved. Try again after the API is up.";
    }
  });
})();
