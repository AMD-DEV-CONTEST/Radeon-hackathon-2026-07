# CLAUDE.md : rocm-autopilot · "Autopilot Act II: the Radeon port"

## Mission & deadline (read this first)

Port gemma-autopilot (Gemma²: our public Apache-2.0 agent that won the Build with Gemma Hackathon Paris, built in one day) to AMD Radeon GPUs + ROCm, for the **AMD AI DevMaster Hackathon, Track 2 (Agentic AI)**.

- ⏰ **HARD DEADLINE: Thursday, August 6, 2026, 5:59 PM CEST.** This is a one-day port sprint: Gemma² itself was built in one day, and ~70% of the work already exists.
- 🧊 **PR frozen by 3:00 PM CEST on Aug 6** (house rule: never submit in the last hours).
- 🏆 Prize eligibility requires **AMD AI Developer Program membership** under the same email as the credited AMD account.

## What we inherit (already built: do NOT rebuild)

The Gemma² loop: probe a live vLLM deployment → read tokens/s, TTFT, energy per token → diagnose the bottleneck in plain language → act on levers (model variant/QAT, client concurrency, max_num_seqs, prefix caching, power cap, attention backend) → re-benchmark until gains flatten. Hard guardrail TTFT ≤ 500 ms. Live leaderboard vs a hand-tuned human baseline. Motto: **"measured, not assumed."** Every unavailable sensor or blocked lever is reported honestly: that honesty is the brand.

## The port deltas (the actual work)

| Gemma² (NVIDIA / H100) | rocm-autopilot (Radeon / ROCm) |
|---|---|
| Energy via NVML energy-counter deltas | **amdsmi / rocm-smi**. Energy counters may be absent → integrate power × time. If telemetry is hidden in the cloud VM → TBP × utilization fallback, documented honestly. |
| vLLM (CUDA) | **vLLM-ROCm**: the Radeon Cloud's native serving is literally vLLM on port 8000; the agent already drives vLLM. Verify knob parity: max_num_seqs, enable_prefix_caching. |
| Attention backends: FLASH_ATTN / TRITON_ATTN / FLASHINFER | Discover what the ROCm build exposes; **measure, don't assume**. |
| Power cap via nvidia-smi -pl (blocked in most clouds; reported honestly) | rocm-smi power cap: likely blocked too; same honest reporting. |
| Gemma 4 QAT variants (gemma-4-qat-q4_0, ...) | Unchanged on ROCm. |

## New in Act II (the "what's new" for judges)

- **Serving-backend lever**: backend ∈ { vLLM-ROCm (default), llama.cpp-HIP, Modular MAX }. The agent explores backends the way it explored attention kernels. ⏱️ MAX gets a **strict 1-hour timebox**: a documented load failure or underperformance is a valid finding, not a defeat: nobody has published vLLM vs llama.cpp vs MAX numbers on RDNA.
- **Carbon label**: gCO2e per 1,000 tokens = measured energy × grid carbon intensity (+ amortized embodied via a Boavizta-style methodology if time allows), rendered as an **A→G label** on the leaderboard. Consume existing tools only: no upstream contributions in this sprint.
- (Only if ahead of schedule) **per-GPU memory** of past runs (SQLite) so the agent never re-benchmarks a known config.

## Judging map (extracted from R&C 2026-08-05; mirror this vocabulary in README & PR)

Track 2 total is **120 points** (the Luma summary says 100; the governing R&C adds a bonus). Full quotes: `docs/rules-and-conditions.md`.

- **60 pts: functional completeness**, split 20/20/20: clear task positioning & creative scenario · core capabilities ("task decomposition, tool invocation, RAG and memory management") · **smooth multi-turn interaction experience** (the demo UX is worth 20 pts on its own).
- **40 pts: Radeon GPU / ROCm adaptation**, split 20/20: core inference running on Radeon GPU · targeted inference-speed optimization (before/after numbers).
- **+20 pts optional bonus**: "Core inference running Using Radeon cloud model API with quantization or distillation or other optimization methods" (sic).
- **Functional gate**: at least 2 of 5 capabilities (RAG · tool invocation · multi-step planning · local multi-turn memory · permission/privacy control); more capabilities earn extra credits → the SQLite run-memory is now scoring-relevant (3rd capability), no longer just a stretch goal.
- ⚠️ Constraint: "Core inference processes shall be executed locally on AMD Radeon GPU; remote APIs are not allowed for core functions." Tension with the Token Factory brain: see docs/private/rc-implications.md §2.

## Submission (hard requirements, confirmed against R&C + repo README)

- Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` → open a **PR titled `Track 2, {Team}, rocm-autopilot`**. If no team name was filled on the Luma registration, use the participant's own name instead (repo README rule). Everything in English. **PRs are public.**
- **Four deliverables required** (details in docs/rules-and-conditions.md): ① Project Specification Document (with agent architecture diagram + inference-speed optimization description) ② source code + README (env config, startup guide, dependency list) ③ demo video 3-5 min ("from command line/GUI to the final result", fluidity + functional completeness) ④ PPT or Poster (choose one; poster is cheaper).
- Pre-existing code: no prohibiting clause in the R&C; IP grant to AMD is non-exclusive. We openly build on our own Apache-2.0 gemma-autopilot: state the lineage in the README ("Act II of the agent that won the Build with Gemma Hackathon; same agent, new silicon"). **Transparency beats discovery.**
- License: R&C is silent on submission licensing → AGPL-3.0 allowed, but relicensing needs François's consent (joint copyright); default = keep Apache-2.0 (see docs/private/licensing.md + rc-implications.md §5). gemma-autopilot itself STAYS Apache-2.0 (do not touch).
- Prize eligibility: Luma registration approved + AMD AI Developer Program membership under the same email; valid Discord + GitHub IDs; teams ≤ 3 with identical team name.
- 🎥 **Record the demo video at the FIRST working session of the agent on Radeon**: never leave the video for the end.

## Repo layout & information hygiene

```
CLAUDE.md            # this file
README.md            # public; states the Gemma² lineage openly
docs/                # public-safe hackathon resources: R&C extracts, Radeon Cloud guide notes, judging criteria
docs/private/        # ⚠️ GITIGNORED: personal notes & strategy; the repo goes public with the PR
autopilot/           # ported agent code (from gemma-autopilot)
scripts/  runs/  assets/  tests/
.env                 # secrets ONLY here (gitignored); .env.example committed with empty keys
```

**Rules for Claude Code**: read `docs/` at the start of every session: it is the source of truth for event constraints. Never copy content from `docs/private/` or `.env` into the README, PR text, commits, code comments, or logs. No employer references anywhere. Personal time and personal/hackathon-provided hardware only.

## Infra quick facts (Radeon Cloud)

- radeon-global.anruicloud.com: Profile → Add Template (enable SSH Access + public key) → Launch → JupyterLab or SSH.
- ⚠️ **A running instance burns credits → Destroy Instance at the end of every session.** Batch the benchmarks.
- **Free Token Factory endpoints** (OpenAI-compatible, zero credits): Qwen3.6-35B-A3B, DeepSeek-V4-Flash → default agent brain. Local-Gemma brain on the Radeon = stretch variant (ticks "local inference" twice).
- Exact GPU/VRAM undocumented → **identify first** (`rocminfo`, `amd-smi static`) and freeze target model variants accordingly.

## Sprint plan (~24-30 h)

- **H0-0.5**: R&C extraction → deliverables checklist in `docs/`.
- **H0.5-2**: SPIKE (go/no-go): instance up · identify gfx target + VRAM · does amdsmi report power/energy? · does vLLM-ROCm serve a Gemma-4 QAT variant with max_num_seqs + prefix caching working? → Destroy if pausing.
- **H2-8**: port the telemetry module (NVML → amdsmi) + adapt the levers · first full agent session on Radeon · **screen-record it immediately**.
- **H8-12**: leaderboard & report on Radeon numbers · carbon label (simple: energy × grid factor → A-G) · README with lineage + port notes.
- **H12-14**: MAX timebox (load attempt → measure or document the failure) · llama.cpp-HIP backend only if trivial.
- **Then**: video edit · README polish · reproducibility pass (scripts, seeds, exact configs) · **PR by 3:00 PM CEST Aug 6**. Sleep is part of the plan.

## Working style for Claude Code

- Small, frequent commits. Keep `STATUS.md` updated at each block (done / next / blockers).
- Loops (code → bench → read metrics → fix) always carry an **explicit stop criterion**.
- **Never invent metrics.** If a sensor or lever is unavailable, the agent and the README say so plainly: honest limitations are part of the product.
- **MVS first** (Minimum Viable Submission = agent optimizing on Radeon + honest metrics + README + video + PR). Enhancers only after the MVS is submittable.

## Out of scope (do not touch)

Model training · upstream contributions (CodeCarbon, Boavizta, or any third-party repo) · Mojo kernels · second modalities (whisper, vision, diffusion) · multi-day refactors · anything requiring employer resources or references.
