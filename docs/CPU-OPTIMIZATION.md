# Portable Qwen CPU profile

Ported from `perf/portable-cpu-qwen` onto the current graph. Baseline: `b4bfb55` on `master`.

Every accepted conversational turn makes one Qwen request. Overloaded requests receive HTTP 503 with `Retry-After: 2`. Transport or invalid-model-output failures keep the existing `rules_fallback` trace.

## What this profile changes

- Send current fact values rather than recursive audit/version/source history.
- Use Ollama JSON Schema constrained decoding and validate with Pydantic. The model cannot assign evidence status.
- Leave GPU offload to Ollama unless `QWEN_NUM_GPU` is set. `QWEN_NUM_GPU=0` forces the portable CPU profile. Choose up to eight threads, respecting affinity and cgroup quota.
- One active inference by default, eight waiting slots, 15-second queue deadline.
- Warm Qwen before building the retrieval index. Close the HTTP client at shutdown.
- Per-turn queue/request/prefill/decode timing on the `propose` trace.

The output budget is 256 tokens (previously 180). That is a ceiling, not a target. Context remains 2048.

This profile did not measure live seconds-per-turn in the original patch environment because Ollama was unavailable there. Measure on this machine:

```bash
python scripts/benchmark_cpu.py --threads 1,2,4 --repeats 2
```
