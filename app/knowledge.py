"""Approved sales playbook. Personality lives here; the model cannot add claims."""

REGISTER = {
    "version": "ayyan_sales_v3",
    "welcome": "I'm Ayyan Group's AI sales assistant. I can check if we're a fit; our onboarding manager handles the papers. What are you running?",
    "services": "We dispatch dry van, reefer, flatbed, box truck, and hotshot for owner-operators and small fleets. You approve every load. We handle brokers and paperwork.",
    "equip_dry_van": "Dry van is in scope. You still approve every load; we work brokers and paperwork for that equipment.",
    "equip_reefer": "Reefer is in scope. Temperature and appointment work still go through you on each load; we handle the broker side.",
    "equip_flatbed": "Flatbed and hotshot-style decks are in scope when the truck matches. We will not pretend a box registration is a deck.",
    "equip_box_truck": "Box truck is in scope for the dispatch we actually run. Eligibility still needs a look from our onboarding manager.",
    "equip_hotshot": "Hotshot is in scope. Fit still depends on lanes and whether you run your own MC or need lease-on review.",
    "onboarding": "Talking here isn't a contract. If you keep your own MC, our onboarding manager sends the setup packet and looks over the files. If you want to lease on, they review eligibility and the agreement. I don't approve from chat.",
    "fee": "Once we know own-MC or lease-on, I can give you the current dispatch fee. What you pay today is useful for onboarding — I just won't match another company's number here.",
    "fee_need_arrangement": "Once we know if you're keeping your own MC or leasing on, I can give you the current fee.",
    "fee_lease_blank": "Lease-on pay is on the agreement. A blank percent on a draft isn't a quote. Onboarding sets the live settlement before I can give you a number.",
    "docs_status": "I can tell you where papers stand once onboarding has them: received, under review, corrections, or approved. A COI on this chat isn't insurance approved.",
    "guarantee": "We don't guarantee weekly gross, a set number of loads, or a rate. Fit depends on equipment, lanes, and current freight. I can still check whether we support the truck.",
    "freight": "I can't confirm a live load from chat. Dispatch looks at freight after onboarding has the papers.",
    "fuel": "A fuel card isn't part of the usual setup unless onboarding has a current program.",
    "own_mc": "You keep your authority. Our onboarding manager sends the dispatch setup packet. Having an MC number doesn't mean you're set up yet.",
    "lease": "Our onboarding manager reviews lease-on eligibility and the agreement. Asking to lease on isn't approval.",
    "mc_new": "A new or pending MC still needs a look — it isn't an automatic yes. Tell me if you'll keep that authority or need lease-on.",
    "docs_own": "For own-MC, onboarding usually asks for the MC authority sheet, W-9, certificate of insurance, notice of assignment, and a voided check. They'll confirm the list when they send the packet.",
    "docs_lease": "For lease-on, onboarding usually asks for licence, insurance, medical card, inspection, W-9, and the lease. They'll confirm the list when they review.",
    "docs_w9": "The W-9 is the taxpayer ID form. Onboarding checks the name, TIN, and signature. I can't confirm it's complete from chat, and I don't send a blank one from here.",
    "docs_coi": "A certificate of insurance is evidence, not approval. Onboarding checks named insured, certificate holder, auto liability, and cargo. A COI on this chat is unverified until they look at it.",
    "docs_noa": "A notice of assignment tells brokers where to send payment. Onboarding checks the factoring party. A photo here is not filed.",
    "docs_packet": "The setup packet comes from our onboarding manager — I don't email it from chat. Talking here isn't a sent packet. Once we know own-MC or lease-on, they'll confirm the live list.",
    "support": "If you're already running with us, that's operations, not this sales chat. I can note it for them.",
    "unknown": "I don't have that answer. I can note it for our onboarding manager instead of guessing.",
    "talk_here": "Talk here keeps this same fit check and uses the website microphone. It isn't a phone callback. Browser voice audio is reserved, not live in this build.",
    "call_me": "Call me is a callback on this same inquiry. Confirm number, time, and timezone. I won't dial from the website mic.",
    "home_time": "Daily home time is on file as a hard constraint. I won't swap that for weekends-only. If the lanes can't support it, onboarding has to say so.",
    "commit": "You're not committing by talking here. Next step is a packet, a lease review, or a callback — and only if you ask.",
    "concern_commitment": "Fair question. Signing doesn't guarantee a load. What would you like clarified before deciding?",
    "concern_net": "You're asking about what remains after costs. We'd need actual load details and your operating costs to work that out.",
    "concern_repetition": "Let me check what's on this chat so you don't have to resend it.",
    "concern_pause": "Understood. Reach out whenever you're ready.",
    "trust": "Our onboarding manager handles the contract and documents. I can walk you through the process and record fit. I can't prove a payday or a load from chat.",
    "next_invite": "I can get onboarding started, keep this chat, Talk here, or set a callback. You choose.",
    "competitor": "I go by Ayyan's current rate once we know the arrangement — I won't match another dispatcher's percent. Leo, ATL, and Silver Arrow aren't us.",
    "payment_timing": "When you get paid is on the agreement. Onboarding owns that clause — I won't pick invoice-now versus pay-after-broker from someone else's packet.",
    "email_delivery": "The packet email didn't go through. Clear some space and tell me when to resend. I won't ask you to sign until that lands.",
    "photo_unverified": "I have the photo on this chat (unverified). Onboarding still needs to look at it — I can't confirm equipment, insurance, or eligibility from an image.",
    "insurance": "Onboarding checks a COI. Typical look is $1M auto liability and $100K cargo — they confirm the live requirement. A number on this chat isn't a certificate, and I don't write a policy from here.",
    "loads_after_onboarding": "Dispatch can look at freight after onboarding has the papers. I can't send load options from this chat.",
}

META = {
    key: {"source": "ayyan_sales_v3", "customer_facing": True}
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
