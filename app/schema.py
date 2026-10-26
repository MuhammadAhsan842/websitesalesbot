CORE_FIELDS = ["equipment", "operatingArea", "mcOwnership"]

ASK_ORDER = [
    "equipment",
    "trailerLength",
    "mcOwnership",
    "insurance",
    "operatingMode",
    "weekdaySchedule",
    "milesPerDay",
    "operatingArea",
    "startDate",
]

QUAL_FIELDS = CORE_FIELDS + ["lanes", "supportNeed", "startDate", "primaryProblem", "trailerLength", "insurance", "operatingMode"]

EXTRA_FIELDS = ["payload", "liftgate", "deadline", "commitmentStance", "weekdaySchedule", "milesPerDay", "fleetSize"]

FACT_KEYS = QUAL_FIELDS + ["name", "phone", "requestedArrangement"] + EXTRA_FIELDS

MOVES = (
    "acknowledge",
    "answer",
    "clarify",
    "qualify",
    "explain_objection",
    "offer_handoff",
    "pause",
)

ANSWER_TOPICS = (
    "dispatch_fee",
    "commitment",
    "guarantee",
    "home_time",
    "services",
    "onboarding",
    "own_mc",
    "lease",
    "support",
    "email_delivery",
    "docs_status",
    "freight",
    "competitor",
    "net_after_costs",
    "talk_here",
    "call_me",
    "pause",
)

PERMITTED_ACTIONS = ("none", "create_case", "callback", "talk_here", "takeover")

VARIANTS = (
    "welcome",
    "answer_services",
    "answer_fee",
    "answer_fee_need_mc",
    "answer_guarantee",
    "explain_commitment",
    "explain_net",
    "repair_repetition",
    "pause",
    "clarify_mc",
    "qualify_next",
    "offer_handoff",
    "route_operations",
    "ack_constraints",
    "email_delivery",
)

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
    "equipment": "What type of truck do you have?",
    "primaryProblem": "What is making you look — rates, keeping loaded, paperwork, or home time?",
    "fleetSize": "How many trucks are on the road?",
    "operatingArea": "Where are you operating from, and which city or ZIP?",
    "lanes": "Which lanes do you want to stay in?",
    "mcOwnership": "Do you currently have your own MC, or are you looking to lease on?",
    "supportNeed": "What support matters most — home time, paperwork, or keeping the truck loaded?",
    "startDate": "When would you like to start?",
    "deadline": "When do you need to be rolling?",
    "phone": "Confirm the callback number, preferred time, and timezone.",
    "trailerLength": "What length trailer or box are you running?",
    "payload": "What payload do you need to haul?",
    "liftgate": "Do you need a liftgate?",
    "operatingMode": "Do you prefer OTR, or staying local?",
    "insurance": "Do you currently have your own insurance on the truck?",
    "weekdaySchedule": "Are you able to stay on the road Monday through Friday?",
    "milesPerDay": "About how many miles can you cover in a day?",
}

CHIPS = {
    "open": ["I need dispatch", "What equipment do you support?", "I'm already a carrier"],
    "equipment": ["Dry van", "Reefer", "Flatbed", "Box truck", "Hotshot"],
    "primaryProblem": ["Better loads", "Home every night", "Paperwork", "Rates"],
    "mcOwnership": ["I have my own MC", "I want to lease on", "Not sure about my MC"],
    "fleetSize": ["1 truck", "2 trucks", "3 trucks", "I don't know yet"],
    "startDate": ["Next week", "I don't know yet"],
    "supportNeed": ["Home every night", "Paperwork", "Keep me loaded"],
    "deadline": ["Monday", "Next week", "I don't know yet"],
    "liftgate": ["Liftgate yes", "No liftgate"],
    "operatingMode": ["OTR", "Local work"],
    "trailerLength": ["26 ft", "40 ft", "48 ft", "53 ft"],
    "insurance": ["I have my own insurance", "I need insurance", "Not sure yet"],
    "weekdaySchedule": ["Monday through Friday", "Home weekends", "Flexible"],
    "milesPerDay": ["400-500", "500-600", "I don't know yet"],
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
    "takeover": ("human_takeover", "Onboarding manager owns conversation", None),
}

EQUIP_LABELS = {
    "dry_van": "dry van",
    "reefer": "reefer",
    "flatbed": "flatbed",
    "box_truck": "box truck",
    "hotshot": "hotshot",
}
