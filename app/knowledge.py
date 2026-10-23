"""Approved sales playbook. Personality lives here; the model cannot add claims."""

REGISTER = {
    "version": "ayyan_sales_v1",
    "welcome": "I'm Ayyan Group's AI sales assistant. I can check dispatch fit; a person handles papers. What are you running?",
    "services": "We dispatch dry van, reefer, flatbed, box truck, and hotshot for owner-operators and small fleets. You approve every load. We handle brokers and paperwork.",
    "equip_dry_van": "Dry van is in scope. You still approve every load; we work brokers and paperwork for that equipment.",
    "equip_reefer": "Reefer is in scope. Temperature and appointment work still go through you on each load; we handle the broker side.",
    "equip_flatbed": "Flatbed and hotshot-style decks are in scope when the truck matches. We will not pretend a box registration is a deck.",
    "equip_box_truck": "Box truck is in scope for the dispatch we actually run. Eligibility still needs a human look.",
    "equip_hotshot": "Hotshot is in scope. Fit still depends on lanes and whether you run your own MC or need lease-on review.",
    "onboarding": "Talking to me is not a contract. Own-MC: a person sends the setup packet and reviews files. Lease-on: a person reviews eligibility and the agreement. I do not approve.",
    "fee": "Staff quote the live dispatch fee after the arrangement is confirmed. I will not invent a percentage, a discount, or an earnings figure. What you pay today is useful context for them — not something I match on the spot.",
    "fee_need_arrangement": "I can quote the staff-approved fee only after we confirm own-MC vs lease-on. I will not invent a number before that.",
    "fee_lease_blank": "Lease-on pay belongs on the agreement. A blank % on a draft is not a quote. Staff publish the live settlement before I can say a number.",
    "docs_status": "I only report verified document status: received, under review, corrections requested, or human-approved. A COI on file is not insurance approved.",
    "guarantee": "We do not guarantee weekly gross, a set number of loads, or a rate. Fit depends on equipment, lanes, and current freight. I can still check whether we support the truck.",
    "freight": "If “better loads” means rate, lanes, empty miles, or appointments, say which. Production reviews live freight. I will not promise a load from chat.",
    "fuel": "A fuel card is not part of the standard dispatch arrangement unless staff confirm a current program.",
    "own_mc": "Keep your authority. Staff send the dispatch setup packet. Having an MC number is not automatic eligibility.",
    "lease": "Staff confirm lease-on eligibility and the agreement. Asking to lease on is not approval.",
    "mc_new": "A new or pending MC is a review item, not an automatic yes. Tell me if you will keep that authority or need lease-on.",
    "docs_own": "Usual own-MC items: MC authority sheet, W-9, certificate of insurance, notice of assignment, voided check. Staff confirm the live list.",
    "docs_lease": "Usual lease-on items: licence, insurance, medical card, inspection, W-9, lease. Staff confirm the live list.",
    "support": "Existing-carrier issues go to the operations desk. I will not run a sales fit check on an open dispatch problem.",
    "unknown": "I do not have an approved answer for that. I can note it for the team instead of guessing.",
    "talk_here": "Talk here keeps this same fit check and uses the website microphone. It is not a phone callback. Browser voice audio is reserved, not live in this build.",
    "call_me": "Call me is a callback on this opportunity. Confirm number, time, and timezone. I will not dial from the website mic.",
    "home_time": "Daily home time is recorded as a hard constraint. I will not swap it for a weekend-home promise. If the lanes cannot support it, staff must say so.",
    "commit": "You are not committing by talking here. The next step is a human packet, a lease review, or a callback — and only if you ask for it.",
    "concern_commitment": "Fair question. Signing does not guarantee a load. What would you like clarified before deciding?",
    "concern_net": "You're asking about what remains after costs. We'd need actual load details and your operating costs to work that out.",
    "concern_repetition": "Let me check what's recorded on this chat so you don't have to resend it.",
    "concern_pause": "Understood. Reach out whenever you're ready.",
    "trust": "Staff handle contracting and documents. I can explain the process and record fit. I cannot prove a payday or a load.",
    "next_invite": "I can start the human task, keep this chat, Talk here, or set a callback. You choose.",
    "competitor": "I will not match another dispatcher’s percent or promise. Staff quote Ayyan’s live schedule only after the arrangement is known. Leo, ATL, and Silver Arrow are not Ayyan.",
    "payment_timing": "When the carrier is paid is a contract term. I will not pick invoice-now versus pay-after-broker from a sample packet. Staff own that clause.",
    "email_delivery": "The packet email did not go through. Clear space and tell me when to resend. I will not ask you to sign until that lands.",
}

META = {
    key: {"source": "ayyan_sales_v1", "customer_facing": True}
    for key in REGISTER
    if key != "version"
}

EQUIP_KEYS = {
    "dry_van": "equip_dry_van",
    "reefer": "equip_reefer",
    "flatbed": "equip_flatbed",
    "box_truck": "equip_box_truck",
    "hotshot": "equip_hotshot",
}

BLOCKED_CLAIMS = ("guarantee", "invented_fee", "load_promise", "insurance_approved", "contract_complete")


def lookup(topic: str) -> str:
    return REGISTER.get(topic) or REGISTER["unknown"]
