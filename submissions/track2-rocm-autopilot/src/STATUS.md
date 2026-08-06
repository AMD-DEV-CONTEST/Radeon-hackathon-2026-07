# STATUS

## 2026-08-06 03:40 (NIGHT COMPLETE: all GPU work done and archived)

**The numbers (all measured, power_integration method, gfx1100 48 GB, Qwen3-14B bf16)**
- Baseline (vLLM defaults, mns 256, conc 8): **84.6 tok/s · TTFT 388 ms · 2.042 J/tok · carbon C**
- Agent winner (mns 128, prefix ON, conc 32, TRITON_ATTN): **260.9 tok/s (×3.08) · TTFT 367 ms · 0.649 J/tok (−68%) · carbon A**
- Controlled isolation: same config cold-start TTFT 990 ms vs warm prefix cache 367 ms → the TTFT win is prefix-cache exploitation; steady-state vs cold-start MUST be labeled in every claim (reproducibility: 367.26 vs 366.69 ms across runs)
- Backend sweep at winner config: TRITON_ATTN / ROCM_ATTN / FLASH_ATTN / ROCM_AITER_UNIFIED_ATTN **all load on gfx1100** and sit within 0.4% throughput (255.1-255.8 tok/s); ROCM_ATTN most frugal (0.643 J/tok)
- Agent behavior: aggressive start → TTFT violation caught by guardrail → diagnosed queueing, halved concurrency → optimum; validated prefix caching necessity (OFF: TTFT ×6). Plain-language diagnoses journaled per iteration.

**Where everything lives**
- Mac: runs/ (journal.jsonl, state.json, session logs) + runs/instance-logs/ (vllm_serve, pipeline, sweep, control)
- Instance: /persistent/rocm-autopilot-results/ (2-min mirror loop) — PVC survives instance destruction
- docs/findings.md: 10 field findings (energy counter dead, gemma-4 dead ends, w4a16 kernel gap, China network specifics)

**MORNING CHECKLIST (Wilfred, 08:00 → PR at 12:00)**
1. If awake before credits die (~04:15): Destroy Instance banks leftover credits for a morning video session (PVC + HF cache on / are lost, but everything needed is mirrored; model re-download ~13 min via hf-mirror)
2. Radeon Cloud: redeem credits if possible → relaunch template → live video re-record; else video assembles from tonight's material (dashboard replays runs/state.json locally)
3. Eligibility (2 min): AMD AI Developer Program GLOBAL membership email == Radeon Cloud login == Luma registration
4. Deliverables: demo video 3-5 min · Project Specification Document (architecture diagram) · poster OR PPT · README rewrite (lineage + honest model-substitution note) · fork + PR "Track 2, {Team|Wilfred Doré}, rocm-autopilot"
5. Optional 1-click: accept gemma-3 license on HF → the retry loop (if instance alive) or a morning session gets a Gemma run for the lineage story

## 2026-08-06 ~02:10 (FIRST MEASURED NUMBERS ON RADEON)

**Done overnight**
- Serving path that works: **Qwen3-14B bf16, native vLLM arch, hermes tool parser, max-model-len 8192** (launch:ok in 69 s). Gemma-4 dead ends + gemma-3 license gate documented in docs/findings.md
- Tool-calling smoke test: clean native tool_calls on Radeon
- **Baseline measured: 84.56 tok/s · TTFT 387.6 ms · 2.0425 J/token @ 153.6 W (power_integration) · carbon label C (0.32 gCO2e/1k tok @ 571 g/kWh)**
- Agent session (6 iters, self-optimization: brain = the benched server) RUNNING since 23:06 instance time
- Resilience hardening after home power outage + flaky instance egress: offline model loads, fully detached pipeline, fire-and-forget kickoff script, results mirrored to /persistent after each phase

**Next**
- Agent session completes → sync journal/state/logs to Mac → leaderboard + before/after numbers
- 08:00 Wilfred: redeem credits if possible (video re-record), eligibility email check, then deliverables: video, spec doc, poster, PR by 12:00

**Blockers**
- Credits exhaust ~04:15 instance-side; all results mirrored before that
- gemma-3 gate: one click on the HF page would unlock a Gemma bonus session (optional)

> Update at each work block: done / next / blockers. This file is the scoreboard habit (playbook rule 7: a scoreboard file, not a feature list).

## 2026-08-05 ~23:30 (SPIKE: GO)

**Done**
- Radeon Cloud instance up (template: ROCm vLLM-dev Navi, PVC storage, SSH enabled); sshd installed manually (image ships without it); Claude has direct SSH access
- SPIKE results: **gfx1100 (Navi 31 / RDNA3), 48 GB VRAM** (DID 0x744b, W7900-class) · 128-core EPYC 9334 host, 503 GB RAM, 3.5 TB disk
- Telemetry verdict: energy accumulator EXISTS but stays at 0 (dead on this SKU) → **power-integration fallback confirmed** (socket_power readable: 18 W idle, cap 241 W, sampling works); amdsmi Python 26.2.2 preinstalled in /opt/venv
- vLLM **0.16.1.dev rocm721** preinstalled in /opt/venv with torch 2.9.1 + triton 3.5.1; HF cache empty (no models yet)

**Next (Claude, overnight)**
- rsync code to instance (exclude docs/private, .env) · port power.py to AmdSmiBackend (power_integration method) · download Gemma-4 QAT (needs HF token) · vLLM knob parity check · first agent session
- 08:00: Wilfred reviews, records video, spec doc + poster, PR by 12:00

**Blockers (need Wilfred BEFORE midnight)**
- HF token (Gemma models are gated; all old keys revoked)
- Token Factory API key (agent brain): https://developer.amd.com.cn/radeon/modelapis
- Credit balance check: confirm the instance can stay up overnight

## 2026-08-05 evening (H0-0.5: R&C extraction DONE)

**Done**
- Rules & Conditions + Luma page + submission-repo README archived verbatim (docs/private/rc-verbatim-2026-08-05.md) and extracted to docs/rules-and-conditions.md
- CLAUDE.md judging map corrected: Track 2 is 120 pts (60 functional 20/20/20 + 40 ROCm 20/20 + 20 bonus); four deliverables confirmed (spec doc w/ architecture diagram, code+README, video 3-5 min, PPT/poster)
- Strategy deltas recorded (docs/private/rc-implications.md): SQLite run-memory promoted to scoring-relevant; PR-title fallback = own name if no team name on Luma form; license gate resolved (R&C silent → keep Apache-2.0 unless François OKs AGPL)

**Next**
- TONIGHT (15 min, Wilfred): log into radeon-global.anruicloud.com with the AMD Dev Program email (credits only granted after first login) · paste SSH pubkey · Add Template (ROCm image, PVC storage, SSH Access ON) · Launch · hand Claude the SSH command + a Token Factory API key
- Claude (autonomous once SSH lands): SPIKE (gfx/VRAM, amdsmi capabilities) → telemetry port → first agent session on Radeon
- 08:00-12:00 Aug 6: review, record video, spec doc + poster, PR. **Effective PR target: 12:00 CEST Aug 6** (availability constraint)
- Decide the agent-brain stance (Token Factory vs local Gemma) per rc-implications.md §2

**Blockers**
- Radeon Cloud login/credits not yet confirmed; Token Factory API key needed (all old keys revoked 2026-07-26)
- Team name unconfirmed (fallback exists: own name)

## 2026-07-27 (pre-hackathon scaffold)

**Done**
- Repo scaffold created; Gemma² code inherited verbatim (autopilot/, datasets/, dashboard, tests, bench script)
- CLAUDE.md mission brief in place; docs/private/ gitignored; .env.example committed

**Next**
- H0-0.5 on hackathon day: extract Rules & Conditions → docs/rules-and-conditions.md
- SPIKE: Radeon Cloud instance up, identify gfx/VRAM, amdsmi capabilities, vLLM-ROCm serves Gemma-4 QAT
- Port autopilot/power.py: NVML → amdsmi (design sketch in docs/private/port-notes.md)

**Blockers**
- All API keys from the Gemma sprint were revoked on 2026-07-26: fresh keys needed (ask Wilfred)
- AMD AI Developer Program membership email must match the credited AMD account (verify before the sprint)
- License decision for this repo pending R&C check (see docs/private/licensing.md); Gemma win now public per organizers, lineage line is safe
