const STORE_KEY = "agoc-demo-v1";

function loadStore() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY)) || { cases: [], events: [] };
  } catch {
    return { cases: [], events: [] };
  }
}

function saveStore(data) {
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
  window.dispatchEvent(new CustomEvent("agoc-store"));
}

function uid(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function addEvent(message, extra = {}) {
  const data = loadStore();
  data.events.unshift({ id: uid("evt"), at: new Date().toISOString(), message, ...extra });
  saveStore(data);
}

function upsertCase(partial) {
  const data = loadStore();
  const existing = partial.id ? data.cases.find((c) => c.id === partial.id) : null;
  if (existing) {
    Object.assign(existing, partial, { id: existing.id, updatedAt: new Date().toISOString() });
    saveStore(data);
    return existing;
  }
  const created = {
    status: "created",
    owner: "Unassigned desk",
    createdAt: new Date().toISOString(),
    documents: [],
    ...partial,
    id: partial.id || uid("case"),
    updatedAt: new Date().toISOString(),
  };
  data.cases.unshift(created);
  saveStore(data);
  return created;
}

function getCase(id) {
  return loadStore().cases.find((c) => c.id === id);
}

function listCases() {
  return loadStore().cases;
}
