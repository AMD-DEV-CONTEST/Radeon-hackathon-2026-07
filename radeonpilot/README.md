# RadeonPilot

**AMD AI DevMaster Radeon GPU Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents**

RadeonPilot is a multi-agent console that performs the full inference-operations
loop on a single AMD Radeon GPU: **diagnose** the ROCm environment, **deploy** a
local model endpoint, **benchmark** it, **locate** bottlenecks, and **propose**
validated optimizations — with every agent generation served by the Radeon itself.

The design mirrors AMD's own ROCm.AI direction (agent-driven GPU workflows) while
running entirely on a private, localhost-bound stack. It never commands real
hardware; it recommends, explains, measures, and audits.

---

## Why this scenario

Most Track 2 entries cluster around document processing. RadeonPilot targets a
blank niche — **GPU inference operations** — that directly exercises every Track 2
capability and is native to this hackathon's hardware:

- The agents themselves run on the local Radeon endpoint, so the "Radeon core
  inference" requirement is satisfied by construction.
- Optimization is measurable: baseline vs optimized vs quantized numbers are
  captured by a benchmark runner, not invented.
- Privacy, latency, and human-approval gates all matter at once, which is exactly
  what a private AI agent should demonstrate.

---

## Architecture at a glance

```
Gradio Ops Console (127.0.0.1)
   |
Python controller (src/radeonpilot)
   |-- deterministic tools   (rocm-smi / amd-smi / endpoint probes / permission gates)
   |-- local BM25 RAG        (data/knowledge/*.md)
   |-- SQLite memory + audit (runtime/radeonpilot.sqlite3)
   |-- Pi bridge HTTP client
   v
Localhost Pi bridge (pi-bridge, Node 22)
   |-- EnvDoctor  |  DeployPlanner  |  BenchmarkRunner  |  OptimAnalyst
   |                       (parallel Pi sessions)
   v                        \
   |                         OpsCommander (synthesis + gated action plan)
   v
Local OpenAI-compatible endpoint on the Radeon (vLLM BF16 or llama.cpp GGUF)
```

Five agent roles run through Pi Agent Harness 0.83.0. All Pi file/shell/edit/
browser/network tools are disabled; agents only see the evidence pack prepared by
the Python controller. Hazardous actions are blocked pending human approval.

---

## Execution modes

| Mode | What it does | Radeon claim |
| --- | --- | --- |
| `demo` | Fully local, labelled synthetic; runs on any machine without a GPU | GPU UNATTESTED |
| `pi` | Real multi-agent generation over a local ROCm endpoint | Attested only if the endpoint PID appears in `amd-smi process --pid` on a Radeon device |

The `pi` mode **fails closed**: if the Pi bridge or the model endpoint is down it
reports the failure and never silently substitutes demo output.

---

## Environment configuration

Reference hardware (the organiser-provided Radeon Cloud instance used here):

| Item | Value |
| --- | --- |
| GPU | 1x AMD Radeon, gfx1100 (RDNA3), 48 GB VRAM |
| ROCm | 7.2.1 |
| OS | Ubuntu 24.04 |
| CPU / RAM | 128 cores / 503 GB |
| Docker | not available (deployment uses venv / source-built binaries) |

### Dependencies

- Python 3.11+ and `gradio` (see `requirements.txt`)
- Node.js 22.19+ for the Pi bridge (`pi-bridge/package.json` pins Pi Agent Harness 0.83.0)
- ROCm 7.2.1 with `rocm-smi` / `amd-smi` on PATH
- Model endpoint: llama.cpp ROCm build (GGUF), the verified engine on this
  instance; a vLLM ROCm path is documented but vLLM 0.26.0 ships no ROCm wheel,
  so on this Docker-less gfx1100 box it requires a source build
- Model: Qwen3-8B (F16 GGUF stable profile + Q4_K_M GGUF quantized bonus)

### One-shot server bootstrap

On the Radeon instance:

```bash
bash scripts/setup_server.sh
```

This installs Node 22, creates `/root/radeonpilot/.venv`, downloads Qwen3-8B via
ModelScope, builds llama.cpp with HIP for `gfx1100`, and converts the F16 and
Q4_K_M GGUF profiles.

---

## Startup guide (pi mode)

Run in order, from this directory:

```bash
# 1. Start the model endpoint (prints its PID; record it as VLLM_PID)
bash scripts/start_endpoint.sh                 # llama.cpp GGUF (default, verified)
# ENGINE=vllm bash scripts/start_endpoint.sh   # vLLM path (requires ROCm source build)

# 2. Export the endpoint PID for attestation
export VLLM_PID=<pid-from-step-1>
export VLLM_BASE_URL=http://127.0.0.1:8000/v1

# 3. Install and start the Pi bridge
cd pi-bridge && npm ci && cd ..
PI_NODE_BIN=node bash scripts/run_bridge.sh

# 4. Start the Gradio console
export RADEONPILOT_MODE=pi
bash scripts/run_app.sh
```

Open `http://127.0.0.1:7860`. In **Audit & Runtime**, confirm the Pi SDK version,
the local model, and the **RADEON ATTESTED** badge.

## Startup guide (demo mode, no GPU)

```bash
export RADEONPILOT_MODE=demo
bash scripts/run_app.sh
```

The console is clearly labelled `DEMO (GPU UNATTESTED)` and performs no GPU work.

---

## Reproducibility

Step-by-step reproduction with checkpoints is in [`docs/REPRODUCE.md`](docs/REPRODUCE.md).
Benchmark evidence lives in `benchmarks/results/*.json` and is validated by
`python scripts/verify_submission.py`.

## Tests

```bash
# Python deterministic paths
python -m unittest discover -s tests -v

# Pi bridge
cd pi-bridge && npm ci && npm test
```

## Project layout

```
app.py                     Gradio Ops Console
src/radeonpilot/           tools, RAG, memory, orchestration, Pi client
pi-bridge/                 hardened Pi SDK multi-agent service
data/knowledge/            local ROCm/vLLM tuning corpus (RAG source)
scripts/                   bootstrap, endpoint launch, benchmark, quality gate, verifier
docs/                      specification, architecture, reproduce, demo script, poster
benchmarks/results/        measured JSON only
submission/                team.json, links.json
tests/                     Python unit tests
```

## Safety and privacy boundary

- Default bind is 127.0.0.1 for both the bridge and the endpoint.
- Pi file, shell, edit, browser, and network tools are disabled.
- Hazardous actions (restart endpoint, apply quantization, kill process, reset GPU)
  are blocked until an `sre` / `ops_commander` approves.
- Audit records redact secrets and store only hashed summaries.
- No fabricated numbers: every benchmark figure is captured by the runner.

## License

MIT. Pi Agent Harness is MIT licensed.
