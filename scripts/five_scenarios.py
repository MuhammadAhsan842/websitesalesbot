"""Replay the five live sales scenarios against http://127.0.0.1:8787."""

from __future__ import annotations

import json
import re
import sys
from time import perf_counter
import urllib.request

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"

SCENARIOS = [
    (
        "SCENARIO 1 — Own-MC fit check → setup packet",
        [
            "I need dispatch",
            "I run one hotshot with my own MC in Texas, paperwork, start next week",
            "I'm ready to start",
        ],
    ),
    (
        "SCENARIO 2 — Fee / competitor 6% before interview",
        [
            "What do you charge? Can you do 6% like Leo Dispatch?",
            "I have my own MC",
        ],
    ),
    (
        "SCENARIO 3 — Earnings guarantee + keep loaded",
        ["Can you guarantee $10,000 a week and keep me loaded?"],
    ),
    (
        "SCENARIO 4 — Call me callback + status",
        ["Call me at 469-555-0199", "What's my status?"],
    ),
    (
        "SCENARIO 5 — Lease-on + daily home time → lease task",
        [
            "I want to lease on. I have to be home every night.",
            "One box truck, Atlanta, start next week",
            "I'm ready to start",
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
    started = perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.load(resp)
        result["_wall_ms"] = round((perf_counter() - started) * 1000, 2)
        return result


def session() -> dict:
    return post("/v1/session", {})


def summarize(text: str, out: dict) -> dict:
    traces = out.get("traces") or []
    pr = next((t for t in traces if t.get("stage") == "propose"), {})
    kn = next((t for t in traces if t.get("stage") == "knowledge"), {})
    ex = next((t for t in traces if t.get("stage") == "execute"), {})
    rp = next((t for t in traces if t.get("stage") == "reply"), {})
    zo = out.get("zoho") or {}
    latest = zo.get("latest") or {}
    reply = out.get("text") or ""
    return {
        "user": text,
        "reply": reply,
        "chips": out.get("chips") or [],
        "case_id": out.get("case_id"),
        "channel": out.get("channel"),
        "state": out.get("conversation_state"),
        "propose": pr.get("source"),
        "model": pr.get("model"),
        "wall_ms": out.get("_wall_ms"),
        "qwen_timing": pr.get("timing") or {},
        "intent": pr.get("intent"),
        "knowledge_keys": kn.get("keys"),
        "hybrid": kn.get("hybrid_rerank"),
        "execute": ex.get("action"),
        "second_pass": rp.get("second_pass"),
        "zoho_kind": latest.get("kind"),
        "zoho_status": latest.get("status"),
        "zoho_verified": zo.get("verified"),
        "leaks": {
            "6%": "6%" in reply,
            "$amount": bool(re.search(r"\$\s*\d", reply)),
            "approved": bool(re.search(r"you('re| are) approved|insurance is approved", reply, re.I)),
            "coi_valid": bool(re.search(r"coi is valid", reply, re.I)),
            "guaranteed_earn": bool(re.search(r"we guarantee|guaranteed \$", reply, re.I)),
        },
    }


def dump(title: str, rows: list[dict]) -> None:
    print("\n" + "=" * 72, flush=True)
    print(title, flush=True)
    print("=" * 72, flush=True)
    for i, row in enumerate(rows, 1):
        print(f"\n--- turn {i} ---", flush=True)
        print("USER:", row["user"], flush=True)
        print("REPLY:", row["reply"].replace("\n", " | "), flush=True)
        print(
            "TRACE: propose=%s model=%s intent=%s keys=%s hybrid=%s exec=%s second=%s"
            % (
                row["propose"],
                row["model"],
                row["intent"],
                row["knowledge_keys"],
                row["hybrid"],
                row["execute"],
                row["second_pass"],
            ),
            flush=True,
        )
        print(
            "LATENCY: api_ms=%s qwen=%s" % (row["wall_ms"], row["qwen_timing"]),
            flush=True,
        )
        print(
            "CRM: kind=%s status=%s verified=%s case=%s channel=%s state=%s"
            % (
                row["zoho_kind"],
                row["zoho_status"],
                row["zoho_verified"],
                row["case_id"],
                row["channel"],
                row["state"],
            ),
            flush=True,
        )
        print("CHIPS:", row["chips"], flush=True)
        print("LEAKS:", row["leaks"], flush=True)


def main() -> None:
    health = json.load(urllib.request.urlopen(f"{API}/v1/health", timeout=10))
    print(
        f"API {API} model={health.get('model')} qwen_ready={health.get('qwen_ready')}",
        flush=True,
    )
    for title, lines in SCENARIOS:
        opened = session()
        sid = opened["session_id"]
        print(f"\nOpened {sid} for {title}", flush=True)
        rows = []
        for line in lines:
            out = post("/v1/turn", {"session_id": sid, "text": line})
            row = summarize(line, out)
            rows.append(row)
            print(f"  [{row['propose']}/{row['intent']}] {line[:60]}", flush=True)
        dump(title, rows)


if __name__ == "__main__":
    main()
