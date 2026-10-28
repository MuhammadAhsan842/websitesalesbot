"""Deterministic guard. Qwen proposes every turn; these rules only constrain and fill gaps."""

from __future__ import annotations

import re

from app.playbook import next_ask
from app.schema import INTENTS


def detect_repair(text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"mailbox|inbox (is )?full|email (couldn'?t|could not|bounced)|send (it )?again|sand again", t):
        return "email_delivery"
    if re.search(r"forget (onboarding|the packet|sales)|need to get paid|where'?s my (money|settlement|paycheck)", t):
        return "leave_sales"
    if re.search(r"no,? i meant|i meant (the )?(fee|percent|charge)|i was asking about (the )?(fee|percent|charge)", t):
        return "topic_fee"
    if re.search(r"authority is ready|mc is ready|authority came (in|through)", t) and not re.search(
        r"own mc|lease on|lease-on", t
    ):
        return "authority_uncertain"
    if re.search(r"already (sent|gave|provided) everything|i have everything", t):
        return "repetition_unverified"
    if re.search(r"actually|make that|not two|three instead|correction", t):
        return "correct_fact"
    return None


PAYMENT_ASK = re.compile(
    r"\b(pay\s*me|payme|payment|paid me|where'?s my (money|check|settlement|paycheck)|"
    r"when (do|will) (i|we) get paid|invoice now|zelle|quick\s*pay)\b",
    re.I,
)


def detect_intent(text: str) -> str:
    t = text.lower()
    repair = detect_repair(text)
    if repair == "leave_sales":
        return "existing_customer"
    if repair == "topic_fee":
        return "fee"
    if repair == "authority_uncertain":
        return "mc_new"
    # Payment complaints are operations — never match substring "lease" inside "please".
    if PAYMENT_ASK.search(text or ""):
        return "existing_customer"
    if re.search(r"(existing|already (a )?carrier|where's my load|where is my load|detention|tonu)", t):
        return "existing_customer"
    if re.search(r"let you know|not right now|i'?ll think|maybe later|next summer", t):
        return "general"
    if re.search(
        r"talk to (an? |the )?(onboarding )?manager|speak (to|with) (an? |the )?(onboarding )?manager|"
        r"talk to (a )?(human|person|agent)|speak (to|with) (a )?(human|person|agent)|dispatcher please|"
        r"route (me )?to (the )?onboarding|handoff to (the )?manager",
        t,
    ):
        return "human"
    if re.search(r"\btalk here\b|website microphone|\bmicrophone\b", t) and not re.search(
        r"manager|human|person|agent|onboarding", t
    ):
        return "talk_here"
    if re.search(r"(call me|callback|phone me|dial)", t):
        return "call_me"
    if re.search(r"not interested|no thanks|don't call|stop (texting|messaging)|leave me alone", t):
        return "decline"
    if re.search(r"sign for nothing|don'?t want to sign|am i binding|just (asking|looking|chatting)|signing up", t):
        return "commit"
    if re.search(r"when do (i|we) get paid|invoice now|pay after|payment timing", t):
        return "fee"
    if re.search(r"other dispatcher|leo dispatch|match (their|his) (rate|percent)|cheaper than (them|leo)", t):
        return "fee"
    if re.search(
        r"\bfees?\b|\bpercent\b|%|\bcharge\b|\bcost\b|how much|expensive|too much|\bcheaper\b",
        t,
    ):
        return "fee"
    if re.search(r"(guarantee|earn|\$\d|weekly gross)", t):
        return "guarantee"
    if re.search(
        r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded|"
        r"\b(have (a |any )?loads?|need (a )?loads?|looking for (a )?loads?|any loads?|"
        r"loads? in |load availability|do we have (a )?load|facebook.{0,40}loads?)\b",
        t,
    ):
        return "freight"
    if "fuel card" in t or re.search(r"\bfuel advance\b", t):
        return "fuel"
    if re.search(r"trust|scam|legit", t):
        return "trust"
    if re.search(r"home (every )?night|home time", t):
        return "hometime"
    if re.search(r"document|packet|onboard|ready to start|get started|i'm ready|how do i start", t):
        return "onboard"
    if re.search(r"new mc|pending (mc|authority)|authority is new|\bi('?m| am) new\b|brand new (mc|authority)", t):
        return "mc_new"
    if re.search(r"\blease(-?on)?\b", t):
        return "lease"
    if re.search(r"\bmc\b|authority", t):
        return "mc"
    if re.search(
        r"(what (trucks|equipment)|do you (haul|dispatch|support)|packages or pallets|"
        r"do you (support|dispatch|haul).{0,20}sprinter|sprinter.{0,20}support)",
        t,
    ):
        return "service"
    if re.search(r"status|approved yet|dispatcher'?s name|waiting on you", t):
        return "status"
    if re.search(r"don'?t know|not sure yet|unknown|skip that", t):
        return "unknown_detail"
    if re.search(r"dispatch|need (a )?dispatcher|looking for dispatch", t):
        return "dispatch_inquiry"
    return "general"


AD_LOAD = re.compile(
    r"facebook|(i (saw|seen|have seen) your)|your post|you seem to have|advertis",
    re.I,
)
EQUIP_PATTERN = (
    r"sprinter\s*van|spriter\s*van|sprintervan|sprinter|"
    r"cargo\s*van|"
    r"step\s*deck|power\s*only|"
    r"reefer|refeer|refer|dry van|flatbed|box truck|hot\s*shot|hotshot|\bbox\b|"
    r"semi\s*truck|semitruck|\bsemi\b"
)
OWNED_TRUCK = re.compile(rf"\bmy\b.{{0,40}}({EQUIP_PATTERN})", re.I)
EQUIP_WORD = re.compile(EQUIP_PATTERN, re.I)
OWNED_CLAIM = re.compile(
    rf"\bi (run|have|drive|got) (a |my )?({EQUIP_PATTERN})",
    re.I,
)
SPRINTER_ASK = re.compile(r"sprinter|spriter", re.I)


def normalize_equip(raw: str | None) -> str | None:
    if not raw:
        return None
    value = re.sub(r"\s+", " ", raw.lower().strip())
    value = value.replace("refeer", "reefer").replace("refer", "reefer").replace("refrier", "reefer")
    aliases = {
        "box": "box_truck",
        "box truck": "box_truck",
        "hot shot": "hotshot",
        "hotshot": "hotshot",
        "dry van": "dry_van",
        "flatbed": "flatbed",
        "reefer": "reefer",
        "semi": "dry_van",
        "semi truck": "dry_van",
        "semitruck": "dry_van",
        "sprinter": "sprinter_van",
        "sprinter van": "sprinter_van",
        "spriter van": "sprinter_van",
        "sprintervan": "sprinter_van",
        "cargo van": "cargo_van",
        "step deck": "step_deck",
        "power only": "power_only",
    }
    if value in aliases:
        return aliases[value]
    value = value.replace(" ", "_")
    return aliases.get(value.replace("_", " "), value)


def is_advertised_equipment(text: str) -> bool:
    return bool(AD_LOAD.search(text or "")) and not OWNED_TRUCK.search(text or "")


def advertised_mention(text: str) -> tuple[str | None, str | None]:
    if not is_advertised_equipment(text):
        return None, None
    mentioned = EQUIP_WORD.search(text or "")
    length = re.search(r"(\d+)\s*(?:-)?\s*(?:ft|foot|feet)\b", (text or "").lower())
    eq = normalize_equip(mentioned.group(0) if mentioned else None)
    ln = f"{length.group(1)}ft" if length else None
    return eq, ln


def owned_equipment_claim(text: str) -> bool:
    t = text or ""
    return bool(OWNED_TRUCK.search(t) or OWNED_CLAIM.search(t))


def _support_for(eq: str | None, length: str | None = None) -> str | None:
    from app.knowledge import EQUIPMENT_LENGTHS_FT, SUPPORTED_EQUIPMENT, UNSUPPORTED_EQUIPMENT

    if not eq:
        return None
    if eq in UNSUPPORTED_EQUIPMENT:
        return "out_of_scope"
    if eq not in SUPPORTED_EQUIPMENT:
        return "out_of_scope"
    allowed = EQUIPMENT_LENGTHS_FT.get(eq)
    if allowed is None:
        # power_only and any type without a trailer-length catalog entry
        return "in_scope"
    if length:
        match = re.match(r"(\d+)", str(length))
        if match and int(match.group(1)) not in allowed:
            return "out_of_scope"
    return "in_scope"


def _pick_equipment(text: str) -> str | None:
    """When several types are named, prefer an in-catalog truck over cargo/Sprinter."""
    from app.knowledge import SUPPORTED_EQUIPMENT, UNSUPPORTED_EQUIPMENT

    mentions = [normalize_equip(m.group(0)) for m in EQUIP_WORD.finditer(text or "")]
    if SPRINTER_ASK.search(text or "") and "sprinter_van" not in mentions:
        mentions.append("sprinter_van")
    if re.search(r"\bcargo\s*van\b", text or "", re.I) and "cargo_van" not in mentions:
        mentions.append("cargo_van")
    mentions = [m for m in mentions if m]
    if not mentions:
        return None
    supported = [m for m in mentions if m in SUPPORTED_EQUIPMENT]
    if supported:
        return supported[-1]
    unsupported = [m for m in mentions if m in UNSUPPORTED_EQUIPMENT]
    return unsupported[-1] if unsupported else mentions[-1]


def extract_facts(text: str) -> list[dict]:
    t = text.lower()
    items = []
    advertised = is_advertised_equipment(text)
    length_early = re.search(r"(\d+)\s*(?:-)?\s*(?:ft|foot|feet|pies)\b", t)
    length_value = f"{length_early.group(1)}ft" if length_early and not advertised else None
    eq = None if advertised else _pick_equipment(t)
    if eq:
        items.append({"key": "equipment", "value": eq, "status": "user_stated"})
        support = _support_for(eq, length_value)
        if support:
            items.append({"key": "equipmentSupport", "value": support, "status": "user_stated"})
        # Keep a secondary note when the message also names an unsupported vehicle.
        others = [
            normalize_equip(m.group(0))
            for m in EQUIP_WORD.finditer(t)
            if normalize_equip(m.group(0)) and normalize_equip(m.group(0)) != eq
        ]
        if re.search(r"\bcargo\s*van\b", t) and eq != "cargo_van":
            others.append("cargo_van")
        if SPRINTER_ASK.search(t) and eq != "sprinter_van":
            others.append("sprinter_van")
        others = list(dict.fromkeys(others))
        if others:
            items.append({"key": "secondaryEquipment", "value": ",".join(others), "status": "user_stated"})
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a": 1}
    count = re.search(
        r"(\d+|one|two|three|four|five|six|a)\s+(?:box\s+|dry\s+|flatbed\s+|reefer\s+|hotshot\s+)?(trucks?|reefers?|vans?|hotshots?)",
        t,
    )
    if count:
        raw = count.group(1)
        value = words.get(raw, int(raw) if raw.isdigit() else None)
        if value is not None:
            status = "corrected" if re.search(r"actually|make that|correction|not one|changed|three instead|now \d", t) else "user_stated"
            items.append({"key": "fleetSize", "value": value, "status": status})
    if re.search(r"authority is ready|mc is ready|authority came (in|through)", t) and not re.search(
        r"own mc|lease on|lease-on", t
    ):
        items.append({"key": "mcOwnership", "value": "unclear", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "needs_clarification", "status": "user_stated"})
    elif re.search(r"(own mc|my own mc|have (an? )?mc|i have mc|my mc (is|has|was)|mc is \d)", t) and not re.search(
        r"new mc|pending|authority is ready|i am new|i'm new", t
    ):
        items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    elif re.search(r"my authority", t) and not re.search(r"ready|pending|new mc", t):
        items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    age_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    age = re.search(
        r"(?:mc|authority).{0,32}(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s*(day|days|week|weeks|month|months|year|years)\s*old|"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s*(day|days|week|weeks|month|months|year|years)\s*old.{0,32}(?:mc|authority)",
        t,
    )
    if age:
        raw_num = age.group(1) or age.group(3)
        unit = (age.group(2) or age.group(4) or "").rstrip("s")
        num = age_words.get(str(raw_num), int(raw_num) if str(raw_num).isdigit() else None)
        if num is not None:
            months = num
            if unit == "day":
                months = max(1, num // 30) if num >= 30 else 0
            elif unit == "week":
                months = max(1, num // 4)
            elif unit == "year":
                months = num * 12
            items.append({"key": "authorityAgeMonths", "value": months, "status": "user_stated"})
            if not any(item["key"] == "mcOwnership" for item in items):
                items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
                items.append({"key": "requestedArrangement", "value": "dispatch_service", "status": "user_stated"})
    if re.search(r"(no mc|don'?t have.*mc|lease on|lease-on)", t):
        items.append({"key": "mcOwnership", "value": "no_own_mc", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "lease_on", "status": "user_stated"})
    if re.search(r"\bi('?m| am) new\b|new to (this|dispatch|trucking)|brand new mc|just got (my )?mc", t) or (
        re.search(r"(pending|not sure|unsure|another company|new mc)", t) and re.search(r"\bmc\b|authority", t)
    ):
        items.append({"key": "mcOwnership", "value": "unclear", "status": "user_stated"})
        items.append({"key": "requestedArrangement", "value": "needs_clarification", "status": "user_stated"})
    area = re.search(
        r"midwest|southeast|northeast|southwest|west coast|southern states|texas|california|georgia|florida|"
        r"dallas|houston|atlanta|chicago|irving|utah|michigan|new jersey|\bnj\b|jersey",
        t,
        re.I,
    )
    if area:
        value = area.group(0).lower().replace("new jersey", "nj").replace("southern states", "southern_states")
        if value in {"jersey"}:
            value = "nj"
        items.append({"key": "operatingArea", "value": value, "status": "user_stated"})
        items.append({"key": "lanes", "value": value, "status": "user_stated"})
    # "pies" = feet in Spanish length answers (e.g. "26 pies").
    if length_value:
        items.append({"key": "trailerLength", "value": length_value, "status": "user_stated"})
        # Re-evaluate catalog lengths once size is known in the same message.
        eq_now = next((item["value"] for item in items if item["key"] == "equipment"), None)
        if eq_now:
            support = _support_for(eq_now, length_value)
            if support:
                items = [item for item in items if item["key"] != "equipmentSupport"]
                items.append({"key": "equipmentSupport", "value": support, "status": "user_stated"})
    payload = re.search(r"(?:payload|weigh(?:t|s)|haul)\s*(?:of\s*)?(\d[\d,]*)\s*(lb|lbs|pound)", t) or re.search(
        r"(\d[\d,]*)\s*(lb|lbs|pounds)\s*(?:payload)?", t
    )
    preferred = re.search(
        r"(?:about |around |prefer(?:ring)? |want(?:ing)? |can (?:do|haul) )?(\d[\d,]*)\s*(?:-|to|–)\s*(\d[\d,]*)\s*(lb|lbs|pounds)?",
        t,
    )
    rejected_load = bool(re.search(r"too much|can'?t (haul|take|do)|over (my|the)|not for my|exceed", t))

    def _digits(raw: str | None) -> str | None:
        if not raw:
            return None
        cleaned = re.sub(r"[^\d]", "", raw)
        return cleaned or None

    pref_lo = _digits(preferred.group(1)) if preferred else None
    pref_hi = _digits(preferred.group(2)) if preferred else None
    # Prefer weight ranges only when lbs/payload cues exist (avoid stealing mileage ranges).
    preferred_is_weight = bool(
        preferred
        and pref_lo
        and pref_hi
        and (
            (preferred.group(3) and re.search(r"lb|pound", preferred.group(3), re.I))
            or re.search(r"\b(lb|lbs|pounds?|payload|weight)\b", t)
        )
    )
    if preferred_is_weight:
        items.append(
            {
                "key": "preferredPayload",
                "value": f"{pref_lo}-{pref_hi}",
                "status": "user_stated",
            }
        )
    elif payload and rejected_load:
        items.append(
            {
                "key": "rejectedLoadWeight",
                "value": payload.group(1).replace(",", ""),
                "status": "user_stated",
            }
        )
    elif rejected_load and not payload:
        # Unitless rejected weight: "18000 is too much" / "can't take 18,000".
        unitless = re.search(
            r"(\d[\d,]{2,})\s*(?:is |are )?(?:too much|too heavy|over)|"
            r"(?:too much|can'?t (?:haul|take|do)|over)\D{0,12}(\d[\d,]{2,})",
            t,
        )
        if unitless:
            raw = unitless.group(1) or unitless.group(2)
            items.append(
                {
                    "key": "rejectedLoadWeight",
                    "value": raw.replace(",", ""),
                    "status": "user_stated",
                }
            )
    elif payload:
        items.append({"key": "payload", "value": payload.group(1).replace(",", ""), "status": "user_stated"})
    # Installed equipment vs load requirements (do not collapse into one field).
    load_liftgate = re.search(
        r"loads? that (do not|don'?t|without).{0,20}liftgate|no liftgate (loads?|required)|"
        r"(do not|don'?t) (want|need|take) (a |any )?liftgate (load|required)|"
        r"without (a )?liftgate",
        t,
    )
    if load_liftgate:
        items.append({"key": "liftgateLoadPreference", "value": "not_required", "status": "user_stated"})
    installed_liftgate = re.search(
        r"\b(have|has|with|got|equipped with) (a |my )?liftgate\b|\bliftgate\b",
        t,
    )
    if installed_liftgate and not load_liftgate:
        if re.search(r"no liftgate|without liftgate|don'?t have (a )?liftgate", t):
            items.append({"key": "liftgate", "value": "no", "status": "user_stated"})
        elif re.search(r"have|has|with|got|equipped|\bliftgate\b", t):
            # Bare "liftgate" in a truck-description list still means installed.
            if re.search(r"no liftgate|without liftgate", t):
                items.append({"key": "liftgate", "value": "no", "status": "user_stated"})
            else:
                items.append({"key": "liftgate", "value": "yes", "status": "user_stated"})
    if re.search(r"pallet\s*jack|pallette\s*jack", t):
        items.append({"key": "palletJack", "value": "yes", "status": "user_stated"})
    accessory_bits = []
    for name, pattern in (
        ("straps", r"\bstraps?\b"),
        ("chains", r"\bchains?\b"),
        ("binders", r"\bbinders?\b"),
        ("tarps", r"\btarps?\b"),
    ):
        if re.search(pattern, t):
            accessory_bits.append(name)
    if accessory_bits:
        items.append({"key": "accessories", "value": ",".join(accessory_bits), "status": "user_stated"})
    # Coverage types — separate from overall insurance slot.
    asks_coverage_need = bool(
        re.search(
            r"do you need .{0,60}(insurance|coverage|cargo|liability)|"
            r"(need|require) (commercial|cargo|both) .{0,20}(insurance|coverage)|"
            r"both coverages\?",
            t,
        )
    )
    if re.search(r"no commercial auto|without commercial auto|no auto liability|don'?t have (commercial )?auto", t):
        items.append({"key": "autoLiabilityCoverage", "value": "absent", "status": "user_stated"})
    elif re.search(r"commercial auto|auto liability", t) and not asks_coverage_need:
        items.append({"key": "autoLiabilityCoverage", "value": "present", "status": "user_stated"})
    if re.search(r"no cargo (insurance|coverage)|without cargo|don'?t have cargo", t):
        items.append({"key": "cargoCoverage", "value": "absent", "status": "user_stated"})
    elif re.search(r"cargo (insurance|coverage)|have cargo", t) and not asks_coverage_need:
        items.append({"key": "cargoCoverage", "value": "present", "status": "user_stated"})
    if re.search(
        r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait",
        t,
    ):
        items.append({"key": "insurance", "value": "needs_insurance", "status": "user_stated"})
    elif asks_coverage_need:
        pass
    elif re.search(r"need insurance|no insurance|don'?t have insurance|looking for insurance", t):
        items.append({"key": "insurance", "value": "needs_insurance", "status": "user_stated"})
    elif re.search(r"have (my |our )?(own )?insurance|i('m| am) insured|got insurance|\binsured\b", t):
        items.append({"key": "insurance", "value": "own_insurance", "status": "user_stated"})
    if re.search(r"\bi use factoring\b|\bfactoring\b", t) and not re.search(r"what is factoring|explain factoring", t):
        items.append({"key": "paymentArrangement", "value": "factoring", "status": "user_stated"})
    if re.search(r"monday through friday|mon(day)?\s*(to|-|through)\s*fri|weekdays", t):
        items.append({"key": "weekdaySchedule", "value": "monday_friday", "status": "user_stated"})
    elif re.search(r"home weekends|weekends? home|flexible schedule", t):
        items.append({"key": "weekdaySchedule", "value": "flexible", "status": "user_stated"})
    miles = (
        re.search(r"(\d{2,4})\s*(?:-|to|–)\s*(\d{2,4})\s*miles(?:\s+(a|per)\s+day)?", t)
        or re.search(r"(\d{2,4})\s*miles (a|per) day", t)
        or re.search(r"(?:cover|do|run)\s+(\d{2,4})\s*(?:-|to|–)\s*(\d{2,4})\s*(?:a|per)\s+day", t)
    )
    # Do not treat bare "7000 to 7500" as mileage when it is a weight/payload range.
    weightish = bool(
        re.search(r"\b(lb|lbs|pounds?|payload|too (much|heavy)|weight)\b", t)
        or any(item.get("key") in {"preferredPayload", "rejectedLoadWeight", "payload"} for item in items)
    )
    if miles and not weightish:
        g2 = miles.group(2) if miles.lastindex and miles.lastindex >= 2 else None
        if g2 and str(g2).isdigit():
            value = f"{miles.group(1)}-{g2}"
        else:
            value = miles.group(1)
        items.append({"key": "milesPerDay", "value": value, "status": "user_stated"})
    if re.search(r"\blocal\b|no otr|not otr|home every night|staying local|local work", t) and not re.search(
        r"\botr\b|over the road", t
    ):
        items.append({"key": "operatingMode", "value": "local", "status": "user_stated"})
    elif re.search(r"\botr\b|over the road", t):
        items.append({"key": "operatingMode", "value": "otr", "status": "user_stated"})
    elif re.search(r"\bregional\b|only want regional|regional work", t):
        # Regional is not a sold mode — record uncertainty so we re-ask OTR vs local.
        items.append({"key": "operatingMode", "value": "unclear", "status": "user_stated"})
    stay = re.search(
        r"(?:stay out|out for|on the road for)\s+(\d+\s*(?:-|to)\s*\d+\s*(?:day|days|week|weeks)|"
        r"(?:a |one |two |three )?weeks?|weekends? home|home weekends)",
        t,
    ) or re.search(r"\b(\d+)\s*(day|days|week|weeks)\s+out\b", t)
    if stay:
        items.append({"key": "stayOutDuration", "value": stay.group(0).strip(), "status": "user_stated"})
    has_auto = any(i.get("key") == "autoLiabilityCoverage" for i in items)
    has_cargo = any(i.get("key") == "cargoCoverage" for i in items)
    if re.search(r"\bboth\b.{0,24}(auto|cargo|liability)|auto .{0,12}cargo|cargo .{0,12}auto", t) and not asks_coverage_need:
        items.append({"key": "coverageTypes", "value": "auto_and_cargo", "status": "user_stated"})
        if not has_auto:
            items.append({"key": "autoLiabilityCoverage", "value": "present", "status": "user_stated"})
        if not has_cargo:
            items.append({"key": "cargoCoverage", "value": "present", "status": "user_stated"})
    elif (
        re.search(r"\b750k\b|\b1\s*m(il)?\b|\$\s*1,?000,?000", t)
        and not asks_coverage_need
        and not any(i.get("key") == "autoLiabilityCoverage" and i.get("value") == "absent" for i in items)
    ):
        items.append({"key": "coverageTypes", "value": "auto", "status": "user_stated"})
        if not has_auto:
            items.append({"key": "autoLiabilityCoverage", "value": "present", "status": "user_stated"})
    elif (
        re.search(r"\$\s*100,?000\b|\b100k\b cargo", t)
        and not asks_coverage_need
        and not any(i.get("key") == "cargoCoverage" and i.get("value") == "absent" for i in items)
    ):
        items.append({"key": "coverageTypes", "value": "cargo", "status": "user_stated"})
        if not has_cargo:
            items.append({"key": "cargoCoverage", "value": "present", "status": "user_stated"})
    elif has_auto and has_cargo:
        auto_v = next(i["value"] for i in items if i["key"] == "autoLiabilityCoverage")
        cargo_v = next(i["value"] for i in items if i["key"] == "cargoCoverage")
        if auto_v == "present" and cargo_v == "present":
            items.append({"key": "coverageTypes", "value": "auto_and_cargo", "status": "user_stated"})
        elif auto_v == "present":
            items.append({"key": "coverageTypes", "value": "auto", "status": "user_stated"})
        elif cargo_v == "present":
            items.append({"key": "coverageTypes", "value": "cargo", "status": "user_stated"})
    if re.search(r"don'?t want to sign|won'?t sign|sign for nothing", t):
        items.append({"key": "commitmentStance", "value": "wont_sign", "status": "user_stated"})
    expired_hist = bool(
        re.search(r"not anymore|that was for last |was for (last )?(friday|monday|week|tuesday|wednesday|thursday)", t)
    )
    if not expired_hist and not any(item["key"] == "weekdaySchedule" for item in items):
        day = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|asap|immediately)\b", t)
        if day:
            items.append({"key": "deadline", "value": day.group(1), "status": "user_stated"})
            items.append({"key": "startDate", "value": day.group(1), "status": "user_stated"})
    if re.search(r"home every night|daily home|home time", t):
        items.append({"key": "supportNeed", "value": "daily_home_time", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "home_time", "status": "user_stated"})
    if re.search(r"\bfactoring\b", t) and not re.search(r"paperwork|broker calls", t):
        # Factoring is a payment arrangement; do not force paperwork as the primary problem.
        pass
    elif re.search(r"paperwork|broker calls", t):
        items.append({"key": "supportNeed", "value": "paperwork", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "paperwork", "status": "user_stated"})
    if re.search(r"better loads?|keep(ing)? (me |the truck )?loaded|empty miles", t):
        items.append({"key": "supportNeed", "value": "keep_loaded", "status": "user_stated"})
        items.append({"key": "primaryProblem", "value": "freight", "status": "user_stated"})
    if re.search(r"expensive|too much|cheaper|rates", t):
        items.append({"key": "primaryProblem", "value": "rates", "status": "user_stated"})
    if re.search(r"start (next week|immediately|asap|monday)", t):
        items.append({"key": "startDate", "value": re.search(r"next week|immediately|asap|monday", t).group(0), "status": "user_stated"})
    if re.search(r"\bnext week\b", t) and "start" not in t:
        items.append({"key": "startDate", "value": "next week", "status": "user_stated"})
    phone = re.search(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
    if phone:
        items.append({"key": "phone", "value": phone.group(0), "status": "confirmed"})
    name = re.search(r"my name is ([a-z][a-z ]{1,40})", text, re.I)
    if name:
        items.append({"key": "name", "value": name.group(1).strip(), "status": "confirmed"})
    if re.search(r"don'?t know|not sure yet|unknown|skip that", t):
        items.append({"key": "_unknown", "value": True, "status": "unknown"})
    # Customer counteroffer — recorded for review, never auto-accepted as the live fee.
    offer = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
    cap = re.search(r"\$?\s*(\d[\d,]*)\s*(?:weekly|week)?\s*cap", t)
    if offer and re.search(r"%|percent|cap|you pay|i (want|need|propose)", t):
        items.append({"key": "requestedFeePercent", "value": offer.group(1), "status": "user_stated"})
    if cap:
        items.append({"key": "requestedWeeklyCap", "value": cap.group(1).replace(",", ""), "status": "user_stated"})
    return items


def blocked_from_text(text: str) -> list[str]:
    t = text.lower()
    blocked = []
    if re.search(r"guarantee|\$\s*\d|weekly gross|10k|per week", t):
        blocked.append("guarantee")
    if re.search(r"\d+\s*%|discount", t):
        blocked.append("invented_fee")
    if re.search(r"coi is valid|insurance (is )?good|you('re| are) approved", t):
        blocked.append("insurance_approved")
    return blocked


def knowledge_for(
    intent: str,
    blocked: list[str],
    equipment: str | None,
    text: str = "",
    extracted: list | None = None,
    arrangement: str | None = None,
) -> list[str]:
    keys = []
    if "guarantee" in blocked or intent == "guarantee":
        keys.append("guarantee")
    mapping = {
        "fee": ["fee", "fee_route_manager"],
        "fuel": ["fuel"],
        "freight": ["freight", "load_evaluate", "loads_after_onboarding"],
        "service": ["services"],
        "talk_here": ["talk_here"],
        "call_me": ["call_me"],
        "human": ["handoff_requested", "fee_route_manager"],
        "existing_customer": ["support"],
        "lease": ["lease"],
        "mc": ["own_mc"],
        "mc_new": ["mc_new"],
        "onboard": ["onboarding", "dispatch_vs_onboarding", "docs_checklist"],
        "trust": ["trust"],
        "commit": ["concern_commitment", "commit"],
        "email_delivery": ["email_delivery"],
        "decline": ["commit"],
        "dispatch_inquiry": ["services", "dispatch_how"],
        "status": ["docs_status"],
    }
    keys.extend(mapping.get(intent, []))
    t = (text or "").lower()
    if PAYMENT_ASK.search(text or ""):
        keys = ["payment_support", "support", "trip_docs_invoice"]
    if re.search(
        r"what do you (actually )?do( for me)?|how (does |do )?(dispatch|your (service|dispatch)) work|"
        r"what (does|do) (a |the )?dispatcher|explain dispatch",
        t,
    ):
        keys.extend(["dispatch_how", "dispatch_vs_onboarding", "load_approval", "freight_roles"])
    if re.search(
        r"\b(what (is|does) (a |the )?(broker|shipper|motor carrier)|freight (ecosystem|roles))\b",
        t,
    ):
        keys.extend(["freight_roles", "pay_to_carrier"])
    if re.search(
        r"\b(payload|lift\s*gate|pallet\s*jack|53\s*ft|48\s*ft|26\s*ft|day\s*cab|sleeper|"
        r"accessories|equipment (size|spec|length))\b",
        t,
    ):
        keys.extend(["equip_specs", "cab_driver_types"])
    if re.search(
        r"\b(quick\s*pay|standard pay|factoring|voided check|broker (pay|payment))\b",
        t,
    ):
        keys.extend(["payment_methods_broker", "pay_to_carrier"])
    if re.search(
        r"fuel advance|diesel (money|before)|can'?t start without (fuel|diesel)|need (a )?fuel (card|advance)|upfront (fuel|diesel)",
        t,
    ):
        keys.extend(["fuel_requirement", "fuel"])
    if re.search(
        r"private (business )?information|that'?s private|sensitive (business|question)|don'?t know you",
        t,
    ):
        keys.extend(["privacy_boundary", "apology_no_pitch"])
    if re.search(
        r"not anymore|that was for last |don'?t need (it|help|dispatch) (now|anymore)|was for (last )?(friday|monday|week)",
        t,
    ):
        keys.append("expired_demand")
    if re.search(r"already hired (a )?dispatcher|have (a |my )?dispatcher|working with (another |a )?dispatcher", t):
        keys.append("existing_dispatcher")
    if re.search(r"situation changed|considering switching|can we (talk|discuss) (about )?dispatch", t):
        keys.append("voluntary_return")
    if re.search(r"\b(otr|over[\s-]?the[\s-]?road|local (loads?|runs?)|miles (a|per) day)\b", t):
        keys.append("lane_prefs")
    if re.search(r"\bmc (age|old)|how old .{0,20}\bmc\b|authority age", t):
        keys.append("mc_age_review")
    if re.search(r"time\s*zone|pacific|eastern|central time|mountain time", t):
        keys.append("timezone_ops")
    if re.search(r"approve (each |every |the )?load|rate confirmation|who (signs|books)", t):
        keys.extend(["load_approval", "docs_rate_con_detail"])
    if re.search(r"\bdetention\b|\blayover\b|\btonu\b|accessorial", t):
        keys.append("accessorials")
    if re.search(r"home every night|daily home time|\bhome time\b", t):
        keys.append("home_time")
    if re.search(r"what (papers|documents|do i (send|need))|document checklist|onboarding docs", t):
        keys.append("docs_checklist")
    if re.search(
        r"do you need .{0,40}insurance|commercial (auto )?(and|&) cargo|cargo (and|&) commercial|"
        r"auto liability|both coverages?|need (commercial|cargo)",
        t,
    ):
        keys.append("insurance")
    if re.search(r"insurance (costs?|is )?(too much|expensive|afford)|can'?t afford insurance|owner will wait", t):
        keys.append("insurance_affordability")
    if re.search(r"sprinter|spriter", t):
        keys.append("equip_sprinter_van")
    if re.search(r"\bcargo\s*van\b", t):
        keys.append("equip_cargo_van")
    if re.search(r"i received (it|the packet)|received the packet|send it tomorrow", t):
        keys.append("packet_received")
    if re.search(r"\d+\s*%|weekly cap|take it off the first delivery", t):
        keys.extend(["negotiation", "broker_vs_fee"])
    if re.search(r"need a trailer|buying (a |the )?truck|don'?t have (a )?trailer", t):
        keys.append("missing_equipment")
    if re.search(r"next summer|i'?ll start again", t):
        keys.append("deferred")
    if re.search(r"sign for nothing|don'?t want to sign", t):
        keys.append("concern_commitment")
    if re.search(r"better loads?|empty miles|keep(ing)? (me |the truck )?loaded|deadhead", t):
        keys.extend(["freight", "load_evaluate"])
    if re.search(r"other dispatcher|leo dispatch|competitor", t):
        keys.append("competitor")
    if re.search(r"invoice|pay after|when.{0,20}paid|payment timing", t):
        keys.extend(["payment_timing", "trip_docs_invoice"])
    from app import docs as docmod

    for key in docmod.keys_for(text, arrangement):
        if key not in keys:
            keys.append(key)
    stated = {item.get("key") for item in extracted or []}
    if equipment and intent in {"service", "dispatch_inquiry"}:
        from app.knowledge import EQUIP_KEYS

        extra = EQUIP_KEYS.get(str(equipment))
        if extra:
            keys.append(extra)
    elif equipment and "equipment" in stated and intent not in {"fee", "guarantee", "commit", "mc", "lease"}:
        from app.knowledge import EQUIP_KEYS

        extra = EQUIP_KEYS.get(str(equipment))
        if extra:
            keys.append(extra)
    return list(dict.fromkeys(keys))


def arrangement_of(facts: dict) -> str | None:
    mc = facts.get("mcOwnership", {}).get("value") if isinstance(facts.get("mcOwnership"), dict) else None
    if mc == "own_mc":
        return "dispatch_service"
    if mc == "no_own_mc":
        return "lease_on"
    if mc == "unclear":
        return "needs_clarification"
    return None


def task_for(arrangement: str | None, intent: str) -> str | None:
    if intent == "existing_customer":
        return "operations_support"
    if intent == "call_me":
        return "callback"
    if arrangement == "dispatch_service":
        return "setup_packet"
    if arrangement == "lease_on":
        return "lease_agreement"
    if arrangement == "needs_clarification":
        return "clarification"
    return None


def _short_answer_facts(text: str, memory: dict | None) -> list[dict]:
    """Map terse answers to the pending qualify slot (chip / yes / no)."""
    pending = (memory or {}).get("last_question_id")
    if not pending:
        return []
    t = (text or "").strip().lower()
    if not t or len(t) > 80:
        return []
    items: list[dict] = []
    yes = bool(re.fullmatch(r"(yes|yep|yeah|y|si|sí|correct|i do|i have|i have it)", t))
    no = bool(re.fullmatch(r"(no|nope|nah|n|i don'?t|do not)", t))
    if pending == "insurance":
        if yes or re.search(r"own insurance|i have (my )?insurance|insured", t):
            items.append({"key": "insurance", "value": "own_insurance", "status": "user_stated"})
        elif no or re.search(r"need insurance|no insurance", t):
            items.append({"key": "insurance", "value": "needs_insurance", "status": "user_stated"})
    elif pending == "coverageTypes":
        if re.search(r"both|auto\s*\+\s*cargo|auto and cargo", t):
            items.append({"key": "coverageTypes", "value": "auto_and_cargo", "status": "user_stated"})
            items.append({"key": "autoLiabilityCoverage", "value": "present", "status": "user_stated"})
            items.append({"key": "cargoCoverage", "value": "present", "status": "user_stated"})
        elif re.search(r"commercial auto|auto liability|\bauto\b", t):
            items.append({"key": "coverageTypes", "value": "auto", "status": "user_stated"})
        elif re.search(r"\bcargo\b", t):
            items.append({"key": "coverageTypes", "value": "cargo", "status": "user_stated"})
    elif pending == "operatingMode":
        if re.search(r"\botr\b|over the road", t):
            items.append({"key": "operatingMode", "value": "otr", "status": "user_stated"})
        elif re.search(r"\blocal\b", t):
            items.append({"key": "operatingMode", "value": "local", "status": "user_stated"})
        elif re.search(r"\bregional\b", t):
            items.append({"key": "operatingMode", "value": "unclear", "status": "user_stated"})
    elif pending == "mcOwnership":
        if yes or re.search(r"own mc|i have (my )?mc", t):
            items.append({"key": "mcOwnership", "value": "own_mc", "status": "user_stated"})
        elif no or re.search(r"lease", t):
            items.append({"key": "mcOwnership", "value": "no_own_mc", "status": "user_stated"})
    return items


def propose(text: str, facts: dict, memory: dict | None = None) -> dict:
    from app import plan as planmod

    from app import memory as memmod

    intent = detect_intent(text)
    repair = detect_repair(text)
    items = extract_facts(text)
    # Prefer short-answer fills when extract didn't already set that key.
    have = {item["key"] for item in items}
    for item in _short_answer_facts(text, memory):
        if item["key"] not in have:
            items.append(item)
            have.add(item["key"])
    current_equip = facts.get("equipment", {}).get("value") if isinstance(facts.get("equipment"), dict) else None
    ad_value, ad_length = advertised_mention(text)
    if ad_value and current_equip and ad_value != current_equip:
        repair = "equip_ambiguous"
    elif memmod.open_ambiguity(memory, "equipment") and not owned_equipment_claim(text):
        repair = "equip_ambiguous"
    blocked = blocked_from_text(text)
    preview = dict(facts)
    for item in items:
        if item["key"] == "_unknown":
            continue
        preview[item["key"]] = {"value": item["value"], "status": item["status"]}
    arrangement = arrangement_of(preview)
    equip = preview.get("equipment", {}).get("value") if isinstance(preview.get("equipment"), dict) else None
    ask = next_ask(preview, memory, intent, repair)
    action = "none"
    if intent == "talk_here":
        action = "talk_here"
    elif intent == "call_me":
        action = "callback"
    elif intent == "human":
        action = "takeover"
    elif intent == "existing_customer" or repair == "leave_sales":
        action = "create_case"
        intent = "existing_customer"
    elif intent == "onboard" and arrangement and equip:
        support = (
            preview.get("equipmentSupport", {}).get("value")
            if isinstance(preview.get("equipmentSupport"), dict)
            else None
        )
        if support != "out_of_scope":
            action = "create_case"
    if repair == "authority_uncertain":
        action = "none"
    if repair == "equip_ambiguous":
        action = "none"
        ask = None
    support_now = (
        preview.get("equipmentSupport", {}).get("value")
        if isinstance(preview.get("equipmentSupport"), dict)
        else None
    )
    if support_now == "out_of_scope" and action == "create_case" and intent != "existing_customer":
        action = "none"
    if repair == "repetition_unverified":
        blocked.append("insurance_approved")
    return {
        "intent": intent if intent in INTENTS else "general",
        "facts": items,
        "knowledge_keys": (
            ["email_delivery"]
            if repair == "email_delivery"
            else knowledge_for(intent, blocked, equip, text, items, arrangement)
        ),
        "blocked": blocked,
        "next_field": ask,
        "arrangement": arrangement,
        "action": action,
        "task": task_for(arrangement, intent),
        "repair": repair,
        "advertised_equipment": ad_value,
        "advertised_length": ad_length,
        "answer_topics": planmod.detect_topics(text, intent, None, repair),
        "_source": "rules",
    }
