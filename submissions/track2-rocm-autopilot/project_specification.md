# Project Specification : rocm-autopilot

Track 2 · Development & Local Deployment of Private AI Agents

## 1. Application scenarios

Anyone deploying an LLM on a GPU faces the same questions: which serving configuration, which batch pressure, which caching, at what energy cost? The honest answer is workload-dependent and hardware-dependent, and almost nobody re-measures. rocm-autopilot is a **private, fully local deployment engineer**: an agent that lives next to your vLLM endpoint on an AMD Radeon GPU, benchmarks it against your real (possibly confidential) workload, explains its diagnosis in plain language, and converges to the best configuration under an explicit latency guardrail, with joules per token and a carbon label as first-class metrics.

Scenarios: private/on-prem LLM deployments (legal, medical, IP-sensitive drafting), edge/workstation Radeon deployments, and any team that wants deployment tuning with evidence instead of folklore.

## 2. Agent architecture

```
┌─────────────────────────── AMD Radeon GPU (gfx1100, 48 GB) ───────────────────────────┐
│                                                                                        │
│   vLLM-ROCm server (port 8000) ◄────────────── serves ──────────────┐                  │
│   Qwen3-14B bf16 · TRITON_ATTN                                      │                  │
│        ▲            ▲                                               │                  │
│        │ restart    │ OpenAI-compatible chat + native tool calls    │                  │
│        │ (health-   │                                               │                  │
│        │  checked,  │                                               │                  │
│        │  rollback) │                                               │                  │
│  ┌─────┴────────────┴─────┐     the brain IS the deployment         │                  │
│  │  Agent loop (Python)   │  ── every benchmark measures the ───────┘                  │
│  │  diagnose → act → re-  │     server that produces its reasoning                     │
│  │  measure, one tool at  │                                                            │
│  │  a time, guardrailed   │                                                            │
│  └───┬────────┬───────┬───┘                                                            │
│      │        │       │                                                                │
│  ┌───▼───┐ ┌──▼───┐ ┌─▼──────────┐                                                     │
│  │ bench │ │ tele-│ │ journal    │                                                     │
│  │ runner│ │ metry│ │ + leader-  │                                                     │
│  │ (vllm │ │ (amd-│ │ board      │──► runs/state.json ──► dashboard (HTML, local)      │
│  │ bench │ │ smi) │ │ + carbon   │                                                     │
│  │ serve)│ │      │ │ label A-G  │                                                     │
│  └───────┘ └──────┘ └────────────┘                                                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Modules (all in `src/autopilot/`): `agent.py` (loop, native tool calling with JSON fallback), `tools.py` (whitelist, bounds, dispatch), `bench_runner.py` (vllm bench serve + energy annotation), `power.py` (amdsmi backend, power-integration energy meter), `journal.py` (persistent journal, leaderboard, dashboard state), `carbon.py` (gCO2e/1k tokens and A-G label). `scripts/restart_vllm.sh` relaunches the deployment with health checks and automatic rollback to the last good configuration.

## 3. Core capabilities

- **Tool invocation** with least-privilege guardrails: every argument bounds-checked; rejections are explanatory strings the model reads and corrects from (demonstrated live: the TTFT-violation recovery).
- **Multi-step task planning** with an explicit convergence criterion (report_done when expected gains < 3%).
- **Local multi-turn memory**: journal persisted across sessions; the leaderboard and dashboard rebuild from disk.
- **Privacy**: benchmark prompts are a confidential-drafting workload; model, telemetry, journal and dashboard are all local. No remote API in the loop.

## 4. Model & local deployment plan

- Deployment: vLLM 0.16.1 ROCm (Radeon Cloud "vLLM-dev Navi" image), single gfx1100, `--max-model-len 8192`, hermes tool parser, model Qwen/Qwen3-14B bf16 (28 GB weights in 48 GB VRAM).
- The agent brain is the deployed model itself (thinking disabled for decision latency); restarts are health-checked with rollback so explorations cannot kill the brain.
- Gemma-4 (Act I family) is blocked on this build by three documented dead ends (no native arch, transformers-fallback native crash, w4a16 group-32 kernel gap on gfx1100): exact errors in `src/docs/findings.md`.

## 5. Inference-speed optimization on AMD Radeon (measured)

Baseline (vLLM defaults, mns 256, conc 8): 84.6 tok/s · TTFT 388 ms · 2.042 J/tok · label C.
After 4 agent iterations (mns 128, prefix caching ON, conc 32): **260.9 tok/s (x3.08) · TTFT 367 ms · 0.649 J/tok (-68%) · label A**.

Method transparency: energy = socket power (amdsmi) integrated at 2 Hz (`power_integration`; the SKU's energy accumulator is dead and we say so). Controls: cold-start vs steady-state TTFT isolated (990 vs 367 ms: prefix-cache exploitation, labeled on every claim); attention-backend sweep (4 backends, all functional on gfx1100, within 0.4% throughput; ROCM_ATTN most frugal). Carbon label: measured J/token x 571 gCO2e/kWh (China grid 2023, Ember, static documented factor) → A-G bands on the leaderboard.

## 6. Team

Wilfred Doré: port design, measurements, submission. Built on our own Apache-2.0 gemma-autopilot (Build with Gemma Hackathon winner, July 2026); lineage stated openly.
