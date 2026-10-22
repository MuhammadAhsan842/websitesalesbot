CORE_FIELDS = ["equipment", "fleetSize", "operatingArea", "mcOwnership"]

ASK_ORDER = [
    "equipment",
    "primaryProblem",
    "fleetSize",
    "operatingArea",
    "mcOwnership",
    "supportNeed",
    "startDate",
]

QUAL_FIELDS = CORE_FIELDS + ["lanes", "supportNeed", "startDate", "primaryProblem"]

FACT_KEYS = QUAL_FIELDS + ["name", "phone", "requestedArrangement"]

INTENTS = (
    "dispatch_inquiry",
    "existing_customer",
    "talk_here",
    "call_me",
    "fee",
    "guarantee",
    "freight",
    "fuel",
    "trust",
    "commit",
    "hometime",
    "human",
    "onboard",
    "lease",
    "mc",
    "mc_new",
    "service",
    "status",
    "unknown_detail",
    "decline",
    "general",
)

CATALOGUE = ("fit_check", "callback", "setup_packet", "lease_agreement", "clarification", "operations_support")

QUESTIONS = {
    "equipment": "What are you running — dry van, reefer, flatbed, box truck, or hotshot?",
    "primaryProblem": "What is making you look — rates, keeping loaded, paperwork, or home time?",
    "fleetSize": "How many trucks are on the road?",
    "operatingArea": "Where are you operating from, and which lanes do you want to keep?",
    "lanes": "Which lanes do you want to stay in?",
    "mcOwnership": "Will you run under your own MC, or are you looking to lease on under Ayyan’s authority?",
    "supportNeed": "What support matters most — home time, paperwork, or keeping the truck loaded?",
    "startDate": "When do you want to start? Unknown is fine.",
    "phone": "Confirm the callback number, preferred time, and timezone.",
}

CHIPS = {
    "open": ["I need dispatch", "What equipment do you support?", "I'm already a carrier"],
    "equipment": ["Dry van", "Reefer", "Flatbed", "Box truck", "Hotshot"],
    "primaryProblem": ["Better loads", "Home every night", "Paperwork", "Rates"],
    "mcOwnership": ["I have my own MC", "I want to lease on", "Not sure about my MC"],
    "fleetSize": ["1 truck", "2 trucks", "3 trucks", "I don't know yet"],
    "startDate": ["Next week", "I don't know yet"],
    "supportNeed": ["Home every night", "Paperwork", "Keep me loaded"],
    "handoff": ["What's my status?", "Talk here", "Call me", "Talk to a human"],
    "voice_id": ["My name is Alex Rivera"],
    "assess": ["I'm ready to start", "Talk here", "Call me", "What is the fee?", "Talk to a human"],
    "default": ["I'm ready to start", "Talk here", "Call me", "What is the fee?", "Talk to a human"],
}

STAFF_ACTS = {
    "packet_sent": ("awaiting_submissions", "Wait for returned documents", "issued"),
    "received": ("under_review", "Human review", "returned"),
    "corrections": ("corrections_requested", "Wait for replacement", None),
    "approve": ("approved_for_handoff", "Production acknowledgment", None),
    "production": ("production_accepted", "Dispatch owns the truck", None),
    "takeover": ("human_takeover", "Staff owns conversation", None),
}

EQUIP_LABELS = {
    "dry_van": "dry van",
    "reefer": "reefer",
    "flatbed": "flatbed",
    "box_truck": "box truck",
    "hotshot": "hotshot",
}
