"""Replay the implemented conversation-slice checks against the live API."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"

SCENARIOS = [
    (
        "INTRO — Ayyan Group sales assistant",
        [],
        [
            ("welcome names Ayyan Group sales assistant", lambda text, facts, mem: "ayyan group's ai sales assistant" in text.lower()),
        ],
    ),
    (
        "A — Qualify + refuse Leo 6% / $5k / loads tomorrow",
        [
            "I run one hotshot with my own MC in Texas, paperwork, start next week",
            "What do you charge? Can you do 6% like Leo Dispatch?",
            "Can you guarantee $5,000 a week and loads tomorrow?",
        ],
        [
            ("no 6%", lambda text, facts, mem: "6%" not in text),
            ("no $5,000", lambda text, facts, mem: not re.search(r"\$\s*5,?000", text)),
            ("no loads tomorrow", lambda text, facts, mem: "loads tomorrow" not in text.lower()),
            ("own_mc stored", lambda text, facts, mem: (facts.get("mcOwnership") or {}).get("value") == "own_mc"),
            ("hotshot stored", lambda text, facts, mem: (facts.get("equipment") or {}).get("value") == "hotshot"),
            ("fee quoted 8% on charge turn, not recap", lambda text, facts, mem: True),  # checked per-turn below
        ],
    ),
    (
        "B — Memory: home every night is not re-asked",
        [
            "I want to lease on. I have to be home every night.",
            "One box truck, Atlanta, start next week",
        ],
        [
            ("home time stored", lambda text, facts, mem: (facts.get("supportNeed") or {}).get("value") == "daily_home_time"),
            ("hard constraint", lambda text, facts, mem: mem.get("hard_constraint") == "home_every_night"),
            ("no support re-ask", lambda text, facts, mem: "what support matters most" not in text.lower()),
            ("no truck re-ask", lambda text, facts, mem: "what are you running" not in text.lower()),
        ],
    ),
    (
        "C — Commitment concern first",
        ["I don't want to sign for nothing."],
        [
            ("commitment copy", lambda text, facts, mem: "does not guarantee a load" in text.lower()),
            ("no fit recap", lambda text, facts, mem: "you're looking for support" not in text.lower()),
        ],
    ),
    (
        "D — Net after costs",
        ["After fuel and fees, what's left?"],
        [
            ("net copy", lambda text, facts, mem: "remains after costs" in text.lower()),
            ("no invented dollar amount", lambda text, facts, mem: not re.search(r"\$\s*\d", text)),
        ],
    ),
    (
        "E — Repetition checks this chat only",
        [
            "I run one box truck in Atlanta",
            "I already sent everything.",
        ],
        [
            ("session record", lambda text, facts, mem: "on this chat" in text.lower()),
            ("no onboarding COI claim", lambda text, facts, mem: "can't see papers onboarding hasn't received" in text.lower()),
        ],
    ),
    (
        "F — Pause, no chase",
        ["I'll let you know when I'm ready."],
        [
            ("pause copy", lambda text, facts, mem: "whenever you're ready" in text.lower()),
            ("driver initiates", lambda text, facts, mem: mem.get("follow_up") == "driver_initiates"),
            ("no next question", lambda text, facts, mem: "?" not in text),
        ],
    ),
    (
        "G — Mixed-initiative fee: no hotshot/Texas recap",
        [
            "I run one hotshot with my own MC in Texas, start next week",
            "What do you charge?",
        ],
        [
            ("answers 8%", lambda text, facts, mem: "8%" in text),
            ("no fit recap", lambda text, facts, mem: "you're looking for support" not in text.lower()),
            ("no Perfect", lambda text, facts, mem: "perfect!" not in text.lower()),
        ],
    ),
    (
        "H — own MC alias + three not two",
        [
            "I have two trucks, own MC",
            "Actually three trucks, not two",
        ],
        [
            ("mc normalized", lambda text, facts, mem: (facts.get("mcOwnership") or {}).get("value") == "own_mc"),
            ("fleetSize 3", lambda text, facts, mem: (facts.get("fleetSize") or {}).get("value") == 3),
            ("no how many trucks", lambda text, facts, mem: "how many trucks" not in text.lower()),
        ],
    ),
]


def post(path: str, body: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def main() -> None:
    health = json.load(urllib.request.urlopen(f"{API}/v1/health", timeout=20))
    print(
        f"API {API} model={health.get('model')} qwen_ready={health.get('qwen_ready')} runtime={health.get('qwen_runtime')}",
        flush=True,
    )
    failed = 0
    for title, lines, checks in SCENARIOS:
        opened = post("/v1/session", {})
        sid = opened["session_id"]
        print("\n" + "=" * 72, flush=True)
        print(title, flush=True)
        print("OPEN:", opened.get("text"), flush=True)
        last_text = opened.get("text") or ""
        charge_text = ""
        for line in lines:
            out = post("/v1/turn", {"session_id": sid, "text": line})
            last_text = out.get("text") or ""
            if "charge" in line.lower() or "6%" in line:
                charge_text = last_text
            traces = out.get("traces") or []
            propose = next((t for t in traces if t.get("stage") == "propose"), {})
            plan = next((t for t in traces if t.get("stage") == "plan"), {})
            print(f"\nYOU: {line}", flush=True)
            print(f"BOT: {last_text}", flush=True)
            print(
                f"TRACE: propose={propose.get('source')} intent={propose.get('intent')} memory={plan.get('memory')}",
                flush=True,
            )
        stored = db.get_session(sid) or {}
        facts = stored.get("facts") or {}
        mem = stored.get("memory") or {}
        print(f"FACTS: { {k: (v or {}).get('value') for k, v in facts.items()} }", flush=True)
        print(f"MEMORY: {mem}", flush=True)
        for name, fn in checks:
            text = opened.get("text") or "" if not lines else last_text
            if name.startswith("fee quoted"):
                ok = "8%" in charge_text and "you're looking for support" not in charge_text.lower()
            else:
                ok = fn(text, facts, mem)
            mark = "PASS" if ok else "FAIL"
            if not ok:
                failed += 1
            print(f"CHECK {mark}: {name}", flush=True)
    if failed:
        raise SystemExit(f"{failed} checks failed")
    print("\nAll listed checks passed.", flush=True)


if __name__ == "__main__":
    main()
