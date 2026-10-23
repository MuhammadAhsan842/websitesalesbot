"""Named reply variants. Qwen may pick an id; code fills the approved sentence."""

from app.knowledge import lookup
from app.schema import VARIANTS

VARIANT_KEYS = {
    "welcome": "welcome",
    "answer_services": "services",
    "answer_fee": "fee",
    "answer_fee_need_mc": "fee_need_arrangement",
    "answer_guarantee": "guarantee",
    "explain_commitment": "concern_commitment",
    "explain_net": "concern_net",
    "repair_repetition": "concern_repetition",
    "pause": "concern_pause",
    "clarify_mc": "mc_new",
    "qualify_next": "welcome",
    "offer_handoff": "next_invite",
    "route_operations": "support",
    "ack_constraints": "home_time",
    "email_delivery": "email_delivery",
}


def text_for(variant_id: str | None) -> str | None:
    if variant_id not in VARIANTS:
        return None
    key = VARIANT_KEYS.get(variant_id)
    return lookup(key) if key else None


def default_move(intent: str | None, repair: str | None, concern: str | None, next_field: str | None) -> str:
    if repair == "email_delivery" or concern == "email_delivery":
        return "acknowledge"
    if repair == "authority_uncertain":
        return "clarify"
    if repair == "leave_sales" or intent in {"existing_customer", "human", "call_me", "talk_here"}:
        return "offer_handoff"
    if concern == "pause" or intent == "decline":
        return "pause"
    if concern in {"commitment", "net_after_costs"}:
        return "explain_objection"
    if intent in {"fee", "guarantee", "service", "freight"} or repair == "topic_fee":
        return "answer"
    if next_field:
        return "qualify"
    return "acknowledge"


def default_variant(move: str | None, concern: str | None, intent: str | None, repair: str | None) -> str:
    if move == "pause" or concern == "pause":
        return "pause"
    if repair == "email_delivery" or concern == "email_delivery":
        return "email_delivery"
    if repair == "leave_sales" or intent == "existing_customer":
        return "route_operations"
    if repair == "authority_uncertain" or move == "clarify":
        return "clarify_mc"
    if concern == "commitment":
        return "explain_commitment"
    if concern == "net_after_costs":
        return "explain_net"
    if concern == "repetition":
        return "repair_repetition"
    if concern == "total_fees":
        return "answer_fee"
    if concern == "guarantee" or intent == "guarantee":
        return "answer_guarantee"
    if intent == "service":
        return "answer_services"
    if move == "offer_handoff":
        return "offer_handoff"
    if move == "qualify":
        return "qualify_next"
    return "answer_services"
