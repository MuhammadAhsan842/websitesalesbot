const QUAL_FIELDS = ["equipment", "fleetSize", "operatingArea", "lanes", "supportNeed", "startDate", "mcOwnership"];

function detectIntent(text) {
  const t = text.toLowerCase();
  if (/(existing|already (a )?carrier|where's my load|where is my load|detention|tonu)/.test(t)) return "existing_customer";
  if (/(talk here|speak|voice|microphone)/.test(t)) return "talk_here";
  if (/(call me|callback|phone me|dial)/.test(t)) return "call_me";
  if (/(fee|percent|%|charge|cost|how much)/.test(t)) return "fee";
  if (/(guarantee|earn|\$\d|weekly gross)/.test(t)) return "guarantee";
  if (/fuel card/.test(t)) return "fuel";
  if (/trust|scam|legit/.test(t)) return "trust";
  if (/home (every )?night|home time/.test(t)) return "hometime";
  if (/talk to (a )?(human|person|agent)|dispatcher please/.test(t)) return "human";
  if (/document|packet|onboard|ready to start|get started/.test(t)) return "onboard";
  if (/lease/.test(t)) return "lease";
  if (/\bmc\b|authority/.test(t)) return "mc";
  if (/(what (trucks|equipment)|do you (haul|dispatch|support))/.test(t)) return "service";
  if (/status|approved yet/.test(t)) return "status";
  if (/don'?t know|not sure yet|unknown|skip that/.test(t)) return "unknown_detail";
  if (/dispatch|need (a )?dispatcher|looking for dispatch/.test(t)) return "dispatch_inquiry";
  return "general";
}

function extractFacts(session, text) {
  const t = text.toLowerCase();
  const equip = t.match(/reefer|dry van|flatbed|box truck|hotshot/)?.[0];
  if (equip) setFact(session, "equipment", equip.replace(" ", "_"));
  const count = t.match(/(\d+)\s+(trucks?|reefers?|vans?|hotshots?)/);
  if (count) {
    const status = /actually|make that|correction|not one|changed/.test(t) ? "corrected" : "user_stated";
    setFact(session, "fleetSize", Number(count[1]), status);
  }
  if (/(own mc|my own mc|my authority|have (an? )?mc)/.test(t)) {
    setFact(session, "mcOwnership", "own_mc");
    setFact(session, "requestedArrangement", "dispatch_service");
  }
  if (/(no mc|don'?t have.*mc|lease on|lease-on)/.test(t)) {
    setFact(session, "mcOwnership", "no_own_mc");
    setFact(session, "requestedArrangement", "lease_on");
  }
  if (/(pending|not sure|unsure|another company)/.test(t) && /mc/.test(t)) {
    setFact(session, "mcOwnership", "unclear");
    setFact(session, "requestedArrangement", "needs_clarification");
  }
  const area = t.match(/midwest|southeast|northeast|southwest|west coast|texas|california|georgia|florida|otr/i);
  if (area) {
    setFact(session, "operatingArea", area[0].toLowerCase());
    if (/midwest|southeast|northeast|otr/.test(area[0].toLowerCase())) setFact(session, "lanes", area[0].toLowerCase());
  }
  if (/home every night|daily home/.test(t)) setFact(session, "supportNeed", "daily_home_time");
  if (/paperwork|broker calls|factoring/.test(t)) setFact(session, "supportNeed", t.match(/paperwork|broker calls|factoring/)[0]);
  if (/start (next week|immediately|asap|monday)/.test(t)) setFact(session, "startDate", t.match(/next week|immediately|asap|monday/)[0]);
  const phone = text.match(/(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/);
  if (phone) setFact(session, "phone", phone[0], "confirmed");
  const name = text.match(/my name is ([a-z][a-z ]{1,40})/i);
  if (name) setFact(session, "name", name[1].trim(), "confirmed");
}

function missingQualification(session) {
  return QUAL_FIELDS.filter((key) => session.facts[key] === undefined);
}

function routeTask(session) {
  const mc = fact(session, "mcOwnership");
  if (mc === "own_mc") return "setup_packet";
  if (mc === "no_own_mc") return "lease_agreement";
  return "clarification";
}

function persistCase(session, extra = {}) {
  const saved = upsertCase({
    id: session.caseId,
    sessionId: session.sessionId,
    opportunityId: session.opportunityId,
    channel: session.channel,
    task: extra.task || routeTask(session),
    status: extra.status || "assigned",
    conversationState: session.conversationState,
    facts: session.facts,
    takeover: session.takeover,
    summary: extra.summary || summaryFacts(session).join("; "),
    nextAction: extra.nextAction || "",
  });
  session.caseId = saved.id;
  addEvent(extra.event || "Case updated", { caseId: saved.id, channel: session.channel });
  return saved;
}

function nextQuestion(session) {
  const missing = missingQualification(session);
  const prompts = {
    equipment: "What equipment are you running?",
    fleetSize: "How many trucks?",
    operatingArea: "What operating area are you in?",
    lanes: "Which lanes do you prefer?",
    supportNeed: "What support matters most — home time, paperwork, or keeping the truck loaded?",
    startDate: "When do you want to start? Say if you do not know yet.",
    mcOwnership: "Will you operate under your own MC, or are you looking to lease on under Ayyan’s authority?",
  };
  if (!missing.length) return null;
  return prompts[missing[0]];
}

function chipsFor(session) {
  if (session.takeover) return ["What's my status?"];
  if (session.handedOver) return ["What's my status?", "Talk here", "Call me", "Talk to a human"];
  if (session.conversationState === "understand_request") {
    return ["I need dispatch", "What equipment do you support?", "I'm already a carrier"];
  }
  const missing = missingQualification(session);
  if (missing[0] === "equipment") return ["Dry van", "Reefer", "Flatbed", "Box truck"];
  if (missing[0] === "mcOwnership") return ["I have my own MC", "I want to lease on", "Not sure about my MC"];
  if (missing[0] === "fleetSize") return ["1 truck", "3 trucks", "I don't know yet"];
  if (missing[0] === "startDate") return ["Next week", "I don't know yet"];
  return ["I'm ready to start", "Talk here", "Call me", "What is the fee?", "Talk to a human"];
}

function continueFromState(session) {
  const ask = nextQuestion(session);
  if (ask) {
    session.conversationState = "discover_needs";
    session.pendingQuestion = ask;
    return `${ask}`;
  }
  session.conversationState = "assess_fit";
  const mc = fact(session, "mcOwnership");
  const fit =
    mc === "own_mc" ? "own-MC dispatch, pending human packet review"
      : mc === "no_own_mc" ? "lease-on review, pending human eligibility"
        : "arrangement unclear — staff must clarify before any packet";
  return `Potential fit: ${fact(session, "equipment") || "equipment noted"}, ${fit}. This is not approval and not a load promise.\n\n${summaryFacts(session).join("\n")}\n\nI can create the human task, you can talk here, or request a callback.`;
}

function handleTalkHere(session) {
  switchChannel(session, "browser_voice", "visitor_requested_talk_here");
  session.identityConfirmedForVoice = true;
  const remainder = continueFromState(session);
  return {
    text: `Talk here uses this same inquiry. I will not re-ask confirmed details.\n\n${remainder}\n\nBrowser voice audio is not live in this build; the case and channel are already switched so the voice agent can attach here.`,
    chips: chipsFor(session),
    mode: "browser_voice",
  };
}

function handleCallMe(session, text) {
  extractFacts(session, text);
  if (!fact(session, "phone")) {
    session.conversationState = "agree_next_action";
    return {
      text: "Call me is a callback, not Talk here. Confirm the number, preferred time, and timezone. I will not dial from the website microphone.",
      chips: ["Call me at 555-218-9040", "Talk here"],
    };
  }
  persistCase(session, {
    task: "callback",
    status: "callback_requested",
    nextAction: "Human or voice worker returns the call on the saved opportunity",
    event: "Callback requested from chat",
  });
  session.handedOver = true;
  session.conversationState = "handed_over";
  switchChannel(session, "callback_pending", "visitor_requested_callback");
  return {
    text: `Callback recorded for ${fact(session, "phone")} on opportunity ${session.opportunityId}. When that call happens, the voice agent loads this case, confirms it is you, then continues from ${session.pendingQuestion || "the unfinished next step"}. That call is not document approval.`,
    chips: chipsFor(session),
  };
}

function reply(session, userText) {
  if (session.takeover) {
    return { text: "A person owns this case. Automated selling is paused.", chips: chipsFor(session) };
  }

  extractFacts(session, userText);
  const intent = detectIntent(userText);

  if (intent === "talk_here") return handleTalkHere(session);
  if (intent === "call_me") return handleCallMe(session, userText);

  if (intent === "existing_customer") {
    session.conversationState = "support_route";
    persistCase(session, {
      task: "operations_support",
      status: "routed_support",
      nextAction: "Operations desk",
      event: "Existing-customer route",
    });
    return { text: lookupKnowledge("support"), chips: ["Talk to a human", "What's my status?"] };
  }

  if (intent === "fee") {
    session.pendingQuestion = nextQuestion(session);
    return { text: lookupKnowledge("fee") + (session.pendingQuestion ? `\n\nWhen you want to continue: ${session.pendingQuestion}` : ""), chips: chipsFor(session) };
  }
  if (intent === "guarantee") return { text: lookupKnowledge("guarantee"), chips: chipsFor(session) };
  if (intent === "fuel") return { text: lookupKnowledge("fuel"), chips: chipsFor(session) };
  if (intent === "service") return { text: lookupKnowledge("services"), chips: chipsFor(session) };
  if (intent === "trust") {
    return { text: "Staff handle contracting and documents. I can explain the process; I cannot prove a load or a payday.", chips: chipsFor(session) };
  }
  if (intent === "hometime") {
    setFact(session, "supportNeed", "daily_home_time");
    return { text: "Daily home time is recorded as a constraint. I will not replace it with a weekend-home promise. Fit still needs a human if the lanes do not allow it.", chips: chipsFor(session) };
  }

  if (intent === "unknown_detail") {
    const missing = missingQualification(session)[0];
    if (missing) markUnknown(session, missing);
    return { text: `Marked ${missing || "that item"} as unknown. We can continue.\n\n${continueFromState(session)}`, chips: chipsFor(session) };
  }

  if (intent === "status") {
    if (!session.caseId) return { text: "No staff case is open yet.", chips: chipsFor(session) };
    if (session.channel !== "chat" && !session.identityConfirmedForVoice) {
      return { text: "Confirm your name or callback number before I read case status on a voice channel.", chips: ["My name is Alex Rivera"] };
    }
    const current = getCase(session.caseId);
    return { text: `Verified status: ${current?.status}. That is not insurance or agreement approval.`, chips: chipsFor(session) };
  }

  if (intent === "human") {
    session.takeover = true;
    persistCase(session, { status: "human_takeover", nextAction: "Staff owns conversation", event: "Human takeover" });
    return { text: "Automated follow-up is paused. Staff have the same session and facts.", chips: chipsFor(session) };
  }

  if (session.conversationState === "understand_request" && intent === "dispatch_inquiry") {
    session.conversationState = "discover_needs";
    return { text: continueFromState(session), chips: chipsFor(session) };
  }

  if (intent === "onboard" || /ready/.test(userText.toLowerCase()) || (!missingQualification(session).length && intent === "general")) {
    if (missingQualification(session).filter((k) => k === "equipment" || k === "mcOwnership").length) {
      return { text: continueFromState(session), chips: chipsFor(session) };
    }
    const task = routeTask(session);
    persistCase(session, {
      task,
      status: "awaiting_human_action",
      nextAction: task,
      event: "Human onboarding task created",
    });
    session.handedOver = true;
    session.conversationState = "handed_over";
    const extra = task === "setup_packet" ? lookupKnowledge("docsOwn") : task === "lease_agreement" ? lookupKnowledge("docsLease") : "Staff will choose the arrangement before any packet is sent.";
    return {
      text: `Human-owned ${task.replace("_", " ")} is recorded. ${extra} I do not send, sign, or approve.`,
      chips: chipsFor(session),
    };
  }

  if (intent === "mc" || intent === "lease" || intent === "general") {
    return { text: continueFromState(session), chips: chipsFor(session) };
  }

  return { text: continueFromState(session), chips: chipsFor(session) };
}
