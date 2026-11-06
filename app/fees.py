"""Staff-approved fee schedule. The model cannot invent or discount these numbers."""

from __future__ import annotations

from app import db
from app.knowledge import lookup
from app.schema import EQUIP_LABELS

# Own-MC dispatch fee by equipment (percent of gross). Power-only stays manager-confirm.
OWN_MC_EQUIPMENT_FEE_PCT: dict[str, float] = {
    "flatbed": 5.0,
    "reefer": 5.0,
    "dry_van": 5.0,
    "step_deck": 5.0,
    "box_truck": 8.0,
    "hotshot": 8.0,
}

_OWN_MC_SCHEDULE_BLURB = (
    "Flatbed, reefer, dry van, and step deck are 5% of gross; box truck and hotshot are 8% of gross."
)


def _fmt(percent: float) -> str:
    return str(int(percent)) if float(percent).is_integer() else str(percent)


def _ensure_equipment_column() -> None:
    try:
        db.execute("ALTER TABLE fee_schedule ADD COLUMN equipment TEXT")
    except Exception:
        pass


def list_fees() -> list[dict]:
    _ensure_equipment_column()
    return db.execute(
        "SELECT * FROM fee_schedule WHERE status = 'approved' ORDER BY id DESC",
        fetch="all",
    ) or []


def latest(arrangement: str, equipment: str | None = None) -> dict | None:
    _ensure_equipment_column()
    if equipment:
        row = db.execute(
            """SELECT * FROM fee_schedule
               WHERE status = 'approved' AND arrangement = ? AND equipment = ?
               ORDER BY id DESC LIMIT 1""",
            (arrangement, equipment),
            fetch="one",
        )
        if row:
            return row
    return db.execute(
        """SELECT * FROM fee_schedule
           WHERE status = 'approved' AND arrangement = ?
             AND (equipment IS NULL OR equipment = '')
           ORDER BY id DESC LIMIT 1""",
        (arrangement,),
        fetch="one",
    )


LEASE_ON_LOCAL_FEE_PCT = 17.0


def approved_percents() -> set[str]:
    """Union of all published percents (legacy scanners). Prefer approved_percents_for()."""
    found = {_fmt(row["percent"]) for row in list_fees()}
    found.update(_fmt(pct) for pct in OWN_MC_EQUIPMENT_FEE_PCT.values())
    found.add(_fmt(LEASE_ON_LOCAL_FEE_PCT))
    return found


def approved_percents_for(
    arrangement: str | None = None,
    *,
    insurance: str | None = None,
    operating_mode: str | None = None,
    equipment: str | None = None,
) -> set[str]:
    """Context-scoped approved percents — own-MC 8% must not authorize lease-on 8%."""
    if arrangement == "lease_on":
        # Needs-insurance: never a numerical chat quote.
        if insurance == "needs_insurance":
            return set()
        mode = str(operating_mode or "").strip().lower() or None
        # Own-insurance local only publishes 17%.
        if mode == "local":
            return {_fmt(LEASE_ON_LOCAL_FEE_PCT)}
        # OTR / unknown mode: negotiation only — no approved chat percent.
        return set()
    if arrangement == "dispatch_service":
        eq = str(equipment or "").strip().lower() or None
        if eq and eq in OWN_MC_EQUIPMENT_FEE_PCT:
            return {_fmt(OWN_MC_EQUIPMENT_FEE_PCT[eq])}
        return {_fmt(pct) for pct in OWN_MC_EQUIPMENT_FEE_PCT.values()}
    return approved_percents()


def publish(
    arrangement: str,
    percent: float,
    approved_by: str,
    *,
    equipment: str | None = None,
) -> dict:
    _ensure_equipment_column()
    if arrangement not in {"dispatch_service", "lease_on"}:
        raise ValueError("arrangement must be dispatch_service or lease_on")
    if percent <= 0 or percent >= 100:
        raise ValueError("percent out of range")
    conditions = "No chat discount. Not an earnings guarantee. Lease drafts with a blank % are not this quote."
    if equipment:
        conditions = f"Equipment={equipment}. " + conditions
    db.execute(
        """INSERT INTO fee_schedule (arrangement, percent, conditions, status, approved_by, created_at, equipment)
           VALUES (?, ?, ?, 'approved', ?, ?, ?)""",
        (
            arrangement,
            percent,
            conditions,
            approved_by or "Staff desk",
            db.now(),
            equipment,
        ),
    )
    db.add_event(
        "Fee schedule published",
        {"arrangement": arrangement, "percent": percent, "equipment": equipment},
    )
    return latest(arrangement, equipment)


def ensure_own_mc_equipment_schedule(*, approved_by: str = "Staff desk") -> None:
    """Idempotent seed of the equipment fee matrix into fee_schedule."""
    _ensure_equipment_column()
    for equipment, percent in OWN_MC_EQUIPMENT_FEE_PCT.items():
        existing = latest("dispatch_service", equipment)
        if existing and float(existing["percent"]) == float(percent):
            continue
        publish("dispatch_service", percent, approved_by, equipment=equipment)


def live_quote(
    arrangement: str | None,
    *,
    insurance: str | None = None,
    equipment: str | None = None,
    operating_mode: str | None = None,
) -> str:
    if not arrangement or arrangement == "needs_clarification":
        return lookup("fee_need_arrangement")

    if arrangement == "lease_on":
        # Needs-insurance: keep manager/options line — never invent a percent.
        if insurance == "needs_insurance":
            return lookup("fee_lease_needs_insurance")
        mode = str(operating_mode or "").strip().lower() or None
        # Own-insurance local: published 17% of gross + negotiation route.
        if mode == "local":
            return lookup("fee_lease_local")
        # Own-insurance OTR: negotiation only — no schedule invent.
        if mode == "otr":
            return lookup("fee_lease_otr_negotiate")
        return lookup("fee_manager_confirm")

    # Own-MC / dispatch_service — quote by equipment when known.
    eq = str(equipment or "").strip().lower() or None
    if eq in OWN_MC_EQUIPMENT_FEE_PCT:
        percent = OWN_MC_EQUIPMENT_FEE_PCT[eq]
        label = EQUIP_LABELS.get(eq, eq.replace("_", " "))
        base = (
            f"For this arrangement, the current own-MC dispatch fee for {label} is {_fmt(percent)}% of gross. "
            "That's the rate our onboarding manager uses — I won't change it here. "
        )
        return base + lookup("fee_route_manager")

    if not eq:
        return (
            f"For own-MC, {_OWN_MC_SCHEDULE_BLURB} "
            "Once your truck type is on file I can quote the exact schedule rate. "
            + lookup("fee_route_manager")
        )

    # Known truck but no published band (e.g. power-only).
    return lookup("fee_manager_confirm")
