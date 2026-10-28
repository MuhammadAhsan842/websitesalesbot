"""Staff-approved fee schedule. The model cannot invent or discount these numbers."""

from app import db
from app.knowledge import lookup


def _fmt(percent: float) -> str:
    return str(int(percent)) if float(percent).is_integer() else str(percent)


def list_fees() -> list[dict]:
    return db.execute(
        "SELECT * FROM fee_schedule WHERE status = 'approved' ORDER BY id DESC",
        fetch="all",
    ) or []


def latest(arrangement: str) -> dict | None:
    return db.execute(
        """SELECT * FROM fee_schedule WHERE status = 'approved' AND arrangement = ?
           ORDER BY id DESC LIMIT 1""",
        (arrangement,),
        fetch="one",
    )


def approved_percents() -> set[str]:
    return {_fmt(row["percent"]) for row in list_fees()}


def publish(arrangement: str, percent: float, approved_by: str) -> dict:
    if arrangement not in {"dispatch_service", "lease_on"}:
        raise ValueError("arrangement must be dispatch_service or lease_on")
    if percent <= 0 or percent >= 100:
        raise ValueError("percent out of range")
    db.execute(
        """INSERT INTO fee_schedule (arrangement, percent, conditions, status, approved_by, created_at)
           VALUES (?, ?, ?, 'approved', ?, ?)""",
        (
            arrangement,
            percent,
            "No chat discount. Not an earnings guarantee. Lease drafts with a blank % are not this quote.",
            approved_by or "Staff desk",
            db.now(),
        ),
    )
    db.add_event("Fee schedule published", {"arrangement": arrangement, "percent": percent})
    return latest(arrangement)


def live_quote(arrangement: str | None) -> str:
    if not arrangement or arrangement == "needs_clarification":
        return lookup("fee_need_arrangement")
    row = latest("lease_on" if arrangement == "lease_on" else "dispatch_service")
    if not row:
        return lookup("fee")
    label = "lease-on settlement" if arrangement == "lease_on" else "own-MC dispatch fee"
    return (
        f"For this arrangement, the current {label} is {_fmt(row['percent'])}% of gross. "
        "That's the rate our onboarding manager uses — I won't change it here. "
        + lookup("fee_route_manager")
    )
