"""Approved sales playbook. Personality lives here; the model cannot add claims."""

REGISTER = {
    "version": "ayyan_sales_v9",
    "welcome": "Hey — I'm Ayyan Group's AI sales assistant. I can help see if we're a fit; our onboarding manager handles the papers. What are you running?",
    "services": "We dispatch box trucks 24 ft or longer, hotshot, dry van, reefer, flatbed, step deck, and power-only. You approve every load. We handle brokers and paperwork.",
    "freight_roles": "Shippers own the cargo. Brokers connect shippers with carriers and pay for completed loads. A dispatcher represents the carrier — finds matching freight, negotiates with brokers, and handles paperwork. The motor carrier runs the truck under FMCSA rules. Broker freight pay goes to the carrier's account — dispatchers don't take those payments personally.",
    "dispatch_how": "Our dispatch team helps find freight that fits your equipment and preferred lanes, handles broker communication and paperwork, and coordinates the load process. You approve each load. Talking here isn't a live load search.",
    "dispatch_vs_onboarding": "Before live dispatch, onboarding confirms fit and papers — authority, insurance, and the setup agreement. Dispatch work starts after that review. If papers aren't done, I won't pretend the truck is already in production.",
    "equip_specs": "Sizes we commonly work with: box 24–28 ft with roughly 10k–17k lb payload and lift gate or pallet jack when needed; hotshot 30–40 ft with straps, tarps, chains, and binders; dry van and reefer 48–53 ft; flatbed and step deck 48–53 ft. Exact fit still needs onboarding. Sprinter and cargo van stay out of scope.",
    "cab_driver_types": "Day cab usually fits local or shorter runs. Sleeper cab supports longer OTR. Solo versus team driving and ELD hours follow FMCSA — we don't override hours-of-service from this chat.",
    "lane_prefs": "We note OTR versus local radius, how many miles you can cover in a day, and how long you can stay out. Daily home time every night is a hard constraint when you need it — if lanes can't support it, onboarding has to say so.",
    "docs_checklist": "Before production, onboarding typically reviews licence, COI, truck registration, equipment photos, and — when factoring — a notice of assignment. Own-MC also needs authority and W-9. Files received here are unverified; dispatch starts after review, and you still approve each load.",
    "pay_to_carrier": "Broker freight payments go to the motor carrier owner's account. Dispatchers don't receive those payments into a personal account.",
    "timezone_ops": "Dispatch coordinates across US Pacific, Mountain, Central, and Eastern time. For a callback, confirm number, time, and timezone.",
    "mc_age_review": "MC age is recorded for onboarding review. A newer authority isn't an automatic yes. Tell me if you'll keep that authority or need lease-on.",
    "load_evaluate": "When dispatch evaluates a load they look at origin and destination, weight, appointments, deadhead, total trip time and cost, and your constraints — not rate-per-mile alone. I can't run that search from this chat.",
    "load_approval": "Ayyan's sequence is: a suitable option is identified, you approve it, then authorized acceptance, then confirmed instructions. We don't book a load for you without that approval.",
    "docs_rate_con_detail": "A rate confirmation records the agreed load terms — addresses, rate, appointments, and accessorials. It isn't the whole legal relationship; the dispatch agreement and carrier paperwork still matter. Signing needs the right authority on your side.",
    "accessorials": "Detention, layover, and TONU are accessorial terms on the rate confirmation or broker agreement when they apply. Dispatch handles those with the broker after you're running — I won't invent amounts from chat.",
    "trip_docs_invoice": "After delivery, BOL, POD, and related receipts support invoicing. Accurate paperwork helps payment move. Settlement timing still comes from your agreement and verified records — not from this sales chat.",
    "broker_vs_fee": "Broker freight negotiation is about the load rate. Ayyan's dispatch fee is separate and only quoted from our published schedule once we know own-MC or lease-on.",
    "equip_dry_van": "Dry van is in scope. You still approve every load; we work brokers and paperwork for that equipment.",
    "equip_reefer": "Reefer is in scope. Temperature and appointment work still go through you on each load; we handle the broker side.",
    "equip_flatbed": "Flatbed and hotshot-style decks are in scope when the truck matches. We will not pretend a box registration is a deck.",
    "equip_box_truck": "Box truck 24 ft or longer is in scope. Eligibility still needs a look from our onboarding manager.",
    "equip_box_truck_short": "We only dispatch box trucks 24 ft or longer. A shorter box is outside our current service.",
    "equip_hotshot": "Hotshot is in scope. Fit still depends on lanes and whether you run your own MC or need lease-on review.",
    "equip_sprinter_van": "We don't provide dispatch services for Sprinter or cargo vans.",
    "equip_cargo_van": "We don't provide dispatch services for cargo vans.",
    "equip_step_deck": "Step deck is in scope. Fit still depends on lanes and whether you run your own MC or need lease-on review.",
    "equip_power_only": "Power-only is in scope. Onboarding still confirms the authority path before production.",
    "equip_unsupported": "That equipment is outside the categories we dispatch. We serve box trucks 24 ft or longer, hotshot, dry van, reefer, flatbed, step deck, and power-only.",
    "onboarding": "Talking here isn't a contract. If you keep your own MC, our onboarding manager sends the setup packet and looks over the files. If you want to lease on, they review eligibility and the agreement. I don't approve from chat.",
    "fee": "Once we know own-MC or lease-on, I can give you the current dispatch fee. What you pay today is useful for onboarding — I just won't match another company's number here.",
    "fee_need_arrangement": "Once we know if you're keeping your own MC or leasing on, I can give you the current fee.",
    "fee_lease_blank": "Lease-on pay is on the agreement. A blank percent on a draft isn't a quote. Onboarding sets the live settlement before I can give you a number.",
    "docs_status": "I can tell you where papers stand once onboarding has them: received, under review, corrections, or approved. A COI on this chat isn't insurance approved.",
    "guarantee": "We don't guarantee weekly gross, a set number of loads, or a rate. Fit depends on equipment, lanes, and current freight. I can still check whether we support the truck.",
    "freight": "I can't confirm a live load from chat. Dispatch looks at freight after onboarding has the papers.",
    "fuel": "A fuel card isn't part of the usual setup. Cash or fuel advances, when operations offers them after you're running, follow the agreement — I won't invent timing from chat.",
    "own_mc": "You keep your authority. Our onboarding manager sends the dispatch setup packet. Having an MC number doesn't mean you're set up yet.",
    "lease": "Our onboarding manager reviews lease-on eligibility and the agreement. Asking to lease on isn't approval.",
    "mc_new": "A new or pending MC still needs a look — it isn't an automatic yes. Tell me if you'll keep that authority or need lease-on.",
    "docs_own": "For own-MC, onboarding usually asks for the MC authority sheet, W-9, certificate of insurance, truck registration, and equipment photos. A notice of assignment applies when you use factoring; a voided check applies for quick-pay setups. They'll confirm the live list when they send the packet.",
    "docs_review_pending": "Got it — your file is saved and waiting on onboarding review (not approved yet). While that sits, I can still help with lanes, timing, or whatever else is on your mind.",
    "payment_methods_broker": "Brokers may pay standard (often multi-week), quick-pay (faster, with a broker deduction and usually a voided check with rate con and POD), or through factoring (NOA on file). Timing and any deduction come from that arrangement and your agreement — I won't invent a payday or percent from chat.",
    "docs_lease": "For lease-on, onboarding usually asks for licence, insurance listing the proper certificate holder, medical card, inspection, W-9, and the lease. They'll confirm the list when they review.",
    "docs_w9": "The W-9 is the taxpayer ID form. Onboarding checks the name, TIN, and signature. I can't confirm it's complete from chat, and I don't send a blank one from here.",
    "docs_coi": "A certificate of insurance is evidence, not approval. Onboarding checks named insured, certificate holder, auto liability, and cargo. A COI on this chat is unverified until they look at it.",
    "docs_noa": "A notice of assignment tells brokers where to send payment when factoring is involved. Onboarding checks the factoring party. A photo here is not filed.",
    "docs_packet": "The setup packet comes from our onboarding manager — I don't email it from chat. Talking here isn't a sent packet. Once we know own-MC or lease-on, they'll confirm the live list.",
    "docs_mc": "The MC authority letter shows FMCSA interstate operating authority. Onboarding needs that sheet for own-MC setup; having an MC number in chat isn't the filed document.",
    "docs_usdot": "A USDOT number identifies the carrier for FMCSA safety and compliance. Onboarding confirms it against the authority paperwork — I won't invent a DOT from chat.",
    "docs_bol": "A bill of lading is the load receipt between shipper and carrier. Dispatch and brokers use it per shipment after you're set up — I don't issue a BOL from this sales chat.",
    "docs_rate_con": "A rate confirmation records agreed load details for one shipment. You still approve each load before authorized acceptance. It isn't the entire contract with Ayyan, and I won't invent a rate con here.",
    "docs_pod": "Proof of delivery is the signed receipt after unload. Together with the BOL it supports invoicing; operations handles that after dispatch has the truck.",
    "docs_ifta": "IFTA covers multi-jurisdiction fuel tax reporting. It's the carrier's compliance file — not something I open from chat.",
    "docs_eld": "ELD or hours-of-service logs are FMCSA driver compliance. We don't override HOS from this chat.",
    "docs_poa": "A power of attorney, when used, lets a dispatcher speak with brokers on the carrier's behalf. Onboarding confirms whether that form is part of your live packet.",
    "docs_factoring": "A factoring agreement is between you and the factor. The notice of assignment tells brokers where to pay. I won't invent advance rates from chat.",
    "support": "If you're already running with us, that's operations, not this sales chat. I can note it for them.",
    "payment_support": "I understand this is about payment. Which load or invoice does it relate to? Operations owns settlement status — I won't promise a payday from chat.",
    "unknown": "I don't have that answer. I can note it for our onboarding manager instead of guessing.",
    "talk_here": "Talk here keeps this same fit check and uses the website microphone. It isn't a phone callback. Browser voice audio is reserved, not live in this build.",
    "call_me": "Call me is a callback on this same inquiry. Confirm number, time, and timezone. I won't dial from the website mic.",
    "home_time": "Daily home time is on file as a hard constraint. I won't swap that for weekends-only. If the lanes can't support it, onboarding has to say so.",
    "commit": "You're not committing by talking here. Next step is a packet, a lease review, or a callback — and only if you ask.",
    "concern_commitment": "Totally fair — you shouldn't sign blind. Signing doesn't guarantee a load; the agreement is about how we work together, and you still approve each one. What worries you most?",
    "concern_net": "You're asking what you'd actually keep after costs — that needs real load numbers and your operating costs. I won't invent a take-home figure here.",
    "concern_repetition": "No worries — I'll stick to what's already on this chat so you don't have to repeat yourself.",
    "concern_pause": "Understood. No pressure — reach out whenever you're ready.",
    "trust": "Our onboarding manager handles the contract and documents. I can walk you through the process and keep your fit straight. I can't prove a payday or a load from chat.",
    "next_invite": "Whenever you're ready, I can get onboarding started, keep chatting here, use Talk here, or set a callback — your call.",
    "competitor": "I go by Ayyan's current rate once we know the arrangement — I won't match another dispatcher's percent. Leo, ATL, and Silver Arrow aren't us.",
    "payment_timing": "When you get paid is on the agreement. Onboarding owns that clause — I won't pick invoice-now versus pay-after-broker from someone else's packet.",
    "email_delivery": "The packet email didn't go through. Clear some space and tell me when to resend. I won't ask you to sign until that lands.",
    "photo_unverified": "I have the photo on this chat (unverified). Onboarding still needs to look at it — I can't confirm equipment, insurance, or eligibility from an image.",
    "insurance": "Onboarding checks commercial auto liability and cargo coverage on your COI — common industry ranges are often around $750,000–$1,000,000 auto liability and about $100,000 cargo, but Ayyan confirms the applicable limits for your setup. You can upload it here for review — a COI on this chat isn't insurance approved.",
    "insurance_affordability": "Understood — insurance cost is holding things up. I don't sell policies from chat. We can pause until you and the owner are ready; no pressure from me.",
    "packet_received": "Nice — you have the packet and plan to return it. On our side it still isn't signed or approved until onboarding has the returned files.",
    "negotiation": "I can record the terms you proposed for onboarding to review. A number in chat isn't an agreed rate until they publish it.",
    "loads_after_onboarding": "Dispatch can look at freight after onboarding has the papers. I can't send load options from this chat.",
    "missing_equipment": "I'll keep what you have today separate from anything you're still buying. A planned purchase isn't a truck on the road yet — what are you running right now?",
    "fuel_requirement": "If you need funding before pickup, that's a real blocker — different from faster pay after delivery. I won't invent a fuel program from chat; we should sort that with the team before calling you ready.",
    "deferred": "Starting later is fine — I'll stop pushing. Reach out when you're ready; I won't invent a follow-up schedule.",
    "human_progress": "Happy to keep this useful without rushing you to sign. Accurate next steps beat a forced close.",
    "expired_demand": "Understood—thanks for the update. I won't treat that old request as current, and I won't keep qualifying it.",
    "existing_dispatcher": "Understood. Thanks for letting me know — I hope the arrangement works well for you. I won't push a switch unless you want to talk about one.",
    "privacy_boundary": "You're right—that was more than I needed to ask. I'm sorry for overstepping. You don't need to share that; I'll leave it there.",
    "apology_no_pitch": "I understand. You don't need to share that information — no pitch from me.",
    "voluntary_return": "Of course. What has changed, and what help are you looking for now?",
    "compound_competitor_fee": "Thanks for explaining. I'll note that as what you were told — not verified competitor policy and not an Ayyan offer. I won't match or undercut it from chat.",
}

META = {
    key: {"source": "ayyan_sales_v9", "customer_facing": True}
    for key in REGISTER
    if key != "version"
}

EQUIP_KEYS = {
    "dry_van": "equip_dry_van",
    "reefer": "equip_reefer",
    "flatbed": "equip_flatbed",
    "box_truck": "equip_box_truck",
    "hotshot": "equip_hotshot",
    "sprinter_van": "equip_sprinter_van",
    "cargo_van": "equip_cargo_van",
    "step_deck": "equip_step_deck",
    "power_only": "equip_power_only",
}

SUPPORTED_EQUIPMENT = frozenset(
    {"dry_van", "reefer", "flatbed", "box_truck", "hotshot", "step_deck", "power_only"}
)
UNSUPPORTED_EQUIPMENT = frozenset({"sprinter_van", "cargo_van"})
BOX_MIN_FT = 24

BLOCKED_CLAIMS = ("guarantee", "invented_fee", "load_promise", "insurance_approved", "contract_complete")


def lookup(topic: str) -> str:
    return REGISTER.get(topic) or REGISTER["unknown"]
