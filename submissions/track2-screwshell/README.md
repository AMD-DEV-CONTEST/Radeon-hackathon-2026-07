# ScrewShell —— 本地私有 AI 调查智能体（AMD Radeon）

> **ScrewShell 是什么**：一个**完全本地、私有**的 AI 调查智能体，专为审查本地文档、代码和笔记而设计。
> **新 Agent 必读**：请首先阅读 `AGENT.md`（仓库根目录总入口，唯一信源索引见 `docs/TRUTH.md`）。
> **项目结构**：`screwshell/` 是核心包，`docs/` 是规范文档，`bench/` 是性能基准结果。
>
> **权威信源（SSOT）**：本仓库所有技术事实以 **`docs/TRUTH.md`** 为唯一权威信源。本文（README）与 `docs/SPEC.md` 是黑客松提交交付物，**以 TRUTH 为准、提交前从 TRUTH 反向同步**；下列架构 / 能力 / 阵容 / 基准若与 TRUTH 不一致，一律以 TRUTH 为准。
>
---

# ScrewShell — One Brain, Two Front Doors, on AMD Radeon

> **ScrewShell** is a fully local, private AI stack on a single AMD Radeon GPU. Its core is a **Mixture-of-LoRA (MoL)** inference engine — one frozen **Qwen3.6-27B** base (Q4_K_M GGUF, served by **llama.cpp** on ROCm) + community-sourced, hot-swappable LoRA experts — running on an **AMD Radeon PRO W7900 (48 GB)** with **ROCm 7.2.4**. Core functionality does not rely on remote APIs.
>
> ScrewShell exposes **two front doors onto one brain**:
> 1. **A private investigation agent** — point it at a workspace folder, ask multi-step questions, get evidence-based answers with line-level citations.
> 2. **An open inference gateway (Agent-as-a-Service)** — the same MoL stack exposed as an OpenAI `/v1`-compatible API, so mature open-source agents (**opencode / pi**) plug in with zero modification and get local expert routing + tuning.

**Track 2 — Private AI Agent Development & Local Deployment** · AMD AI DevMaster Hackathon 2026

---

## 1. Application Scenario

### 1.1 The private investigation agent

Knowledge workers accumulate sensitive material — design docs, contracts, codebases, meeting notes — that cannot be uploaded to cloud AI services. ScrewShell is a **private investigator for your own machine**: point it at a workspace folder and ask multi-step questions like

> *“What are the main risks in the ROCm migration plan? Cite the relevant documents.”*
> *“Now investigate this repo and explain why the benchmark is slow. Use only local files.”*

ScrewShell plans the investigation, retrieves evidence with local RAG, calls read-only local tools, and returns **evidence-based answers with line-level citations** (`file.md#L42-L58`). Every step is auditable; nothing ever leaves the machine.

### 1.2 The open inference gateway (Agent-as-a-Service)

The same MoL brain is exposed as an **OpenAI `/v1`-compatible inference gateway**, so mature open-source agents — **opencode / pi** — connect in with zero modification:

```
opencode / pi  ──▶  ScrewShell relay (/v1, :18090)  ──▶  llama-server (ROCm, MoL)
```

Point an agent at ScrewShell's port and it gains, per request, **local expert routing** (a request can carry `X-Expert: cybersec` to force a skill), **inference tuning** (thinking on/off, KV quantization, capacity planning), and **unified observability** (`/v1/observ`, traffic split by entry point). This is not merely deploying a model — it is exposing an entire **agent inference stack** as a service.

### 1.3 What makes it distinctive

1. **Private by default** — core inference, embeddings, retrieval and memory are all on-device; the six read-only tools are local-only (no web tools ship in this build; earlier drafts' "web_search/fetch_url" were never implemented).
2. **MoL multi-skill on one base** — one frozen 27B base (Qwen3.6-27B Q4_K_M GGUF) + multiple LoRA experts, hot-swapped on the same resident base. Community-trained experts are plug-and-play: drop a GGUF adapter in, gain a skill.
3. **Evidence-based answers** — every claim is backed by an evidence card with file/line citations and an audit trail, so conclusions can be re-verified.

## 2. Agent Architecture

```
User ── Web UI (Gradio) / CLI
   │
   │  opencode / pi (OpenAI /v1 tools)
   │       │  X-Expert auth + SkillRouter + InferenceCoordinator
   │       ▼
   │  Relay Gateway (:18090)
   │       │
   ▼       ▼
   Orchestrator (self-built lightweight ReAct loop)
   ├─ Task Planner        → Task Card + sub-steps (skill-tagged)
   ├─ Skill Router        → heuristic routing → activates a LoRA expert   ← MoL entry
   ├─ Local RAG Pipeline  → ingest → chunk → local embed → vector search → citations
   ├─ Tool Layer          → rag_search / read_file / list_dir / grep /
   │                        shell_readonly / rocm_smi   (read-only, sandboxed)
   ├─ Artifact Store      → raw tool outputs (off-context)
   ├─ Evidence Store      → evidence cards: claim + citations + confidence
   ├─ Memory Store        → SQLite session history / task state / preferences
   ├─ Safety Layer        → workspace sandbox, tool & path allowlists,
   │                        dangerous-command rejection, JSON audit log
   ├─ Unified Observability  → /v1/observ/{summary,events,gpu,slots,expert,props,gpu_history,llama_metrics} + /health
   ├─ Auto-tune Loop         → autotune/{scorer,mapper,cycle}; POST /v1/tune/{start,stop,status}
   └─ MoL Inference Core                                             ← 40-pt optimization
         ├─ Frozen Qwen3.6-27B-Q4_K_M GGUF (~16.8 GB, resident in W7900 VRAM via llama-server)
         ├─ LoRA experts (GGUF): btl3 (tool/code) · cybersec (security) · rag_n7 (doc/evidence) · teichai_plan (NO weights — degrades to base)
         ├─ Router: per-step LoRA hot-swap on the resident base (llama.cpp adapter swap)
         ├─ autotune L1/L2/L3: skillpack · hardware planner · L3 governor (dual-mode LoRA swap)
         └─ ROCm runtime: llama.cpp HIP build + llama-server (OpenAI-compatible /v1)
```

> *架构权威版见 `docs/TRUTH.md` §1.3（本文为提交交付物，以 TRUTH 为准）。*

Framework policy: RAG components are standard/neutral; agent orchestration is a self-built ReAct loop (the MoL Router *is* the orchestration core); the inference core runs on llama.cpp (HIP/ROCm build) with a GGUF base + hot-swappable GGUF LoRA adapters (backend selected via `MOL_BACKEND=llamacpp`). No closed-source agent platform is involved.

## 3. Core Capabilities (5/5)

| Capability | Implementation | Demo |
|---|---|---|
| **Local RAG** | folder ingest → line-aware chunking → local GPU embeddings (Qwen3-Embedding-0.6B) → cosine retrieval → `file#Lx-Ly` citations | ask about local docs, get cited answers |
| **Tool calling** | six read-only local tools behind a permission gate; raw outputs off-context in the Artifact Store | tool receipts visible in UI |
| **Multi-step planning** | Task Planner emits a Task Card; each step is skill-tagged and routed to a LoRA expert | live plan panel with per-step expert |
| **Multi-turn memory** | SQLite session history + task state + evidence store; follow-up questions resolve against prior conclusions | “which file supports that?” works |
| **Permission control** | workspace sandbox, tool/path allowlists, secrets-path blocklist, dangerous-command rejection, approval-hook interface (reserved; no write tools in the core demo), JSON audit log, zero telemetry | audit panel in UI |

> *五大能力权威表见 `docs/TRUTH.md` §1.4（本文为提交交付物，以 TRUTH 为准）。*

## 4. Model and Local Deployment

- **Base model**: `Qwen3.6-27B-Q4_K_M.gguf` (~16.8 GB, 4-bit quantized) served by **llama.cpp** (`llama-server`, ROCm/HIP build) on the W7900 — fully local, zero cloud.
- **LoRA experts** (GGUF, hot-swappable on the resident base; base = Qwen3.6-27B):
  - `btl3` — `badtheorylabs/BTL-3` (r32/α64) — tool/code execution · **converted ✓**
  - `cybersec` — `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) — security audit (NEW pipeline step) · **converted ✓**
  - `teichai_plan` — `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` (r64) — multi-step planning · *no GGUF weights available — router silently degrades to base (data gap, not a bug)*
  - `rag_n7` — `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) — doc/evidence report · **converted ✓**; fallback = base native thinking
  - **Lineup change (2026-07-29):** removed `hermes_s2` (silent base mismatch — true base is `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`, not clean `Qwen/Qwen3.6-27B`) and `fable5` (repo 404/privatized, never downloaded). All four current LoRA bases verified == `Qwen/Qwen3.6-27B`.
- **Embeddings**: `Qwen/Qwen3-Embedding-0.6B`, local GPU.
- **阵容权威表（含 teichai_plan 无权重降级 base）见 `docs/TRUTH.md` §2**；本文为提交交付物，以 TRUTH 为准。
- **Stack**: llama.cpp (ROCm 7.2.4 HIP build) + OpenAI-compatible `/v1` server; Python client in `screwshell.core.mol_engine_llamacpp`.
- **Run**:
  ```bash
  # 1) PRODUCTION bring-up (one command: relay gateway + auto-tuned llama-server)
  python -m screwshell.gateway.cli --model /path/to/Qwen3.6-27B-Q4_K_M.gguf
  # 2) DEV / alternative — start the inference server manually (llama.cpp, ROCm)
  llama-server -m /path/to/Qwen3.6-27B-Q4_K_M.gguf --host 127.0.0.1 -p 8080 --alias screwshell-base
  # 3) DEV / alternative — launch ScrewShell (MOL_BACKEND=llamacpp talks to the server)
  MOL_BACKEND=llamacpp python -m screwshell.ui.app --workspace /path/to/your/folder   # Web UI :7860
  python -m screwshell.cli     --workspace /path/to/your/folder  # CLI fallback
  ```

## 5. AMD Radeon GPU Inference Optimization

**Problem**: an agent needs several specialist skills. Naively that means one full model per skill — a full reload per switch, or N× VRAM that won't fit a single 48 GB card.

**Optimization — MoL hot-swap on Radeon (llama.cpp)**: keep one frozen 27B base resident in W7900 VRAM (served once by `llama-server`) and switch MB-scale LoRA adapters per investigation step. The switch re-applies a tiny adapter on the same resident weights instead of reloading a full model.

**Measured on W7900 48 GB, ROCm 7.2.4 (2026-07-28, raw data in `bench/benchmark_pathd.json`):**

| Metric | Naive per-skill models | MoL hot-swap (measured) |
|---|---|---|
| VRAM for 3 skills | **~50 GB** (3×16.8 GB Q4_K_M — does not fit in 48 GB) | **18.9 GB** (base + adapters resident, measured) |
| Skill switch | full 27B reload = **seconds** | **avg 0.65 ms** (`POST /lora-adapters` scale toggle, n=3/expert; per-expert 0.5–0.8 ms) |
| Throughput | one dedicated model per skill | base **31.0 tok/s** decode / ~100 tok/s prefill; 23.4–26 tok/s with active adapter |
| Model load | per-switch reload cost | **9 s** once, then resident |

> *MoL 优化实测权威表（含 0.65ms 控制面热切、teichai 行为差异注记）见 `docs/TRUTH.md` §1.5；验收闸 G1–G5 见 `bench/LORA_GGUF_GATES.md`。*

Behavior differentiation verified at temp=0 with identical prompts: `btl3` returns more concise, direct tool-calling answers; `teichai_plan` produces an 8-step plan with post-mortem + canary rollout vs the base's 6 steps; `cybersec` gives structured security analysis; `rag_n7` returns tighter, citation-focused answers. The decode-rate drop with an active adapter is the unmerged-LoRA runtime cost — it also proves the adapter is genuinely in the compute path.

*Note on the 0.65 ms figure:* it measures the **control-plane** `POST /lora-adapters` scale toggle — a near no-op HTTP call, **not** the real switch cost. The real cost of an active adapter is a **per-token decode tax of 15–25%** (observed 31 → 23.4–26 tok/s), paid only on steps that need the expert (see `docs/E2E_OPTIMIZATION.md` §1.2).

**Measured switch-path cost (2026-08-04, `bench/kv_reprefill_report.md`):** on a fixed 1660-token prefix (W7900, id_slot pinned), a per-request `lora` override **destroys the prefix KV cache 100%** (full re-prefill, +1656 tok / **+2.35 s**), while the global `POST /lora-adapters` toggle **keeps 99.8% of cached tokens** (4/1660, a **415×** difference) — the measured justification for ScrewShell's serial-global-switch relay architecture, and the physical evidence behind the Phase 0 P0 fix (mixing both paths silently reverts experts to base).

**Answer-quality gate (2026-08-04):** `screwshell/eval/` (measurement gate: citation accuracy / coverage / RAG recall / latency scorers) and `screwshell/core/citations.py` (T4 validator: syntax → file → actually-retrieved, with off/annotate/strip modes) are wired into the orchestrator — final-answer citations are programmatically checked and step findings carry real tool citations, not empty lists. Run `python bench/eval_e2e.py --cases core_10 --mode mock` locally (no GPU needed). Full implementation status: `docs/E2E_OPTIMIZATION.md` §13.
*Note*: the earlier 9B-PEFT stack's 8.04 ms `set_adapter` figure is retired; the numbers above are the real 27B llama.cpp measurements (see `bench/BENCHMARK_STATUS.md`).

**One-click auto-tune loop (implemented).** `screwshell/autotune/{scorer,mapper,cycle}.py` drives a closed-loop tuning pass: measure live inference quality/throughput (scorer), map results to a deploy config (mapper), and cycle the server with the new config (cycle). It is exposed via `POST /v1/tune/{start,stop,status}` and has a dedicated tuning tab in the UI. For production P1 bring-up, tune with `--flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --parallel 2` (with `--ctx-size 98304`); long-tail first-token latency drops from 30–172 s to **6.3 s**. Cross-ref `docs/SPEC.md` §5.2 and `docs/AUTOTUNE.md`.

Additional ROCm tuning: llama.cpp HIP build is ROCm-native (bf16, no fp64 fallback on RDNA3); `enable_thinking=False` for agentic JSON tool-calls returns fast acks; live `rocm_smi` VRAM/util observability is surfaced in the UI to prove on-Radeon execution during the demo. ROCm-engineering contribution: we patched llama.cpp's `convert_lora_to_gguf.py` (PR #24627 approach) to convert Qwen3.6 LoRA into GGUF on RDNA3.

---

### Repository Layout

```
screwshell/          core package
  core/              MoL engine · Skill Router · ReAct orchestrator
  rag/               local RAG pipeline (chunk/embed/retrieve/cite)
  tools/             sandboxed read-only tool layer
  memory/            session/task/evidence/artifact stores
  safety/            permission gate + audit log
  ui/                Gradio multi-panel UI
  gateway/           relay gateway (:18090, OpenAI /v1, X-Expert auth) + tuning knobs
  eval/              answer-quality gate (citation/coverage/recall/latency scorers)
  observ/            observability store (metrics/history endpoints)
  autotune/          L1/L2/L3 tuning: skillpack · hardware planner · L3 governor (dual-mode LoRA swap)
scripts/             day1-day4 verification scripts + deploy
bench/               MoL A/B benchmark + results
demo_workspace/      demo corpus (docs + code with planted perf bugs)
```

### License & Compliance

Apache-2.0. All models and adapters are Apache-2.0/open. Core functionality performs **zero remote API calls** (no web tools are implemented; all six tools are local read-only).
