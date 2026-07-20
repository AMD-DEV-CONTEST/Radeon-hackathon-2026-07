[← Back to README](../README.md)

# Performance

Full stage-by-stage optimization history, batched-decode numbers, and the Ollama/llama.cpp cross-engine comparison. The headline numbers are also summarized on the [main README](../README.md#benchmark-vte-vs-ollama-llamacpp).

On this page:

- [Single-sequence decode (batch=1)](#single-sequence-decode-batch1): the 18.8 → ~100 tok/s optimization history
- [Batched decode](#batched-decode)
- [Benchmark: VTE vs. Ollama (llama.cpp)](#benchmark-vte-vs-ollama-llamacpp): methodology, per-model write-ups, the VRAM-reduction pass
- [Portability: dynamic Compute-Unit detection](#portability-dynamic-compute-unit-detection-rdna2rdna3-not-just-the-rx-7600)
- [Optimizations tried and rejected](#optimizations-tried-and-rejected)
- [Investigation: pushing past ~100 tok/s (2026-07)](#investigation-pushing-past-100-toks-2026-07): speculative decoding feasibility, RDNA3 kernel micro-architecture audit, tooling gaps
- [Thesis V6: achieved-bandwidth-driven `gemv_q4k` optimization (2026-07)](#thesis-v6-achieved-bandwidth-driven-gemv_q4k-optimization-2026-07): the header-coalescing kernel rewrite that followed the V5 investigation above, a same-process A/B methodology bug caught along the way, and the real end-to-end tok/s gain measured on all three Q4_K models
- [Follow-up: GPU duty-cycle investigation (2026-07)](#follow-up-gpu-duty-cycle-investigation-2026-07): a live Task Manager observation after V6, two plausible hypotheses killed by measurement, and the real (smaller) per-token overhead found outside the kernel itself, in sampling and LM-head logits readback
- [GPU-side top-k logits reduction (2026-07)](#gpu-side-top-k-logits-reduction-2026-07): an opt-in greedy-decode path that reads back a small candidate set instead of the full vocabulary, an eager version that measured as a net loss, and the HIP-Graph-captured version that fixed it
- [Extending these optimizations to other quantizations (2026-07)](#extending-these-optimizations-to-other-quantizations-2026-07): what applies to Granite/Q8_0 and Qwen3.5/Q6_K, and what does not
- [First real Linux/W7900 run: CU-scaling investigation (2026-07)](#first-real-linuxw7900-run-cu-scaling-investigation-2026-07): a plausible under-utilization hypothesis on a 96-CU card (3x the RX 7600), tested with the existing `VTE_NUM_CUS` override, and killed by measurement

## Single-sequence decode (batch=1)

| Stage | Throughput (batch=1) | What changed |
|---|---|---|
| Naive per-thread GEMV | ~18.8 tok/s | Baseline: one thread per output element, no coalescing |
| Coalesced GEMV | ~31.5 tok/s | Threads in a block cooperate on one output neuron, coalesced weight reads |
| In-kernel Q4_K/Q6_K dequantization | ~37.9 tok/s | FFN weights dequantized inline during the GEMV instead of a separate dequant pass ("No-Sync Direct Unpack") |
| QKV Two-Pass Split-K fusion | ~41.0 tok/s | Fills all 32 CUs instead of leaving most idle. See [Architecture: QKV fusion](ARCHITECTURE.md#why-qkv-projection-is-fused-and-why-ffn-fusion-is-off) |
| Vectorized sampler | ~62–70 tok/s | Top-k/top-p/softmax/argsort restricted to the ~50 surviving candidates instead of the full 151936-token vocabulary. See [Bugs found during development](BUGS.md) |
| LM Head captured into the HIP Graph | ~71.7 tok/s | Eliminated the last eager (non-graph) kernel launch in the decode loop. See [Bugs found during development](BUGS.md) |
| Split-KV (Flash-Decoding) attention | ~78–79 tok/s, and *flat* across generation length | Fills far more of the 32 CUs during attention instead of 12; fixes a decline that used to reach ~50.8 tok/s by token 250. See [Bugs found during development](BUGS.md) |
| Keep-alive pulse removed (`VTE_KEEPALIVE_PULSE_MS=0.0`, default) | **~100 tok/s** | A 2ms/tick safety pulse (added to stop WDDM's DPM from downclocking between bursts) became the largest artificial cost once the tick above got fast enough that DPM never gets an idle window long enough to act. See [Bugs found during development](BUGS.md) |

None of the last four rows touched a GEMV kernel's core math: each came from profiling the actual per-token wall-clock budget (not just "the GPU part") and finding real, measurable non-algorithmic costs: CPU-side dispatch overhead, GPU occupancy left on the table, and finally a fixed-cost safety mechanism whose own justification had quietly expired. The GPU-only decode graph itself measures ~130 tok/s in isolation (via HIP Graph replay timing): the ~100 tok/s end-to-end figure is now close enough to that ceiling that further gains need actual kernel-level work (GEMV efficiency, WMMA), not more overhead-hunting.

## Batched decode

`generate_batch` (same-length prompts, lockstep): GPU-only, HIP Graph replay in isolation (no sampler, no logits readback):

| Batch size | Aggregate tok/s | Efficiency vs. ideal linear scaling |
|---|---|---|
| 1 | 110.7 | 100% (baseline) |
| 2 | 165.3 | 75% |
| 4 | 204.2 (peak) | 46% |
| 8 | 193.5 (regresses) | 22% |

The batch=8 regression is attributed to Infinity Cache (32MB) thrashing: FFN weights are ~27.5MB per layer (~88% of per-layer traffic), and at batch=8 the working set for weight reuse across the batch no longer fits comfortably alongside everything else competing for the cache. This hasn't been fixed yet. See [Known limitations](LIMITATIONS.md).

Independently re-measured and reconfirmed after a full repository reorganization (200.7 tok/s aggregate / 50.2 tok/s per sequence at batch_size=4, over 100 decode ticks): these numbers reflect the current state of the code, not a one-off historical run. That said, the ~200 tok/s figure is GPU-only (HIP Graph replay in isolation); the same eager-LM-Head/sampler overhead found in single-sequence decode was also present in batched decode.

**Real end-to-end `generate_batch()` throughput at batch_size=4** (sampler + logits readback included, the number that actually matters for a caller): **127.6 tok/s aggregate** (31.9 tok/s/sequence), up from 118.9 tok/s after capturing the LM Head into the batched HIP Graph (same technique as single-sequence decode, adapted to `[batch_size, vocab_size]` geometry), a real but modest 7.4% gain, smaller than a naive Amdahl's-law projection suggested. See [Bugs found during development](BUGS.md) for why: most of the eagerly-measured LM Head cost turned out to be genuine GPU work (the model's single largest GEMV, batched 4-wide), not removable dispatch overhead.

## Benchmark: VTE vs. Ollama (llama.cpp)

Both models were benchmarked against Ollama running the *exact same GGUF files on disk* (registered with `ollama create <name> -f Modelfile` using `FROM <absolute-path>`, cross-checked via Ollama's own reported SHA256 to confirm it wasn't silently re-quantizing or re-downloading anything). Same prompt, same `num_predict`/`max_tokens`, `temperature=0` on both sides, decode-only timing (prefill/first-token latency excluded on the VTE side; `eval_count`/`eval_duration` used on the Ollama side, the same decode-only window).

**Current numbers** (after the raw-quantized-weight VRAM-reduction pass described below; prompt: "Write a long, detailed essay about the history of space exploration.", ~700 tokens, `temperature=0`):

| Model | VTE | Ollama (llama.cpp) | VTE / Ollama |
|---|---|---|---|
| Qwen2.5 1.5B (Q4_K_M) | **112.98 tok/s** | 110.76 tok/s | **102.0% (VTE faster)** |
| Qwen2.5 7B (Q4_K_M) | 39.60 tok/s | 42.71 tok/s | 92.7% |
| Granite 4.1 3B (Q8_0) | **55.65 tok/s** | 50.84 tok/s | **109.5% (VTE faster)** |
| Qwen3.5 2B (Q6_K) | 69.00 tok/s | 77.00 tok/s | 89.6% |

This is a real milestone: Granite now decodes *faster* on VTE than on Ollama/llama.cpp with the identical GGUF file, and so does Qwen2.5 1.5B after Thesis V6's `gemv_q4k` fix below.

**Note on the Qwen2.5 rows**: the VTE side of both was re-measured with the exact prompt/token-count/`temperature=0` methodology described here, after Thesis V6's header-coalescing fix. The Ollama side was not re-run (Ollama's local model registrations from the original benchmark session were not still present when this was checked), so these two ratios compare a fresh VTE number against an older Ollama number, not a same-session matched pair like Granite/Qwen3.5 above.

### Qwen 2.5 7B (Q4_K_M)

Same methodology, same GGUF file on both sides (registered in Ollama via `ollama create qwen25-7b-ref -f Modelfile` with `FROM "<absolute path>"`: the path needs quoting, this repo's own path has a space in it, `Aetheris Flow`, an unquoted `FROM` silently reads garbage). File size matching (4683074208 bytes both sides) is **not** sufficient verification on its own: a raw fixed-offset byte comparison between the two files showed differences starting at byte 0, which looked alarming until parsing both with `gguf.GGUFReader` (which respects each file's own tensor-offset table rather than assuming identical raw layout) confirmed the actual tensor data is byte-identical; Ollama's ingestion repacks the metadata/header section, shifting every tensor's absolute file offset without changing a single weight value. Verify by comparing tensor `sha256` through `gguf.GGUFReader`, not raw file diffing, in future benchmarks. Prompt: "Write a long, detailed essay about the history of space exploration.", `num_predict`/`max_tokens=700`, `temperature=0`, decode-only timing (first token excluded on both sides).

**39.60 tok/s (VTE, post-V6) vs. 42.71 tok/s (Ollama): 92.7%.** The largest model registered so far (28 layers, hidden=3584, ffn=18944, 2.3x Qwen2.5 1.5B's hidden size), and still the widest gap of the four models, though smaller than before V6 (was 84.0%). Per-category profiling (`VTE_PROFILE=1`, eager/`FallbackExecutor` path: the only one instrumented; absolute ms/tok don't transfer to the HIP-Graph production path due to eliminated per-launch dispatch overhead, but the *proportion* between categories does) confirms the gap lives where expected: ~73% of GPU time in the four large GEMV categories (FFN_Gate_Up 28.0%, QKV_proj 18.4%, FFN_Down 15.9%, AttnOutput 6.9%, LMHead 3.8%): the same shared GEMV/FFN kernels already tuned for Qwen2.5 1.5B and Granite, not a dispatch-overhead or missing-fusion problem (both already ruled out at this model's smaller siblings).

Effective-bandwidth math makes the size-dependent trend concrete: VTE moves its 4495MB of resident weights at ~178 GB/s effective (39.60 tok/s), Ollama at ~192 GB/s (42.71 tok/s). The same math at 1.5B (942MB resident weights) puts VTE at ~106 GB/s effective (112.98 tok/s) against Ollama's ~104 GB/s (110.76 tok/s): VTE is now marginally ahead there, not just tied. The relative gap to llama.cpp's hand-tuned GEMV still widens as the matrices get bigger, but by less than before V6's fix (9.3 points between the two ratios now, was 13.4). Leading hypothesis for the remainder (not yet proven down to the instruction level, would need `rocprof` or equivalent): `gemv_q4k.hip.template`'s per-layer working set roughly doubles at this size (ffn=18944 vs 8960), and RDNA3's 32MB Infinity Cache likely holds a smaller fraction of it in cache across the decode of a single token: the same cache-pressure mechanism already documented for the batch=8 batched-decode regression, just triggered by model width here instead of batch size.

**Accepted as the current number, not a pending TODO**: same posture as the Qwen3.5 tok/s gap above. Closing it further would mean re-tuning the shared GEMV kernel's tiling for larger `K`/`N` dimensions specifically, which risks regressing the already-tuned 1.5B/Granite paths and is a real kernel-engineering project, not a quick fix: deferred until there's a specific reason to prioritize it over other work.

<details>
<summary>Previous numbers (before the VRAM-reduction pass), kept for history</summary>

| Model | VTE | Ollama (llama.cpp) | VTE / Ollama |
|---|---|---|---|
| Qwen2.5 1.5B (Q4_K_M) | 101.68 tok/s (9.84 ms/tok) | 114.67 tok/s (8.72 ms/tok) | 88.7% |
| Granite 4.1 3B (Q8_0) | 45.66 tok/s (21.90 ms/tok) | 51.46 tok/s (19.43 ms/tok) | 88.7% |

Notably consistent at the time: VTE delivered ~89% of llama.cpp's throughput on both models, an identical ratio despite very different architectures (different RoPE convention, different quantization format, ~2x the parameters).
</details>

Ollama was used only as a disposable reference during these benchmarks: the models, their Modelfiles, and the Ollama server process were all removed/stopped afterward; VTE has no runtime or build dependency on it.

It's also worth stating plainly what that number means, because it's the actual point of measuring against Ollama at all: the code doing the dispatching here is **Python**, not C++. Ollama's inference math runs in llama.cpp: hand-tuned C++ GEMV kernels with years of upstream optimization, called through a thin Go server. VTE's Python layer builds the compute graph, resolves kernel arguments, and drives every HIP launch through ctypes: the language usually blamed for making GPU dispatch too slow to compete. Beating llama.cpp's throughput on Granite, and tying it on Qwen2.5, with that much interpreter overhead in the loop is direct evidence for this project's core bet: that CPU-side dispatch overhead and VRAM-bandwidth waste are engineering problems you can profile and remove (HIP Graphs, a sampler restricted to top-k, the LM Head captured into the graph, and now raw-quantized weight routing. See [Bugs found during development](BUGS.md)), not an inherent tax Python has to pay.

### VRAM-reduction pass: routing `attn_q/k/v/output` raw instead of dequantizing to FP16

Both `qwen_mapper.py` and `granite_mapper.py` previously dequantized the four attention projection weights (`attn_q`, `attn_k`, `attn_v`, `attn_output`) from their on-disk quantized format (Q4_K/Q6_K/Q8_0) to FP16 at load time, so they could feed the fused QKV+RoPE kernel (`fused_norm_matmul_rope`/`split_k_qkv_pass2`), which only knows how to read raw `__half*` buffers. This roughly doubles those four matrices' footprint in VRAM relative to the actual bytes on disk.

Granite's GGUF is Q8_0 (2x expansion when dequantized to FP16); attacking `attn_q/k/v` in addition to `attn_output` was accepted as a deliberate bigger-risk/bigger-reward move (~700MB more saved, at the cost of losing the QKV+RoPE fusion for the layers where these weights are now raw). The change:

- `granite_mapper.py::is_raw_q8_0_weight` no longer excludes `attn_q/k/v/attn_output` by name: all Q8_0 tensors are now routed raw (dequantized in-kernel by the GEMV instead of at load time).
- `qwen_mapper.py::is_raw_q4k_weight`/`is_raw_q6k_weight` similarly extended to cover `attn_q/attn_k/attn_output` (Q4_K) and `attn_v` (Q6_K).
- The QKV+RoPE fusion is dynamically disabled per-layer whenever any of these four weights is raw for that layer (the fused kernel has no dequant logic and would otherwise read garbage): both `fallback_executor.py` and `hip_graph_executor.py` check the raw-weight sets before attempting the fusion.

Measured impact:

- **Granite**: VRAM 4010.7MB → 3448.2MB (weights), tok/s 48.26 → 55.65 (used to trail Ollama at 88.7%, now leads at 109.5%).
- **Qwen2.5**: weights ~986MB → 942.0MB, tok/s ~101.68 → 107.85 (closed the gap from 88.7% to 97.4%).

The counter-intuitive result is that losing the QKV+RoPE fusion (previously assumed to be a pure win. See [Architecture: why QKV is fused](ARCHITECTURE.md#why-qkv-projection-is-fused-and-why-ffn-fusion-is-off)) is more than paid back by the reduced VRAM bandwidth traffic of never writing/reading the FP16-expanded copies of these four matrices: at batch=1 decode, VRAM bandwidth for weight reads dominates over the fixed cost of one extra kernel launch. This only holds for `attn_q/k/v/output` specifically; it does not generalize to arbitrarily fusing less. See "Optimizations tried and rejected" below for cases where fusion removal or kernel-count reduction measured as a net loss or null result.

### Qwen 3.5 2B (hybrid Gated DeltaNet)

Same methodology, same GGUF file on both sides: **~69 tok/s** decode-only on VTE vs. **77 tok/s** on Ollama (llama.cpp), ~89.6% of Ollama's throughput, measured after the correctness work in [Multi-architecture support: Qwen 3.5](QWEN35.md) landed (that document covers the actual bugs found bringing this architecture up; this section is performance only).

Three kernel-fusion/occupancy experiments were tried afterward to close the remaining gap, each measured with the same protocol (150 tokens, decode-only, excluding the first token/prefill): all three came back as null results, kept in the code (numerically validated, harmless) rather than reverted, so they aren't blindly re-attempted:

1. **Fusing `a_proj`+`b_proj` into one kernel** (later superseded by the larger fusion below): 67.00 tok/s: within noise of the ~66.78 tok/s baseline.
2. **`causal_conv1d` occupancy tuning** (block size 256→64, exactly one RDNA wavefront, grid 24→96 blocks to use all 32 CUs instead of leaving half idle): 66.66 tok/s: null.
3. **Fusing `qkv_proj`+`z_proj`+`a_proj`+`b_proj` into a single kernel** (`fused_gdn_proj.hip.template`, combining Q6_K and Q8_0 dequant logic in one per-line launch, removing 3 of the ~15 nodes per `linear_attention` layer, 54 nodes total, ~15% of the 393-node graph): 67.26 tok/s: still null.

Per-category GPU profiling (`VTE_PROFILE=1`) explains why: the new Gated DeltaNet kernels already account for only ~17.5% of GPU time in the eager profile, so optimizing them further has little headroom left to recover. The remaining ~56% is the large GEMV/FFN kernels Qwen3.5 *shares* with Qwen2.5/Granite (already tuned there): closing more of the gap to Ollama would mean touching that shared, already-optimized infrastructure and risking regressions on the other two models, not another isolated Qwen3.5-only change. ~69 tok/s is treated as the real number for this architecture for now, not a pending optimization TODO.

## Portability: dynamic Compute-Unit detection (RDNA2/RDNA3, not just the RX 7600)

Several grid-sizing formulas throughout this project were tuned empirically for the RX 7600's 32 CUs specifically (the only card this was developed and measured on): comments like "espalha por todos os 32 CUs da RX 7600" litter the codebase for a reason. `HIPRuntime.get_num_cus()` (new) reads the real CU count of whatever GPU is active at runtime, so those formulas scale to any RDNA2/RDNA3 card instead of silently under- or over-subscribing a different one:

- **`vte/core/split_kv_attention.py::_chunk_size_for_cus(num_cus)`**: the Split-KV attention chunk size (fixed `32` before) is now `clamp(round(1024 / num_cus), 8, 64)`: reproduces `32` exactly at `num_cus=32` (zero regression on the reference card, verified byte-for-byte identical output), and scales inversely (more CUs → smaller chunks → more parallel blocks; fewer CUs → larger chunks → less reduce-kernel overhead per mostly-idle block) elsewhere.
- **`causal_conv1d`'s grid** (Qwen3.5 Gated DeltaNet) was *already* hardware-agnostic despite its comment implying otherwise: its block count derives from `conv_dim / 64` (a model-width constant, not a GPU-count constant), so it already produces enough blocks (96, for Qwen3.5) to reasonably occupy any RDNA2/RDNA3 card without needing `num_cus` as an input. Comment corrected; no logic change.
- **QKV Two-Pass Split-K's factor of 32** (`vte/core/fused_qkv_dispatch.py`, `split_k_qkv_pass1/pass2.hip.template`) was *not* made dynamic in this pass: the constant is baked into pointer arithmetic in two kernel templates (not a single `#define`, unlike the Split-KV case) and has a real correctness constraint (`hidden_size` must divide evenly by the split factor) that would need verifying against every supported model's `hidden_size` before any change. Deferred as a deliberate scope decision, not an oversight: the Split-KV fix addresses the same underlying problem (a kernel calibrated only for 32 CUs) with much lower risk.

**A real bug found along the way, worth calling out separately from the CU work itself**: `HIPRuntime`'s hand-maintained `hipDeviceProp_t` struct was silently returning garbage (`38911`) for `multi_processor_count`. See the writeup in [Bugs found during development](BUGS.md) for the full investigation (a struct-layout mismatch with the installed driver, and a genuine RDNA quirk where `hipDeviceGetAttribute`'s multiprocessor-count attribute reports WGPs, not raw CUs: `*2` corrects it). `get_num_cus()` uses the fixed, corrected path.

`VTE_NUM_CUS` env var overrides the detected count for testing (e.g. simulating a different card's CU count on the same physical GPU) without needing the actual hardware.

## Optimizations tried and rejected

Kept disabled rather than removed, so they don't get re-implemented blindly:

- **FFN kernel fusion** (RMSNorm+Gate+Up+SiLU in one launch): measured slower than the unfused version (12.7–13.5 tok/s vs. 18.8 tok/s): register pressure from holding two accumulators in one loop drops occupancy enough to erase the round-trip savings. Kept behind `VTE_ENABLE_FFN_FUSION` for anyone who wants to re-run the experiment. Full root-cause in [Architecture: Why QKV projection is fused, and why FFN fusion is off](ARCHITECTURE.md#why-qkv-projection-is-fused-and-why-ffn-fusion-is-off).
  - **Update**: `fused_gate_up_silu_kernel` previously produced NaN outright (`ffn_gate.weight`/`ffn_up.weight` are kept raw Q4_K in VRAM per `is_raw_q4k_weight`, but the kernel read them as plain `__half*`). Fixed with a scalar per-element Q4_K dequant matching `gemv_q4k`'s superblock layout, output is correct now, verified coherent on Qwen2.5-1.5B. Re-measured against the current ~100 tok/s baseline: **4.2 tok/s**, far worse than even the old rejected numbers above. Root cause: the scalar dequant recomputes each superblock's `d`/`dmin`/scale from scratch on every one of the 1536 `k` iterations instead of amortizing them once per 256-element superblock (`gemv_q4k` caches this per-block and vectorizes the load with `uint4`). Still not viable; still disabled by default. A properly block-cached dequant might close the gap, but that's a real optimization exercise, not a bugfix, and was not attempted here.
- **WMMA/Tensor Cores**: rejected early for pure batch=1 GEMV (no benefit at that arithmetic intensity). Worth re-measuring now that batch>1 GEMM is a real, validated code path: not yet done.
- **LDS double-buffering, Split-K for FFN GEMV, explicit ILP prefetch, and other RDNA3 micro-architecture ideas for `gemv_q4k`/attention**: all evaluated and rejected in the 2026-07 investigation cycle below, see [Investigation: pushing past ~100 tok/s](#investigation-pushing-past-100-toks-2026-07) for the full reasoning on each.

## Investigation: pushing past ~100 tok/s (2026-07)

A follow-up investigation cycle asked two questions. First, is speculative decoding (draft-free, via Prompt Lookup Decoding) worth building on top of the current pipeline. Second, is there still real headroom in the GEMV/attention kernels themselves, between the ~100 tok/s end-to-end number and the decode graph's own ~130 tok/s GPU-only ceiling. Both were run with the same discipline as everything else on this page: measure before implementing, and be willing to close a line of investigation on evidence (including static/structural analysis, not just benchmark numbers) rather than implement something the evidence already argues against.

**Bottom line up front**: no viable optimization was found this round. Two real, independent, previously-undiscovered bugs got fixed along the way (below). Speculative decoding was re-evaluated with a cheap feasibility check and killed *before* implementation this time, unlike the earlier draft-model/PLD implementation-then-revert in [Known limitations](LIMITATIONS.md#reverted-features-and-vram-management), which found out the hard way. ~100 tok/s stands as the practical ceiling for this hardware/codebase until either RGP hardware counters become available (needs a full AMD driver install, not attempted) or a genuinely different architectural approach is pursued.

### Tooling: RGP unavailable, and a real profiler bug fixed

- **Radeon GPU Profiler (RGP) is not usable on this dev machine.** `RadeonDeveloperServiceCLI.exe` fails with `Failed to create router context: DD_RESULT_DD_GENERIC_UNAVAILABLE`. AMD's Developer Driver Toolkit hook, which RGP/RDP's capture depends on, isn't present. This machine only has the bare `amdhip64.dll` HIP runtime (from the HIP SDK install), not a full Radeon Software/Adrenalin driver package; it's the full driver that ships the Developer Driver service. Not fixable by running RDS/the RDP CLI elevated (tried both, including verifying a genuinely fresh elevated service instance by PID/start-time; same error persists on the client side regardless), since the hook genuinely isn't in the installed driver stack. Installing the full AMD driver would fix it but is a real driver-level system change, more invasive and less reversible than anything else this round (portable RGP/RDP/RDS zip, HIP SDK to a custom directory), so it was not attempted, out of scope for this round. Hardware-counter data (wavefront occupancy, cache hit rate, `s_waitcnt` stalls, achieved vs. theoretical memory bandwidth) is consequently unavailable here; every finding below comes from software-side timing (`VTE_PROFILE=1`) and static compiler analysis (`hipcc -Rpass-analysis=kernel-resource-usage`, `-save-temps` plus assembly inspection) instead.
- **`VTE_PROFILE=1`'s category report never worked until now.** `KernelProfiler.mark_token()` existed (with a clear docstring purpose) but was never called anywhere in the codebase, so `report()` always short-circuited on `tokens == 0` ("nenhum token medido" / "no tokens measured"). Fixed by timing each decode iteration in `model.py`'s `generate()` loop and calling `mark_token()`, gated on `PROFILER.enabled` so there's zero cost when profiling is off. This had apparently never produced output in this codebase's history before this fix.
- **Category breakdown only works under `FallbackExecutor` (`use_hip_graph=False`)**. `hip_graph_executor.py` has no `set_category()`/`record()` calls at all, since HIP Graph replay bundles kernel launches rather than dispatching them individually from Python. This means the *absolute* wall-clock/overhead numbers from a `VTE_PROFILE=1` run are only representative of the eager fallback path (much higher CPU dispatch overhead than the real HIP-Graph decode loop), but the *relative* GPU-ms split between kernel categories should still be meaningful, since HIP Graph capture removes CPU dispatch overhead, not the GPU-side kernel execution time itself.

### Category breakdown (Qwen2.5-1.5B, 150 decode tokens, fallback executor, post-`mark_token`-fix)

| Category | % of GPU time | Notes |
|---|---|---|
| FFN_Gate_Up | 25.1% | 2 `gemv_q4k` launches/token (gate_proj + up_proj), `out_features=intermediate_size=8960` each |
| QKV_proj | 17.4% | `out_features≈2048` (GQA) |
| FlashAttention | 17.2% | Split-KV kernels |
| FFN_Down | 13.4% | 1 `gemv_q4k` launch/token, `out_features=hidden_size=1536` |
| RMSNorm | 6.5% | |
| AttnOutput | 6.4% | `gemv_coalesced` (FP16, not Q4_K) |
| LMHead | 5.7% | |
| RoPE | 5.1% | |
| SwiGLU | 3.2% | |

QKV_proj + FFN_Gate_Up + FFN_Down (all `gemv_q4k`, the Q4_K GEMV family) together are **55.9%** of GPU time, the largest single target. FlashAttention + AttnOutput add another 23.6%. Together, **79.5% of GPU time is accounted for by kernels that got a full static-analysis audit** (below); every one came back clean.

### Speculative decoding feasibility (Thesis V4: Prompt Lookup Decoding)

Before touching any kernel, the cheaper question was checked first: is speculative decoding even worth pursuing here. A standalone, read-only script simulated PLD's n-gram lookup drafter against real generated token sequences with no engine changes: for each decode position, search backward through the known context for the most recent prior occurrence of the last 2-3 tokens, propose what followed it last time (up to 5 tokens), and compare against what the model actually generated.

| Prompt style | Coverage (draft found) | Accept ratio when drafted | Overall acceptance rate |
|---|---|---|---|
| Favorable: code generation (Python class) | 25.8% | 27.4% | **27.6%** |
| Favorable: summary+repeat (weaker test; the 1.5B model didn't reliably follow the literal-repeat instruction) | 25.8% | 21.8% | 21.8% |
| Unfavorable: free-form creative story | 2.4% | 8.0% | 8.0% |

Gate (set before measuring): 40% or higher acceptance on the favorable case to be worth pursuing further. **Result: 27.6% best case, fails the gate.** Even code generation, PLD's classic sweet spot, doesn't give the n-gram lookup enough repeated structure to work with on this model's short, non-repetitive outputs. Speculative decoding (verification kernel, GPU-side rejection, KV-cache rollback) was not implemented this round on the strength of this result, matching the project's own prior experience the hard way (see [Known limitations](LIMITATIONS.md#reverted-features-and-vram-management): an earlier draft-model plus PLD implementation was built, made correct, and still measured as a net loss).

### RDNA3 kernel micro-architecture audit (Thesis V5)

A structured pass through several falsifiable hypotheses about why the GEMV/attention kernels might have headroom left, run in order, each closed on evidence before moving to the next:

1. **Split-K for FFN GEMV, to fix "low occupancy from ~35 blocks": rejected, wrong premise.** The "~35 blocks" figure is real, but belongs to `fused_gate_up_silu_kernel` (`block_size=256`, `grid≈intermediate_size/256≈35`), the fused FFN path, disabled by default (`VTE_ENABLE_FFN_FUSION`) and already measured as 24x worse (see "Optimizations tried and rejected" above). It does not describe the kernel that's actually running. `gemv_q4k`'s actual grid (`fallback_executor.py::_coalesced_gemv_dims`: `grid=(out_features, batch*seq_len, 1)`) is one block *per output row*: 8960 blocks for FFN gate/up (~280 blocks/CU on this 32-CU card), 1536 for FFN down (~48 blocks/CU). Neither is remotely occupancy-starved. Implementing Split-K here would have added a VRAM reduction pass to solve a problem that doesn't exist in this code path.
2. **LDS double-buffering for `gemv_q4k`: rejected on structural analysis, not implemented.** Each block reads its own Q4_K weight row and its assigned slice of the input vector `X` exactly once per thread, with no repeated access to the same address within a block for LDS caching to eliminate. `X` is technically re-read redundantly *across* blocks, but LDS is per-block scratchpad and can't help with cross-block reuse (only L1/L2 hardware cache can, and `X` is small enough, 3KB for Qwen2.5's `hidden_size=1536`, to almost certainly stay resident there already). The kernel's own header comment states its current design (async global loads straight to VGPRs, no `__syncthreads()`) already targets latency hiding via ILP; adding LDS buffers would mean reintroducing sync barriers to reimplement something already happening implicitly.
3. **Per-launch comparison, FFN_Gate_Up vs. FFN_Down.** `_profile_category()` groups gate_proj+up_proj together as `FFN_Gate_Up` (2 launches/token) and down_proj alone as `FFN_Down` (1 launch/token). Per-launch: ~12.55% each for gate/up (280 blocks/CU) vs. 13.4% for down (48 blocks/CU), nearly identical despite a ~6x difference in blocks-per-CU, even though both directions move the same total weight bytes (`1536×8960` either way, just transposed). Occupancy in the 48 to 280 blocks/CU range doesn't measurably change per-launch throughput here, further evidence against an occupancy-bound story.
4. **Static assembly audit (`hipcc -Rpass-analysis=kernel-resource-usage`, `-save-temps`): clean across every kernel checked.** `gemv_q4k`: 37 VGPRs, **0 VGPR spill, 0 SGPR spill, 0 bytes/lane scratch**, 16 waves/SIMD occupancy (compiler-reported max for this footprint), confirmed by grepping the generated `.s` for `scratch_store`/`scratch_load` (zero matches, no register spilling at the instruction level, not just the summary line). `flash_attention.hip.template`, `flash_attention_split_kv_partial`, `flash_attention_split_kv_reduce`: same signature, 0 spill, 16 waves/SIMD, 11-22 VGPRs. No compiler-level inefficiency found anywhere in the 79.5%-of-GPU-time kernels audited.
5. **Explicit ILP prefetch (issue load N+1 before consuming load N): found architecturally inapplicable to most of the target, not implemented.** `gemv_q4k`'s inner loop runs `for (sb_base = 0; sb_base < n_sb; sb_base += 8)` where `n_sb = in_features / 256`. For FFN_Gate_Up and QKV_proj, `in_features = hidden_size = 1536`, so `n_sb = 6`, meaning **each thread executes exactly one iteration of that loop**: there's no "next iteration" within a thread to prefetch across at all, and this covers 42.5 of the 55.9 percentage points (FFN_Gate_Up 25.1% + QKV_proj 17.4%). Only FFN_Down (`in_features=intermediate_size=8960`, `n_sb=35`, 5 iterations) has genuine loop-carried structure. Separately, since occupancy is already compiler-confirmed at its maximum (16 waves/SIMD, hundreds of blocks queued per CU), the GPU already has abundant alternate wavefronts to switch to while any one wave's load is in flight: the standard occupancy-based latency-hiding mechanism is already saturated, making instruction-level prefetch within a single wave likely redundant even for the FFN_Down slice where it would structurally apply.
6. **X-vector read vectorization: checked, already optimal.** The C++ source reads `X[xbase+bl]` in an unrolled scalar-looking loop (32 individual `__half` accesses per thread), which looked like a possible missed-vectorization bug. Checked directly in the generated assembly: `hipcc`'s backend already auto-vectorizes these into `global_load_b128` (128-bit) instructions on its own. 4 of the 5 `global_load_b128` instructions in the compiled kernel are the auto-vectorized `X` reads, the 5th is the explicit weight `uint4` load. Nothing to fix here.

### Conclusion

Across `gemv_q4k` (55.9% of GPU time) and the FlashAttention family (23.6%), 79.5% combined, every kernel checked shows zero VGPR/SGPR spill, zero scratch memory, maximum compiler-reported occupancy, and already-vectorized memory access. Every hypothesis generated this round (Split-K occupancy fix, LDS double-buffering, per-launch occupancy sensitivity, ILP prefetch depth, X-read vectorization) was checked against real evidence, assembly output, dispatcher code, or measured per-launch timing, rather than assumed, and each came back either factually wrong about the active code path or already handled by the compiler. That convergence is itself the finding: these kernels are close to what `hipcc`'s backend can extract for this access pattern on this hardware, using tools available on this machine. Closing the remaining gap to the ~130 tok/s GPU-only ceiling (let alone the ~250 tok/s theoretical bandwidth ceiling) most likely requires hardware-counter data (achieved vs. theoretical memory bandwidth, real cache hit rates, true wavefront stall reasons) that RGP would provide and this machine's driver stack can't (see "Tooling" above), or a genuinely different architectural approach, not further micro-tuning of the current kernels.

## Thesis V6: achieved-bandwidth-driven `gemv_q4k` optimization (2026-07)

V5 above left one thing unmeasured: the *achieved* memory bandwidth of `gemv_q4k` in isolation, as opposed to its compiler-reported resource usage (which was already clean). A kernel can have zero register spill and maximum occupancy and still leave bandwidth on the table through access-pattern effects invisible to `-Rpass-analysis`. This round measured that directly with a standalone HIP-events microbenchmark (`tools/bench_gemv_q4k_bandwidth.py`), rather than inferring it from end-to-end tok/s, which conflates the GEMV with attention, sampler, and dispatch overhead.

### Phase A: the achieved-bandwidth gate

Isolated `gemv_q4k` against a same-topology read-bandwidth baseline kernel (coalesced `uint4` reads, no dequant, no MAC) on the FFN-down shape (`in_features=8960`, `out_features=1536`, Qwen2.5-1.5B's largest single Q4_K GEMV). Getting a trustworthy number took four failed methodologies in a row before landing on one (documented in the tool's own module docstring): sync-per-launch was dominated by CPU dispatch overhead; no-sync batch timing let the GPU pipeline/overlap launches and defeated the cold-buffer pool; per-launch GPU-only event timing (`VTE_PROFILE=1`) fixed the signal-to-noise problem but still showed real clock/thermal drift across runs with a short warm-up. The fix: a 300-launch warm-up before each timed section, 5 independent trials per run, reporting median/min/max.

**Result: `gemv_q4k` achieved a median 76.5% of the baseline's bandwidth** (range 71.5% to 85.9% across 5 trials), inside the plan's pre-registered 55 to 85% "real headroom exists" band, not the 85%-or-higher "already saturated" band. Root cause identified by reading the kernel against the RDNA3 memory-hierarchy notes in [`RDNA3-ARCHITECTURE.md`](ROCm/RDNA3-ARCHITECTURE.md#memory-hierarchy): each superblock's 16-byte header (`d`/`dmin`/`scales`) was read independently by all 8 threads sharing that superblock, 8x redundant small scattered loads, alongside the already-coalesced 128-bit weight-chunk loads.

### Phase B1: header coalescing via `__shfl`

Rewrote `gemv_q4k.hip.template` so only the thread at `chunk==0` in each 8-thread `sbgroup` issues the single aligned 16-byte header load (`uint4`), broadcasting `d`/`dmin`/`scales` to its 7 peers via `__shfl` (register-to-register, no extra memory traffic). Valid because an 8-thread `sbgroup` never crosses a wave32 boundary (`sbgroup*8` is always a multiple of 8, and 8 divides 32).

**Bug found and fixed along the way**: the first working version compiled with `ScratchSize: 32 bytes/lane` despite zero VGPR/SGPR spill, a real register-spill regression the header-coalescing rewrite introduced. Root cause: dynamically indexing (`s[sub0]`, with a runtime `sub0 = 2*mblk`) into a *local* byte array to extract scale/min bytes forces scratch-memory allocation, because dynamic indexing into register-resident local data has no hardware support, unlike the same pattern against *global* memory, which the original kernel already did safely. Fixed with a pure-ALU helper (`q4k_header_sbyte()`, ternary select plus variable shift over separate scalar words instead of array indexing) that brought `ScratchSize` back to 0. General lesson for future RDNA3 kernel work here: local/register-resident aggregates must be indexed statically or via ALU select, never dynamically like a global-memory pointer.

Numeric correctness: validated against `dequantizer.py::dequantize_q4_k`, the correct reference for this kernel (`math_refs.py::ref_dequantize_q4_k_m` has an unrelated `-8.0` nibble offset used by a *different* kernel, `matmul.hip.template`, and does not apply here). Output was bit-identical to the original kernel's on a real random-weight validation run.

### The same-process methodology trap (a second lesson this round)

Comparing Phase A's cross-process runs naively (76.5% before B1, separately re-run at 82.8% after) looked like a solid ~6-point win. It wasn't trustworthy: the *unchanged* baseline kernel's own measured bandwidth drifted more than 5% between the two separate `python` process launches (210 to 196 GB/s), meaning some, possibly most, of the apparent ratio improvement was GPU clock/thermal state varying between process launches, not the code change. Caught by comparing `gemv_q4k`'s own *absolute* GB/s across the two runs: it went slightly *down* (160.9 to 156.4), while the ratio went up, a result that shouldn't happen if the kernel change were a real, clean win.

Fixed with a same-process, interleaved A/B tool (`tools/bench_gemv_q4k_ab_compare.py`): both kernel versions loaded and compiled once, benchmarked back-to-back within one process, alternating which one runs first each trial so neither is systematically favored by warm-up state. First pass (5 trials) was still noisy (median +1.3% per-trial, one trial negative). Extended to 15 trials for a clean signal: **mean +4.41%, median +3.8% per-trial gain, stdev 3.65%, 14 of 15 trials favored B1** (only one trial slightly negative, -2.1%), a real, directionally consistent effect, more modest than the naive cross-process comparison implied but not noise.

### End-to-end verification

Per the plan's own gate (`gemv_q4k` is shared by every Q4_K model, so a change here must be validated beyond one model): full `pytest` green (77 passed, 3 skipped, unchanged from baseline), then real decode-only tok/s (`VTEModel.generate()`'s own `stats['decoding_speed_tps']` accounting, excludes prefill) measured on all three Q4_K models, `temperature=0`, median of 3 runs of 300 tokens each, same essay prompt used elsewhere on this page, before (original kernel, via `git stash`) and after (B1):

| Model | Before (original) | After (B1) | Gain |
|---|---|---|---|
| Qwen2.5 1.5B (Q4_K_M) | 108.24 tok/s | 112.92 tok/s | +4.3% |
| Qwen2.5 7B (Q4_K_M) | 37.15 tok/s | 40.36 tok/s | +8.6% |
| Llama 3.1 8B (Q4_K_M) | 35.83 tok/s | 38.52 tok/s | +7.5% |

All three generations remained coherent (no NaN/garbage output). The gain is larger on the 7B/8B models than on 1.5B, consistent with `gemv_q4k` making up a larger share of total GPU time on bigger models (more/larger FFN GEMVs per layer relative to the fixed per-token dispatch/attention overhead).

**Verdict: kept.** B1 passes the plan's own gate (measurably faster, numerically correct) on real, verified evidence rather than the initially-misleading cross-process ratio. The gain is modest, not transformative, and remains well short of the ~130 tok/s GPU-only ceiling discussed in V5, but it is real, reproducible, and positive on every model tested, with no regression anywhere.

## Follow-up: GPU duty-cycle investigation (2026-07)

After V6 shipped, live observation of Windows Task Manager during real generation suggested Qwen2.5 1.5B's GPU usage dropped to ~70% after the B1 change (from ~90% before), while Qwen2.5 7B and Llama 3.1 8B stayed pinned near ~90% throughout. Rather than building a theory on a visual reading, this was measured with tool-independent HIP events (`hipEventRecord`/`hipEventElapsedTime` bracketing the real production decode-graph replay, `HIPGraphExecutor.execute_decode`), since Task Manager's default "GPU" graph is usually the 3D engine rather than the Compute engine HIP kernels actually run on, and its sampling is coarser than a per-token measurement.

### Real GPU duty cycle (GPU-busy-ms / wall-clock-ms, `tools/bench_dispatch_vs_gpu_duty.py`)

| Model | Kernel | Duty cycle | tok/s |
|---|---|---|---|
| Qwen2.5 1.5B | original | 87.3% | 105.35 |
| Qwen2.5 1.5B | B1 | 86.4% | 110.71 |
| Qwen2.5 7B | original | 96.1% | 37.39 |
| Qwen2.5 7B | B1 | 95.6% | 40.15 |

The directional shape of the live observation was real (1.5B does run at a visibly lower duty cycle than 7B), but the before/after comparison was not: B1 barely moved either model's duty cycle (within ~1 point, noise-level), not a 90% to 70% drop. Two specific hypotheses were then tested and **both rejected by measurement**:

1. **"Bigger kernels end up less optimized": rejected.** If true, 7B (bigger GEMVs) should show a *lower* duty cycle than 1.5B. The data show the opposite (96% vs 87%).
2. **"The 95% GPU duty-cycle safety limiter (`HIPRuntime._enforce_duty_cycle_limit`, `_duty_cycle_limit = 0.95`) is capping 7B near that ceiling": rejected.** 7B's duty cycle sitting suspiciously close to 95% was coincidence, not causation. Instrumenting `_throttle_before_dispatch()` (the preventive check before every launch) and `synchronize()` (which also triggers the limiter) directly showed the limiter never actually engaged a sleep for either model (0/213 and 0/163 preventive checks slept; only 1/213 and 1/163 `synchronize()` calls exceeded 1ms, consistent with ordinary OS scheduling noise, not a real throttle event).

### The real cause: a per-token decode-step breakdown (`tools/bench_decode_step_breakdown.py`)

| Bucket | Qwen 1.5B | Qwen 7B |
|---|---|---|
| staging buffer memcpys | 0.298 ms/tok (3.7%) | 0.354 ms/tok (1.5%) |
| `graph_launch()` wall time | 7.464 ms/tok (93.5%) | 23.724 ms/tok (97.6%) |
| of which GPU-busy | 6.431 ms/tok (80.6%) | 22.238 ms/tok (91.5%) |
| `synchronize()` | 0.219 ms/tok (2.7%) | 0.231 ms/tok (0.9%) |
| **total wall/tok** | **7.98 ms** | **24.31 ms** |

Neither model's non-GPU time is dominated by a single big cost. It's distributed across staging-buffer memcpys, the `hipGraphLaunch` dispatch call itself, and the final device sync, all roughly *similar in absolute milliseconds* between the two models (~1.5 to 2ms combined), while GPU-busy time scales up ~3.5x from 1.5B to 7B. A near-fixed cost against a growing denominator is exactly what produces a lower duty-cycle *percentage* on the smaller/faster model: plain Amdahl's-law overhead amortization, not a sign of unoptimized kernels.

**Instrumentation self-check**: before trusting that ~1 to 2ms/tok gap, it was checked against measurement artifact. `bench_decode_step_breakdown.py`'s own HIP-event wrapping (2 extra `hipEventRecord` calls plus `hipEventElapsedTime`, none of which exist in production) could itself inflate the measured gap. A leaner check (`tools/bench_lean_decode_step.py`, a single `perf_counter` pair around the *unmodified* `execute_decode()`, zero added HIP calls) measured 7.69 ms/tok for Qwen 1.5B, close to but about 0.29ms below the heavier instrumentation's 7.98ms/tok. Conclusion: most of the gap is real production overhead, with a smaller (~0.3ms/tok) slice attributable to the measurement tool itself. This distinction matters before proposing any fix here: it's the same "verify against real state, not the first number you get" discipline used throughout V6's own methodology traps.

### An overhead layer entirely outside the kernel dispatch path (`tools/bench_outer_loop_breakdown.py`)

The lean measurement also surfaced a second, separate gap: production `decoding_speed_tps` (114.03 tok/s, 8.77 ms/tok for Qwen 1.5B) is itself higher than lean `execute_decode()` alone (7.69 ms/tok), an extra **~1.08 ms/tok spent outside the HIP dispatch path entirely**, in `model.py`'s `generate()` Python loop (sampling, LM-head logits readback, detokenizing). Broken down directly, not guessed:

| Component | ms/tok |
|---|---|
| Logits device-to-host memcpy (`tag="logits_d2h"`) | 0.380 |
| `Sampler.sample()` | 0.272 |
| `Tokenizer.decode_bytes()` | 0.010 |
| Keep-alive pulse | 0.007 |
| *(remainder: Python loop/generator overhead)* | ~0.43 |

The logits memcpy and sampler cost together (~0.65 ms/tok) are notable because they scale with **vocabulary size** (151936 entries for Qwen2.5, read back in full every token), not model parameter count: the same fixed cost on Qwen 1.5B and Qwen2.5 7B alike, again hitting the faster model's smaller per-token budget harder. Read against the sampler's own optimization history above ("Vectorized sampler": top-k/top-p/argsort already restricted to ~50 surviving candidates instead of the full vocabulary) this looks like a real mismatch worth investigating on its own: the *compute* was narrowed to ~50 candidates, but the *readback* still moves the full 151936-entry logits buffer across PCIe every token before that narrowing happens on the CPU side.

### Status

Both hypotheses that motivated this follow-up (unoptimized big kernels, safety-limiter throttling) were killed by direct measurement, a valid, useful outcome, not a dead end. The real, smaller, and previously-uninvestigated opportunity this surfaced is the sampling/LM-head readback path (`_read_logits()` + `Sampler.sample()` in `vte/core/model.py`'s `generate()` loop), not `gemv_q4k` itself. This is a genuinely different subsystem, shared by every model, on every token, and correctness-sensitive, so it was scoped as its own follow-up investigation below rather than folded into V6.

## GPU-side top-k logits reduction (2026-07)

The follow-up above ended with a specific, small opportunity: the logits device-to-host memcpy and `Sampler.sample()` together cost ~0.65 ms/tok, scaling with vocabulary size rather than model size. This section covers the opt-in feature built to attack it (`VTE_TOPK_LOGITS_READBACK=1`), the first version that measured as a net loss, and the redesign that actually delivered.

### Correctness design

The greedy (`temperature<=0`) decode path is the target, since it's deterministic and matches every benchmark methodology used on this page. Repetition penalty (`Sampler.compute_repetition_ids`) only ever *decreases* a logit, never increases one. That single fact makes it possible to prove, not just hope, that reading back a small candidate set instead of the full 151936-entry vocabulary produces the identical answer: the post-penalty winner is always either (a) a token from the recent repetition window, whose exact value is gathered directly on the GPU, since only those tokens can change under penalty, or (b) the best *non-window* token in each of 1024 thread-local strides, since non-window values never change and are therefore final as soon as they're read.

A new kernel, `topk_reduce_greedy_kernel` (`vte/compiler/templates/topk_reduce_greedy.hip.template`), does both in one pass: 1024 threads, each scanning its own stride of the vocabulary for the best non-excluded value, plus an explicit gather of the (at most 512) window token values. `TopKLogitsReducer` (`vte/core/topk_logits_reducer.py`) owns the small output buffers and the exclusion list upload; `Sampler.pick_greedy_from_gpu_candidates` reconstructs the final answer on the CPU side.

**Bug found during validation**: the first implementation's tie-breaking picked whichever thread reported a value first, not the smallest vocabulary index, unlike `np.argmax` on the full array. This was assumed to be a negligible edge case (bit-identical floating point ties are rare), but logits leave the LM Head kernel in FP16, a much coarser format than the FP32 used internally, so ties across different threads' strides turn out to be common, not rare. A real divergence showed up in a 300-token validation run at character 719. Fixed by comparing (value, index) pairs explicitly rather than relying on `np.argmax`'s scan order, both for the non-window group and for the window vs. non-window tie case. Revalidated across 7 diverse prompts (essay, code generation, lists, story, technical explanation, a short factual question, and a prompt engineered to induce repetition) on both Qwen2.5 1.5B and Qwen2.5 7B: all bit-identical to the full-array path afterward.

### First attempt: eager launch, a net loss

The first working version launched the reduction kernel eagerly, right after each decode step, the same way `_read_logits()` used to run. Measured end-to-end (10 interleaved trials, Qwen2.5 1.5B): **median -0.42% tok/s**, only 3 of 10 trials favoring it. The theoretical savings on the memcpy (~0.11 to 0.12ms/tok, confirmed separately by measuring D2H transfer time at several sizes and finding it latency-bound below ~64KB, not bandwidth-bound) were real, but launching a new kernel outside the HIP Graph pays its own dispatch and upload cost, which turned out to be larger than what it saved.

### Second attempt: captured inside the HIP Graph

The fix was to stop paying that dispatch cost at all: `topk_reduce_greedy_kernel` is now captured into the same HIP Graph as the LM Head (`HIPGraphExecutor._capture_topk_reduce`, called right after `_capture_lm_head`), using the same pattern already used for `kv_cache_offset`: the kernel's arguments (buffer addresses) stay fixed at capture time, and only their *contents* change between replays via a small host-to-device upload before each `graph_launch()` call. No `hipGraphExecKernelNodeSetParams`, no new eager launch.

Measured end-to-end (10 interleaved trials, Qwen2.5 1.5B): **median +1.08% tok/s, mean +1.45%, 9 of 10 trials favoring it.** A modest but real, repeatable gain, matching the original theoretical estimate.

Extended validation, `context_length=2048` (the project's own default) with a ~1500-token generation, on all three Q4_K models:

| Model | Before | After | Gain |
|---|---|---|---|
| Qwen2.5 1.5B (Q4_K_M) | 108.27 tok/s | 109.92 tok/s | +1.52% |
| Qwen2.5 7B (Q4_K_M) | 37.12 tok/s | 36.82 tok/s | -0.82% |
| Llama 3.1 8B (Q4_K_M) | 35.05 tok/s | 34.93 tok/s | -0.34% |

All three generations were bit-identical to the full-array path (single runs; the 7B/8B numbers sit within the trial-to-trial noise band already measured on 1.5B, and shouldn't be read as a proven regression on their own). The gain concentrates on the smallest, fastest model, where the fixed per-token overhead this feature removes is a larger fraction of a smaller total budget, consistent with the Amdahl's-law reasoning in the follow-up section above. Shipped opt-in (`VTE_TOPK_LOGITS_READBACK=1`, off by default) rather than as the new default, since the benefit is real but small and model-dependent.

## Extending these optimizations to other quantizations (2026-07)

With the header-coalescing fix and the top-k logits reduction both landed for Qwen2.5's Q4_K path, the natural next question was whether either generalizes to Granite (raw Q8_0) or Qwen3.5 (raw Q6_K).

**Top-k logits reduction: confirmed compatible, no changes needed.** It operates purely on the final FP16 logits buffer, after the LM Head, regardless of which quantization produced it. Tested directly against Granite (`granite-4.1:3b-q8_0`): 6 of 7 validation prompts confirmed bit-identical to the full-array path (the 7th prompt's comparison output wasn't captured due to a logging artifact, not a failure), tok/s roughly neutral (~57 tok/s either way), consistent with a mid-size model where the fixed per-token overhead this feature removes is a smaller fraction of the total budget.

**Header coalescing: kernel-specific, does not generalize automatically.** Reading `gemv_q6k.hip.template`, `gemv_q8_0.hip.template`, and `gemv_q5_0.hip.template` directly (not assumed) found:

- `gemv_q6k`: all 64 threads in a block process the same superblock per iteration, and each independently re-reads the 2-byte scale `d` from the identical address, a redundancy factor of 64x, larger than Q4_K's original 8x. Q6_K is Qwen3.5 2B's primary quantization, not a fallback path, so this looked like a promising, analogous target.
- `gemv_q8_0` and `gemv_q5_0`: each thread processes its own disjoint block, with no shared superblock and no redundant header read at all. The header-coalescing fix has nothing to attack here; these kernels' 210/34/22-byte block sizes (not multiples of 16) mean their real inefficiency, if any, is the lack of `uint4` vectorization, a different and more invasive problem.

### `gemv_q6k` attempt: implemented, measured, reverted

Phase A confirmed real headroom before touching any code: `gemv_q6k` achieved a median 74.0% of baseline read bandwidth (range 68.4% to 76.0% across 5 trials, `tools/bench_gemv_q6k_bandwidth.py`, Qwen3.5 2B's FFN-down shape, `in_features=6144`, `out_features=2048`), inside the same 55 to 85% "real headroom exists" band as the original Q4_K result.

The same header-coalescing pattern was implemented (only lane 0 of each of the two wavefronts reads `d`, broadcasting via `__shfl`), compiled clean (49 VGPRs, zero spill, 16 waves/SIMD, matching Q4_K's clean profile), and verified numerically correct (relative error 0.07%, consistent with ordinary FP16 accumulation-order noise, confirmed identical against the unmodified kernel using the same test data).

The same-process, interleaved A/B comparison (`tools/bench_gemv_q6k_ab_compare.py`, 15 trials) told a different story from Q4_K's: **median -25.4% bandwidth, 14 of 15 trials favoring the original, unmodified kernel.** A clear, real regression, not noise.

**Root cause**: the two redundancies look identical in source code but are not identical on the hardware. Q4_K's original problem was 8 threads reading 8 *different* small addresses scattered across one 16-byte region, genuinely poor coalescing that the GPU's memory subsystem cannot merge on its own. Q6_K's `d` read is 64 threads reading the *same single* address, a uniform/broadcast access pattern that RDNA3's cache hardware already serves efficiently, effectively for free. The rewrite replaced that already-free read with an explicit branch (`if (lane==0)`) plus a real `__shfl` instruction on every iteration, adding genuine instruction overhead to remove a bottleneck that didn't actually exist.

## First real Linux/W7900 run: CU-scaling investigation (2026-07)

The AMD hackathon's cloud instance gave the codebase its first ever run on a card other than the RX 7600: an AMD Radeon PRO W7900 (`gfx1100`, 96 CUs, 48GB VRAM, 3x the RX 7600's 32 CUs), Linux/ROCm 7.2.1 instead of the Windows HIP SDK every prior number in this document was measured on. Full environment/bug writeup in [BENCHMARK_W7900.md](BENCHMARK_W7900.md); this section covers only the tok/s investigation that followed the first cross-engine comparison.

**Initial comparison** (Qwen2.5 1.5B Q4_K_M, `llama-cpp-python` w/ HIP backend as the reference, same GGUF bytes on both sides): VTE decoded at ~140.2 tok/s against llama.cpp's ~201.5 tok/s (69.6%), a wider relative gap than the ~102% (VTE *faster*) measured on the RX 7600 for the same model in the table above. Granite 4.1 30B Q8_0 showed a smaller, more RX-7600-like gap (~20.2 vs ~22.5 tok/s, 89.8%).

**Hypothesis**: `_chunk_size_for_cus(num_cus)` (Split-KV attention, [Portability](#portability-dynamic-compute-unit-detection-rdna2rdna3-not-just-the-rx-7600) above) was derived and validated only against `num_cus=32`. FlashAttention is the single largest kernel category by GPU time (32.0% at Qwen2.5 1.5B, confirmed via `VTE_PROFILE=1` on this card, see below) -- a formula that degrades outside the range it was tuned on would hit here hardest.

**Test**: `VTE_NUM_CUS` (existing override, no code change) swept across `[16, 32, 48, 64, 96, 128]`, each value a fresh process (grid dimensions are baked into the HIP Graph at capture time, so the override must be set before the model loads, not after), real end-to-end decode tok/s measured through the production HIP-Graph path (`scripts/sweep_num_cus_w7900.py`):

| `VTE_NUM_CUS` | Decode tok/s |
|---|---|
| 16 | 118.64 |
| 32 (RX 7600's value) | 133.22 |
| 48 | 137.89 |
| 64 | 139.53 |
| **96 (auto-detected, real value)** | **139.96** |
| 128 | 139.28 |

**Result: hypothesis killed.** The auto-detected value (96, the card's real CU count) is already the best point in the sweep, plateauing from 64 upward -- `_chunk_size_for_cus` scales correctly onto this card; it is not the source of the gap. A separate, earlier `VTE_PROFILE=1` reading (eager/`FallbackExecutor` path, category GPU-ms sum) had shown a 67.4 tok/s GPU-only ceiling on this card, *lower* than the RX 7600's documented ~130 tok/s HIP-Graph-replay ceiling for the same model -- initially read as a red flag, but the two numbers use different measurement methodologies (eager per-kernel GPU timestamps, which include inter-kernel sync/launch latency baked into each category's own timing, vs. one contiguous HIP Graph replay) and are not directly comparable; the sweep above is the real, apples-to-apples signal, and it says the CU-scaling path is healthy.

**Standing conclusion**: the ~140 tok/s figure is a genuine kernel-efficiency ceiling on this card for this model, the same category of ceiling as the RX 7600's own ~100 tok/s ("further gains need actual kernel-level work ... not attempted here", [Investigation: pushing past ~100 tok/s](#investigation-pushing-past-100-toks-2026-07) above). Closing the remaining gap to llama.cpp on the W7900 would mean the same kind of `gemv_q4k`/attention tiling work already deferred there, without RGP or any hardware-counter profiler available on this cloud instance either (no full Radeon driver install, out of scope for a rented instance with limited hours). Not attempted this round; a real kernel-engineering project, not a quick fix, matching this document's own standing rule for the RX 7600 findings above.

**Reverted.** `gemv_q6k.hip.template` is unchanged from before this investigation. The real inefficiency behind Q6_K's 74% bandwidth ceiling is still open and registered here for a future investigation: the leading candidate, given the kernel's own header comment, is the total absence of vectorized (`uint4`) loads anywhere in the kernel, since its 210-byte block size isn't a multiple of 16 and every `ql`/`qh`/`scales` read is scalar. Closing that would mean a real layout/access-pattern redesign, not a targeted coalescing fix, and has not been attempted.

## Thesis V7: real hardware counters, and closing the "no profiler on this cloud instance" gap (2026-07)

The CU-scaling investigation above ended on an open question: closing the W7900 gap to llama.cpp "would mean the same kind of `gemv_q4k`/attention tiling work already deferred [on the RX 7600], without RGP or any hardware-counter profiler available on this cloud instance either." That was revisited directly: the W7900 instance's full ROCm 7.2.1 install does ship `rocprof`/`rocprofv2`/`rocprofv3`/`rocprof-compute`, in principle removing that blocker. In practice, none of them produced usable hardware-counter data on this instance -- `rocprof-compute` (renamed Omniperf) refuses to run on `gfx1100` at all (its metric definitions are CDNA-only), `rocprofv2`/legacy `rocprof` fail to execute regardless of syntax, and `rocprofv3`'s raw `--pmc` counters return real data only for two counters derivable from dispatch-trace metadata alone (`SQ_WAVES`, `SQ_BUSY_CYCLES`) -- every other counter tested (cache hit rate, occupancy, wait-states, instruction mix, memory bandwidth) returned a hard zero on every kernel, with no error. Full reproduction steps and command transcripts in [PLATFORM_ISSUES.md](../../PLATFORM_ISSUES.md). Net effect: the hardware-counter gap from the CU-scaling investigation is *not* closed by this cloud instance, and every finding below still comes from the same software-side methodology (HIP-events microbenchmarks, static `hipcc -Rpass-analysis` audits) already used throughout this document, not from real hardware counters.

### `gemv_q4k` bandwidth, revalidated on W7900 (both the 1.5B and 32B FFN-down shapes)

`tools/bench_gemv_q4k_bandwidth.py` (V6's own methodology, unmodified) re-run on this card for Qwen2.5 1.5B's actual FFN-down shape (`in_features=8960, out_features=1536`), and a new variant (`tools/bench_gemv_q4k_bandwidth_qwen32b.py`) parameterized to Qwen2.5 32B's real published shape (`in_features=27648, out_features=5120`, confirmed against the model's own `config.json`, not assumed):

| Shape | Median ratio (5 trials) | Spread |
|---|---|---|
| Qwen2.5 1.5B FFN-down | **99.6%** of read-bandwidth baseline | 97.1-99.7% |
| Qwen2.5 32B FFN-down | **94.4%** of read-bandwidth baseline | 94.2-94.5% |

Both clear the ≥85% "memory-saturated, no recoverable headroom" gate decisively, with far less trial-to-trial noise than the original V6 measurement (which had to work through several methodology traps before landing on a trustworthy number). **Direct answer to the CU-scaling investigation's open question**: there is no further `gemv_q4k` kernel-level headroom on the W7900, on either the small or the large model's GEMV shape. The ~140 tok/s ceiling on Qwen2.5 1.5B and the ~20-22 tok/s ceiling on the 30B/32B-class models are real physical memory-bandwidth walls, not unexploited kernel inefficiency -- confirmed with data now, not left as a deferred hypothesis.

### FFN fusion: fixed, and its generalization limit

Two real bugs were found and fixed in `fused_rmsnorm_gate_up_silu.hip.template` (the FFN Gate+Up+SiLU fusion kernel, previously rejected on the RX 7600 at 12.7-13.5 tok/s vs 18.8 tok/s unfused, see [Architecture](ARCHITECTURE.md#why-qkv-projection-is-fused-and-why-ffn-fusion-is-off)):

1. **Silent LDS buffer overflow.** `FUSED_FFN_MAX_HIDDEN` was hardcoded to 1536 (Qwen2.5 1.5B's `hidden_size`) with no bounds check anywhere in the dispatcher before passing the model's real `hidden_size` (Qwen2.5 7B=3584, Llama 3.1 8B=4096, Qwen2.5 32B=5120) into the kernel. Any of those three models would have silently overflowed the shared-memory buffer if fusion were ever enabled for them. Raised to 8192 (16KB/block LDS, well inside the confirmed 64KB/block budget) before any generalization testing.
2. **Per-element dequant, not per-superblock.** The scalar Q4_K dequant helper was called once per `k` (0..`hidden_size`), recomputing each superblock's `d`/`dmin`/scale from scratch every single call -- 1536 redundant recomputations for a superblock that only changes every 256 elements. Rewritten (`q4k_dequant_row_accumulate`) to amortize `d`/`dmin` once per 256-element superblock and `sc`/`mn` once per 64-element `mblk`, the same amortization cadence V6 used for `gemv_q4k` (but without V6's `__shfl` cross-thread trick, since this kernel is one-thread-per-output-neuron, not warp-cooperative).

Measured on Qwen2.5 1.5B (the hackathon demo's model), W7900, production config (`use_hip_graph=True`): HIP Graph node count dropped from 395 to 339 (exactly 2 kernels/layer x 28 layers, confirming the fusion engaged correctly), output stayed coherent (no NaN/garbage) in every trial. Median gain **+3.5%** (138.6 -> 143.4 tok/s, 3 trials each side, zero overlap between groups) -- the first time in this project's history FFN fusion has been a net win.

**Generalization across model sizes, tested and found narrow.** The same fix, re-measured on Qwen2.5 7B, Llama 3.1 8B, and Qwen2.5 32B:

| Model | `hidden_size` | Unfused | Fused (scalar dequant) | Delta |
|---|---|---|---|---|
| Qwen2.5 1.5B | 1536 | 138.6 tok/s | 143.4 tok/s | **+3.5%** |
| Qwen2.5 7B | 3584 | 87.5 tok/s | 85.9 tok/s | **-1.9%** |
| Llama 3.1 8B | 4096 | 81.6 tok/s | 73.4 tok/s | **-10.0%** |
| Qwen2.5 32B | 5120 | 23.1 tok/s | 21.7 tok/s | **-6.0%** |

Fusion wins only on the smallest model tested; it regresses on all three larger ones, not monotonically with `hidden_size` (Llama 3.1 8B regresses more than the larger Qwen2.5 32B). Two mechanisms were hypothesized and checked against real data, in order:

- **Register pressure/occupancy**: ruled out. `hipcc -Rpass-analysis=kernel-resource-usage` on the actual kernel reports `VGPRs=61, ScratchSize=0 bytes/lane, spill=0, Occupancy=16 waves/SIMD` (the theoretical max) -- and since `hidden_size` is a runtime loop-trip-count parameter, not compiled into the kernel, this is the *same* number for every model size. There is no spill or occupancy loss possible in any tested configuration.
- **Scalar (non-vectorized) memory access**: also ruled out. The dequant loop's innermost byte-at-a-time reads of the `qs` payload were rewritten to use 2x `uint4` (128-bit) loads per `mblk`, matching `gemv_q4k`'s own vectorization pattern exactly (verified 16-byte-aligned offsets, same guarantee `gemv_q4k`'s header documents). Re-measured, same-session, back-to-back to avoid cross-run clock-drift noise:

| Model | Unfused | Fused, vectorized | Delta |
|---|---|---|---|
| Qwen2.5 1.5B | 169.3 tok/s | 172.3 tok/s | **+1.8%** |
| Qwen2.5 7B | 86.9 tok/s | 86.1 tok/s | **-0.9%** |
| Llama 3.1 8B | 81.3 tok/s | 73.2 tok/s | **-10.0%** (unchanged) |
| Qwen2.5 32B | 23.2 tok/s | 21.7 tok/s | **-6.2%** (unchanged) |

Vectorization gave zero measurable benefit on the two biggest-regression models and only a marginal improvement on 7B -- the opposite of what the scalar-access theory predicts (it predicts the largest gain precisely where there's the most `qs` payload to stream, i.e. 8B/32B). Both of the two most plausible mechanisms are now disproven by direct measurement; the actual cause of the larger models' regression is unidentified, and finding it would need real hardware counters (achieved occupancy, cache hit rate, stall reasons) that are confirmed non-functional on this instance (see above). Not pursued further.

**Standing conclusion**: `VTE_ENABLE_FFN_FUSION` stays opt-in, default off. The vectorization fix is kept regardless (harmless, numerically identical output, real static-analysis improvement), but the fusion itself is a narrow, real win specific to small models (confirmed on Qwen2.5 1.5B, the exact model this hackathon's demo runs) rather than the broad architectural improvement it looked like on first measurement.

## Thesis V9: RoPE fusion into Split-KV attention (tried, correct, reverted)

Follow-up to the kernel-boundary-cost hypothesis from Thesis V7/V8 (each of the ~339 kernel launches in a decode tick was hypothesized to cost roughly 2.5us from pipeline drain and command-buffer re-fetch, a number arrived at by curve-fitting -- 339 x 2.5us matches the measured gap to llama.cpp almost exactly, which is itself a reason to distrust it without an independent measurement). The standalone `rope_kernel` runs once per layer per decode step (28 launches/token on a 28-layer model) and was picked as a controlled experiment to calibrate that per-boundary cost with real data instead of a fitted constant.

**Design.** RoPE cannot be fused the same way for Q and K. K's rotation cannot move into the attention kernel's read loop: that loop replays the *entire* KV cache history every token, and every historical position was already rotated correctly when it was first written -- rotating it again on every subsequent read would double-rotate it, silently, with no NaN or crash, just a phase error that grows with distance from the token's original position (worse at long `seq_len`, invisible at short `seq_len`). The only safe point to rotate K is where it's written into the cache exactly once: `kv_cache_append_kernel`. Q has no such hazard -- it's loaded once per attention launch and reused read-only for the whole chunk loop -- so it was fused directly into `flash_attention_split_kv_partial_kernel`, applied to the shared-memory copy right after loading, before the online-softmax loop starts. Both fusions are gated behind `VTE_FUSE_ROPE=1` (default off) and `rope_type==0` (NEOX/Qwen2.5 only; Granite and Qwen3.5 keep using the standalone kernel).

**A premise check that failed, then a premise check that was itself wrong.** Mid-implementation, reading `fused_qkv_dispatch.py` showed that the *default* QKV projection path (Two-Pass Split-K) already applies RoPE inside its Pass2 kernel as an existing, unrelated optimization -- which looked like it invalidated the whole thesis (no spare `rope_kernel` launches left to eliminate) and, worse, looked like it explained an observed generation divergence as double-rotation corruption. That conclusion was reported and nearly acted on. It was wrong: that QKV fusion path is disabled for this exact model, because Qwen2.5 1.5B's `attn_q`/`attn_k`/`attn_output` weights are raw Q4_K (a VRAM-reduction routing decision from an earlier session), and raw-quantized attention weights unconditionally disable QKV fusion (confirmed directly: `is_raw_q4k_weight()` returns true for all three tensors on this checkpoint). So the standalone `rope_kernel` genuinely does run as 28 real launches/token on the default path for this model, and the fusion had a real target after all.

**Validation, once the premise was actually confirmed.**

- HIP Graph decode-capture node count: 395 -> 367 with `VTE_FUSE_ROPE=1` -- exactly 28 fewer, matching the eliminated launches with nothing extra and nothing missing.
- K's fused rotation (`kv_cache_append_kernel`, `rope_type==0`) compared bit-for-bit against the standalone `rope_kernel` applied to the same raw K buffer, same cos/sin cache, same position: **0.000000 max diff**.
- Q's fused rotation plus the full split-KV attention pipeline (append -> partial -> reduce, 3 real decode steps building actual cache history) compared against a numpy reference built from the cos/sin cache read directly off the GPU (not reimplemented independently): **0.00056 max diff**, consistent with ordinary FP16 rounding.
- Both `VTE_FUSE_ROPE=0` and `=1` are internally deterministic -- confirmed by running each twice in separate processes and diffing the greedy-decoded text byte-for-byte (identical both times). The text does differ *between* the two configurations, but that's expected: swapping which kernel performs a numerically-equivalent-to-FP16-precision computation changes the rounding order, which can flip a close greedy-argmax choice after enough layers. The same effect is already documented for the FFN fusion above (`demo_ffn_fusion.py`'s own before/after runs produce different text too) and isn't itself evidence of a bug -- the two independent numerical checks above are what actually establish correctness.
- Median tok/s (5 runs each side, Qwen2.5 1.5B, RX 7600): 110.79 -> 111.41, **+0.6%**. Calibrated boundary cost: `(1000/110.79 - 1000/111.41) * 1000 / 28 ≈ 1.77us/boundary` -- same order of magnitude as the curve-fit 2.5us estimate, but a real measurement now, not a fit.

**Decision: reverted anyway.** The fusion is correct and the gain is real, but +0.6% doesn't clear the bar for the added surface area -- two new kernel variants with a conditional rotation path each, an opt-in flag that's a no-op on every architecture except Qwen2.5/NEOX, and a correctness hazard class (double-rotation) that's silent by nature and would need re-auditing on every future change to either kernel. Kept as a documented, calibrated data point rather than shipped code: `VTE_FUSE_ROPE` is not present in the current tree.
