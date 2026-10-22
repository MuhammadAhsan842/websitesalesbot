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
        "I'm Ayyan's dispatch fit check — not a load board and not a contract. In a few questions I'll see if we support your trucks and lanes. A person handles papers. What are you running?",
    );
    renderChips(list && list.length ? list : ["I need dispatch", "What equipment do you support?", "I'm already a carrier"]);
  }

  async function ensureSession() {
    sessionId = sessionStorage.getItem(STORE);
    if (sessionId) {
      showIntro();
      return;
    }
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
    const pending = addMsg("bot", "Checking fit against approved services…", true);
    try {
      const response = await fetch(`${API}/v1/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, text: value, equipment: pageEquipment() }),
      });
      const data = await response.json();
      channel = data.channel || channel;
      channelLabel.textContent = channelText();
      pending.classList.remove("pending");
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
