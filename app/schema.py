CORE_FIELDS = ["equipment", "operatingArea", "mcOwnership"]

ASK_ORDER = [
    "equipment",
    "trailerLength",
    "mcOwnership",
    "insurance",
    "coverageTypes",
    "authorityAgeMonths",
    "operatingMode",
    "milesPerDay",
    "stayOutDuration",
    "weekdaySchedule",
    "operatingArea",
    "startDate",
]

QUAL_FIELDS = CORE_FIELDS + ["lanes", "supportNeed", "startDate", "primaryProblem", "trailerLength", "insurance", "operatingMode"]

EXTRA_FIELDS = [
    "payload",
    "preferredPayload",
    "rejectedLoadWeight",
    "liftgate",
    "liftgateLoadPreference",
    "palletJack",
    "accessories",
    "cargoCoverage",
    "autoLiabilityCoverage",
    "coverageTypes",
    "paymentArrangement",
    "authorityAgeMonths",
    "equipmentSupport",
    "secondaryEquipment",
    "deadline",
    "commitmentStance",
    "weekdaySchedule",
    "milesPerDay",
    "stayOutDuration",
    "fleetSize",
    "requestedFeePercent",
    "requestedWeeklyCap",
    "insuranceRoute",
]

FACT_KEYS = QUAL_FIELDS + [
    "name",
    "phone",
    "requestedArrangement",
    "callbackTime",
    "callbackTimezone",
] + EXTRA_FIELDS

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
    "payment_support",
    "insurance",
    "negotiation",
    "dispatch_how",
    "load_approval",
    "accessorials",
    "equip_specs",
    "freight_roles",
    "broker_pay",
    "lane_prefs",
    "fuel_requirement",
    "expired_demand",
    "existing_dispatcher",
    "privacy_boundary",
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

CATALOGUE = (
    "fit_check",
    "callback",
    "setup_packet",
    "lease_agreement",
    "insurance_quote",
    "clarification",
    "operations_support",
)

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
    "phone": (
        "What number should our onboarding manager call? Please include the country code if you have one, "
        "plus a preferred time and timezone."
    ),
    "trailerLength": "What length trailer or box are you running?",
    "payload": "What payload do you need to haul?",
    "liftgate": "Do you need a liftgate?",
    "operatingMode": "Do you prefer OTR or staying local?",
    "insurance": "Do you currently have your own insurance on the truck?",
    "coverageTypes": "What coverage does your policy include — commercial auto, cargo, or both?",
    "authorityAgeMonths": "About how old is your MC or authority?",
    "weekdaySchedule": "Are you able to stay on the road Monday through Friday, with weekends at home?",
    "milesPerDay": "How many miles can you cover in a day?",
    "stayOutDuration": "How long are you comfortable staying out before returning home?",
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
    "trailerLength": ["24 ft", "26 ft", "28 ft", "30 ft", "40 ft", "48 ft", "53 ft"],
    "insurance": ["I have my own insurance", "I need insurance", "Not sure yet"],
    "coverageTypes": ["Auto + cargo", "Commercial auto", "Cargo", "Not sure yet"],
    "authorityAgeMonths": ["Under 3 months", "About 5 months", "1 year+", "Not sure"],
    "weekdaySchedule": ["Monday through Friday", "Home weekends", "Flexible"],
    "milesPerDay": ["400-500", "500-600", "I don't know yet"],
    "stayOutDuration": ["Home weekends", "1-2 weeks out", "Flexible", "Not sure yet"],
    "handoff": ["What's my status?", "Talk here", "Call me", "Talk to onboarding manager"],
    "voice_id": ["My name is Alex Rivera"],
    "assess": ["I'm ready to start", "Talk here", "Call me", "What is the fee?", "Talk to onboarding manager"],
    "default": ["I'm ready to start", "Talk here", "Call me", "What is the fee?", "Talk to onboarding manager"],
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
    "sprinter_van": "Sprinter van",
    "cargo_van": "cargo van",
    "step_deck": "step deck",
    "power_only": "power only",
}

# Structured meanings for chip labels (and matching free text). Parser uses these first.
CHIP_VALUES: dict[str, dict] = {
    "auto + cargo": {"coverageTypes": "auto_and_cargo", "autoLiabilityCoverage": "present", "cargoCoverage": "present"},
    "commercial auto": {"coverageTypes": "auto", "autoLiabilityCoverage": "present"},
    "750k / 1m auto": {"coverageTypes": "auto", "autoLiabilityCoverage": "present"},
    "cargo": {"coverageTypes": "cargo", "cargoCoverage": "present"},
    "cargo ~$100k": {"coverageTypes": "cargo", "cargoCoverage": "present"},
    "under 3 months": {"authorityAgeMonths": 2},
    "about 5 months": {"authorityAgeMonths": 5},
    "1 year+": {"authorityAgeMonths": 12},
    "400-500": {"milesPerDay": "400-500"},
    "500-600": {"milesPerDay": "500-600"},
    "otr": {"operatingMode": "otr"},
    "local work": {"operatingMode": "local"},
    "i have my own insurance": {"insurance": "own_insurance"},
    "yes, i have insurance": {"insurance": "own_insurance"},
    "yes i have insurance": {"insurance": "own_insurance"},
    "i need insurance": {"insurance": "needs_insurance"},
    "i have my own mc": {"mcOwnership": "own_mc", "requestedArrangement": "dispatch_service"},
    "i want to lease on": {"mcOwnership": "no_own_mc", "requestedArrangement": "lease_on"},
    "not sure about my mc": {"mcOwnership": "unclear", "requestedArrangement": "needs_clarification"},
    "home weekends": {"stayOutDuration": "home_weekends", "weekdaySchedule": "flexible"},
    "1-2 weeks out": {"stayOutDuration": "1-2 weeks"},
}

# Widget / model may send legacy field names; map to FACT_KEYS.
CHIP_FIELD_ALIASES = {
    "authority": "mcOwnership",
    "mc": "mcOwnership",
    "trailerLengthFt": "trailerLength",
    "trailer_length": "trailerLength",
    "length": "trailerLength",
    "coverage": "coverageTypes",
    "local_or_otr": "operatingMode",
    "truck_age_years": "authorityAgeMonths",
}

# Soft chip values → canonical fact values.
CHIP_VALUE_NORMALIZE = {
    "insurance": {
        "yes": "own_insurance",
        "y": "own_insurance",
        "true": "own_insurance",
        "own": "own_insurance",
        "have": "own_insurance",
        "own_insurance": "own_insurance",
        "no": "needs_insurance",
        "n": "needs_insurance",
        "false": "needs_insurance",
        "need": "needs_insurance",
        "needs_insurance": "needs_insurance",
    },
    "mcOwnership": {
        "yes": "own_mc",
        "own": "own_mc",
        "own_mc": "own_mc",
        "no": "no_own_mc",
        "lease": "no_own_mc",
        "lease_on": "no_own_mc",
        "no_own_mc": "no_own_mc",
        "unclear": "unclear",
    },
    "operatingMode": {
        "local": "local",
        "otr": "otr",
        "over the road": "otr",
    },
}


def length_chip_labels(equipment: str | None) -> list[str]:
    """Length chips must match EQUIPMENT_LENGTHS_FT — never show van lengths for a box truck."""
    from app.knowledge import EQUIPMENT_LENGTHS_FT

    allowed = EQUIPMENT_LENGTHS_FT.get(str(equipment or ""))
    if not allowed:
        return list(CHIPS.get("trailerLength") or [])
    return [f"{n} ft" for n in sorted(allowed)]


def chip_options(field: str | None, facts: dict | None = None) -> list[dict]:
    """API chip payloads: label for display, field+value for reliable submission."""
    if not field:
        return [{"label": label, "field": None, "value": label} for label in CHIPS.get("default") or []]
    if field == "trailerLength":
        equip = None
        if isinstance(facts, dict):
            item = facts.get("equipment")
            if isinstance(item, dict):
                equip = item.get("value")
            elif item:
                equip = item
        labels = length_chip_labels(equip)
    else:
        labels = CHIPS.get(field) or CHIPS.get("default") or []
    out = []
    for label in labels:
        mapped = CHIP_VALUES.get(label.lower(), {})
        value = mapped.get(field)
        if value is None and field == "trailerLength":
            digits = "".join(ch for ch in label if ch.isdigit())
            value = f"{digits}ft" if digits else label
        if value is None and mapped:
            value = mapped.get("coverageTypes") or mapped.get("operatingMode") or next(iter(mapped.values()), label)
        payload = {"label": label, "field": field, "value": value if value is not None else label}
        for key in ("autoLiabilityCoverage", "cargoCoverage", "requestedArrangement"):
            if key in mapped:
                payload[key] = mapped[key]
        out.append(payload)
    return out
