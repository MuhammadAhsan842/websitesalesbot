"""MD behavior pack → strategy cards for retrieval. Not fee policy; not case packets."""

from __future__ import annotations

import json
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent.parent / "notes-extract" / "behavior"
CARDS_PATH = PACK_DIR / "policy_cards.jsonl"

# Conversation-pack success patterns (de-identified). Strategy only — never copy case facts.
REF_EXAMPLES = (
    {
        "id": "ref_cargo_then_box",
        "source": "conversation_reference_pack",
        "tags": ("unsupported", "cargo_van", "box_truck", "answer"),
        "situation": "Unsupported cargo van, then a supported box truck",
        "strategy": "Refuse the van clearly and stop qualifying it. When a supported truck appears, switch focus without replaying the greeting or asking insurance for the van.",
        "pattern": "We don't dispatch cargo vans. Happy to talk about your box truck — own MC or lease-on?",
        "context": "Driver mentioned cargo van then 26-ft box",
        "user": "Cargo van. I also have a 26-ft box truck.",
        "move": "answer",
        "variant": "answer_services",
        "reply": "We don't provide dispatch services for cargo vans. We can discuss the box truck — will you run it under your own MC or lease on?",
    },
    {
        "id": "ref_bundled_facts",
        "source": "conversation_reference_pack",
        "tags": ("qualify", "bundled", "acknowledge"),
        "situation": "Several fit facts in one message",
        "strategy": "Keep every explicit fact. Ask only the next unanswered useful question. Do not re-ask truck type, length, or MC. Stated insurance is not verified coverage.",
        "pattern": "Got the truck and MC on file — ask one next slot only.",
        "context": "26-ft box, liftgate, own MC, insurance, Dallas, regional → re-ask OTR vs local",
        "user": "I have a 26-ft box truck with a liftgate. Own MC, insurance, based in Dallas. I want regional work.",
        "move": "qualify",
        "variant": "qualify_next",
        "reply": "Got it — 26-ft box with liftgate, own MC, insurance on file, Dallas. We work OTR or local — which do you prefer?",
    },
    {
        "id": "ref_insurance_before_qualify",
        "source": "conversation_reference_pack",
        "tags": ("insurance", "answer", "explain_objection"),
        "situation": "Driver asks commercial vs cargo before lanes",
        "strategy": "Answer the coverage question first. Keep uncertainty as uncertainty. Do not invent numerical limits unless approved policy supplies them.",
        "pattern": "They're separate coverages — onboarding checks each on the COI.",
        "context": "Commercial and cargo question mid-qualify",
        "user": "I have insurance. Do you need commercial and cargo both?",
        "move": "answer",
        "variant": "answer_services",
        "reply": "They're separate coverages. Onboarding checks each against your arrangement; the COI shows the details. Until it's reviewed, we keep that unconfirmed.",
    },
    {
        "id": "ref_upload_pending_review",
        "source": "conversation_reference_pack",
        "tags": ("documents", "acknowledge", "review_pending"),
        "situation": "Upload saved; human review pending",
        "strategy": "Receipt is not approval. Keep helping with preferences and process while review is pending. Do not invent a reviewer deadline or claim someone is reading it now.",
        "pattern": "Saved and awaiting review — we can still sort lanes while that sits.",
        "context": "Driver uploaded insurance",
        "user": "I uploaded my insurance. Can we discuss where I want to run?",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "The file is saved and awaiting review — that's not approval yet. Sure, which areas would you like to stay in?",
    },
    {
        "id": "ref_pending_authority_urgency",
        "source": "conversation_reference_pack",
        "tags": ("new_mc", "lease", "registration", "clarify"),
        "situation": "Pending MC, missing registration, wants to start fast",
        "strategy": "Urgency does not clear eligibility. Keep authority, arrangement, registration, and local preference as separate facts. Temporary tags need human review.",
        "pattern": "Pending authority and registration still need review — local preference doesn't replace that.",
        "context": "Lease-on interest while MC pending; temporary tag",
        "user": "My MC hasn't come through yet. Can I lease on for now? I'm also waiting for registration. I only want local loads.",
        "move": "clarify",
        "variant": "clarify_mc",
        "reply": "Lease-on needs review and an agreement — we can explore that while authority is pending. Registration is still outstanding; a temporary tag alone isn't enough for me to confirm. Local preference is noted, and it doesn't clear those document checks.",
    },
    {
        "id": "ref_fuel_blocker",
        "source": "conversation_reference_pack",
        "tags": ("fuel", "blocker", "explain_objection"),
        "situation": "Fuel advance required before pickup",
        "strategy": "Treat required pre-pickup funding as a real blocker. Do not swap it for quick-pay-after-delivery. Do not invent a fuel program from chat history.",
        "pattern": "If you need diesel money before pickup, we have to resolve that before calling you ready.",
        "context": "Driver cannot start without fuel advance",
        "user": "Do you offer a fuel advance? I can't start without diesel money.",
        "move": "explain_objection",
        "variant": "explain_objection",
        "reply": "If you need funding before pickup, that's different from faster pay after delivery. I don't have a confirmed advance program on this inquiry, so we shouldn't treat you as ready until that's sorted with the team.",
    },
    {
        "id": "ref_sign_for_nothing",
        "source": "conversation_reference_pack",
        "tags": ("commitment_concern", "explain_objection"),
        "situation": "Agreement concern before signing",
        "strategy": "Hear the value concern. Signing does not guarantee a load. Do not invent cancellation/refund terms. Clarify what the agreement actually covers before pushing a signature.",
        "pattern": "Fair — signing doesn't guarantee a load. What worries you most about the agreement?",
        "context": "Doesn't want to sign blindly",
        "user": "I don't want to sign for nothing. What if you don't find me a load?",
        "move": "explain_objection",
        "variant": "explain_commitment",
        "reply": "Fair question. Signing doesn't mean a particular load is waiting. The agreement covers how we work together; you still approve each load. What would you like clarified before deciding?",
    },
    {
        "id": "ref_weight_rejection",
        "source": "conversation_reference_pack",
        "tags": ("payload", "acknowledge", "dispatch"),
        "situation": "Rejected offered weight, preferred range stated",
        "strategy": "Keep offered weight, rejected weight, preferred range, and verified capacity separate. Never store a rejected offer as verified payload.",
        "pattern": "Got it — that weight is too heavy; note the range you're comfortable with.",
        "context": "8500 too heavy; prefers 7000-7500",
        "user": "8,500 pounds is too much for my trailer. Seven thousand to seven five hundred.",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Understood — 8,500 lb is too heavy for you. I'll note you want options around 7,000–7,500 lb.",
    },
    {
        "id": "ref_payme_support",
        "source": "conversation_reference_pack",
        "tags": ("payment_support", "leave_sales"),
        "situation": "Payment request after dispatch talk",
        "strategy": "Leave sales qualification. Identify the load/invoice. Do not read 'please' as lease-on. Do not promise a payday from chat.",
        "pattern": "This sounds like payment support — which load or invoice?",
        "context": "Please payme",
        "user": "Please, I need you to payme.",
        "move": "offer_handoff",
        "variant": "offer_handoff",
        "reply": "I understand this is about payment. Which load or invoice does it relate to? Operations owns settlement status — I won't promise a payday from chat.",
    },
    {
        "id": "ref_future_purchase",
        "source": "conversation_reference_pack",
        "tags": ("missing_equipment", "acknowledge"),
        "situation": "Current short equipment vs future purchase",
        "strategy": "Assess what they have today. A future purchase is not on the road. Do not invent a hotshot length minimum from box-truck rules.",
        "pattern": "We'll assess the setup you have today — a planned purchase stays separate.",
        "context": "20-ft now, might buy 30-ft later",
        "user": "I have a 20-ft trailer now. I might buy a 30-ft one later. I can't buy another until I find work.",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "I'll keep today's trailer and any planned purchase separate. The setup you have now is what we should assess — a future buy isn't equipment on the road yet.",
    },
    {
        "id": "ref_insurance_pause",
        "source": "conversation_reference_pack",
        "tags": ("insurance_affordability", "pause"),
        "situation": "Owner waits on insurance cost",
        "strategy": "Preserve the affordability blocker and pause. 'Si' confirms the pause — it does not mean coverage is active. Do not tack on another qualify question.",
        "pattern": "Understood — we can resume when you and the owner are ready.",
        "context": "Insurance too expensive; owner will wait; Si",
        "user": "The owner says insurance costs too much. He wants to wait. Si",
        "move": "pause",
        "variant": "pause",
        "reply": "Understood — insurance cost is holding things up. Reach out whenever you and the owner are ready.",
    },
    {
        "id": "ref_success_not_force_sign",
        "source": "conversation_reference_pack",
        "tags": ("success", "pause", "behave"),
        "situation": "Success is accurate progress, not forced close",
        "strategy": "A clear unsupported answer, an honest blocker, a respected pause, or a corrected misunderstanding can be success. Do not pressure every prospect to sign.",
        "pattern": "Helpful accurate progress beats forcing a signature.",
        "context": "Staff coaching on success definition",
        "user": "Maybe later, I need to think about the agreement.",
        "move": "pause",
        "variant": "pause",
        "reply": "Totally fine. Take the time you need on the agreement — I'm here when you want to pick it back up.",
    },
)

# Case T01 / DOCUMENT 2 — expired demand, existing dispatcher, privacy (no historical prices).
T01_EXAMPLES = (
    {
        "id": "t01_expired_requirement",
        "source": "ayyan_scenarios_t01",
        "tags": ("expired_demand", "close", "pause"),
        "situation": "Original Facebook/load request is no longer current",
        "strategy": "Acknowledge the requirement expired. Stop qualification for that old need. Do not promise consistent loads or start MC/insurance probing. Closing courteously is success.",
        "pattern": "Understood—thanks for letting me know. I won't treat that old request as current.",
        "context": "Need was for a previous day; help no longer needed",
        "user": "Not anymore. That was for last Friday.",
        "move": "pause",
        "variant": "pause",
        "reply": "Understood—thanks for letting me know. I won't treat that old request as current.",
    },
    {
        "id": "t01_existing_dispatcher",
        "source": "ayyan_scenarios_t01",
        "tags": ("existing_dispatcher", "close", "competitor"),
        "situation": "Prospect already hired another dispatcher",
        "strategy": "Acknowledge without challenging. Do not ask what they charge or pitch a switch unless they express dissatisfaction. End active qualification for the original inquiry.",
        "pattern": "Understood. Thanks for the update—I hope the arrangement works well for you.",
        "context": "Already hired a dispatcher; no switching interest stated",
        "user": "Already hired a dispatcher.",
        "move": "pause",
        "variant": "pause",
        "reply": "Understood. Thanks for the update, and I hope the arrangement works well for you.",
    },
    {
        "id": "t01_unhappy_with_dispatcher",
        "source": "ayyan_scenarios_t01",
        "tags": ("existing_dispatcher", "switching", "explain_objection"),
        "situation": "Has a dispatcher but is unhappy",
        "strategy": "Dissatisfaction changes the situation. Explore what they want handled differently. Do not open with earnings questions or reuse old competitor fees.",
        "pattern": "What would you want handled differently?",
        "context": "Hired someone but unhappy with service",
        "user": "I hired someone, but I'm unhappy with the service.",
        "move": "clarify",
        "variant": "clarify_mc",
        "reply": "Sorry it's not working out. What is the main issue you're hoping to resolve?",
    },
    {
        "id": "t01_compound_competitor_fee",
        "source": "ayyan_scenarios_t01",
        "tags": ("competitor", "negotiation", "acknowledge"),
        "situation": "Customer reports a compound competitor fee",
        "strategy": "Attribute to the prospect. Keep fixed and percent components distinct. Do not publish as verified competitor policy or match/undercut. Do not ask earnings unless needed for a comparison they requested.",
        "pattern": "Thanks for explaining—I'll treat that as what you were told, not verified policy.",
        "context": "Customer volunteered a fixed-plus-percent fee description",
        "user": "They charge a flat fee per load plus a percent.",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Thanks for explaining. I'll note that as what you were told—not something I'll treat as verified competitor policy or an Ayyan offer.",
    },
    {
        "id": "t01_privacy_boundary",
        "source": "ayyan_scenarios_t01",
        "tags": ("privacy", "trust", "close"),
        "situation": "Prospect objects to private business / earnings questions",
        "strategy": "Acknowledge the boundary, apologize briefly, stop probing. Do not attach an earnings pitch or ask the same question differently. Preserve closed-outreach state.",
        "pattern": "You're right—I'm sorry for overstepping. You don't need to share that.",
        "context": "Question felt private and sensitive",
        "user": "I don't know you, and that's private business information.",
        "move": "pause",
        "variant": "pause",
        "reply": "You're right—that was more information than I needed to ask for. I'm sorry for overstepping. You don't need to share that; I'll leave it there.",
    },
    {
        "id": "t01_apology_no_pitch",
        "source": "ayyan_scenarios_t01",
        "tags": ("privacy", "apology", "close"),
        "situation": "Apology after intrusive question must not become another pitch",
        "strategy": "Repair only. No consistent-loads promise, no weekly-gross figure, no immediate callback ask. Ending respectfully is success.",
        "pattern": "I understand. You don't need to share that information.",
        "context": "After a privacy objection",
        "user": "Why are you asking how much I make?",
        "move": "pause",
        "variant": "pause",
        "reply": "You're right to call that out. You don't need to share that—I'll leave the sales pitch there.",
    },
    {
        "id": "t01_voluntary_return",
        "source": "ayyan_scenarios_t01",
        "tags": ("reopen", "switching", "qualify"),
        "situation": "Prospect returns voluntarily after earlier closure",
        "strategy": "Reopen because they initiated. Confirm the new need. Revalidate stale facts. Preserve earlier privacy boundary. Do not reuse old competitor numbers or start with earnings questions.",
        "pattern": "Of course. What has changed, and what help are you looking for now?",
        "context": "Situation changed; considering switching",
        "user": "My situation changed. Can we talk about dispatch? I'm considering switching.",
        "move": "clarify",
        "variant": "qualify_next",
        "reply": "Of course. What has changed, and what would you want handled differently this time?",
    },
    {
        "id": "t01_formatting_hygiene",
        "source": "ayyan_scenarios_t01",
        "tags": ("formatting", "identity", "close"),
        "situation": "Representative change and outbound text quality",
        "strategy": "Use approved Ayyan identity. Preserve prior outcome. Strip list numbers, placeholders, and editing debris before delivery. Do not restart an ended inquiry just because a new rep is assigned.",
        "pattern": "Keep approved identity; remove formatting debris; preserve closure.",
        "context": "Staff continuity / outbound hygiene coaching",
        "user": "still looking for loads?",
        "move": "pause",
        "variant": "pause",
        "reply": "I'll stick with what's already on this inquiry—if your situation has changed and you want to talk again, just say so.",
    },
    {
        "id": "pers_answer_before_qualify",
        "source": "ayyan_behaviour_001",
        "tags": ("personality", "answer", "insurance"),
        "situation": "Answer the current question before more qualification",
        "strategy": "Answer what they asked first. Do not append unrelated policy paragraphs. Only then ask one necessary next question if useful.",
        "pattern": "Answer first, then one useful next step.",
        "context": "DOCUMENT 1 personality / model-led conversation",
        "user": "Do you need commercial and cargo both?",
        "move": "answer",
        "variant": "answer_services",
        "reply": "They're separate coverages—onboarding checks each on the COI for your arrangement. Until reviewed, we keep that unconfirmed.",
    },
    {
        "id": "pers_success_includes_closure",
        "source": "ayyan_behaviour_001",
        "tags": ("personality", "success", "close"),
        "situation": "Successful outcomes include respectful closure",
        "strategy": "A sale is not required. Clear unsupported answers, identified blockers, respected pauses, and courteously closed expired inquiries are successful handling.",
        "pattern": "Accurate helpful progress beats forcing a close.",
        "context": "DOCUMENT 1 appropriate successful outcomes",
        "user": "I don't need help anymore.",
        "move": "pause",
        "variant": "pause",
        "reply": "Understood—thanks for letting me know. I'll leave it there.",
    },
)


def load_policy_cards() -> list[dict]:
    if not CARDS_PATH.exists():
        return []
    rows = []
    for line in CARDS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def cards_as_examples() -> list[dict]:
    """Map published policy cards into the examples search shape."""
    out = []
    for card in load_policy_cards():
        if (card.get("status") or "") != "published":
            continue
        triggers = card.get("triggers") or []
        avoid = card.get("avoid") or []
        behavior = (card.get("behavior") or "").strip()
        reply = (card.get("illustrative_reply") or "").strip()
        if not behavior:
            continue
        # Pattern/situation stay generic — illustrative replies often contain lengths/cities.
        pattern = behavior.split(".")[0][:160]
        out.append(
            {
                "id": f"card_{card.get('id')}",
                "source": "policy_cards_md",
                "tags": tuple(
                    {
                        "behavior",
                        str(card.get("category") or "guidance"),
                        *[str(t).replace(" ", "_")[:32] for t in triggers[:6]],
                    }
                ),
                "situation": card.get("title") or card.get("id"),
                "strategy": behavior,
                "pattern": pattern,
                "context": f"Applies when: {', '.join(triggers[:8])}. Avoid: {'; '.join(avoid[:4])}",
                "user": " ".join(triggers[:6]) or (card.get("title") or ""),
                "move": _move_for(card),
                "variant": None,
                "reply": reply or behavior[:220],
                "status": "published",
                "version": card.get("version") or 1,
            }
        )
    return out


def _move_for(card: dict) -> str:
    cat = (card.get("category") or "").lower()
    title = (card.get("title") or "").lower()
    if "pause" in title or cat == "fuel" and "advance" in title:
        return "explain_objection"
    if cat in {"objection", "fuel"}:
        return "explain_objection"
    if cat in {"insurance", "documents", "company_policy"}:
        return "answer"
    if cat in {"qualification", "interpretation", "authority", "onboarding", "equipment"}:
        return "qualify"
    if cat == "conversation":
        return "acknowledge"
    return "acknowledge"
