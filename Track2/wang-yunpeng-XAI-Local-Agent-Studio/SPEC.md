# XAI Local Agent Studio — Project Specification Document

**AMD AI DevMaster Hackathon · Track 2: Agentic AI**
Team: wang yunpeng (solo participant) · Application name: `XAI Local Agent Studio`
Submission date: 2026-08-06 · All materials in English.

---

## 1. Application Scenario

XAI targets a user who needs a **private, offline-capable AI agent team** that can reason,
plan, use tools, write/run code, and execute file/shell operations — **without sending any
data to a third-party cloud**. Typical users:

- **Privacy-conscious professionals** (finance, legal, research) who cannot expose documents
  to external APIs.
- **Local "digital employee" workflows** — multi-step automation that chains reasoning →
  coding → execution on the user's own machine.
- **Offline / edge deployment** — runs on a single AMD Radeon GPU workstation, no internet.

The product is a **visual studio**: a canvas where agents are nodes, a shared "room" where
multiple agents collaborate, and a governance layer that gates dangerous actions behind
human approval.

---

## 2. Agent Architecture

```
                         ┌──────────────── XAI Studio (Web UI :8000) ────────┐
                         │  Canvas (React Flow)      Agent Room (Buzz)       │
                         └───────────────┬───────────────────┬──────────────┘
                                         │                   │
                         ┌───────────────▼───────────────────▼──────────────┐
                         │            Control Loop (single-direction)        │
                         │  Intent Router → Orchestrator                     │
                         │   • Hermes      : reasoning / planning            │
                         │   • Grok Build  : code generation & refactor      │
                         │   • OpenClaw    : execution gateway (shell/file)  │
                         │   • Memory Core : 8-layer metacognitive memory    │
                         │  Guardian : P0/P1/P2 risk grading + HITL queue    │
                         └───────────────┬───────────────────┬──────────────┘
                                         │                   │
                         ┌───────────────▼───────────────────▼──────────────┐
                         │  Model Registry → backends (local-first)          │
                         │   vLLM (ROCm, OpenAI-compat)  Ollama(ROCm)         │
                         │   llamacpp_backend (ROCm)  openai_compat_backend   │
                         │  failure_correction: read-side injection/inf      │
                         └───────────────────────────────────────────────────┘
                                          │
                                  AMD Radeon GPU (ROCm / vLLM)
```

**Design principle:** the control loop is *single-direction* — the Guardian approves/denies
tool actions but can never be called back by the reasoning layer, which structurally prevents
the "model persuades its own approver" exploit.

---

## 3. Core Capabilities

1. **Reasoning & planning (Hermes)** — chain-of-thought, self-refine, multi-trajectory
   budgeting; routes tasks by intent.
2. **Visual workflow canvas (Canvas-as-Context)** — the canvas is not a static diagram. Its
   serialized content is injected as *shared context* into the model, and the system supports
   **time-travel**: agent/canvas state can be rolled back to any checkpoint.
3. **Buzz multi-agent collaboration** — reasoning, coding, and execution agents operate in one
   shared room with one canvas and one memory pool, exchanging messages and artifacts.
4. **Tool & shell execution (OpenClaw)** — file read/write, command run, browser, scheduler,
   MCP — gated by Guardian.
5. **8-layer metacognitive memory** — working / short-term / long-term / anchor / reflection /
   causal / user-profile / **failure_correction**. The `failure_correction` layer records
   (task → error → correction) triples and injects the most recent three into every inference,
   so the agent stops repeating mistakes.
6. **Guardian governance** — P0 (delete/force-push/credential write → default-deny, needs
   human OK), P1 (command/network/install → allowed but logged), P2 (read/compute → auto).
   HITL queue exposed via HTTP for the UI.
7. **Honest self-acceptance** — a black-box self-tester walks public HTTP/CLI probes only
   (never mutates internals), scores six dimensions, and treats `unknown` as a first-class
   result; results append to an immutable ledger.
8. **GEPA self-evolution (auto-learning)** — a `GepaEvolver` + `GepaScheduler` (daemon thread)
   continuously evolves agent skills via model-driven mutation and evaluation feedback
   (triggered by `/evolve`). The system *improves itself* between runs instead of staying
   static. Verified at runtime: `~/.xai/memory.db` holds **288 `failure_correction`
   tuples** and the evolver is wired (not a stub).

---

## 4. Model Introduction & Local Deployment Plan

### 4.1 Model

For this submission we run **locally on AMD Radeon** with:

- **DeepSeek-R1-Distill-Qwen-32B-AWQ** (4-bit AWQ quantization, ~20 GB) served by **vLLM
  0.16.0 on ROCm 7.2.1** — the primary reasoning/coding model. This is the model actually
  benchmarked in §5.
- Optional fallback: **DeepSeek-R1-Distill-Qwen-14B** (fp16, ~28 GB) if a larger model does
  not fit; the 14B path was validated end-to-end during development.

The model is reached through XAI's `openai_compat_backend` (registered as provider `ollama`,
which in XAI is the OpenAI-compatible implementation), pointed at the vLLM endpoint.

No cloud API key is required; `DEEPSEEK_API_KEY` is optional and **off by default**.

### 4.2 Local deployment on AMD Radeon (ROCm / vLLM)

1. Provision an AMD Radeon instance (Radeon Cloud `vllm-dev` image: ROCm 7.2.1, vLLM 0.16.0).
2. Serve the model with vLLM on the GPU:
   ```bash
   /opt/venv/bin/vllm serve casperhansen/deepseek-r1-distill-qwen-32b-awq \
     --quantization awq --port 8002 --max-model-len 8192 \
     --gpu-memory-utilization 0.95 --max-num-seqs 32 --enable-prefix-caching
   ```
3. Verify the GPU is being used: `amd-smi monitor` shows 100% utilization under load.
4. Register and activate the endpoint in XAI (admin APIs use `X-Auth-Token`):
   ```bash
   TOKEN=$(cat /root/.xai/.server_token)
   MID=$(curl -s http://localhost:8002/v1/models | python3 -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])")
   curl -X POST http://localhost:8000/api/models/add -H "X-Auth-Token: $TOKEN" \
     -d "{\"name\":\"DeepSeek-R1-Distill-Qwen-32B-AWQ (Radeon)\",\"provider\":\"ollama\",\"base_url\":\"http://localhost:8002/v1\",\"model\":{\"id\":\"$MID\"}}"
   curl -X POST http://localhost:8000/api/models/activate/<id> -H "X-Auth-Token: $TOKEN"
   ```
5. Launch XAI: `python server_xai.py` (serves :8000).
6. All agent inference now executes on the Radeon GPU via vLLM; no data leaves the machine.

---

## 5. Inference-Speed Optimization on AMD Radeon GPU (ROCm)

This section addresses the 40-point "AMD Radeon GPU and ROCm optimization" criterion.
All numbers below were measured on the actual Radeon instance (single AMD Radeon GPU,
48 GB VRAM, RDNA3; ROCm 7.2.1; vLLM 0.16.0) running DeepSeek-R1-Distill-Qwen-32B-AWQ.

| Technique | What we do | Measured effect |
|-----------|------------|-----------------|
| **4-bit AWQ quantization** | Run 32B at AWQ 4-bit (~20 GB) instead of fp16 (~64 GB) | Fits 48 GB VRAM with ~28 GB headroom for KV cache |
| **vLLM on ROCm** | Use the preinstalled vLLM 0.16.0 ROCm build, not CPU | Enables GPU kernels; 100% GPU utilization |
| **High batch concurrency** | `--max-num-seqs 32`, prefix caching | Near-linear scaling: 3.64 → 14.5 → 28.9 tok/s at ×1/×4/×8 |
| **KV-cache & context** | `--max-model-len 8192`, prefix caching across turns | Stable latency at 2K / 4K context |
| **GPU memory tuning** | `--gpu-memory-utilization 0.95` | Maximizes KV cache, minimizes eviction |
| **Single-direction control loop** | Cheap guard/route logic kept off the GPU path | More GPU time for inference |

**Measured throughput (see `benchmark_results.json`):**

| Scenario | Throughput | Note |
|----------|-----------|------|
| Single stream (baseline) | 3.64 tok/s | 32B-AWQ, 1 sequence |
| Concurrency ×4 | 14.5 tok/s | ~4× linear scaling |
| Concurrency ×8 | 28.9 tok/s | ~8× linear scaling, GPU at 100% |
| Long context 2K / 4K | ~3.6 tok/s | stable across context length |

Peak GPU utilization **100%**, VRAM **94%**, thermal **42 °C** under concurrency load.
The headline ROCm result is **near-linear throughput scaling with batch size** — the Radeon
GPU saturates at 100% utilization under multi-agent concurrency, the exact workload pattern
for agentic AI.

---

## 6. Differentiation vs. Typical Agent Frameworks

Most open agent frameworks give you: a planner + a tool caller + a vector memory. XAI adds
five things judges will not see elsewhere:

1. **Canvas-as-Context with time-travel** — the workspace is live, inspectable, rollback-able
   agent context.
2. **Buzz same-room multi-agent** — reasoning/coding/execution truly share one space + memory.
3. **Guardian** — default-deny, human-in-the-loop safety for agents that can run shell/file
   commands, with a structurally safe (single-direction) approval node.
4. **8-layer metacognitive memory** — including a `failure_correction` layer (288 real tuples
   at runtime) that injects past mistakes into every inference, so the agent stops repeating them.
5. **GEPA self-evolution** — the agent *evolves its own skills* via model-driven mutation +
   evaluation, improving between runs rather than staying frozen.

All of it runs **locally on AMD Radeon via ROCm/vLLM** — privacy is an architecture property, not a setting.

---

## 7. Submission Artifacts

- `README.md` — quick start, architecture, differentiation.
- `SPEC.md` — this document.
- `radeon_setup.sh` — ROCm launch + benchmark helper.
- `benchmark_results.json` — measured throughput on the Radeon GPU.
- `demo.mp4` — 3–5 min walkthrough running on AMD Radeon (from CLI/GUI to result).
- `XAI_Hackathon_Deck.pptx` — highlights & architecture.
