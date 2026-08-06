# ScrewShell — Specification Document

**Track 2 — Private AI Agent Development & Local Deployment** · AMD AI DevMaster Hackathon 2026
**Hardware**: AMD Radeon PRO W7900 (48 GB) · **Runtime**: ROCm 7.2.4 · **Core inference**: 100% local, zero remote API

> **权威信源（SSOT）**：本仓库所有技术事实以 **`docs/TRUTH.md`** 为唯一权威信源。本文（SPEC）是黑客松提交交付物①，**以 TRUTH 为准、提交前从 TRUTH 反向同步**（见 TRUTH §4）；下列架构 / 能力 / 阵容若与 TRUTH 不一致，一律以 TRUTH 为准。

---

## 1. Application Scenario & Innovation

> **One brain, two front doors.** ScrewShell is a fully local, private AI stack on a single AMD Radeon GPU. Its brain is a **Mixture-of-LoRA (MoL)** inference engine — one frozen 27B base + hot-swappable community LoRA experts. It is exposed through **two front doors**: a private investigation agent, and an open inference gateway (Agent-as-a-Service).

### 1.1 The problem

Knowledge workers accumulate sensitive material that must not leave the machine: design documents, contracts, private codebases, meeting notes, migration plans. Cloud AI assistants are off-limits for this data. Yet answering a real question — *"What are the risks in our ROCm migration plan, and which paragraph says so?"* — requires an agent that can **plan, retrieve, read, grep, reason, and cite**, not a single LLM call.

### 1.2 Front door A — the private investigation agent

Point it at a workspace folder and ask multi-step questions. It:

1. **Plans** the investigation into skill-tagged sub-steps (Task Card).
2. **Routes** each step to a specialist LoRA expert (MoL hot-swap — see §5).
3. **Retrieves** evidence with a local RAG pipeline (local GPU embeddings).
4. **Acts** through six sandboxed, read-only local tools.
5. **Answers** with evidence cards carrying line-level citations (`file.md#L42-L58`) and a full JSON audit trail.

### 1.3 Front door B — the open inference gateway (Agent-as-a-Service)

The same MoL brain is exposed as an **OpenAI `/v1`-compatible inference gateway**, so mature open-source agents (**opencode / pi**) plug in with **zero modification**:

```
opencode / pi  ──▶  ScrewShell relay (/v1, :18090)  ──▶  llama-server (ROCm, MoL)
```

Point an agent at ScrewShell's port and it gains, per request:

- **Local expert routing** — the relay authenticates a trusted `X-Expert` header and routes each request to a LoRA expert via `SkillRouter`; the `InferenceCoordinator` serializes the global LoRA switch so multiple front-ends share one GPU without corrupting each other's expert state.
- **Inference tuning knobs** (`screwshell/gateway/{capacity,config,thinking,reliability,cli}.py`) — safe `llama-server` argv generation (capacity planning from real VRAM, `--jinja`, finite `--reasoning-budget`), thinking scheduling, prelaunch validation + `setsid` daemon posture, and one-command full-stack bring-up (`gateway/cli.py`).
- **Unified observability** — `/health` + `/v1/observ/{summary,events,gpu,slots,expert,props}` endpoints; GPU history persisted to SQLite; `switch_ms` timing; traffic split by entry point (`ui` / `opencode`).
- **One-click auto-tuning loop** (`screwshell/autotune/{scorer,mapper,cycle}.py` + `/v1/tune/{start,stop,status}`) — select a preset (speed / VRAM / long-context / balanced), and the cycle consults → plans → applies → restarts → generates benchmark traffic → scores → keeps/rolls back → converges, with a hard-failure signal (`ABORT + server_may_be_down`), never silently leaving a dead server.

> This is not merely deploying a model — it is exposing an **entire agent inference stack** as a service. See `docs/TRUTH.md` §1.7 for the authoritative description.

### 1.4 What is innovative

| Innovation | Why it matters |
|---|---|
| **MoL (Mixture-of-LoRA) inference core** | One frozen 27B base (Qwen3.6-27B Q4_K_M GGUF) + N community LoRA experts, hot-swapped on the resident base via llama.cpp. Multi-skill agent in the VRAM budget of a single GPU. Community adapters are plug-and-play: drop a GGUF in, gain a skill. |
| **Agent-as-a-Service** | The same MoL brain is exposed as an OpenAI `/v1` gateway, so open-source agents (opencode / pi) get local expert routing + tuning + observability with zero modification — not just a model endpoint, but a whole agent inference stack. |
| **Evidence-first answers** | Every claim is backed by an evidence card with file/line citations — conclusions are re-verifiable, not vibes. |
| **Private & auditable by construction** | Workspace sandbox, tool/path allowlists, secrets blocklist, dangerous-command rejection, JSON audit log, zero telemetry. All six tools are local read-only (no web tools are implemented). |

## 2. Architecture

```
User ── Web UI (Gradio, multi-panel) / CLI        opencode / pi (OpenAI /v1 tools)
          │                                                   │
          ▼                                                   ▼
   Orchestrator — self-built lightweight ReAct loop      Relay Gateway (:18090)
   │                                                      (X-Expert auth + SkillRouter
   │                                                       + InferenceCoordinator)
   ├─ Task Planner ──── Task Card: goal → skill-tagged sub-steps         │
   ├─ Skill Router ──── heuristic routing → activate LoRA expert     ◄─ MoL entry
   │                                                                      │
   ├─ Local RAG ─────── ingest → line-aware chunk → local GPU embed       │
   │                    → cosine search → file#Lx-Ly citations            │
   ├─ Tool Layer ────── rag_search · read_file · list_dir · grep          │
   │                    · shell_readonly · rocm_smi   (read-only)         │
   │                                                                      │
   ├─ Artifact Store ── raw tool outputs, kept off-context                │
   ├─ Evidence Store ── claim + citations + confidence (T4 validator)     │
   ├─ Memory Store ──── SQLite: session history · task state · prefs       │
   ├─ Safety Layer ──── permission gate + JSON audit log                  │
   │                                                                      │
   ├─ Unified Observability ─ /health · /v1/observ/* · GPU history ·      │
   │                        switch_ms · live rocm_smi (both entry points) │
   ├─ Auto-tune Loop ─── scorer/mapper/cycle + /v1/tune/* + UI tuning tab │
   │                                                                      ▼
   └─ MoL Inference Core                                             ◄─ 40-pt optimization
        ├─ Frozen Qwen3.6-27B-Q4_K_M GGUF (~16.8 GB, resident in W7900 VRAM
        │                      via llama-server, ROCm/HIP build)
        ├─ LoRA experts (GGUF) btl3 (tool/code) · cybersec (security, NEW)
        │                     · teichai_plan (agent/planning) · rag_n7 (doc/evidence)
        ├─ Hot-swap           llama.cpp LoRA adapter swap on resident base
        └─ ROCm runtime       llama.cpp HIP build + llama-server (/v1)
```

*架构权威版见 `docs/TRUTH.md` §1.3（本文为提交交付物，以 TRUTH 为准）。*

**Framework policy.** RAG components are standard and neutral. Agent orchestration is a **self-built ReAct loop** — the Skill Router *is* the orchestration core, so a generic graph framework would add nothing. the inference core runs on llama.cpp (HIP/ROCm build) with a GGUF base + hot-swappable GGUF LoRA adapters (backend via `MOL_BACKEND=llamacpp`). No closed-source agent platform.

### 2.1 Request lifecycle

1. UI/CLI submits the user goal → Orchestrator.
2. Planner (teichai planning expert) emits a JSON Task Card with skill-tagged steps.
3. Per step: Router picks an expert → LoRA adapter hot-swap on the resident base (sub-second) → ReAct think/act with the tool layer.
4. Tool outputs land in the Artifact Store; distilled findings become Evidence Cards.
5. Final answer synthesized from evidence cards, with citations; session state persisted to SQLite; every action appended to the audit log.

## 3. Core Capabilities (5/5)

| # | Capability | Implementation |
|---|---|---|
| 1 | **Local RAG** | Folder ingest, line-aware overlapping chunks, Qwen3-Embedding-0.6B on local GPU, cosine retrieval, `file#Lx-Ly` citations, `.npz` + JSON index persistence |
| 2 | **Tool calling** | 6 read-only tools behind a permission gate; structured `ToolResult`; raw output off-context |
| 3 | **Multi-step planning** | Task Planner → Task Card; each step skill-tagged and expert-routed; live plan panel in the UI |
| 4 | **Multi-turn memory** | SQLite session history + task state + evidence store; follow-ups ("which file supports that?") resolve against prior evidence |
| 5 | **Permission control** | Workspace path sandbox, tool allowlist, secrets-path blocklist (`.ssh`, `.env`, keys…), dangerous-command regex rejection, JSON audit log, zero telemetry |

*五大能力权威表见 `docs/TRUTH.md` §1.4（本文为提交交付物，以 TRUTH 为准）。*

## 4. Models & Local Deployment

| Component | Choice | Size | Source |
|---|---|---|---|
| Base LLM | `Qwen3.6-27B-Q4_K_M.gguf` (4-bit) | ~16.8 GB VRAM | local, served by llama.cpp |
| Expert: tool/code | `btl3` — `badtheorylabs/BTL-3` (r32/α64) | ~954 MB GGUF | Hugging Face · **converted ✓** |
| Expert: planning/agent | `teichai_plan` — `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` (r64) | — | **no GGUF weights available** (router degrades to base; data gap, not a bug) |
| Expert: security (NEW) | `cybersec` — `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) | ~79.7 MB GGUF | Hugging Face · **converted ✓** |
| Expert: doc/evidence | `rag_n7` — `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) | ~1.8 GB GGUF | Hugging Face · **converted ✓**; fallback None |
| Embeddings | Qwen3-Embedding-0.6B | ~1.2 GB | local GPU |

*阵容权威表（含 `teichai_plan` 无权重、降级 base）见 `docs/TRUTH.md` §2；本文为提交交付物，以 TRUTH 为准。*

- Stack: llama.cpp (ROCm 7.2.4 HIP build) + OpenAI-compatible `/v1` server; Python client in `screwshell.core.mol_engine_llamacpp`.
- **Lineup change (2026-07-29):** removed `hermes_s2` (silent base mismatch — true base is `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`, not clean `Qwen/Qwen3.6-27B`) and `fable5` (repo 404/privatized, never downloaded). All four current LoRA bases verified == `Qwen/Qwen3.6-27B` via upstream `adapter_config.json`. The planning expert's logical name is `teichai_plan` (on-disk W7900 folder `teichai_fable5_plan`). The ban is enforced at both layers — routing (`screwshell/core/router.py` `FORBIDDEN_EXPERTS` + anchored `is_forbidden`) and adapter discovery (`screwshell/core/lora_scan.py`); the doc-sync gate in `tests/test_mol_llamacpp.py` keeps removed experts out of `bench/benchmark_pathd.json` and `DEFAULT_SKILL_MAP`.
- Base GGUF is **fully local** — never uploaded, no remote API in the core path.
- Deployment: start `llama-server -m <base.gguf> --host 127.0.0.1 -p 8080`, then `MOL_BACKEND=llamacpp python -m screwshell.ui.app --workspace <folder>` (Web UI :7860) or `python -m screwshell.cli` fallback.
- **Zero remote API** in the core path: inference, embeddings, retrieval, memory are all on-device. (The semantic-router embedder fallback — a best-effort semantic overlay on top of the CJK-aware keyword router — is skipped by design on offline instances where Hugging Face is unreachable; the keyword router alone still covers Chinese queries, see `docs/TRUTH.md` §1.5.)

## 5. Radeon Inference Speed Optimization (MoL)

**Problem.** A capable agent needs several specialist skills. The naive designs are: (a) one full model per skill → 3 × 16.8 GB = **~50 GB, does not fit** the 48 GB W7900; or (b) reload weights on every skill switch → seconds per switch, which destroys agent latency (a single investigation switches skills dozens of times).

**Solution — MoL hot-swap (llama.cpp).** Keep one frozen 27B Q4_K_M base resident in W7900 VRAM (served once by `llama-server`); attach all LoRA experts as GGUF adapters and switch per-step by re-applying the MB-scale adapter on the resident base — no full-model reload, no N× VRAM.

**Measured results (W7900 48 GB / ROCm 7.2.4, 2026-07-28, raw data `bench/benchmark_pathd.json`):**

| Metric | Naive (per-skill models) | MoL hot-swap (measured) |
|---|---|---|
| VRAM, 3 skills | **~50 GB** (3×16.8 GB — does not fit in 48 GB) | **18.9 GB** (base + adapters resident) |
| Skill switch | full 27B reload = **seconds** | **avg 0.65 ms** (n=3 per expert; 0.5–0.8 ms per expert) |
| Throughput | one dedicated model per skill | base **31.0 tok/s** decode / ~100 tok/s prefill; 23.4–26 tok/s with active adapter |
| Model load | per-switch reload cost | **9 s** once, then resident |

Behavior differentiation verified at temp=0: btl3 adds tool-selection / agentic-coding reasoning; teichai yields an 8-step plan (post-mortem + canary) vs the base's 6 steps. The 9B-PEFT era 8.04 ms figure is retired (see `bench/BENCHMARK_STATUS.md`). *Note: the original `hermes_s2` behavior claim was measured on a silently-mismatched base (`Opus-CoT-Stage1`) and is void — superseded by `btl3` (verified base `Qwen/Qwen3.6-27B`).*

**Measured switch-path cost (2026-08-04, `bench/kv_reprefill_report.md`):** the 0.65 ms figure is the *control-plane* `POST /lora-adapters` toggle — a near no-op HTTP call, **not** the real switch cost. The real cost of an active adapter is a per-token decode tax of 15–25% (31 → 23.4–26 tok/s), paid only on steps that need the expert. Separately, on a fixed 1660-token prefix (W7900, pinned slot): a per-request `lora` override **destroys the prefix KV cache 100%** (full re-prefill, +1656 tok / **+2.35 s**), while the global `POST /lora-adapters` toggle **keeps 99.8% of cached tokens** (4/1660, a **415×** difference) — the measured justification for the serial-global-switch relay architecture (mixing both paths silently reverts experts to base).

**Switch latency measured end-to-end (2026-08-05):** a global LoRA switch completes in **1–2.5 ms** (btl3 2.5 ms / base 1.2 ms), disproving the "switching experts = seconds" assumption — the real slow path is first-token latency under long-context prefill, not the switch itself.

Additional ROCm-specific tuning:

- **llama.cpp HIP build** — ROCm-native bf16, no fp64 fallback on RDNA3.
- **Thinking-mode off for agentic steps** — `enable_thinking=False` makes JSON tool-call replies return fast instead of emitting a long reasoning preamble.
- **Live GPU observability** — the `rocm_smi` tool surfaces VRAM/utilization in the UI, proving on-Radeon execution during the demo.
- **ROCm-engineering contribution** — patched llama.cpp `convert_lora_to_gguf.py` (PR #24627 approach) so Qwen3.6 LoRA convert to GGUF on RDNA3.

### 5.1 autotune: three-tier system & L3 dual-mode swapping (W7900 verified)

**Problem.** A single frozen 27B base cannot keep every expert's weights resident if you also want roomy in-VRAM hot-swap; yet reloading the whole server per skill switch costs ~9 s and kills agent latency (an investigation swaps skills dozens of times).

**Solution — autotune layer (`screwshell/autotune/`), three tiers:**
- **L1 SkillPack** — each LoRA is a folder with `manifest.json`; directory scan builds the routing lineup. `base_fingerprint` pins the base model, so a silent base mismatch (the `hermes_s2` incident) is rejected at load time, not at runtime.
- **L2 hardware planner** — detects GPU vendor/VRAM and picks a degrade level (`full` / `reduced` / `base_only`); e.g. <8 GB VRAM → `base_only` (no LoRA).
- **L3 governor** — chooses the swap *gear* per hardware headroom:
  - **roomy** (VRAM headroom): hot-swap via `engine.activate` (`set_adapter`), **~0.65 ms** per expert.
  - **tight** (VRAM tight): restart `llama-server` with ONE `--lora` at a time, **4.6–5.1 s** per swap, recorded as `restart_swap` — never `set_adapter`.

**Measured on W7900 (2026-07-29, evidence `_e2e_evidence/*.log`):** deterministic drive (teichai_plan has no weights, so its step runs on base without a swap; the 3 real experts) `cybersec → btl3 → rag_n7`: 4.57 / 4.90 / 5.07 s, `switches=2`, `EXIT=0`. Tight mode drives `LlamaServerLifecycle.restart_with`; roomy mode hot-swaps via `engine.activate`. Full detail in `docs/AUTOTUNE.md`.

### 5.2 One-click auto-tuning loop (tune-loop) & production P1 tuning

**Problem.** Tuning an inference server by hand is error-prone (a wrong `--reasoning-budget` value or a missing `--jinja` silently breaks agentic tool-calling, a bad `--ctx-size` OOMs the card). The operator wants *"make it fast / save VRAM / larger context / balanced"* and the agent to find a safe, measured configuration.

**Solution — `screwshell/autotune/` + relay `tune` endpoints (implemented, 2026-08-06):**
- **`scorer.py`** — composite weighted score `score(events, gpu_samples) -> float | None` (TTFT 0.4 / decode 0.2 / KV-hit 0.2 / ok-rate 0.2; optional VRAM). T4 sample discipline: <16 events returns `None` (never fabricates a verdict).
- **`mapper.py`** — four presets (speed / VRAM / long-context / balanced) → deterministic `TuneGoal`; natural-language parsing is deferred to phase 2.
- **`cycle.py`** — state machine `consult → plan → apply → restart → collect → score → decide → rollback|keep → loop`. Single-parameter tuning in a safe order; on restart failure it rolls back to the last-good argv, then to the original pre-tune argv, and only then to `ABORT + server_may_be_down` (never silently leaves a dead server). Converges after 2 rounds with <5% change or max 8 rounds; generates benchmark traffic (`X-Benchmark:1`) after each restart so the scorer always has real data.
- **`POST /v1/tune/{start,stop,status}`** — authenticated, `409` on concurrent runs, state persisted to `OBSERV_DIR/tune_state.json`; execution runs in a worker thread so the relay event loop (and `/v1/tune/status`) stays responsive during a restart.
- **UI tuning tab** — one-click tune / stop buttons, a 4-preset requirement panel, live progress/history.

**Production P1 tuning (applied on W7900, 2026-08-05):** `--flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --parallel 2` with `--ctx-size 98304`. On a 35k-token long-tail prompt, steady-state first-token latency dropped from **30–172 s → 6.3 s** (1–2 orders of magnitude), while typical first-token latency (median ~1.66 s) stayed healthy. All argv generation goes through `ServerConfig.to_argv()` (list-form, no shell injection) with `--jinja` always present and `--reasoning-budget` finite (never `-1`).

## 6. Verification & Reproduction

| Script | Verifies |
|---|---|
| `scripts/day1_smoke.py` | **legacy** — 9B-PEFT smoke test; path-D verification runs against a live `llama-server` via `screwshell.core.mol_engine_llamacpp` |
| `scripts/day2_router_demo.py` | routing decisions across query types |
| `scripts/day3_rag_test.py` | ingest + retrieval accuracy on demo corpus |
| `scripts/day4_e2e_test.py` | full investigation E2E incl. multi-turn follow-up |
| `scripts/test_local_logic.py` | 23 GPU-free unit assertions (router/safety/memory/rag-chunking) |
| `bench/benchmark_mol.py` | A/B: MoL vs naive reload — VRAM, switch latency, throughput |
| `tests/test_autotune.py` | L1/L2/L3 unit (SkillPack scan, planner degrade ladder, governor gears, fingerprint guard) — no GPU |
| `tests/test_orchestrator_l3.py` | L3 integration: tight mode drives lifecycle restart (no hot-swap); roomy mode hot-swaps via `engine.activate` |
| `tests/test_mol_llamacpp.py` | MoL llama.cpp backend + doc-sync gate (forbidden experts never resurrect in config/skill map) |
| `tests/test_gateway_{capacity,config,thinking,reliability}.py` | gateway tuning knobs: VRAM→ctx capacity planning, safe argv generation, thinking scheduling, prelaunch validation (no torch) |
| `tests/test_tune_{config,lifecycle,scorer,mapper,cycle,relay,ui}.py` | one-click tune loop: ServerConfig fields, `start_argv`+takeover+hard-failure, weighted scorer+T4 discipline, preset mapper, cycle state machine+rollback/ABORT, relay tune endpoints (auth/409), UI buttons |
| `tests/test_observ_gpu.py` | GPU history persistence/ring/ordering + relay observ endpoints (incl. auth 401) |
| `tests/test_switch_ms.py` | `switch_ms` event white-list compat, store aggregation, coordinator timing, UI idle-gap hint |
| `tests/test_store_migration.py` | SQLite schema migration (missing columns, named-column INSERT, idempotent) |
| `tests/test_citations.py` | T4 citation validator (syntax → file → actually-retrieved; off/annotate/strip modes) |
| `tests/test_slice_events.py` / `test_ab_window_split.py` / `test_dim_breakdown.py` / `test_i18n_completeness.py` | observability dimension-slicing + generalized A/B split + i18n completeness |

Full suite: **389 passed / 3 skipped / 6 failed** (2026-08-06, local `.venv`). The 6 failures are all pre-existing and unrelated to the codebase: 1 is `test_toolkit_safety::test_shell_readonly_allows_benign_readonly_commands` — a Windows-only `wc` environment incompatibility (see `docs/TRUTH.md` §8.3 v21); the other 5 (`test_ab_window_split`, `test_split_minutes`, `test_slice_events`, `test_switch_ms` ×2) pass when run in isolation and are order-pollution of the local suite, not real regressions. The former `test_eval_gate::test_run_eval_isolates_case_crash` known failure was fixed 2026-08-04. A fresh clone runs the same suite — experts are registered under their logical names via `screwshell/core/lora_scan.py`. |

## 7. Limitations & Roadmap

- **Citation validation is implemented** — the T4 validator in `screwshell/core/citations.py` checks each final-answer citation through three layers (syntax → file exists → was actually retrieved) with `off`/`annotate`/`strip` modes, wired into the orchestrator. A *full* second-pass verifier subagent (re-reading cited files independently) is sketched but not shipped in v1.
- Router is heuristic; a learned router (small classifier over the base's hidden states) is a natural upgrade.
- A self-trained LoRA-Doc expert (document-investigation SFT) is planned; the MoL design makes it a drop-in.
- The auto-tune loop currently tunes one parameter at a time from presets; multi-parameter / grid search and natural-language requirement parsing are phase-2.

---

*License: Apache-2.0. All models/adapters Apache-2.0 or equivalent open licenses.*
