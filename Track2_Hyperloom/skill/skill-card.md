# Skill Card

## Description

Autonomously finds and closes LLM-inference kernel-performance gaps on AMD GPUs (ROCm/HIP). Detects the exact gfx target, maps its real ISA capability surface with the assembler (not marketing claims), builds a measured roofline, finds unexploited instructions and underperforming kernels, writes and tunes correctness-gated HIP kernels, and validates every claim by execution — using layered fault-isolation (silicon → driver → runtime → compiler → kernel → format → serving) so a fault is fixed at its real layer.

## Owner

The-Monk (community contribution). Built and validated on RDNA4 (gfx1201 / Radeon AI PRO R9700).

## License

MIT

## Status

Working. A reference implementation of the "autonomously optimizes LLM inference on AMD GPUs" capability, proven on RDNA4 (a target the current catalog's kernel tooling does not yet fully cover — see the metrix/compare RDNA4 gap in AMD-AGI/Magpie#70). Bundles a self-contained toolkit (ISA census, disassembly verification, unused-instruction sweep, Magpie/metrix kernel evaluation, perf-level-aware rocprofv3 profiling).

## Validated results (MEASURED on gfx1201, correctness-gated)

- **int4 decode lever** — native `v_dot8_i32_iu4` GEMV = **~2.2×** vs the dp4a route (unpack→`v_dot4_i32_iu8`), bit-exact vs CPU reference.
- **int4 2:4 sparse SWMMAC** — native `v_swmmac_i32_16x16x64_iu4` raw-instruction ceiling = **3.90×** vs int8 WMMA / 1.95× vs int4 dense WMMA (8-way ILP; residual ~2.7% is a real fixed sparsity-decode cost, not schedulable).
- **Full ISA audit** — of ~19 present ML instructions on gfx1201, 17 exploited; the 2 gaps (`v_swmmac_i32_16x16x64_iu4` int4-sparse, `v_dot2_f32_bf16`) surfaced by an assembler-ground-truth sweep and given correctness-proven (err=0) coverage.
- **Perf-level counter unlock** — the GL2C/FETCH_SIZE "broken counters read 0" myth on RDNA3/4 root-caused to a perf-level gate (STABLE_STD), not firmware.
