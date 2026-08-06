---
name: rocm-autopilot
description: Drive rocm-autopilot, the self-optimizing LLM deployment agent ported to AMD Radeon/ROCm. Use when benchmarking a vLLM-ROCm deployment, running the autonomous optimization loop, porting telemetry from NVML to amdsmi, reading the run journal or leaderboard, or computing the carbon label. Triggers include rocm-autopilot, Radeon optimization, amdsmi, ROCm benchmark, joules per token, carbon label.
---

# rocm-autopilot (Gemma² Act II on Radeon)

The Gemma² loop on AMD silicon: benchmark, diagnose in plain language, act through function calling, re-benchmark, with energy metering and a gCO2e/1k-tokens label. Motto: measured, not assumed.

## Discovery first (never skip on a fresh instance)

```bash
rocminfo | grep gfx            # gfx target
amd-smi static                 # GPU model, VRAM
amd-smi metric                 # does an energy accumulator exist? power readable?
curl -s localhost:8000/v1/models   # native vLLM-ROCm serving on the Radeon Cloud
```

## Run

```bash
# server: the Radeon Cloud ships vLLM on port 8000; otherwise:
vllm serve $BENCH_MODEL --port 8000 --max-model-len 16384 \
  --gpu-memory-utilization 0.92 --enable-auto-tool-choice \
  --tool-call-parser gemma4 --reasoning-parser gemma4 \
  --chat-template tool_chat_template_gemma4.jinja   # if Gemma-4 brain/workload

export BENCH_MODEL=... BENCH_PRECISION=... BRAIN_MODEL=...   # see .env.example
python3 -m autopilot.agent --iters 5    # journal in runs/, dashboard reads runs/state.json
```

## Port state and rules

- Telemetry port design and fallback tree: `docs/private/port-notes.md` (energy counter → power x time integration → TBP estimate, each labeled honestly in RunResults).
- Never invent metrics; an unavailable sensor is reported, not simulated.
- Benchmark only against a server that answers `/v1/models` (a compiling or dead server yields zeros).
- Agent explanations arrive in `reasoning_content` when reasoning parsers are on, not `content`.
- `pkill` patterns must not self-match: use the bracket trick, e.g. `pkill -f 'vllm serv[e]'`.
- Destroy the Radeon Cloud instance at the end of every session: it burns credits while idle.
