"""Reviewed conversation examples. Separate from the fee register and from case packets."""

from __future__ import annotations

import math
import re

TOKEN = re.compile(r"[a-z0-9]+")
LEAK = re.compile(
    r"6\s*%|8\s*%|15\s*%|16\s*%|18\s*%|loads tomorrow|\$\s*\d|onboard in 30|reserved slot|"
    r"silver arrow|we can provide (you with )?mc|make \$\d|two slots left",
    re.I,
)

# Reviewed, de-identified situations from Union / Jason / Moses / Ezequiel.
# Driver wording is kept; replies are rewritten. Fees and load promises stay out.
BANK = (
    {
        "id": "union_local_no_mc",
        "source": "union_moving",
        "tags": ("new_mc", "local_work", "qualify"),
        "context": "No active MC; local work only",
        "user": "I do not have Mc active. Im do only local jobs",
        "move": "clarify",
        "variant": "clarify_mc",
        "reply": "Local work is on file. Own-MC vs lease-on still needs a person — I will not treat that as set up.",
    },
    {
        "id": "union_worth_it",
        "source": "union_moving",
        "tags": ("commitment_concern", "fleet", "explain_objection"),
        "context": "Wants to see if dispatch is worth putting trucks on the road",
        "user": "I want to see if it's worth it, if I'll make money. I have two trucks and a Sprinter van.",
        "move": "explain_objection",
        "variant": "explain_net",
        "reply": "Fair — two trucks and a Sprinter are recorded. I will not quote a weekly gross. A person can walk the live fit.",
    },
    {
        "id": "union_nj_monday",
        "source": "union_moving",
        "tags": ("deadline", "liftgate", "payload_limit", "acknowledge"),
        "context": "Needs New Jersey by Monday; 26-ft box, liftgate, 8k, e-track",
        "user": "Do you have anything I need to go to NJ I need to be there by Monday. 26 box truck I can care 8k I do have lift gate no palls jackets. Ei have e track",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Got it — NJ by Monday, 26-ft box, liftgate, 8k, no pallet jack. I cannot confirm a live load here. Own MC or lease-on?",
    },
    {
        "id": "union_has_everything_dot",
        "source": "union_moving",
        "tags": ("repetition", "acknowledge"),
        "context": "Driver says they already have authority paperwork",
        "user": "I do have everything",
        "move": "acknowledge",
        "variant": "repair_repetition",
        "reply": "I'll only use what is on this chat. I cannot see documents staff have not received.",
    },
    {
        "id": "union_otr_after_local",
        "source": "union_moving",
        "tags": ("operating_mode", "acknowledge"),
        "context": "Earlier said local; now says OTR",
        "user": "OTR",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Updated to OTR. I will not re-ask local vs OTR.",
    },
    {
        "id": "union_new_mc_broker",
        "source": "union_moving",
        "tags": ("new_mc", "broker", "clarify"),
        "context": "MC about a month old; already set up with a broker",
        "user": "I us will tql yes",
        "move": "clarify",
        "variant": "clarify_mc",
        "reply": "Broker relationship is recorded as user-stated. A new MC still needs a human look — that is not eligibility.",
    },
    {
        "id": "union_mailbox_full",
        "source": "union_moving",
        "tags": ("email_delivery", "acknowledge"),
        "context": "Setup packet bounced because the mailbox was full",
        "user": "Tell him to sand again",
        "move": "acknowledge",
        "variant": "email_delivery",
        "reply": "We'll resend after the mailbox can receive it. I will not ask you to sign until that email lands.",
    },
    {
        "id": "union_pause_next_week",
        "source": "union_moving",
        "tags": ("postpone", "pause"),
        "context": "Interested, but busy this week",
        "user": "Morning I'm pretty busy this week, but I appreciate it! Let's see about next week. Thanks",
        "move": "pause",
        "variant": "pause",
        "reply": "No problem. Reach out when you're ready next week.",
    },
    {
        "id": "jason_legal_next_week",
        "source": "jason_chats",
        "tags": ("postpone", "pause"),
        "context": "26-ft box; still getting legal; ready end of next week",
        "user": "I will be looking for loads by the end of next week. There's a few things I need to get in order to be legal.",
        "move": "pause",
        "variant": "pause",
        "reply": "Take the time to get legal. Reach out when you're ready — I will not restart qualification.",
    },
    {
        "id": "jason_call_later",
        "source": "jason_chats",
        "tags": ("callback", "offer_handoff"),
        "context": "Follow-up after they asked for time",
        "user": "Can I call you later?",
        "move": "offer_handoff",
        "variant": "offer_handoff",
        "reply": "Yes. Call me is a callback on this same inquiry — confirm a number when you want it.",
    },
    {
        "id": "jason_waiting_insurance",
        "source": "jason_chats",
        "tags": ("blocker", "acknowledge"),
        "context": "Last time they were waiting on insurance quotes",
        "user": "Hey buddy, not yet. I'm hoping today or tomorrow for sure. Just getting several quotes",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Last time you were waiting on insurance — still the hold-up. I will not treat a quote as coverage.",
    },
    {
        "id": "jason_new_mc_lease_rate",
        "source": "jason_chats",
        "tags": ("new_mc", "total_fees", "explain_objection"),
        "context": "Challenged a lease-on pitch on a young MC",
        "user": "What you just want me to sign onto your MC authority or someone else's what is the percentage rate on that?",
        "move": "explain_objection",
        "variant": "answer_fee_need_mc",
        "reply": "Own-MC vs lease-on first. I will not invent a special percent. Staff quote Ayyan's live schedule after that.",
    },
    {
        "id": "jason_too_much",
        "source": "jason_chats",
        "tags": ("total_fees", "explain_objection"),
        "context": "Rejected a lease-on special",
        "user": "To much no thank you",
        "move": "explain_objection",
        "variant": "answer_fee",
        "reply": "Understood. I will not match a chat discount. Staff quote the live own-MC fee only after the arrangement is on file.",
    },
    {
        "id": "jason_tql_own_mc",
        "source": "jason_chats",
        "tags": ("broker", "new_mc", "qualify"),
        "context": "Already on a broker that works new authority",
        "user": "I'm on tql and they work with new MC authorities. There's no money left to give anybody.",
        "move": "acknowledge",
        "variant": "clarify_mc",
        "reply": "Broker on file as user-stated. We'll keep your own MC and send that for review — not a lease-on push.",
    },
    {
        "id": "moses_wont_sign",
        "source": "moses_banks",
        "tags": ("commitment_concern", "explain_objection"),
        "context": "Wants loads but does not want to sign blindly",
        "user": "Would you you get me some loads I just don't wnna sign for nothing",
        "move": "explain_objection",
        "variant": "explain_commitment",
        "reply": "Fair question. Signing does not guarantee a load. What would you like clarified before deciding?",
    },
    {
        "id": "moses_truck_tomorrow",
        "source": "moses_banks",
        "tags": ("blocker", "waiting_registration", "acknowledge"),
        "context": "Collecting the truck tomorrow; registration comes after",
        "user": "I'm picking up my truck tomorrow morning. I'll send the registration after.",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Got it — truck tomorrow, registration after that. We can pick this up then.",
    },
    {
        "id": "moses_photo_not_onboarded",
        "source": "moses_banks",
        "tags": ("repetition", "acknowledge"),
        "context": "Sent a photo of a rental contract as registration",
        "user": "I already sent my registration",
        "move": "acknowledge",
        "variant": "repair_repetition",
        "reply": "A photo on this chat is stored unverified. It is not a title check and not approval. I will not promise loads from it.",
    },
    {
        "id": "ezequiel_payload_too_heavy",
        "source": "ezequiel",
        "tags": ("payload_limit", "acknowledge"),
        "context": "8500 lb is too much for the trailer",
        "user": "Ok 8500 lb it's Little Too Much For My trailer. From Seven Thousand tu Seven Five Hundred",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Payload on file as 7000–7500 lb, user-stated. I will not assign a load from chat.",
    },
    {
        "id": "ezequiel_ready_today",
        "source": "ezequiel",
        "tags": ("onboard", "offer_handoff"),
        "context": "Payload set; driver says they are ready",
        "user": "Ok I'm ready",
        "move": "offer_handoff",
        "variant": "offer_handoff",
        "reply": "Ready is recorded. A person owns the next step. I will not put you on a load from this chat.",
    },
    {
        "id": "ezequiel_commodity",
        "source": "ezequiel",
        "tags": ("freight", "answer"),
        "context": "Asked for a specific commodity",
        "user": "We needed heatong loads",
        "move": "answer",
        "variant": "answer_services",
        "reply": "Specific product is a production call. I will not guarantee that freight from chat. What are you running?",
    },
    {
        "id": "fee_after_own_mc",
        "source": "staff_rewrite",
        "tags": ("total_fees", "answer"),
        "context": "Arrangement already on file",
        "user": "What do you charge?",
        "move": "answer",
        "variant": "answer_fee",
        "reply": "Staff quote the live own-MC dispatch fee after the arrangement is confirmed. I will not invent a discount.",
    },
    {
        "id": "meant_the_fee",
        "source": "staff_rewrite",
        "tags": ("total_fees", "topic_repair"),
        "context": "Prior turn was not about the fee",
        "user": "No, I meant what do you charge?",
        "move": "answer",
        "variant": "answer_fee",
        "reply": "You want the fee. I can quote the staff schedule after own-MC vs lease-on is on file.",
    },
    {
        "id": "need_to_get_paid",
        "source": "staff_rewrite",
        "tags": ("operations", "offer_handoff"),
        "context": "Left sales for a pay issue",
        "user": "Forget onboarding, I need to get paid",
        "move": "offer_handoff",
        "variant": "route_operations",
        "reply": "That leaves sales. Operations owns pay questions on an open case.",
    },
    {
        "id": "authority_ready",
        "source": "staff_rewrite",
        "tags": ("new_mc", "clarify"),
        "context": "Authority mentioned without own vs lease",
        "user": "My authority is ready",
        "move": "clarify",
        "variant": "clarify_mc",
        "reply": "Ready authority still needs own-MC vs lease-on. I will not treat that as verified paperwork.",
    },
    {
        "id": "three_not_two",
        "source": "staff_rewrite",
        "tags": ("fleet", "acknowledge"),
        "context": "Corrected truck count",
        "user": "Actually three trucks, not two",
        "move": "acknowledge",
        "variant": "ack_constraints",
        "reply": "Updated to three trucks. I will not re-ask fleet size.",
    },
)


def _tokens(text: str) -> set[str]:
    return set(TOKEN.findall((text or "").lower()))


def allowed(row: dict) -> bool:
    blob = f"{row.get('user', '')} {row.get('reply', '')} {row.get('context', '')}"
    return not LEAK.search(blob)


def _doc_tokens(row: dict) -> set[str]:
    tags = " ".join(row.get("tags") or ())
    return _tokens(f"{row['user']} {row.get('context', '')} {row['id'].replace('_', ' ')} {tags}")


def _index_rows(rows: list[dict]) -> list[dict]:
    return [{**row, "tokens": _doc_tokens(row)} for row in rows if allowed(row)]


INDEX = _index_rows(list(BANK))


def published() -> list[dict]:
    try:
        from app import db

        extra = db.list_examples("published")
    except Exception:
        extra = []
    by_id = {row["id"]: row for row in BANK}
    for row in extra:
        by_id[row["id"]] = {
            "id": row["id"],
            "source": row.get("source") or "staff",
            "tags": tuple(row.get("tags") or ()),
            "context": row.get("context") or "",
            "user": row.get("user_text") or row.get("user") or "",
            "move": row.get("move"),
            "variant": row.get("variant"),
            "reply": row.get("reply") or "",
        }
    return list(by_id.values())


def _passage(row: dict) -> str:
    tags = " ".join(row.get("tags") or ())
    return f"{row.get('user', '')} {row.get('context', '')} {tags}"


def reload_index() -> int:
    global INDEX
    INDEX = _index_rows(published())
    return len(INDEX)


def ensure_embeddings() -> dict:
    from app import embed

    rows = INDEX or _index_rows(published())
    return embed.ensure("example", [{"id": row["id"], "text": _passage(row)} for row in rows])


def _bm25(query: set[str], doc: set[str], df: dict[str, int], n: int) -> float:
    if not query or not doc:
        return 0.0
    score = 0.0
    for token in query:
        if token not in doc:
            continue
        idf = math.log(1 + (n - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5))
        score += idf
    return score


def search(text: str, limit: int = 2, tags: list[str] | None = None) -> list[dict]:
    query = _tokens(text)
    extra = {tag.lower() for tag in tags or []}
    query |= extra
    rows = INDEX or _index_rows(published())
    if not rows:
        return []
    n = len(rows)
    df: dict[str, int] = {}
    for row in rows:
        for token in row["tokens"]:
            df[token] = df.get(token, 0) + 1
    lex_scores = {row["id"]: _bm25(query, row["tokens"], df, n) for row in rows}
    lex_ranked = [row for row in sorted(rows, key=lambda row: lex_scores[row["id"]], reverse=True) if lex_scores[row["id"]] > 0]
    from app import embed

    q_vec = None
    if any(embed.get_cached("example", row["id"]) for row in rows):
        q_vec = embed.embed(text)
    vec_scores = {row["id"]: embed.cosine(q_vec, embed.get_cached("example", row["id"])) for row in rows}
    vec_ranked = [row for row in sorted(rows, key=lambda row: vec_scores[row["id"]], reverse=True) if vec_scores[row["id"]] > 0]
    if q_vec and vec_ranked:
        lex_rank = {row["id"]: i for i, row in enumerate(lex_ranked)}
        vec_rank = {row["id"]: i for i, row in enumerate(vec_ranked)}
        keys = list(dict.fromkeys([row["id"] for row in lex_ranked] + [row["id"] for row in vec_ranked]))
        order = [key for key, _ in embed.rrf(lex_rank, vec_rank, keys)]
        ranked = [{**next(row for row in rows if row["id"] == key)} for key in order]
    else:
        ranked = lex_ranked
    picked = []
    picked_tokens: set[str] = set()
    by_id = {row["id"]: row for row in rows}
    for row in ranked:
        row = by_id[row["id"]]
        if lex_scores[row["id"]] <= 0 and vec_scores[row["id"]] <= 0:
            continue
        overlap = len(row["tokens"] & picked_tokens) / max(len(row["tokens"]), 1)
        if picked and overlap > 0.55:
            continue
        picked.append(
            {
                "id": row["id"],
                "user": row["user"],
                "move": row["move"],
                "variant": row["variant"],
                "tags": list(row.get("tags") or ()),
                "context": row.get("context") or "",
                "reply": row.get("reply") or "",
            }
        )
        picked_tokens |= row["tokens"]
        if len(picked) >= limit:
            break
    return picked
