# Datapath evidence map — microbench → model realization

**The discipline:** a microbench proves the *raw hardware capability* in isolation; **model realization** proves it survives a real kernel on a real model. The gap between them is closed by a specific, named **tweak**. Every row below is MEASURED on gfx1201 (Radeon AI PRO R9700), correctness-gated. This is what separates "the instruction can do X" from "a served model actually runs X% faster."

## Decode datapaths (GEMV, bandwidth-bound)

| Instruction | Microbench (isolated) | Model-realized | Realization tweak | Evidence |
|---|---|---|---|---|
| `v_dot8_i32_iu4` (int4 dot8) | **~2.2×** vs dp4a-route, bit-exact — but **29% HBM util = instruction-bound**, so the microbench *overstates* the decode win | **1.10–1.34×** vs dp4a in the real `mmvq_iu4` decode kernel (K=4096→14336) | wire `vec_dot_iu4` into `mmvq` gated M=1; decode is bandwidth-bound so the *byte-width* is the real lever, not the instruction | decode microbench (this session) + T170 |
| `v_dot4_i32_iu8` (dp4a) | 7376 emissions, production baseline | served models (coherent) | — (baseline) | ISA sweep + served |
| `v_dot2_f32_f16` | 125,666 emissions (flash-attn) | served, all attention decode | — | ISA sweep |

## Prefill datapaths (GEMM, compute-bound)

| Instruction | Microbench (isolated) | Model-realized | Realization tweak | Evidence |
|---|---|---|---|---|
| `v_swmmac_i32_16x16x64_iu4` (int4 2:4 sparse) | **3.90×** vs int8 WMMA (raw ISA ceiling, ILP≥8; residual ~2.7% = fixed sparsity-decode cost) | **3.67×** vs int8 / 1.72× vs int4-dense in a **full tiled GEMM** @ K=8192 = **88–95% of the raw ceiling** | **pre-packed 2:4 layout** (compress once at quant time, not in the hot loop) + **ILP≥4** + **row-pitch pad** (avoid the DRAM critical-stride cliff) | T187 microbench + full-GEMM (this session), err=0, test-backend-ops 1141/1141 |
| `v_wmma_i32_16x16x16_iu8` (int8) | 358 TOPS = 95% of 382.7 spec (ILP=1) → **394 TOPS = 103% at ILP=2** | production MMQ prefill (pp512) | MMQ auto-picks `mmq_x=128` → ILP=2 (the K16-shape ILP target) | T178 hardware map |
| `v_wmma_f32_16x16x16_fp8` (native fp8) | 358 TOPS (≡ int8, no throughput edge) | served fp8 models (Quacken-27B etc.), coherent + normal PPL | native-fp8 MMQ kernel + hw fp8 encoder | ISA sweep + served |

## Format datapaths (Quark → GGUF → served on Radeon)

| Format | Microbench (bit-level) | Model-realized | Realization tweak | Evidence |
|---|---|---|---|---|
| MXFP6 (E3M2) | bit-exact vs `block_mxfp6` (round-trip err=0) | **Ornith-35B brain served coherent** + Quark models PPL **10.59** | `pack_mxfp6_preserve` + `qwen3_5_moe` converter (drops-layers bug fixed) | T184 + served brain (this session) |
| MXFP4 | bit-exact vs Quark `scaled_real_quantize` (err=0) | served coherent, PPL **11.93** | `pack_mxfp4_preserve` (nibble repack) | T185 (this session) |
| NVFP4 | relerr identical to Quark ref (15 sig-figs) | served coherent, PPL **11.12** | **`build_ffn` NULL-scale bug fix** (per-block scale was silently dropped on 68 arch families → garbage PPL 42M) | T185 (this session) |
| F8E4M3 / F8E5M2 | struct-identical to `block_f8e4m3` | served coherent ("Paris.") | `--fp8-native` accepts Quark quant_method | T185 (this session) |
| MXFP8 | — | **not producible** — Quark 0.12 MX path is hard-asserted to fp4/fp6 only | (honest producer gap, documented not faked) | T185 (this session) |

## The pattern this map proves

1. **Decode**: the instruction barely matters (bandwidth-bound); the microbench *overstates* — realization gives the honest byte-width win. Hyperloom flags this instead of shipping the inflated microbench number.
2. **Prefill**: compute-bound, so the microbench *is* close to real — but only with the pre-pack + ILP tweaks; a naive kernel captures 58%, the tuned kernel 88–95%.
3. **Format**: bit-exact isn't enough — realization exposed a silent scale-drop bug (PPL 42M → 11.12) that only a served-model correctness gate catches.

*Microbench answers "can the silicon do it." Model realization answers "does a served model actually get faster/smaller, and what tweak makes it so." Hyperloom reports both — and only trusts the second.*
