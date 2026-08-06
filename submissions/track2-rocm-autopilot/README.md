# rocm-autopilot : a self-optimizing LLM deployment agent on AMD Radeon

**Track 2 · Agentic AI · AMD AI DevMaster Hackathon 2026**

rocm-autopilot is an autonomous agent that optimizes its own LLM serving deployment on an AMD Radeon GPU. The brain of the agent IS the deployment being optimized: the model served by vLLM-ROCm reasons about its own benchmark results, forms a diagnosis in plain language, acts on serving levers through guarded tools, and re-measures, until gains flatten. No remote API is involved anywhere in the loop: reasoning, serving and measurement all happen on one Radeon GPU.

This is Act II of [gemma-autopilot](https://github.com/wdore/gemma-autopilot) (Apache-2.0), the agent that won the Build with Gemma Hackathon (Paris, July 2026): same agent, new silicon. The port from NVIDIA/CUDA to Radeon/ROCm was done in one overnight sprint on the Radeon Cloud, and every number below was measured there.

## Results (measured on Radeon Cloud, gfx1100, 48 GB VRAM, ROCm 7.2.1, vLLM 0.16.1-rocm)

Model under optimization and agent brain: Qwen/Qwen3-14B, bf16, single GPU.

| | vLLM defaults | after the agent (4 iterations) | delta |
|---|---|---|---|
| Throughput | 84.6 tok/s | **260.9 tok/s** | **x3.08** |
| TTFT (steady state) | 388 ms | **367 ms** | within the 500 ms guardrail |
| Energy | 2.042 J/token | **0.649 J/token** | **-68%** |
| Carbon label | C (0.33 gCO2e/1k tok) | **A (0.10 gCO2e/1k tok)** | 2 classes |

Winning configuration found by the agent: `max_num_seqs 128 · prefix caching ON · client concurrency 32 · TRITON_ATTN`.

The agent's own trajectory (from `runs/journal.jsonl`, reasoning included): it probed the aggressive end (concurrency 64), hit TTFT 1012 ms, was blocked by the guardrail (a violating run scores 0), diagnosed queueing delay in plain English, halved concurrency to reach the optimum, then verified prefix caching is load-bearing (without it: TTFT x6).

**Controlled follow-ups (also in the journal):**
- Cold-start vs steady-state, same config: TTFT 990 ms cold vs 367 ms warm. The TTFT win is largely prefix-cache exploitation on workloads with shared prompt prefixes; we label every claim accordingly. Reproducibility across the night: 367.26 vs 366.69 ms.
- Attention-backend sweep at the winning config: TRITON_ATTN, ROCM_ATTN, FLASH_ATTN and ROCM_AITER_UNIFIED_ATTN **all load and run on gfx1100** and land within 0.4% of each other in throughput; ROCM_ATTN was the most frugal (0.643 J/token).

## Honest limitations (they are part of the product)

- The amdsmi energy accumulator on this SKU reads permanently 0; energy is measured by integrating socket power (amdsmi, 2 Hz) over each benchmark window and every run records `method: power_integration`.
- GPU power capping is denied in the cloud container; the agent reports the denial instead of silently skipping the lever.
- Gemma 4, the model family of Act I, cannot be served by this vLLM ROCm build: no native `gemma4` architecture (March 2026 snapshot), the transformers fallback crashes natively mid-load, and the QAT w4a16 checkpoint (group size 32) has no compatible WNA16 kernel on gfx1100 (Conch requires group 128, Exllama requires fp16 activations). All three dead ends are documented with exact errors in `docs/findings.md`: the agent therefore runs on Qwen3-14B. The agent is model-agnostic by design.
- The carbon label uses a static, documented grid factor (571 gCO2e/kWh, China grid 2023, Ember) matching the instance's location; the bands are relative comparisons of configurations of one deployment, not a cross-hardware standard.

## The five agent capabilities (Track 2 mapping)

1. **Tool invocation**: whitelisted, bounds-checked tools (`run_benchmark`, `restart_server`, `set_power_cap`, `search_web`, `search_papers`, `report_done`); rejections return explanations the model reads and adapts to.
2. **Multi-step planning**: probe aggressively, diagnose, correct, converge; explicit stop criterion (<3% expected gain).
3. **Local multi-turn memory**: the run journal persists every run + reasoning across sessions (`runs/journal.jsonl`) and rebuilds the leaderboard on restart.
4. **Task execution**: server relaunches with health checks and automatic rollback to the last good configuration: a failed exploration can never kill the agent's own brain.
5. **Privacy by construction**: the benchmark workload is a confidential-drafting scenario; nothing leaves the machine: local model, local telemetry, local journal.

## Repository layout & reproduction

See `src/` for the full agent, `src/docs/findings.md` for the field notes, `src/runs/` for the measured journal, state and session logs of the actual overnight sprint. Reproduction: `src/README.md` section "Run it".

Demo video: see `demo_video.md`.
