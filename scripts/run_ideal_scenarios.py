#!/usr/bin/env python3
"""Replay the six ideal conversation scripts against the live API and dump results."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/agoc_ideal_scenario_results.json")
REPORT = Path("/tmp/agoc_ideal_scenario_report.md")


def post(path: str, body: dict, timeout: int = 220) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post_file(path: str, filename: str, content: bytes, content_type: str = "application/pdf") -> dict:
    boundary = "----agocbound"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def new_session() -> dict:
    return post("/v1/session", {})


def turn(sid: str, text: str, chip: dict | None = None) -> dict:
    body: dict = {"session_id": sid, "text": text}
    if chip:
        body["chip"] = chip
    t0 = time.time()
    try:
        out = post("/v1/turn", body)
    except Exception as exc:  # noqa: BLE001
        return {"in": text, "chip": chip, "error": str(exc), "ms": int((time.time() - t0) * 1000)}
    chips = out.get("chips") or []
    return {
        "in": text,
        "chip": chip,
        "out": out.get("text"),
        "chips": [
            {"label": c.get("label"), "field": c.get("field"), "value": c.get("value")}
            for c in chips
            if isinstance(c, dict)
        ],
        "mgr_req": out.get("manager_requested"),
        "mgr_acc": out.get("manager_accepted"),
        "case_id": out.get("case_id"),
        "takeover": out.get("takeover"),
        "conversation_state": out.get("conversation_state"),
        "ms": int((time.time() - t0) * 1000),
    }


def pick_chip(chips: list | None, *needles: str) -> dict | None:
    for c in chips or []:
        label = (c.get("label") or "").lower()
        if all(n.lower() in label for n in needles):
            return {k: c[k] for k in ("label", "field", "value") if k in c and c[k] is not None}
    return None


def run_script(name: str, steps: list[tuple[str, dict | None]], *, welcome: bool = True) -> dict:
    print(f"\n=== {name} ===", flush=True)
    s = new_session()
    sid = s["session_id"]
    turns = []
    if welcome:
        turns.append(
            {
                "in": "(session open)",
                "out": s.get("text"),
                "chips": [
                    {"label": c.get("label"), "field": c.get("field"), "value": c.get("value")}
                    for c in (s.get("chips") or [])
                    if isinstance(c, dict)
                ],
                "ideal_note": "welcome",
            }
        )
        print(f"  WELCOME: {(s.get('text') or '')[:140]}", flush=True)
    last = turns[-1] if turns else {}
    for text, chip in steps:
        if callable(chip):
            chip = chip(last)
        r = turn(sid, text, chip)
        turns.append(r)
        last = r
        preview = (r.get("out") or r.get("error") or "")[:180].replace("\n", " ")
        print(f"  IN: {text}\n  OUT: {preview}", flush=True)
    return {"session": sid, "turns": turns, "case_id": (turns[-1] or {}).get("case_id") if turns else None}


def main() -> None:
    results: dict = {}

    # 1. Box truck → lease-on → OTR → onboarding
    results["s1_box_lease_otr"] = run_script(
        "S1 box lease OTR",
        [
            ("I need dispatch", None),
            (
                "I want to lease on",
                {
                    "label": "I want to lease on",
                    "field": "mcOwnership",
                    "value": "no_own_mc",
                    "requestedArrangement": "lease_on",
                },
            ),
            ("Box truck", None),
            ("26 ft", {"label": "26 ft", "field": "trailerLength", "value": "26 ft"}),
            (
                "I have my own insurance",
                {"label": "I have my own insurance", "field": "insurance", "value": "own_insurance"},
            ),
            (
                "Auto + cargo",
                {"label": "Auto + cargo", "field": "coverageTypes", "value": "auto_and_cargo"},
            ),
            ("OTR", {"label": "OTR", "field": "operatingMode", "value": "otr"}),
            ("Home weekends", {"label": "Home weekends", "field": "stayOutDuration", "value": "home_weekends"}),
            ("Dallas, Texas", None),
            ("I'm ready to start", None),
            ("Can we talk while they review it?", None),
        ],
    )

    # 2. Supported equipment → reefer → uncertain authority
    results["s2_reefer_uncertain"] = run_script(
        "S2 reefer uncertain",
        [
            ("What equipment do you support?", None),
            ("I'm ready to start", None),
            ("I have a refeer 53 ft", None),
            (
                "Not sure about my MC",
                {"label": "Not sure about my MC", "field": "mcOwnership", "value": "unclear"},
            ),
            ("Reefer", None),
            ("Yes", None),
            ("Yes", None),
            ("555-123-4567", None),
            ("Tomorrow afternoon, Central time", None),
        ],
    )

    # 3. Hotshot → own MC → coverage → local → negotiation
    s3_steps: list = [
        ("I need dispatch service", None),
        ("30 ft hotshot", None),
        (
            "I have my own MC",
            {
                "label": "I have my own MC",
                "field": "mcOwnership",
                "value": "own_mc",
                "requestedArrangement": "dispatch_service",
            },
        ),
        (
            "I have my own insurance",
            {"label": "I have my own insurance", "field": "insurance", "value": "own_insurance"},
        ),
        (
            "Auto + cargo",
            {"label": "Auto + cargo", "field": "coverageTypes", "value": "auto_and_cargo"},
        ),
        ("My MC is about five months", None),
        ("Local work", {"label": "Local work", "field": "operatingMode", "value": "local"}),
        ("400-500", {"label": "400-500", "field": "milesPerDay", "value": "400-500"}),
        ("Dallas", None),
        ("Yes", None),
        ("Next week. What is the fee?", None),
        ("Talk to onboarding manager", None),
        ("What's my status?", None),
        ("I would like 6% on the dispatch fee. It is easier for me that way.", None),
        ("Can I send my documents while I wait?", None),
    ]
    s3 = run_script("S3 hotshot own MC negotiate", s3_steps)
    # upload COI
    sid = s3["session"]
    try:
        up = post_file(
            f"/v1/session/{sid}/attachment",
            "coi.pdf",
            b"%PDF-1.4 fake COI for scenario test\n",
        )
        s3["upload"] = up
        print(f"  UPLOAD: {json.dumps(up)[:200]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        s3["upload"] = {"error": str(exc)}
        print(f"  UPLOAD ERR: {exc}", flush=True)
    r = turn(sid, "Has it been approved?")
    s3["turns"].append(r)
    print(f"  IN: Has it been approved?\n  OUT: {(r.get('out') or r.get('error') or '')[:180]}", flush=True)
    results["s3_hotshot_negotiate"] = s3

    # 4. Dry van → lease-on → coverage → corrected mileage
    results["s4_dryvan_mileage_correct"] = run_script(
        "S4 dry van mileage correct",
        [
            ("I need dispatch", None),
            ("Dry van", None),
            ("53 ft", {"label": "53 ft", "field": "trailerLength", "value": "53 ft"}),
            (
                "I want to lease on",
                {
                    "label": "I want to lease on",
                    "field": "mcOwnership",
                    "value": "no_own_mc",
                    "requestedArrangement": "lease_on",
                },
            ),
            (
                "I have my own insurance",
                {"label": "I have my own insurance", "field": "insurance", "value": "own_insurance"},
            ),
            (
                "Auto + cargo",
                {"label": "Auto + cargo", "field": "coverageTypes", "value": "auto_and_cargo"},
            ),
            ("Local work", {"label": "Local work", "field": "operatingMode", "value": "local"}),
            ("400-500", {"label": "400-500", "field": "milesPerDay", "value": "400-500"}),
            ("500-600", None),
            ("Yes", None),
            ("Atlanta", None),
            ("Yes", None),
            ("I'm ready now", None),
        ],
    )

    # 5. Nightly home time — accept path then reject path (two sessions)
    results["s5a_home_time_accept"] = run_script(
        "S5a home every night → weekends ok",
        [
            ("I need to be home every night.", None),
            ("Weekends at home would work.", None),
        ],
    )
    results["s5b_home_time_reject"] = run_script(
        "S5b home every night → must nightly",
        [
            ("I need to be home every night.", None),
            ("No, I have to return home every night.", None),
            ("I'm ready to start", None),
        ],
    )

    # 6. Manager accept takeover — reuse hotshot-like short path then staff act
    s6 = run_script(
        "S6 manager accept",
        [
            ("30 ft hotshot with own MC, local Dallas", None),
            ("Talk to onboarding manager", None),
            ("Has the manager joined?", None),
        ],
    )
    case_id = None
    for t in reversed(s6["turns"]):
        if t.get("case_id"):
            case_id = t["case_id"]
            break
    if not case_id:
        # force create via ready/handoff
        r = turn(s6["session"], "Talk to onboarding manager")
        s6["turns"].append(r)
        case_id = r.get("case_id")
    s6["case_id"] = case_id
    if case_id:
        try:
            act = post(f"/v1/cases/{case_id}/act", {"act": "takeover"})
            s6["takeover_act"] = {"ok": True, "status": act.get("status"), "next_action": act.get("next_action")}
            print(f"  STAFF takeover: {act.get('status')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            s6["takeover_act"] = {"error": str(exc)}
            print(f"  STAFF ERR: {exc}", flush=True)
        r = turn(s6["session"], "Has the manager joined?")
        s6["turns"].append(r)
        print(f"  IN: Has the manager joined?\n  OUT: {(r.get('out') or r.get('error') or '')[:180]}", flush=True)
        # get session flags
        try:
            sess = json.loads(
                urllib.request.urlopen(BASE + f"/v1/session/{s6['session']}", timeout=30).read().decode()
            )
            s6["session_after"] = {
                "takeover": sess.get("takeover"),
                "manager_requested": sess.get("manager_requested"),
                "manager_accepted": sess.get("manager_accepted"),
            }
        except Exception as exc:  # noqa: BLE001
            s6["session_after"] = {"error": str(exc)}
    else:
        s6["takeover_act"] = {"error": "no case_id"}
        print("  NO case_id for takeover", flush=True)
    results["s6_manager_accept"] = s6

    OUT.write_text(json.dumps(results, indent=2))
    print(f"\nWROTE {OUT}", flush=True)

    # Compact markdown for human compare
    lines = ["# Ideal scenario replay results\n"]
    for key, block in results.items():
        lines.append(f"## {key}\n")
        for t in block.get("turns") or []:
            lines.append(f"**Driver:** {t.get('in')}\n")
            lines.append(f"**Bot:** {t.get('out') or t.get('error')}\n")
            chips = t.get("chips") or []
            if chips:
                labels = ", ".join(c.get("label") or "?" for c in chips[:6])
                lines.append(f"*Chips:* {labels}\n")
            lines.append("")
        if block.get("upload"):
            lines.append(f"Upload: `{json.dumps(block['upload'])[:300]}`\n")
        if block.get("takeover_act"):
            lines.append(f"Takeover act: `{json.dumps(block['takeover_act'])}`\n")
        if block.get("session_after"):
            lines.append(f"Session after: `{json.dumps(block['session_after'])}`\n")
        lines.append("")
    REPORT.write_text("\n".join(lines))
    print(f"WROTE {REPORT}", flush=True)


if __name__ == "__main__":
    # wait for server
    for i in range(60):
        try:
            urllib.request.urlopen(BASE + "/v1/health", timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("server not up")
    main()
