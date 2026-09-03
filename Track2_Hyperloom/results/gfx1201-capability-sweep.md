# gfx1201 ML-instruction capability sweep — full evidence

Every ML-relevant matrix/dot/convert instruction on the Radeon AI PRO R9700 (gfx1201), swept three ways and cross-referenced:

- **Silicon** — is it real on the part? (`llvm-mc` ground truth — the assembler can't lie; bypasses the clang builtin arity-before-target-feature false-positive)
- **Emitted** — does the roc9 llama.cpp actually generate it, and how many times, in which kernel? (`--save-temps` disassembly of all 110 compute kernels)
- **Throughput** — measured TOP/s and % of AMD's rated spec (isolated microbench, ILP-saturated)

| Instruction | Silicon | Emitted (count · top kernel) | Measured throughput | % of spec | Notes |
|---|---|---|---|---|---|
| **Matrix — dense WMMA** | | | | | |
| `v_wmma_f32_16x16x16_f16` | ✅ | 7,860 · fattn-mma | — | — | flash-attn |
| `v_wmma_f32_16x16x16_bf16` | ✅ | 3,072 · mmf | — | — | |
| `v_wmma_f32_16x16x16_fp8` | ✅ | 1,532 · mmq-f8e4m3 | 358 TOPS | 94% | native fp8, ≡ int8 |
| `v_wmma_f32_16x16x16_bf8` | ✅ | 368 · mmq-f8e5m2 | 358 TOPS | 94% | E5M2 |
| `v_wmma_i32_16x16x16_iu8` | ✅ | 7,740 · mmq-q2_k/q8_0 | 358→394 TOPS (ILP2) | 95→103% | int8 baseline |
| `v_wmma_i32_16x16x32_iu4` | ✅ | 44 · mul_mat_iu4_mmq | 386→767 TOPS (K16→K32) | 50→100% | int4 dense, 2 rungs |
| **Matrix — SWMMAC (2:4 sparse)** | | | | | |
| `v_swmmac_f32_16x16x32_fp8` | ✅ | 482 · mul_mat_2of4_fp8 | — | — | prefill, served (PPL 7.03) |
| `v_swmmac_f32_16x16x32_f16` | ✅ | 2 · 2of4_f16 | — | — | dormant |
| `v_swmmac_i32_16x16x64_iu4` | ✅ | **5** · mul_mat_2of4_iu4_k64 (was **0** — gap CLOSED this session) | 1345→1551 TOPS (ILP1→≥4) | 100–101% of 1531 | the unexploited find, now covered; full-GEMM realizes **3.67×** |
| **Dot (decode / GEMV)** | | | | | |
| `v_dot8_i32_iu4` (int4 dot8) | ✅ | 4 · mmvq_iu4 | microbench ~2.2x vs dp4a | — | model-realized 1.1–1.34× (bandwidth-bound) |
| `v_dot4_i32_iu8` (dp4a) | ✅ | 8,624 · mmvq/fattn-vec | — | — | production decode |
| `v_dot4_f32_fp8` | ✅ | 110 · mmvq | — | — | fp8 dot |
| `v_dot2_f32_f16` | ✅ | 125,666 · fattn-tile | — | — | attention decode |
| `v_dot2_f32_bf16` | ✅ | **1** · dot2_bf16_probe (was **0** — gap CLOSED this session) | — | — | covered for completeness (no perf upside vs the f16 sibling, but no longer a gap) |
| **Convert / packed** | | | | | |
| `v_cvt_pk_fp8_f32` | ✅ | 3 · quantize | — | — | fp8 encode |
| `v_cvt_pk_bf8_f32` | ✅ | 2 · quantize | — | — | |
| `v_cvt_sr_fp8` | ✅ | 2 · quantize_sr | — | — | stochastic round |
| `v_pk_fma_f16` | ✅ | 155,080 · fattn | — | — | packed FMA |
| `v_pk_mul_f16` | ✅ | 21,545 · fattn-mma | — | — | |
| **Gated / absent (do NOT chase)** | | | | | |
| `v_dot2c_f32_f16` (dual-issue) | ❌ gated | — | — | — | GFX12 auto-packer excludes it |
| `v_cvt_scalef32_*` (MX scale-units) | ❌ gated | — | — | — | gfx950/1250-only (arity-trap false positive) |

## What the sweep establishes (evidence, not assertion)

- **Coverage is now complete — 19/19, zero unused** (fresh sweep of the current tree, all 114 compute kernels): the 2 gaps the assembler-ground-truth sweep found (`v_swmmac_i32_iu4`, `v_dot2_f32_bf16`) were both closed this session with correctness-proven coverage kernels (err=0). A re-sweep confirms 0 unused ML instructions on gfx1201.
- **Throughput lands at 88–103% of AMD's rated spec** where measured (int8 103% at ILP2, int4-dense 100%, int4-2:4 100–101% of the 1531 marketing peak — *confirmed*, not derived).
- **Two "obvious" facts were false and only measurement caught them:** the scale-convert units read as "available" to a compile-probe but are gated (`llvm-mc` refutes); the "counters read 0 = broken hardware" was a perf-level gate (STABLE_STD unlocks them).

*Bandwidth ceiling: 638 GB/s (decode wall). Compute crossover AI = 560 op/byte → decode is bandwidth-bound (instruction ~irrelevant), prefill is compute-bound (WMMA ceiling). All numbers roc9/build-roc9-714, GPU0, correctness-gated.*
