# Portable Qwen CPU profile

Branch: `perf/portable-cpu-qwen`. Baseline: `b4bfb55` on `master`.

Every accepted conversational turn makes one Qwen request, including repeated
messages. There is no answer cache, model bypass, distillation, or second model.
An overloaded request receives HTTP 503 with `Retry-After: 2`, without a rules-only
reply. Transport or invalid-model-output failures retain the existing explicit
`rules_fallback` trace; do not count these turns as successful Qwen inference.

## Changes

- Send current fact values rather than recursive audit/version/source history.
  User text and current values are preserved. The system prompt and schema stay
  identical across turns, allowing the runtime to reuse prefixes where supported.
- Use Ollama JSON Schema constrained decoding and validate against the same
  Pydantic schema. Optional empty fields can be omitted. Model output cannot
  assign evidence/verification status. Truncated JSON is rejected, not repaired.
- Default to CPU (`num_gpu=0`). Choose up to eight threads, respecting process
  affinity and standard Linux cgroup CPU quotas. Explicit thread overrides support
  measured tuning. CPU instruction selection remains Ollama's responsibility.
- Retain one active inference by default, with eight bounded waiting requests and
  a 15-second queue deadline. This avoids unbounded queuing/CPU oversubscription.
  Queue rejection and task cancellation release reservations correctly.
- Retain HTTP connection reuse and the existing non-thinking/warm-model settings,
  warm Qwen before building the retrieval index, and close the client at shutdown.
- Add per-turn queue/request/model-load/prefill/decode timing and token counts to
  the `propose` trace. Logs contain timing only, not prompts or model responses.

The output budget is 256 tokens (previously 180). This is a ceiling, not a target:
valid short JSON ends sooner. The extra capacity protects multi-fact turns from
truncation. The context remains 2048. Neither smaller context nor a hard lower
output ceiling should be advertised as a free accuracy-preserving speedup.

## Local test

In a separate checkout of the branch, use your existing virtual environment or:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Keep your existing Ollama service running. Confirm the exact model is installed
with `ollama list`. No model download or replacement occurs automatically.
Start the API on another port to avoid replacing the current demo:

```bash
QWEN_NUM_GPU=0 python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788/`. The existing scenario script can target it:

```bash
python scripts/five_scenarios.py http://127.0.0.1:8788
```

A separate checkout gives separate local SQLite files; do not copy production
data, OAuth tokens, or a credential-bearing `.env` into this test checkout. The
existing scenario script creates local cases/outbox items. For inference-only
measurement with **no CRM/session writes**, run the benchmark instead.

## Tune on the actual CPU

Stop other inference workloads while benchmarking. Start with the automatic
thread choice, then test a few counts within the Ollama host's available cores:

```bash
python scripts/benchmark_cpu.py --repeats 2 --output /tmp/qwen-cpu-auto.json
python scripts/benchmark_cpu.py --threads 1,2,4 --repeats 3 --output /tmp/qwen-cpu-sweep.json
```

The sweep warms each setting and runs five extraction/multi-intent canaries.
It reports wall-clock p50/p95, token counts, model durations, schema failures,
model digest/quantization when available, and proposes a thread count only when
all canaries pass. A full sweep can take many minutes on a slow CPU. Re-run the
winning candidates with more repetitions before selecting a deployment profile.
The benchmark deliberately does not change configuration automatically.

Use the selected value on restart, for example `QWEN_NUM_THREAD=4`. If Ollama
runs on a different machine, automatic sizing describes the API host: explicitly
set threads to a measured value for the **Ollama host**.

Keep Ollama's own concurrency consistent with the API. For a dedicated CPU
service, start Ollama with `OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1`.
These are **Ollama service settings**; setting them on Uvicorn does not change an
already running Ollama service. A single resident model may cause the existing
embedding model to evict Qwen; measure that path before choosing this setting.
Prefer a separate embedding service or a memory-qualified two-model setup if
hybrid retrieval is frequently used. Do not disable retrieval solely for a nicer
inference benchmark. Keep one Uvicorn worker on a single shared CPU model: each
worker has a separate admission queue and does not create more model capacity.

| API environment variable | Default | Purpose |
| --- | --- | --- |
| `QWEN_NUM_THREAD` | affinity/quota-aware, at most 8 | Decode CPU threads |
| `QWEN_NUM_GPU` | 0 | CPU profile; explicit GPU opt-in if later needed |
| `QWEN_NUM_CTX` | 2048 | Context ceiling |
| `QWEN_NUM_PREDICT` | 256 | Output token ceiling |
| `QWEN_MAX_INFLIGHT` | 1 | Per-process active model requests |
| `QWEN_MAX_WAITING` | 8 | Per-process queue slots |
| `QWEN_QUEUE_TIMEOUT_SEC` | 15 | Wait deadline; then HTTP 503 |
| `QWEN_TIMEOUT_SEC` | 90 | HTTP operation timeout |
| `QWEN_KEEP_ALIVE` | 30m | Warm model retention |
| `QWEN_MODEL` | qwen3.5:2b | Installed checkpoint/tag |
| `OLLAMA_URL` | http://127.0.0.1:11434 | Inference service |

Quantization is part of the installed model artifact, not a Python setting.
The benchmark records it when Ollama exposes it. Compare a supported Q4 model
with the existing checkpoint using the same canaries before replacing anything.
This patch does not manufacture a quantized model or guarantee AVX/ARM speedups.

## Acceptance and limits

Compare `master` and this branch on the same CPU, exact model digest, RAM,
thread count, prompts, and warm/cold conditions. Track full `/v1/turn` wall time
as well as model timing, and reject faster settings that fail case/fee/guarantee
regressions or introduce `rules_fallback`. Re-run the five real sales flows with
Qwen connected; mocked transport tests do not establish model accuracy.

This profile does not certify seconds-per-turn or 8,000 concurrent calls. No
actual Qwen latency was measured in the development environment because Ollama
was unavailable. A thread sweep plus full API/concurrency measurement on the
Dell is still required. Synchronous CRM work, retrieval embedding contention,
SQLite concurrency, and the pre-existing staff/auth/static-file/CRM verification
issues are outside this CPU patch. Keep testing on localhost; those previously
identified security and integrity defects still require fixes before deployment.
