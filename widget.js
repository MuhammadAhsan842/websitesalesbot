(() => {
  const API = "";
  const STORE = "agoc_session_v2";
  let sessionId = sessionStorage.getItem(STORE);
  let channel = "chat";
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
    <form class="agoc-form" id="agoc-form">
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
    if (channel === "browser_voice") return "Talk here · same fit check, voice reserved";
    if (channel === "callback_pending") return "Call me · callback on this opportunity";
    return "Chat · Talk here keeps this case; Call me is a callback";
  }

  function addMsg(role, text, pending = false) {
    const msg = el("div", { class: `agoc-msg ${role}${pending ? " pending" : ""}` });
    msg.innerHTML = String(text).replace(/\n/g, "<br>");
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  function renderChips(list) {
    chips.innerHTML = "";
    (list || []).forEach((label) => {
      const btn = el("button", { type: "button" }, label);
      btn.addEventListener("click", () => send(label));
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
    renderChips(list && list.length ? list : ["I need dispatch", "What equipment do you support?", "I'm already a carrier"]);
  }

  function renderHistory(data) {
    log.innerHTML = "";
    channel = data.channel || channel;
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
      showIntro(data.text, data.chips);
    } catch {
      addMsg("bot", "The fit check is not reachable. Start the API, then open this again.");
    }
  }

  async function send(text) {
    const value = text.trim();
    if (!value) return;
    await ensureSession();
    addMsg("user", value);
    renderChips([]);
    const pending = addMsg("bot", "Listening — keeping this on the same case…", true);
    const turnId = crypto.randomUUID ? crypto.randomUUID() : `turn_${Date.now()}`;
    const post = () =>
      fetch(`${API}/v1/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, text: value, equipment: pageEquipment(), turn_id: turnId }),
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
      channelLabel.textContent = channelText();
      pending.innerHTML = String(data.text || "I do not have an approved answer for that.").replace(/\n/g, "<br>");
      if (data.fit_summary) pending.classList.add("fit");
      renderChips(data.chips || []);
    } catch {
      pending.classList.remove("pending");
      pending.textContent = "The fit check is not reachable. Start the API, then send again.";
    }
  }

  window.addEventListener("agoc-reset", () => {
    sessionId = null;
    sessionStorage.removeItem(STORE);
    log.innerHTML = "";
    chips.innerHTML = "";
    channel = "chat";
  });
  launcher.addEventListener("click", async () => {
    panel.classList.add("open");
    if (!log.children.length) await ensureSession();
  });
  panel.querySelector("[data-close]").addEventListener("click", () => panel.classList.remove("open"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(form.message.value);
    form.message.value = "";
  });
})();
