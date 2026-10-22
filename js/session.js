function createSession() {
  return {
    sessionId: uid("session"),
    channel: "chat",
    previousChannel: null,
    conversationState: "understand_request",
    stateVersion: 1,
    facts: {},
    caseId: null,
    opportunityId: uid("opp"),
    takeover: false,
    handedOver: false,
    identityConfirmedForVoice: false,
    pendingQuestion: null,
  };
}

function setFact(session, key, value, status = "user_stated") {
  const previous = session.facts[key];
  session.facts[key] = {
    value,
    status,
    sourceChannel: session.channel,
    version: session.stateVersion,
    previous: previous ? { value: previous.value, status: previous.status } : null,
  };
  session.stateVersion += 1;
}

function fact(session, key) {
  const item = session.facts[key];
  if (!item || item.status === "unknown") return undefined;
  return item.value;
}

function markUnknown(session, key) {
  setFact(session, key, null, "unknown");
}

function summaryFacts(session) {
  return Object.entries(session.facts).map(([key, item]) => {
    if (item.status === "unknown") return `${key}: unknown`;
    return `${key}: ${item.value} (${item.status})`;
  });
}

function switchChannel(session, nextChannel, reason) {
  if (session.channel === nextChannel) return;
  session.previousChannel = session.channel;
  session.channel = nextChannel;
  session.stateVersion += 1;
  addEvent(`Channel ${session.previousChannel} → ${nextChannel}`, {
    sessionId: session.sessionId,
    reason,
  });
}
