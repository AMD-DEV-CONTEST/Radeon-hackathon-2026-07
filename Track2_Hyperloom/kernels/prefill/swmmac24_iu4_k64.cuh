// gfx1201 ISA-coverage follow-up (T186): V_SWMMAC_I32_16X16X64_IU4
// driver-completeness self-test. Full sweep of the RDNA4 ISA (llvm-mc +
// BuiltinsAMDGPU.inc, gfx1201) found this instruction PRESENT in silicon
// (`__builtin_amdgcn_swmmac_i32_16x16x64_iu4_w32`, feature gate
// "swmmac-gfx1200-insts,wavefrontsize32" -- SAME family gate as the K32 form
// this driver already ships, NOT the gfx1250-only gate some sibling K64/K128
// forms carry, e.g. bf16/f16 SWMMAC) but with ZERO uses across all roc9
// compute kernels. This is the K=64 sibling of swmmac24.cuh's already-
// validated V_SWMMAC_I32_16X16X32_IU4 (K=32): same M=16,N=16 2:4-sparse
// int4 GEMM tile, twice the logical K per instruction (compressed A now 2
// registers/lane instead of 1, dense B now 4 registers/lane instead of 2,
// per gfx1201's own doubled ops/WGP/cycle for this form -- 16384 vs 8192,
// confirmed via ROCm/amd_matrix_instruction_calculator --detail-instruction,
// ~/int4-research/INT4-IU4-FULL-REPORT.md appendix A).
//
// Does NOT touch swmmac24.cuh/swmmac24.cu (avoid risking the already-shipped
// K32 form) -- this is a new, standalone, opt-in-only self-test file. It
// reuses swmmac24.cuh's shared v2i/v4i/v8i/Loc/swmmac24_put_bits/
// swmmac24_d_loc (the D-matrix 16x16 output layout is K-independent, doc-
// confirmed) but defines its OWN per-lane A/B/idx addressing functions below
// -- the K32 file's a_loc/b32_loc_4bit are hardcoded for the K32 form's
// narrower (0..15) compressed-column / (0..31) K-row ranges and do not
// generalize to K64's wider (0..31) / (0..63) ranges.
//
// Per-lane layout PROVENANCE: derived from ROCm/amd_matrix_instruction_
// calculator's `--architecture rdna4 --detail-instruction` dump for this
// exact instruction (wave32, "Wave32 matrix element to register mapping"
// section -- an independent, doc-adjacent tool, not a guess), cross-checked
// for internal consistency against this driver's OWN already-hardware-
// validated K32 form (same lane-split / byte-per-group / natural-index-field
// convention, just with the group count and register count doubled). The
// natural (unswapped, no-XOR) idx field convention is used, matching what
// this driver already validated at K32 (int4_24_probe.cu's header records
// that a DIFFERENT project's CK-internal "swap+XOR1" convention was tried
// against this driver's own encoding and measured WRONG -- the natural
// encoding is what this driver's from-scratch derivation actually matches on
// real hardware). This is a HYPOTHESIS until the self-test below proves it
// on real gfx1201 silicon -- if it fails, the reported max_abs_err is the
// evidence, not a guess dressed up as a result.
//
// Zero effect on any existing model/quant/kernel path when GGML_HIP_
// SWMMAC24_IU4_K64_SELFTEST is unset. Runs at most once per process, same
// call-site pattern as GGML_HIP_SWMMAC24_IU4_FIXED_SELFTEST (ggml-cuda.cu).
#pragma once

#include "common.cuh"
#include "swmmac24.cuh"

bool ggml_cuda_swmmac24_iu4_k64_selftest();
