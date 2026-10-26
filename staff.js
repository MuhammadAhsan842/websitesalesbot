const API = "";

function chip(task) {
  if (task === "setup_packet") return '<span class="chip chip-own">OWN MC PACKET</span>';
  if (task === "lease_agreement") return '<span class="chip chip-lease">LEASE-ON</span>';
  return '<span class="chip chip-review">CLARIFY MC</span>';
}

function factLine(facts = {}) {
  return ["equipment", "mcOwnership", "requestedArrangement", "fleetSize", "operatingArea", "lanes", "primaryProblem", "supportNeed", "startDate", "phone", "name"]
    .filter((k) => facts[k]?.value !== undefined && facts[k]?.value !== null)
    .map((k) => `${k}: ${facts[k].value} (${facts[k].status})`)
    .join(" · ");
}

function flagList(files = []) {
  if (!files.length) return "<p class='muted'>No files read yet. Store original → OCR/text, then a person reviews.</p>";
  return files.map((f) => `
    <div class="card" style="margin-top:8px">
      <p><strong>${f.doc_type}</strong> · ${f.filename} · v${f.version || 1} · ${f.status}${f.duplicate ? " · same file, skipped" : ""}</p>
      <p class="muted">unverified · ${f.method || "unread"} ${f.ocr_confidence != null ? `· OCR ${f.ocr_confidence}` : ""}</p>
      ${f.version > 1 ? `<p class="muted">${(f.diff || []).length ? `Changed: ${f.diff.map((d) => `${d.field}: ${d.from} → ${d.to}`).join("; ")}` : "Replacement file. No clause change — human still owns the conflict."}</p>` : ""}
      ${(f.flags || []).map((flag) => `<p class="${flag.severity === "blocking" ? "" : "muted"}">[${flag.severity}] ${flag.message}<br><span class="muted">span: ${flag.span || flag.evidence}</span></p>`).join("")}
    </div>
  `).join("");
}

function zohoBox(crm = {}) {
  const latest = crm.latest || {};
  const rows = crm.rows || [];
  return `
    <p>Mode: <strong>${crm.mode || "offline"}</strong> · verified: <strong>${crm.verified ? "yes" : "no"}</strong> · pending ${crm.pending || 0} · failed ${crm.failed || 0}</p>
    <p class="muted">${crm.note || ""} Latest: ${latest.kind || "—"} (${latest.status || "none"})${latest.zoho_id ? ` · ${latest.zoho_id}` : ""}</p>
    ${rows.slice(0, 6).map((row) => `<p class="muted">${row.kind} · ${row.status}${row.error ? ` · ${row.error}` : ""}</p>`).join("")}
  `;
}

function reqBox(packet = {}) {
  const rows = packet.requirements || [];
  if (!rows.length) return "<p class='muted'>No packet issued yet. Mark packet sent to start the SLA clock.</p>";
  return `
    <p class="muted">${packet.returned || 0}/${packet.issued || 0} returned · ${packet.overdue || 0} overdue · outstanding: ${(packet.outstanding || []).join(", ") || "none"}</p>
    ${rows.map((r) => `<p><strong>${r.label}</strong> · ${r.status}${r.overdue ? " · OVERDUE" : ""} · due ${r.due_at ? new Date(r.due_at).toLocaleDateString() : "—"}</p>`).join("")}
  `;
}

function entityBox(report = {}) {
  const lines = [...(report.different || []), ...(report.abstain || []), ...(report.same || [])];
  if (!lines.length) return "<p class='muted'>No entity decisions yet.</p>";
  return lines.map((row) => `<p><strong>${row.decision}</strong> — ${row.reason}</p>`).join("");
}

async function loadCases() {
  const response = await fetch(`${API}/v1/cases`);
  return response.json();
}

async function renderFees() {
  const box = document.getElementById("fee-box");
  if (!box) return;
  const data = await (await fetch(`${API}/v1/fees`)).json();
  const rows = data.fees || [];
  box.innerHTML = `
    <p>${rows.length ? rows.map((r) => `${r.arrangement}: <strong>${r.percent}%</strong> (${r.approved_by})`).join(" · ") : "No live fee published. The bot will not invent one."}</p>
    <form id="fee-form" class="actions" style="align-items:center">
      <select name="arrangement">
        <option value="dispatch_service">Own-MC dispatch</option>
        <option value="lease_on">Lease-on</option>
      </select>
      <input name="percent" type="number" min="0.1" max="99" step="0.1" placeholder="%" style="width:80px" required />
      <button class="btn btn-navy" type="submit">Publish approved fee</button>
    </form>
    <p class="muted">Publishing is a staff act. Chat may then quote that % after the arrangement is known. No chat discount.</p>
  `;
  box.querySelector("#fee-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    await fetch(`${API}/v1/fees`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        arrangement: form.arrangement.value,
        percent: Number(form.percent.value),
        approved_by: "Staff desk",
      }),
    });
    await renderFees();
  });
}

async function renderZohoConnect() {
  const box = document.getElementById("zoho-connect-box");
  if (!box) return;
  const data = await (await fetch(`${API}/v1/zoho/status`)).json();
  const conn = data.connection || {};
  const connected = conn.connected ? "live / connected" : "offline until you authorize";
  box.innerHTML = `
    <h3>Zoho CRM</h3>
    <p>Mode: <strong>${conn.mode || data.mode || "offline"}</strong> · ${connected}</p>
    <p class="muted">Redirect URI that must be saved on the Zoho client: <code>${conn.redirect_uri || "http://127.0.0.1:8787/v1/zoho/callback"}</code></p>
    <p class="muted">Chat still saves locally first. Live Deals write only after this connection is verified.</p>
    <div class="actions" style="align-items:center">
      <a class="btn btn-navy" href="${conn.connect_url || "/v1/zoho/connect"}">Connect Zoho</a>
    </div>
    <form id="zoho-grant-form" class="actions" style="align-items:center;margin-top:10px">
      <input name="code" placeholder="Self-client grant token" style="min-width:240px" required />
      <button class="btn btn-ghost" type="submit">Exchange grant</button>
    </form>
  `;
  box.querySelector("#zoho-grant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = event.target.code.value.trim();
    const result = await fetch(`${API}/v1/zoho/self-client`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const body = await result.json().catch(() => ({}));
    if (!result.ok) {
      alert(body.detail || "Zoho grant failed");
      return;
    }
    await renderZohoConnect();
  });
}

async function renderExamples() {
  const box = document.getElementById("examples-box");
  if (!box) return;
  const data = await (await fetch(`${API}/v1/examples`)).json();
  const rows = data.examples || [];
  const sources = data.sources || [];
  box.innerHTML = `
    <h3>Conversation examples</h3>
    <p>Published index: <strong>${data.index || 0}</strong> · sources ${sources.length}</p>
    <p class="muted">Chat PDFs can become examples after review. Packets, COIs, W-9s, and licences stay on the case — they are not personality.</p>
    <form id="example-upload" class="actions" style="align-items:center">
      <input type="file" name="file" accept=".pdf,image/*" required />
      <button class="btn btn-navy" type="submit">Ingest chat PDF</button>
    </form>
    ${sources.slice(0, 8).map((s) => `<p class="muted">${s.filename} · ${s.kind} · ${s.status}</p>`).join("")}
    ${rows.slice(0, 12).map((row) => `
      <div class="card" style="margin-top:8px">
        <p><strong>${row.id}</strong> · ${row.status} · ${(row.tags || []).join(", ")}</p>
        <p class="muted">${(row.user_text || "").slice(0, 160)}</p>
        <p>${(row.reply || "").slice(0, 220)}</p>
        ${row.status !== "published" ? `<button class="btn btn-ghost" type="button" data-publish="${row.id}">Publish</button>` : ""}
        ${row.status !== "withdrawn" && row.status !== "rejected" ? `<button class="btn btn-ghost" type="button" data-reject="${row.id}">Withdraw</button>` : ""}
      </div>
    `).join("")}
  `;
  box.querySelector("#example-upload").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = event.target.file.files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const result = await fetch(`${API}/v1/examples/ingest`, { method: "POST", body });
    const payload = await result.json().catch(() => ({}));
    if (payload.status === "duplicate") alert("That file was already ingested. Duplicate, not new experience.");
    if (payload.status === "rejected_kind") alert("That file is a packet or identity document. It is not a conversation example.");
    await renderExamples();
  });
  box.querySelectorAll("[data-publish]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API}/v1/examples/${btn.dataset.publish}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "published", reviewed_by: "Staff desk" }),
      });
      await renderExamples();
    });
  });
  box.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API}/v1/examples/${btn.dataset.reject}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "withdrawn", reviewed_by: "Staff desk" }),
      });
      await renderExamples();
    });
  });
}

async function renderPeft() {
  const box = document.getElementById("peft-box");
  if (!box) return;
  const data = await (await fetch(`${API}/v1/eval/hard-turns`)).json();
  box.innerHTML = `
    <h3>PEFT / LoRA / distillation</h3>
    <p>Hard turns logged: <strong>${data.count || 0}</strong> · reviewed: <strong>${data.reviewed || 0}</strong> / 1000</p>
    <p class="muted">${data.peft_ready ? "Adapter training is allowed on reviewed failures only." : "Not ready. Collect ~1,000 reviewed failures first."} Distillation is off. Fees are never training labels.</p>
  `;
}

async function render() {
  const rows = await loadCases();
  const table = document.getElementById("case-rows");
  if (!rows.length) {
    table.innerHTML = '<tr><td colspan="5">No cases yet. Open the public site and complete a chat handoff.</td></tr>';
    return rows;
  }
  table.innerHTML = rows.map((c) => `
    <tr data-id="${c.id}">
      <td><a href="?case=${c.id}">${c.id.slice(-8)}</a></td>
      <td>${chip(c.task)}</td>
      <td>${c.status}</td>
      <td>${c.owner}</td>
      <td>${new Date(c.updated_at).toLocaleString()}</td>
    </tr>
  `).join("");
  return rows;
}

async function renderDetail(id) {
  const box = document.getElementById("case-detail");
  if (!id) {
    box.classList.add("hidden");
    return;
  }
  const response = await fetch(`${API}/v1/cases/${id}`);
  if (!response.ok) {
    box.classList.add("hidden");
    return;
  }
  const current = await response.json();
  const blocking = current.blocking || [];
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="card">
      <h3>${current.id}</h3>
      <p>${chip(current.task)} · ${current.status}</p>
      <p class="muted">${factLine(current.facts)}</p>
      <p>${current.summary || ""}</p>
      ${current.desk ? `<p><strong>After-hours card:</strong> ${current.desk.line || ""}</p><p class="muted">Owner: ${current.desk.owner || "assistant"} · next: ${current.desk.next_step || current.next_action || "—"}</p>` : `<p><strong>Next:</strong> ${current.next_action || "—"}</p>`}
      <p class="muted">Received is not reviewed. Reviewed is not approved. Approved is not production-accepted. The worker cannot approve a COI.</p>
      <div class="card" style="margin-top:12px">
        <h3>Zoho</h3>
        ${zohoBox(current.zoho)}
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn btn-navy" data-act="packet_sent">Mark packet / lease sent</button>
        <button class="btn btn-ghost" data-act="received">Documents received</button>
        <button class="btn btn-navy" data-doc>Read sample COI / lease</button>
        <button class="btn btn-ghost" data-ack ${blocking.length ? "" : "disabled"}>Acknowledge flags (${blocking.length})</button>
        <button class="btn btn-ghost" data-act="corrections">Request corrections</button>
        <button class="btn btn-gold" data-act="approve">Human approve</button>
        <button class="btn btn-navy" data-act="production">Production accept</button>
        <button class="btn btn-ghost" data-act="takeover">Take over / pause bot</button>
      </div>
    </div>
    <div>
      <div class="card">
        <h3>Packet requirements</h3>
        <p class="muted">Issued transaction, not a merged carrier file. OCR stays unverified.</p>
        ${reqBox(current.packet)}
      </div>
      <div class="card">
        <h3>Document worker</h3>
        <p class="muted">Original stored, then text/OCR. Auto-approval is off. Not used on the live voice path.</p>
      </div>
      <div class="card">
        <h3>Entity resolution</h3>
        <p class="muted">Auto-merge is off. Abstain is a valid result.</p>
        ${entityBox(current.entities)}
      </div>
      ${flagList(current.files)}
      ${(current.attachments || []).length ? `
      <div class="card" style="margin-top:8px">
        <h3>Chat photos</h3>
        <p class="muted">Stored unverified. Vision notes are not equipment eligibility, insurance, or approval. Screenshots keep OCR, not image similarity.</p>
        ${current.attachments.map((a) => `<p class="muted">${a.filename} · ${a.kind} · ${a.vision_status || "unread"}${a.description ? ` · ${a.description}` : ""}</p>`).join("")}
      </div>` : ""}
    </div>
  `;
  box.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const result = await fetch(`${API}/v1/cases/${id}/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ act: btn.dataset.act }),
      });
      if (result.status === 409) {
        alert("Acknowledge flagged COI/lease issues first. The worker cannot approve.");
        return;
      }
      await render();
      await renderDetail(id);
    });
  });
  box.querySelector("[data-doc]")?.addEventListener("click", async () => {
    await fetch(`${API}/v1/cases/${id}/review-packet`, { method: "POST" });
    await render();
    await renderDetail(id);
  });
  box.querySelector("[data-ack]")?.addEventListener("click", async () => {
    await fetch(`${API}/v1/cases/${id}/acknowledge-flags`, { method: "POST" });
    await renderDetail(id);
  });
}

(async () => {
  await renderZohoConnect();
  await renderFees();
  await renderExamples();
  await renderPeft();
  const rows = await render();
  const selected = new URLSearchParams(location.search).get("case") || rows[0]?.id;
  if (selected) await renderDetail(selected);
})();
