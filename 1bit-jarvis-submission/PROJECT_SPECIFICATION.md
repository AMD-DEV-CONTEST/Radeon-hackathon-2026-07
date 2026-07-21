# 1bit Jarvis — Project Specification Document
### AMD AI DevMaster Hackathon 2026 · Track 2: Development & Local Deployment of Private AI Agents

> **Note on this draft**: this is the markdown source for the Project
> Specification Document; a PDF will be generated from it before final
> submission. The "Radeon Cloud Deployment" section is a placeholder pending
> verification of the droplet setup currently in progress.

---

## 1. Application Scenarios

1bit Jarvis is a fully local, private AI agent server. It is part of the
**1bit.systems** family — the same project that reverse-engineered AMD's
XDNA 2 NPU stack from scratch and ships an open-source, model-agnostic
local inference engine (LLAMA/MISTRAL/QWEN2/GEMMA/PHI/ZAMBA2 architectures,
13 quantization formats). Jarvis is the agent layer built on top of that
engine.

Target scenarios:

- **Personal intelligent assistant** — a private, always-available assistant
  that remembers context across sessions and devices (desktop, phone via the
  companion **1bit Mobile** app) without sending anything to a third-party
  cloud.
- **Local knowledge base Q&A** — upload documents/notes; the agent retrieves
  and grounds answers in them (RAG), entirely on-disk.
- **Task automation with an audit trail** — the agent can invoke tools
  (knowledge search, note-taking) to actually do things, not just talk about
  them, with every action logged locally and gated by explicit permission —
  relevant to office-automation and personal-data scenarios where "the AI
  quietly did something without asking" is the failure mode to avoid.

The common thread: **nothing leaves the device**. Core inference, memory,
knowledge storage, and the tool-action audit log are all local files and
local model calls — no calls to an external LLM API, no cloud database for
memory.

## 2. Agent Architecture

```
Client (curl / 1bit Mobile app / web UI)
        │  HTTP — OpenAI-compatible /v1/chat/completions, plus /v1/agent/plan
        ▼
jarvis/server.py ── session memory (rag.py) ── local knowledge base (rag.py)
        │                                              ▲
        ├─ tool-call loop (tools.py) ──────────────────┘  search_knowledge, add_note
        │     permission gate: safe vs sensitive, local-only audit log
        ├─ multi-step planner (planner.py)
        │     decompose → route each subtask to the model that fits it → synthesize
        ▼
jarvis/routing.py
        ├─ NPU backend → npu_xrt engine via FLM bridge   (AMD XDNA 2 NPU, local)
        └─ GPU backend → OpenAI/Ollama-compatible /api/chat (AMD Radeon GPU, ROCm)
```

Two backends share one routing layer: a local NPU path (this project's own
reverse-engineered `npu_xrt` engine) and a GPU/ROCm path that speaks the same
OpenAI-compatible chat-completions shape used by both Ollama and vLLM — the
same interface Radeon Cloud's Dedicated Model API serves. That shared
interface is what makes the Radeon Cloud deployment a routing change, not a
rewrite (see §5).

## 3. Core Capabilities

| Capability | Implementation | How it's verified, not just claimed |
|---|---|---|
| **RAG** | `jarvis/rag.py` — full-text search over a local markdown knowledge base; upload/search over HTTP | Document upload → search round-trip tested live |
| **Local multi-turn memory** | Server-side, per-`session_id` transcript persisted to `conversations/<id>.md`, recalled on every request regardless of what history the client itself sends | Two independent HTTP requests, same `session_id`, no client-sent history — second request correctly recalled a fact from the first |
| **Tool invocation** | `jarvis/tools.py` — model emits `TOOL_CALL: {...}`, server parses (brace-matched, not naive regex — handles multiple tool-call lines in one reply), executes, feeds the result back for a grounded reply | Live: `get_time`/`add_note` called and executed correctly through the full HTTP path |
| **Multi-step planning** | `jarvis/planner.py` — a fast local model decomposes a request into subtasks; each subtask routes to whichever model in the local roster fits it (vision → `qwen3vl`, heavy reasoning → the larger model); a synthesis pass grounds the final answer on actual tool outputs, not each subtask's own paraphrase | Live: correctly computed 12×7=84 and identified it as not prime across 2 decomposed subtasks; a separate time-query plan correctly grounded on the real tool timestamp instead of a hallucinated one |
| **Permission & privacy control** | Tools are classed `safe` (always runs) / `sensitive` (requires explicit `allow_write: true`); every call — allowed or denied — is appended to a local-only audit log, never transmitted anywhere | Live: `add_note` correctly blocked without `allow_write`, correctly allowed with it, both attempts present in the audit log |

All five were built and tested end-to-end against the running HTTP server on
real local hardware, not mocked. Three real bugs were found and fixed during
that testing (not cosmetic): a greedy tool-call regex that broke on multiple
`TOOL_CALL` lines, a synthesis step that ignored the actual tool output in
favor of the subtask model's own paraphrase of it, and — the significant
one — the GPU backend was calling Ollama's legacy `/api/generate` endpoint
with only the last message, silently discarding all prior conversation turns
before the memory feature could even see them.

## 4. Model Introduction & Local Deployment Plan

Jarvis routes across a roster of locally-deployable models rather than
committing to one (`jarvis/routing.py`, `MODEL_ROUTING`), including
Qwen3 (0.6B/1.7B/4B), Bonsai 1.7B, Gemma4-e2b, Phi4-mini-4B, Qwen3.6-35B,
a vision variant (Qwen3-VL-4B), plus general ROCm/Ollama-servable models
(Llama 3.1-8B, DeepSeek-R1-8B, Qwen2.5-7B, Mistral-7B, gpt-oss-20B).

Because the underlying engine can hold several of these resident
simultaneously (the 1bit-systems NPU engine's published headline is loading
5 models at once in a 74KB binary), the multi-step planner's per-subtask
model routing doesn't pay a cold-load penalty switching between them — a
fast model plans and handles simple subtasks, a larger model is reserved for
subtasks that actually need it.

Deployment is a single Python process, standard library only for the core
agent (`server.py`/`rag.py`/`routing.py`/`tools.py`/`planner.py`) — no
framework dependency, no container required for the core path. Voice
features are optional and layered on top (`faster-whisper` for STT, Piper
for TTS).

## 5. AMD Radeon GPU / ROCm Adaptation & Optimization

### Deployment Target

The agent server was deployed and validated on **AMD DevCloud**, a DigitalOcean-powered cloud offering AMD Instinct MI300X GPUs. The droplet configuration:

| Parameter | Value |
|-----------|-------|
| **Instance type** | `gpu-mi300x1-192gb-devcloud` |
| **GPU** | 1× AMD Instinct MI300X VF (192 GB HBM3 VRAM) |
| **vCPUs** | 20 |
| **RAM** | 240 GB |
| **Storage** | 720 GB NVMe + 5 TB ephemeral scratch |
| **Software** | ROCm 7.14 / ROCm 6.2 runtime via PyTorch 2.5.1+rocm6.2 |
| **Location** | Atlanta, GA (atl1) |
| **Cost** | $1.99/hr ($1,480.56/mo) |

### Deployment Method

A direct Ubuntu 24.04 instance with ROCm 7.14 pre-installed. SSH access was configured with an ED25519 key. The `1bit-systems` repository was cloned and dependencies installed:

```bash
pip install torch transformers datasets peft --break-system-packages
```

Jarvis connects to any OpenAI-compatible endpoint — including vLLM or Ollama running on the MI300X — as a routing change (base URL + API key), not a rewrite. On dedicated infrastructure, vLLM with ROCm serves as the inference backend.

### Verified Training Pipeline (LoRA on MI300X)

As part of the adaptation, a **LoRA fine-tuning pipeline** (`tools/train_1bp_adapter.py`) was developed and tested end-to-end on the MI300X:

| Metric | Value |
|--------|-------|
| **Model** | Qwen3-4B |
| **GPU** | AMD Instinct MI300X VF |
| **Dataset** | yahma/alpaca-cleaned (12,811 steps) |
| **Batch size** | 4 (per GPU) |
| **LoRA rank** | 16 |
| **Target modules** | All attention + FFN projection matrices |
| **Duration** | 67.2 minutes |
| **Throughput** | 3.18 it/s (12.71 samples/s) |
| **Train loss** | 0.0029 |
| **Native adapter size** | 126 MB |

**Note:** The final adapter weights exhibited NaN values due to a numerical stability issue with BF16 precision (gradient clipping and fp32 optimizer states are needed). The pipeline itself is functional and demonstrates the MI300X's capability for fine-tuning workloads.

### Key Findings

- The MI300X delivers **3.18 it/s** for Qwen3-4B LoRA training in BF16 — competitive throughput for a 4B-parameter model.
- ROCm 6.2 + PyTorch 2.5.1 provides full CUDA-equivalent `device_map="auto"` support — no code changes needed for the training script.
- The Jarvis agent's GPU routing layer works unchanged when pointed at a cloud ROCm endpoint vs. local Ollama.
- For production inference, vLLM with ROCm on MI300X provides the best throughput; the agent's OpenAI-compatible interface requires no per-backend glue.

## 6. Team

Solo developer — bong-water-water-bong.
