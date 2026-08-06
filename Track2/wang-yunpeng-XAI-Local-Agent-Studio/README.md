# XAI — Local Private Multi-Agent Studio

> **AMD AI DevMaster Hackathon · Track 2: Agentic AI — Development & Local Deployment of Private AI Agents**
> Team: wang yunpeng (solo) · Application: `XAI Local Agent Studio`
> Runs **100% local inference on AMD Radeon GPUs via ROCm / vLLM** — no data leaves your machine.

---

## 1. What is XAI

XAI is a **local, private, open-source "Agent OS"** — a visual workspace where multiple
specialized AI agents reason, plan, use tools, share memory, and execute tasks **on your own
hardware**. It is built for the Track 2 scenario: *private AI agents with local deployment on
AMD Radeon GPUs and ROCm optimization*.

Unlike cloud-agent frameworks, XAI makes three architectural bets that most agent stacks omit:

| # | Differentiator | Why it matters for Track 2 |
|---|----------------|----------------------------|
| 1 | **Canvas-as-Context** — the visual workflow canvas is injected as *shared context* into the model, with time-travel / state rollback | Agents act on a living, inspectable workspace, not a blind prompt loop |
| 2 | **Buzz — multi-agent "same-room" collaboration** — reasoning / coding / execution agents share one room, one canvas, one memory pool | Real multi-agent orchestration, not isolated single bots |
| 3 | **Guardian governance gate** — P0/P1/P2 risk grading + human-in-the-loop approval, default-deny, single-direction node | Enterprise-grade safety for local agents that hold shell/file power |

Under the hood it also ships an **8-layer metacognitive memory with a `failure_correction` layer**
(agents stop repeating past mistakes) and an **honest self-acceptance harness** (black-box
self-test where "unknown" is a first-class result).

---

## 2. Why this fits AMD Radeon + ROCm (the 40-point criterion)

- **Local inference only.** XAI talks to models through pluggable backends:
  `ollama_backend.py`, `llamacpp_backend.py`, `openai_compat_backend.py`, `model_registry.py`.
  On AMD hardware it serves the model with **vLLM built for ROCm** (OpenAI-compatible API,
  registered in XAI as the `ollama` provider), so every token is generated on the Radeon GPU —
  nothing is sent to a cloud API.
- **Reproducible ROCm acceleration.** We ship `radeon_setup.sh` that launches vLLM on the
  Radeon instance, wires it into XAI, and runs a **benchmark** (tokens/sec vs concurrency,
  KV-cache behavior). See §5.
- **Off-the-shelf image.** The Radeon Cloud `vllm-dev` ROCm 7.2.1 image works without custom
  drivers — vLLM 0.16.0 + ROCm are preinstalled.

---

## 3. Quick Start (on AMD Radeon Cloud)

```bash
# 1) On a Radeon Cloud instance (ROCm 7.2.1, vLLM 0.16.0 preinstalled), serve the model:
nohup /opt/venv/bin/vllm serve casperhansen/deepseek-r1-distill-qwen-32b-awq \
  --quantization awq --port 8002 --host 0.0.0.0 \
  --max-model-len 8192 --gpu-memory-utilization 0.95 --max-num-seqs 32 \
  --enable-prefix-caching > /tmp/vllm32.log 2>&1 &

# 2) Register the vLLM endpoint into XAI (NOTE: XAI admin APIs use X-Auth-Token, not Bearer):
TOKEN=$(cat /root/.xai/.server_token)
MID=$(curl -s http://localhost:8002/v1/models | python3 -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])")
curl -X POST http://localhost:8000/api/models/add -H "X-Auth-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"DeepSeek-R1-Distill-Qwen-32B-AWQ (Radeon)\",\"provider\":\"ollama\",\"base_url\":\"http://localhost:8002/v1\",\"model\":{\"id\":\"$MID\"}}"

# 3) Activate it (activation rebuilds XAI's inference backend to point at vLLM):
curl -X POST http://localhost:8000/api/models/activate/<returned_model_id> -H "X-Auth-Token: $TOKEN"

# 4) Open the studio and chat — all inference runs on the Radeon GPU:
#    http://localhost:8000   (expose via rc-tunnel on Radeon Cloud for remote access)
```

Minimal Python core (logic tests, no GPU needed):

```bash
python -m pytest tests/ -q     # 73 unit tests
python examples/smoke.py       # end-to-end 5-stage smoke
```

---

## 4. Architecture

```
┌─────────────────────────── XAI Local Agent Studio ───────────────────────────┐
│  Web UI (Vite/React, :8000)  ── Canvas (React Flow DAG) ── Agent Room (Buzz)  │
│        │                                  │                                 │   │
│        ▼                                  ▼                                 ▼   │
│  ┌──────────── Control Loop (single-direction) ──────────────────────────┐   │
│  │  Intent Router → Orchestrator (pipeline + collaboration modes)        │   │
│  │     ├─ Hermes  (reasoning core)      ├─ Grok Build (coding engine)    │   │
│  │     ├─ OpenClaw (execution gateway)  └─ Memory Core (8 layers)        │   │
│  │  Guardian  (P0/P1/P2 grading + HITL approval queue)  ◀── tool/shell   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│        │                                  │                                 │   │
│        ▼                                  ▼                                 ▼   │
│   Model Registry ──▶ vLLM (ROCm, OpenAI-compat) / Ollama(ROCm) / llama.cpp(ROCm)│
│   Failure-correction memory  ◀── read-side injection on every inference      │
└─────────────────────────────────────────────────────────────────────────────┘
```

Key modules (all under `core/`):

- `canvas/` — Canvas-as-Context: canvas content serialized and injected as shared context.
- `agent_room.py` — Buzz: multiple agents in one shared room + shared canvas + memory.
- `guardian.py` — risk grading table, approval queue, HITL HTTP endpoints.
- `memory_core.py` — 8-layer memory; `record_failure()` / read-side injection.
- `ollama_backend.py`, `llamacpp_backend.py`, `openai_compat_backend.py`, `model_registry.py`
  — local-first model backends (ROCm-capable; the vLLM endpoint is reached via `openai_compat_backend`).

---

## 5. ROCm Optimization & Benchmark (measured on AMD Radeon)

The model is **DeepSeek-R1-Distill-Qwen-32B-AWQ** (4-bit AWQ, ~20 GB) served by
**vLLM 0.16.0 on ROCm 7.2.1**, running on a single **AMD Radeon GPU (48 GB VRAM, RDNA3)**.

| Scenario | Throughput | Note |
|----------|-----------|------|
| Single stream (baseline) | **3.64 tok/s** | 32B-AWQ, 1 sequence |
| Concurrency ×4 | **14.5 tok/s** | ~4× linear scaling |
| Concurrency ×8 | **28.9 tok/s** | ~8× linear scaling, GPU at 100% |
| Long context 2K / 4K | ~3.6 tok/s | stable across context length |

- **Peak GPU utilization: 100%** · **VRAM: 94%** · **thermal: 42 °C** (under concurrency load).
- The single-stream number is modest because 32B-AWQ is a large model; the key ROCm story is
  **near-linear throughput scaling with batch size** — the Radeon GPU saturates at 100% util
  under multi-agent concurrency, exactly the agentic workload pattern.

Results are written to `benchmark_results.json` for the submission evidence.

---

## 6. Project Structure

```
xai/
├─ core/            # Python reference core (model-agnostic, runs/tests standalone)
│  ├─ canvas/       # Canvas-as-Context
│  ├─ agent_room.py # Buzz multi-agent collaboration
│  ├─ guardian.py   # P0/P1/P2 governance + HITL
│  ├─ memory_core.py# 8-layer metacognitive memory + failure_correction
│  ├─ ollama_backend.py / llamacpp_backend.py / openai_compat_backend.py
│  └─ model_registry.py
├─ rust/            # Rust integration skeletons (guardian / reason / meta / runner)
├─ frontend/        # Vite + React + React Flow studio UI
├─ tests/           # 73 unit tests
├─ examples/        # end-to-end smoke
├─ radeon_setup.sh  # AMD Radeon (ROCm) launch + benchmark helper
└─ server_xai.py    # local server (:8000) serving the production frontend
```

---

## 7. Differentiation Summary (for judges)

1. **Canvas-as-Context + time-travel** — the workspace is first-class agent context, not a
   static diagram. You can roll back agent state.
2. **Buzz same-room multi-agent** — reasoning, coding, and execution agents genuinely
   collaborate in one shared space with one memory, not three disconnected bots.
3. **Guardian** — structured, default-deny, human-in-the-loop safety for agents that can run
   shell/file commands. Single-direction node prevents the "model talks the approver into
   approving itself" exploit.
4. **failure_correction memory** — agents surface and reuse "what went wrong last time".
5. **Honest self-acceptance** — a black-box self-tester where "unknown" is a legal answer,
   with an append-only ledger. Structure guarantees honesty instead of asking the model to be honest.

All of the above run **locally on AMD Radeon via ROCm/vLLM** — privacy by architecture.

---

## 8. License & IP

MIT-licensed reference implementation. No personal data is required; all inference is local.

**Attribution.** This is a secondary-development project built on multiple open-source
components and community practices. See [`THIRD_PARTY_LICENSES.md`](./THIRD_PARTY_LICENSES.md)
for the full list of dependencies and borrowed implementations. Model weights
(`DeepSeek-R1-Distill-Qwen-32B-AWQ`) are pulled at runtime from Hugging Face under their
respective license and are **not** included in this repository.
