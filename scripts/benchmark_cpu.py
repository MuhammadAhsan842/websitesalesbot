"""Measure real Ollama CPU inference without sessions, files, or CRM writes."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app import qwen
from app.cpu import available_cpus


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    facts: dict
    keys: tuple[str, ...] = ()


CASES = (
    Case("own_mc", "I run one hotshot with my own MC in Texas, paperwork, start next week", {"equipment": "hotshot", "fleetSize": 1, "mcOwnership": "own_mc", "operatingArea": "Texas"}),
    Case("fee", "What do you charge? Can you do 6% like Leo Dispatch?", {}, ("fee",)),
    Case("guarantee_freight", "Can you guarantee $10,000 a week and keep me loaded?", {}, ("guarantee", "freight")),
    Case("callback", "Call me at 469-555-0199", {"phone": "469-555-0199"}),
    Case("lease", "I want to lease on. I have one box truck in Atlanta and must be home every night.", {"mcOwnership": "no_own_mc", "fleetSize": 1, "equipment": "box_truck"}),
)


def correctness(proposal: qwen.Proposal, case: Case) -> list[str]:
    facts = {fact.key: fact.value for fact in proposal.facts}
    errors = [f"missing/wrong fact: {key}" for key, expected in case.facts.items() if facts.get(key) != expected]
    errors += [f"missing knowledge: {key}" for key in case.keys if key not in proposal.knowledge_keys]
    if case.name == "guarantee_freight" and "guarantee" not in proposal.blocked:
        errors.append("missing guarantee block")
    return errors


def summarize(rows: list[dict]) -> dict:
    timings = sorted(row["wall_ms"] for row in rows)
    completed = [row for row in rows if row.get("schema_valid")]
    return {
        "requests": len(rows), "schema_valid": len(completed),
        "canaries_passed": sum(row.get("canary_passed", False) for row in rows),
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": timings[max(0, math.ceil(len(timings) * .95) - 1)],
        "mean_output_tokens": round(statistics.mean(row.get("eval_count", 0) for row in completed), 2) if completed else None,
    }


async def run(args) -> dict:
    results = []
    metadata = {"model": args.model, "python": platform.python_version(), "platform": platform.system(), "api_host_available_cpus": available_cpus()}
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout, connect=5.0)) as client:
        try:
            show = await client.post(f"{args.url}/api/show", json={"model": args.model})
            show.raise_for_status()
            metadata["details"] = show.json().get("details", {})
            tags = await client.get(f"{args.url}/api/tags")
            tags.raise_for_status()
            metadata["digest"] = next((row.get("digest") for row in tags.json().get("models", []) if row.get("name") == args.model), None)
        except (httpx.HTTPError, ValueError):
            metadata["metadata_unavailable"] = True
        for threads in args.threads:
            cfg = replace(qwen.CONFIG, model=args.model, url=args.url, threads=threads, num_gpu=0)
            # Separate warm-up per setting. No model pull/quantization is performed.
            print(f"Warming model, threads={threads}", file=sys.stderr, flush=True)
            warm = await client.post(f"{args.url}/api/chat", json=qwen.request_payload("I need dispatch", {}, "understand_request", cfg))
            warm.raise_for_status()
            warm_body = warm.json()
            qwen.Proposal.model_validate_json(warm_body.get("message", {}).get("content", ""))
            rows = []
            for repeat in range(args.repeats):
                for case in CASES:
                    started = perf_counter()
                    row = {"case": case.name, "repeat": repeat + 1, "schema_valid": False, "canary_passed": False}
                    try:
                        response = await client.post(f"{args.url}/api/chat", json=qwen.request_payload(case.text, {}, "understand_request", cfg))
                        response.raise_for_status()
                        body = response.json()
                        if body.get("done_reason") == "length":
                            raise ValueError("output truncated")
                        proposal = qwen.Proposal.model_validate_json(body.get("message", {}).get("content", ""))
                        errors = correctness(proposal, case)
                        row.update(schema_valid=True, canary_passed=not errors, errors=errors)
                        for key in ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration", "prompt_eval_count", "eval_count"):
                            row[key] = body.get(key, 0)
                    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                        # Exception class only: never save a model response or credential.
                        row["error"] = type(exc).__name__
                    row["wall_ms"] = round((perf_counter() - started) * 1000, 2)
                    rows.append(row)
                    print(f"threads={threads} {case.name}: {row['wall_ms']}ms pass={row['canary_passed']}", file=sys.stderr, flush=True)
            results.append({"threads": threads, "summary": summarize(rows), "samples": rows})
    qualified = [result for result in results if result["summary"]["canaries_passed"] == result["summary"]["requests"]]
    best = min(qualified, key=lambda result: result["summary"]["p95_ms"]) if qualified else None
    return {"metadata": metadata, "note": "Warm sequential inference only; not full API, concurrency, voice, or statistical accuracy certification.", "suggested_threads": best["threads"] if best else None, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=qwen.OLLAMA)
    parser.add_argument("--model", default=qwen.MODEL)
    parser.add_argument("--threads", default=str(qwen.CONFIG.threads), help="Comma-separated thread counts; only one tested at a time")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, help="Optional local JSON report")
    args = parser.parse_args()
    try:
        args.threads = list(dict.fromkeys(int(value) for value in args.threads.split(",")))
        if not args.threads or any(value < 1 or value > 1024 for value in args.threads) or args.repeats < 1 or args.timeout <= 0:
            raise ValueError()
    except ValueError:
        parser.error("Use positive threads (1..1024), repeats, and timeout")
    args.url = args.url.rstrip("/")
    try:
        result = asyncio.run(run(args))
    except (httpx.HTTPError, ValueError) as exc:
        parser.exit(1, f"Ollama warm-up failed: {type(exc).__name__}; check model/runtime compatibility and availability.\n")
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    if result["suggested_threads"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
