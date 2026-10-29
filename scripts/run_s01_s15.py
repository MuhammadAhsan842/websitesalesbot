#!/usr/bin/env python3
"""Replay S01–S15 ideal scripts against live API; dump exact actuals + eval fields."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/agoc_s01_s15_results.json")
PLAIN = Path("/tmp/agoc_s01_s15_plain.md")


def post(path: str, body: dict, timeout: int = 220) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def new_session() -> dict:
    return post("/v1/session", {})


def turn(sid: str, text: str, chip: dict | None = None) -> dict:
    body: dict = {"session_id": sid, "text": text}
    if chip:
        body["chip"] = chip
    t0 = time.time()
    last_exc: Exception | None = None
    out = None
    for attempt in range(4):
        try:
            out = post("/v1/turn", body)
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc)
            if "503" in msg or "timed out" in msg.lower():
                time.sleep(3 + attempt * 2)
                continue
            return {"in": text, "chip": chip, "error": msg, "ms": int((time.time() - t0) * 1000)}
    if out is None:
        return {"in": text, "chip": chip, "error": str(last_exc), "ms": int((time.time() - t0) * 1000)}
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
        "desk": out.get("desk"),
        "ms": int((time.time() - t0) * 1000),
    }


SCENARIOS = [
    (
        "S01",
        [
            "I have a 26-ft box truck, my own MC for one year, auto and cargo insurance, and I'm based in Dallas. I want local work.",
            "400–500 miles per day.",
            "Monday–Friday with weekends home works for me. I'm ready to start next week.",
            "Which documents should I provide?",
            "Do I need a notice of assignment if I don't use factoring?",
        ],
    ),
    (
        "S02",
        [
            "I want to lease on with my 53-ft reefer. I have commercial auto and cargo insurance.",
            "OTR.",
            "Monday–Friday is fine. I'll start from Atlanta.",
            "I'm ready to start. What paperwork do you need?",
            "Can I ask about the agreement while insurance is being reviewed?",
        ],
    ),
    (
        "S03",
        [
            "I want to lease on with a 53-ft dry van.",
            "I have my own insurance.",
            "Auto + cargo.",
            "Local work.",
            "400–500.",
            "Actually, make that 500–600 miles per day. I'll start from Houston.",
            "I'm ready to start. What documents come next?",
        ],
    ),
    (
        "S04",
        [
            "I run a 30-ft hotshot under my own MC and have insurance.",
            "Auto + cargo.",
            "About five months.",
            "About five months.",
            "Correction—my MC is over one year old. I want local work from Dallas.",
            "400–500 miles per day. I'm ready next week.",
        ],
    ),
    (
        "S05",
        [
            "My own MC is pending, but I want to lease on for now. I have a 26-ft box truck.",
            "I have auto and cargo insurance, but registration isn't here yet. I have a temporary tag.",
            "I only want local loads from Atlanta, around 400 miles per day.",
            "I'm ready today. Can I start before registration arrives?",
            "What should I send to the onboarding manager?",
        ],
    ),
    (
        "S06",
        [
            "I have a refeer 53 ft and need dispatch.",
            "Not sure about my MC.",
            "I have a number, but I don't know whether the authority is active.",
            "I have insurance and want OTR. I'm ready to start.",
            "Which authority document would help?",
        ],
    ),
    (
        "S07",
        [
            "I have a 26-ft box truck, own MC, auto and cargo insurance. I want local work from Dallas.",
            "I can drive 500 miles in a day, but I want to stay within 150 miles of Dallas.",
            "The 150 is my radius, not what I can drive in a day.",
            "Monday–Friday is fine. I'm ready to start.",
            "What documents do you need for my own MC?",
        ],
    ),
    (
        "S08",
        [
            "I want to lease on with a 53-ft dry van. I have auto and cargo insurance and prefer OTR.",
            "What schedule do you offer?",
            "That schedule works. I'll start from Charlotte.",
            "I'm ready to start next Monday. Send me the document list.",
            "Does that mean a load is guaranteed for Monday?",
        ],
    ),
    (
        "S09",
        [
            "I have a 30-ft hotshot, my own MC and insurance. I want local work from Dallas.",
            "I need to return home every night. That's essential.",
            "No, weekends only won't work. I must be home each night.",
            "I'm ready to start, but only with nightly home time.",
            "Should I still send my documents?",
        ],
    ),
    (
        "S10",
        [
            "I have a 26-ft box truck, own MC for a year, auto and cargo insurance, based in Dallas. Local, 400 miles a day.",
            "What's your fee?",
            "I can do 6%, and I'm ready to start.",
            "Talk to onboarding manager.",
            "While I wait, what documents should I prepare?",
            "So is my 6% approved?",
        ],
    ),
    (
        "S11",
        [
            "I want to lease on with a 26-ft box truck. I have insurance.",
            "Only commercial auto. I don't have cargo coverage.",
            "I want local work from Atlanta and can drive 400 miles per day.",
            "My agent says cargo has now been added.",
            "I'm ready. Does this mean my insurance is approved?",
            "What document should I upload?",
        ],
    ),
    (
        "S12",
        [
            "I have a 53-ft dry van, my own MC, auto and cargo insurance, based in Memphis. OTR and Monday–Friday works.",
            "I'm ready to start. What do I send?",
            "I already sent the COI and W-9.",
            "Are my papers approved?",
            "What's still missing?",
        ],
    ),
    (
        "S13",
        [
            "I run a 30-ft hotshot under my own MC, have auto and cargo, and start from Houston. I want OTR.",
            "I use a factoring company and I'm ready to start.",
            "What's the notice of assignment, and do you need mine?",
            "Does factoring mean you pay me within 24 hours?",
            "If I stop factoring later, will the paperwork change?",
        ],
    ),
    (
        "S14",
        [
            "I want to lease on with a 53-ft reefer. I have auto and cargo insurance, prefer local from Atlanta, and can drive 400 miles per day.",
            "Monday–Friday with weekends home is fine. I'm ready.",
            "Talk to onboarding manager.",
            "Please update my mileage to 500–600 per day.",
            "What documents should I prepare while I wait?",
            "Has someone accepted my request yet?",
        ],
    ),
    (
        "S15",
        [
            "I have two trucks: a 26-ft box truck for own-MC dispatch and a 53-ft dry van I want to lease on.",
            "Start with the box truck. It has auto and cargo insurance, is based in Dallas, and can run 400 miles per day locally.",
            "Monday–Friday works. I'm ready to start with that truck.",
            "Which paperwork is for the box truck and which is for the lease-on dry van?",
            "The insurance I mentioned is only for the box truck. The dry van policy isn't ready.",
            "Can both start after you review the box truck documents?",
        ],
    ),
]


def run_one(name: str, messages: list[str]) -> dict:
    print(f"\n=== {name} ===", flush=True)
    s = new_session()
    sid = s["session_id"]
    turns = [
        {
            "in": "(session open)",
            "out": s.get("text"),
            "chips": [
                {"label": c.get("label"), "field": c.get("field"), "value": c.get("value")}
                for c in (s.get("chips") or [])
                if isinstance(c, dict)
            ],
        }
    ]
    for text in messages:
        r = turn(sid, text)
        turns.append(r)
        preview = (r.get("out") or r.get("error") or "")[:160].replace("\n", " ")
        print(f"  IN: {text[:80]}\n  OUT: {preview}", flush=True)
    return {"session": sid, "turns": turns, "case_id": (turns[-1] or {}).get("case_id")}


def _load_results() -> dict:
    if not OUT.exists():
        return {}
    try:
        data = json.loads(OUT.read_text())
        data.pop("_progress", None)
        return data
    except Exception:
        return {}


def _save_results(results: dict, progress: str | None = None) -> None:
    payload = dict(results)
    if progress:
        payload["_progress"] = progress
    OUT.write_text(json.dumps(payload, indent=2))


def main() -> None:
    results: dict = _load_results()
    for name, messages in SCENARIOS:
        done = results.get(name) or {}
        # complete = welcome + all driver messages
        if done.get("turns") and len(done["turns"]) >= len(messages) + 1:
            print(f"SKIP {name} (already have {len(done['turns'])} turns)", flush=True)
            continue
        results[name] = run_one(name, messages)
        _save_results(results, progress=name)
        print(f"CHECKPOINT {name} -> {OUT}", flush=True)

    lines = ["# S01–S15 ACTUAL transcripts\n"]
    for name, _ in SCENARIOS:
        block = results.get(name) or {}
        lines.append(f"\n## {name}\n")
        for t in block.get("turns") or []:
            lines.append(f"**Driver:** {t.get('in')}\n\n**Assistant:** {t.get('out') or t.get('error')}\n\n")
            chips = t.get("chips") or []
            if chips:
                lines.append(f"*Chips:* {' · '.join(c.get('label') or '?' for c in chips)}\n\n")
            if t.get("ms"):
                lines.append(f"*Latency:* {t.get('ms')} ms | mgr_req={t.get('mgr_req')} mgr_acc={t.get('mgr_acc')} case={t.get('case_id')}\n\n")
    PLAIN.write_text("".join(lines))
    print(f"WROTE {OUT}\nWROTE {PLAIN}", flush=True)


if __name__ == "__main__":
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/v1/health", timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("server not up")
    main()
