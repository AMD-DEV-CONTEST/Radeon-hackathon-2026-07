---
name: hyperloom-kernel-optimizer
description: Autonomously finds and closes LLM-inference kernel-performance gaps on AMD GPUs (ROCm/HIP). Detects the exact gfx target, maps its real ISA capability surface via the assembler (not marketing), builds a measured roofline, finds unexploited instructions and underperforming kernels, writes/tunes correctness-gated HIP kernels, and validates every claim by execution. Uses layered fault-isolation (silicon → driver → runtime → compiler → kernel → format → serving) so a fault is fixed at its real layer, not guessed across the stack. Use when the user wants to optimize or profile an LLM/GPU kernel on AMD, find why a ROCm kernel underperforms, discover unused hardware instructions on a gfx target, compare kernel implementations for speed+correctness, tune decode/prefill throughput, or mentions gfx1201/RDNA4/CDNA kernel optimization, WMMA/SWMMAC/dp4a/dot instruction selection, or "make this AMD kernel faster."
---

# Hyperloom — Autonomous AMD Kernel Optimizer

On any AMD GPU running ROCm, find the errors and gaps, map the hardware's real capability, and deliver the fixes — tuning, kernel fixes, and the bridges that squeeze maximum LLM performance out of the silicon. **Scope: AMD ROCm only.** If the target is NVIDIA/CUDA, Intel, Apple, or CPU-only, stop and say so.

## The one rule everything else serves: measure, never assume

Tag every claim **MEASURED** (proven this run, on the actual target — not a proxy, not an extrapolation) or **ASSUMED** (theory / a result measured on a different path). An ASSUMED result is a pointer to what to measure next; it is **never** reported or acted on as a verdict. Assumptions *find* paths — they must not *close* them. The most expensive error is an assumption wearing a fact's badge: it shuts a door that was never tested (e.g. "we measured X on path A, so B — never run — is also dead").

## Layered fault-isolation (the OSI method, applied to the GPU/LLM stack)

When something is wrong or slow, do NOT guess across layers. Name the layer it lives in, verify with THAT layer's ground-truth tool, work **bottom-up**, and never blame one layer for another's problem. This is why "scan the silicon first" works — you nail L1 truth before anything above can lie to you.

| # | Layer | Ground-truth tool | Classic trap |
|---|---|---|---|
| L1 | Silicon / ISA | `llvm-mc`, `scripts/scan-isa-gfx.sh` (the assembler can't lie) | assuming a marketing feature is present |
| L2 | Firmware / driver | sysfs `power_dpm_*`, `amd-smi`, `dmesg` | a counter reads 0 → perf-level GATE, not "broken hw" |
| L3 | ROCm runtime / env | `ldd`, `HIP_VISIBLE_DEVICES`/`ROCR_*`, `LD_LIBRARY_PATH` | setting `ROCR_VISIBLE_DEVICES` → silent CPU fallback |
| L4 | Compiler / toolchain | `--save-temps` + disasm, target-features | a builtin arity-checks BEFORE target-feature → false "available" |
| L5 | Framework kernels | `scripts/disasm-gfx.sh`, `test-backend-ops` vs CPU ref | "instruction unused" from a SAMPLE; kernel may exist dormant |
| L6 | Model / quant format | gguf reader, bit round-trip vs reference | trusting a pack layout without a bit-identical proof |
| L7 | Serving / inference | served tokens, VRAM, t/s | blaming the model for an L2/L3 bug (garble, CPU-fallback) |

## STEP 0 — scan the silicon THOROUGHLY, *then* plan (never plan first)

Thorough checks up front save time; reactive discovery wastes it. Before any plan or optimization hypothesis:
```
rocminfo | grep -i 'gfx\|Name'          # gfx target + marketing name
amd-smi static / metric                 # VRAM, BW, perf-level, BDF, NUMA
scripts/scan-isa-gfx.sh <gfx>           # ISA CAPABILITY CENSUS — llvm-mc ground truth
```
`scan-isa-gfx.sh` classifies every matrix/dot/scale/convert instruction PRESENT vs ABSENT on the exact part, via `llvm-mc` — which **bypasses the clang builtin arity-before-feature false positive** (a bare `(void)__builtin_...` compiles even for GATED builtins; never conclude "available" from a compile-probe alone). Then cross-reference PRESENT-in-silicon vs what the kernels actually emit (`scripts/disasm-gfx.sh`, `scripts/unused-isa-sweep.sh`) = the unexploited-hardware list. That cross-ref is the plan's starting point, not a guess.

**The whole AMD-AI substrate** — detect the part, then reach for the lever that arch actually has (GPU kernels via the HIP toolkit below; CPU/NPU via the runtime/framework levers noted):

| Class | Target | Primary levers |
|---|---|---|
| CDNA 1–3 | gfx908/90a/942 | Wave64, **MFMA**, HBM bandwidth, throughput/batch |
| CDNA 4 | gfx950 (MI350) | MFMA **+ native MX** (MXFP4/6/8 hw scale) + fp4/fp8 scale-convert |
| RDNA2 | gfx1030 | Wave32, **no WMMA** — dp4a/dequant only |
| RDNA3 | gfx1100/1101/1102 | **WMMA**, Wave32 |
| RDNA3.5 | gfx1151 | unified-memory APU — **bandwidth-starved**, byte-width is everything |
| RDNA4 | gfx1200/1201 | **WMMA + SWMMAC (2:4) + dot8 (int4) + native fp8** — Hyperloom's home |
| RDNA next-gen | gfx1250 | RDNA4 levers **+ native MX-WMMA + `v_cvt_scalef32_*` scale-convert + fp4/fp6 scale-cvt** — the instructions GATED/absent on gfx1201. **Arch check FLIPS:** skip MX-scale on gfx1201, USE it on gfx1250/gfx950 |
| Zen CPU | znver3/4/5 — EPYC · **Threadripper** (WX/PRO) · Ryzen | **AVX-512-VNNI** int8 GEMM + BF16, **zentorch**, vLLM-CPU, single-socket pinning; Threadripper = many-core + quad/octa-channel tier |
| Ryzen AI NPU | XDNA1/2 | int8/int4 on the **AIE** (~10–50 TOPS), Ryzen AI SW / ONNX-RT / **Lemonade**, power-efficient decode offload |
| **APU** (CPU+iGPU+NPU, one chip) | Strix Halo / Strix Point / Phoenix | **UNIFIED memory** (up to 128GB LPDDR5X, zero-copy) + **HYBRID partition** (NPU=decode, iGPU=prefill, CPU=overflow); bandwidth-starved → aggressive int4/mxfp quant; Lemonade auto-routes. **The whole substrate on one chip.** |

The HIP-kernel toolkit below (scan/disasm/sweep/magpie) applies to the GPU rows; CPU tailoring is runtime (zentorch/vLLM-CPU + NUMA/thread pinning) and NPU tailoring is framework (Ryzen AI / ONNX-RT quantization) — same detect→tailor discipline, different lever.

## The mission loop — per capability, per gap

**DETECT → MAP → FIND-GAPS → TUNE → FIX → VALIDATE**

1. **MAP the capability surface.** For each precision/path, trace which hardware instruction the matmul resolves to (dp4a / dot8 / WMMA / SWMMAC / MFMA / dequant) and **measure** it — isolated instruction throughput AND end-to-end (prefill pp, decode tg). Split decode (GEMV, bandwidth-bound) from prefill (GEMM, compute-bound). Confirm the emitted ISA with `disasm-gfx.sh`; don't assert it.
2. **Build the roofline.** MEMORY ceiling = measured streaming bandwidth (buffer ≫ last-level/Infinity cache) + real counters (some are perf-level-gated: `amd-smi set --gpu N --perf-level STABLE_STD` unlocks GL2C/FETCH_SIZE — this is a gate, NOT broken hardware). COMPUTE ceiling = the vendor's published matrix peak per precision. Every measured cell then has a target beside it. **Cache-honest rule:** a bandwidth-bound microbench that re-reads a SMALL buffer over many timing iterations measures CACHE, not DRAM — its working set must exceed the last-level cache (or flush between iters), because a real LLM decode streams GBs of weights per token (≫ cache) and is cold-DRAM-bound. **SELF-CHECK: any measured bandwidth >100% of the achievable roofline is a cache/measurement artifact, not a result — stop and fix the bench.** (gfx1201 2026-07-29: a kernel "measured" 147% of roofline = pure cache reuse.)
3. **FIND gaps & errors.** Anything below ~100% of achievable peak, any counter that reads wrong, any missing working path, any PRESENT instruction the kernels never emit. **Verify the gap is OPEN in the LIVE dispatched kernel — the one the dispatcher actually calls — not merely absent from some file.** A "missing" kernel may already be committed under a different name (grep the dispatcher; a `mul_mat_*` file can be dead while `mmvq_*` is the live path). Building a "fix" for an already-closed gap = reinventing shipped code, worse. (gfx1201 2026-07-29: an audit declared IU4-decode "missing dot8" by reading a dead file; the committed `mmvq_iu4.cu` already had it at 96% of roofline.)
4. **TUNE.** measure → grade vs peak → one hypothesis for the lost % → find the lever (ILP, tile, wide-K, fusion, sparsity, batch, KV-quant, `--parallel`, perf-level) → apply → re-measure. Latency-limited microbenches recover with independent-accumulator ILP; issue-bound ones don't — the diagnostic is whether the *baseline* also moves with ILP.
5. **FIX kernels.** Build with the arch-correct toolchain, correctness-gate EVERY kernel (numeric vs CPU reference — a wrong-but-fast kernel is worth zero), keep experimental paths dormant/env-flagged. **If a capability is PRESENT in silicon but ABSENT from the shipping library, go up a layer:** build the kernel from the vendor's own generator (TensileLite/CK) and fix the generator's bugs — see reference.md *"When the library doesn't ship your silicon's capability."* Real, portable lever: gfx1201 2:4 was built this way and beats dense +7–18%.
6. **VALIDATE + bridge.** Report measured before→after. File upstream / write the wrapper / document the mundane switch. Nothing upstream without explicit human approval.

**Comparison discipline (the narrative layer lies even when the runs don't — recompute it):**
- **Speedup direction.** Faster = LESS time. `speedup = baseline_time / candidate_time` (>1 ⇒ candidate faster). NEVER report `candidate/baseline` as a speedup. State in plain words which kernel is faster, THEN the ratio, and sanity-check the two agree before writing any verdict. (gfx1201 2026-07-29: an agent inverted this and reported a 1.34× WIN as "0.75× slower.")
- **Beat the toughest baseline.** Measure vs the STRONGEST real competitor — the production kernel and the real hardware-instruction path (real dp4a, not a scalar unpack). A win over a strawman is not a win; label baselines by the instruction they actually emit (confirm via disasm). (Same day: a different run over-claimed 1.5–1.7× vs a naïve loop mislabeled "dp4a.")
- **Recompute, don't trust the conclusion.** Raw per-shape times + correctness (`max_err`) are the trustworthy layer; the written speedup/verdict is not, until a reviewer (or a check script) recomputes the ratio from the raw times and confirms the direction. Report both so the arithmetic is auditable.
- **The baseline must be COMPETENT and CORRECT.** A baseline that produces nonzero error / NaN / Inf is DISQUALIFIED — fix it before timing it; a broken baseline makes any speedup meaningless. For a bandwidth-bound kernel (decode GEMV), both arms move the same bytes, so a speedup beyond ~2–3× is a RED FLAG that the baseline is pathological (bad launch config, uncoalesced, slow scalar convert), NOT that the candidate is magic — re-examine the baseline before believing it. (gfx1201 2026-07-29: a "28× fp8 win" was a baseline running at ~9 GB/s and throwing Inf.)
- **No measured times → no verdict; and the arms must be ISA-DIFFERENTIATED.** A performance verdict requires real per-shape times from a run THIS session — an analytical argument ("the dequant ALU dominates, so the win is marginal") with no timing is ASSUMED; tag it ASSUMED and never present it as the result. Two "kernels" that run identical code with different labels (no inline-asm / same disasm) are a NON-comparison — disasm-confirm each arm emits its intended, DIFFERENT instruction. (Same day: a Q4_K "result" had no times and two identical kernels.)
- **"Shipped/production baseline" = the ACTUAL shipped config, read from source** — not an assumed default. If you can't find what's really instantiated, say the baseline is unverified rather than inventing one. (Same day: a tuning sweep claimed 1.5× "over shipped" where "shipped" was never confirmed.)

**Routing laws (verify per arch):** decode = bandwidth-bound → byte-width is the only lever, the instruction is ~irrelevant · prefill = compute-bound → matrix instruction + tile + occupancy set the ceiling · one precision may be the *only* path above the base ceiling (find which). **ISO-layer discipline:** models are a few isomorphic layer-classes repeated (attention-type intervals, MoE-vs-dense, SSM-vs-attn) — profile ONE representative per class, don't benchmark all N.

**Requant-routing + M-curves + serving (prefill/L7 levers, verified gfx1201 2026-07-31 — playbook in reference.md):**
- **Requant a low-bit quant onto a library GEMM:** dequant weight → re-quant to a HW-GEMM type → Tensile/hipBLASLt. Per-channel **int8** (fast, low-bpw, symmetric) OR **fp8-e4m3** (its EXPONENT preserves per-block dynamic range a per-row int8 scale COLLAPSES). int8 is always faster but silently breaks wide-range/high-bpw quants → the **PPL-gate is MANDATORY on every requant route; never ship int8 on speed alone.** The byte-win does NOT help compute-bound prefill via int4/WMMA (decode-only lever).
- **M is a curve, not a point:** matmul M = min(prompt_len, n_ubatch); `pp1024` runs at M=512. Heavy-unpack requant routes REGRESS small-M and win large-M → SWEEP M and gate behind a measured-crossover threshold; cheap-dequant routes win throughout M, stay ungated. A single-M reading is not a verdict (a real +17/+26% "win" hid a −44% M=64 regression until review swept it).
- **Calibrate a crossover at GRAPH level, not a tight loop:** an in-kernel micro-timer over a few-iter loop pipelines the route's kernels and HIDES per-call dispatch overhead → mis-fires and picks a regressing threshold. Use a real forward-pass A/B (route-on vs off). Ratios are stable across clock; absolutes swing ~3× with DPM → pin perf-level for measurement; the crossover is PER-MODEL (tracks hidden-size, MOVES with clock — sign can flip).
- **Serving is a lever:** continuous-batching slot count (`-np`/`--parallel`) is PER-MODEL and VRAM-coupled to ctx-per-slot — pick it by the MEASURED throughput KNEE (argmax, stop at the first <3% marginal step = flat-tail/pre-cliff), NOT VRAM-fit-max. Sweep clock-pinned with adequate ntg. Worth 3–14× aggregate on a decode-bound model, near-free.
- **Know what you're editing; stop when saturated:** distinguish the config-ADVISOR from the serving ENGINE — verify the serve-launch passthrough empirically before assuming a config knob reaches the launched process. When decode kernels sit at 95–97% of the measured roofline the kernel lane is SATURATED: the next 20–40% is one level UP (accept-rate/multi-block MTP, active-bytes model co-design, serving throughput), not more ISA polish. A huge speedup that merely restores a self-inflicted slow default path is **baseline-repair, not a net-new win** — don't credit it as one.

## Kernel evaluation (correctness + performance)

Use the bundled `scripts/magpie.sh` (AMD Magpie) for compile + correctness + ranking — do NOT hand-roll a benchmark harness. `magpie compare a.hip b.hip` ranks implementations vs a baseline. **RDNA4 note:** Magpie's default `rocprof-compute` perf backend is CDNA-only; on gfx12xx use `metrix` (wraps `rocprofv3`, has a gfx1201 backend) for duration + HBM/L2 counters, and rank by metrix duration (see `reference.md`). Counters beyond duration: `scripts/profile-datapath-gfx.sh` (rocprofv3, perf-level-aware).

## GPU safety (non-negotiable)

Run a hammering research/benchmark kernel on a NON-display GPU — sustained compute on the display GPU can ring-timeout and kill the desktop. Detect the display GPU (`/sys/class/drm`) and keep it out of your compute set (steady-state *serving* on a card is fine). Never run destructive ops (module reload, perf-level changes) without a rollback plan.

## Output — what you deliver

For every finding: **{ gap · evidence (pasted stdout) · root cause · fix (flag / patch / wrapper / documented switch) · validation (measured before → after) }.** Tuning recommendations graded `measured / peak / %` with the lever that closed each gap. Kernel fixes correctness-gated. Gaps scoped to what's genuinely a vendor issue vs a mundane switch. Nothing upstream without explicit human approval. **Every speed claim shows the raw per-shape times of candidate AND baseline so the reader can recompute the ratio — and states which kernel is faster in words (see Comparison discipline). A verdict whose direction contradicts its own raw times is a red flag, not a result.**

*Detect the silicon, map what it can really do, turn every rock, and leave ROCm better than you found it.*
