#pragma once
// RDNA4 2:4-STRUCTURED-SPARSE SWMMAC -- driver-completeness capability.
//
// Purpose (JM doctrine 2026-07-06, "Completeness is defined by the HARDWARE, not by
// today's models", wiki/tech/hardware-up-optimization-flow.md): gfx1201/RDNA4 silicon
// natively implements 2:4-structured-sparse Wave Matrix Multiply Accumulate (SWMMAC),
// ISA doc 70651 sec 7.12 ("RDNA4" Instruction Set Architecture). No current ggml model
// path uses it (T99: every perf angle -- weight-2:4 accuracy, activation-2:4 mask/pack
// cost, all beaten by fp8 -- was killed on the numbers). This file makes the CAPABILITY
// correct + present + reachable in the driver regardless, so a future co-trained-2:4
// model (or a future perf idea) has a validated instruction-level building block ready.
// It is DELIBERATELY UNUSED by any model/quant default path -- see swmmac24.cu's
// self-test hook, gated behind an opt-in env var, for how it's reached.
//
// Three SWMMAC forms are implemented here (the first two are the gfx1201-native
// forms validated in ~/phase2-spike/{int4_swmmac_throughput,fp8_swmmac_throughput,
// act24_mask_pack}.hip; the third, card 141, is the same clang builtin family
// confirmed present for gfx1201 -- "wmma-128b-insts,wavefrontsize32" feature gate,
// same as the fp8 form -- via BuiltinsAMDGPU.inc, hardware-validated the same way):
//   V_SWMMAC_I32_16X16X32_IU4        (int4 A/B, int32 accumulate)
//   V_SWMMAC_F32_16X16X32_FP8_FP8    (fp8e4m3 A/B, fp32 accumulate)
//   V_SWMMAC_F32_16X16X32_F16        (fp16 A/B, fp32 accumulate -- card 141)
//
// Per-lane VGPR layout is transcribed directly from the ISA doc's Table
// "Matrix Element Storage in VGPRs" (sec 7.12.2, A-Matrix/B-Matrix/C-D-Matrix rows) and
// the Structured-Sparse-Matrices index-expansion pseudocode (sec 7.12.3). ONE piece
// (B-Matrix 32x16 physical layout at 8-bit dataSize, needed for the fp8 form's dense B
// operand) is NOT spelled out in the doc for 8-bit -- it was derived by induction from
// the doc's own fully-documented 4-bit K16->K32 transition rule, then HARDWARE-VALIDATED
// via one-hot basis-vector probes on a real R9700 before being trusted (see
// wiki/tech/swmmac-complete-notes.md for the probe methodology and results; the
// standalone probe lives at ~/phase2-spike/swmmac24_correctness.hip). Everything else
// below is a direct, doc-given transcription, not a derivation.

#include "common.cuh"

#include <cstdint>
#include <vector>

// T122 fix: this header used to be gated `defined(GGML_USE_HIP) && defined(RDNA4)`
// in its entirety. `RDNA4` (== `__GFX12__`) is only ever predefined during
// HIP-clang's DEVICE compilation pass for a gfx12 offload target -- it is
// NEVER defined during the HOST pass. Since swmmac24.cu's HOST-side trial
// code (`test_iu4_swmmac_24`/`test_fp8_swmmac_24`) needs the `Loc` type, the
// per-lane layout functions, and `swmmac24_put_bits` too, wrapping all of it
// in an `RDNA4`-only guard meant NONE of it was ever visible to the host
// pass -- the only thing that *could* compile in the host pass was the
// vacuous `#else` stub in swmmac24.cu. Fix: gate this header on
// `GGML_USE_HIP` only (true in both passes); the two `__global__` kernels'
// actual hardware-instruction calls (device-pass-only, gfx12-only) get their
// own inner `RDNA4` guard below, following the same convention used
// throughout mma.cuh/common.cuh for arch-gated builtins.
#if defined(GGML_USE_HIP)

namespace ggml_cuda_swmmac24 {

typedef int   v2i __attribute__((ext_vector_type(2)));
typedef int   v4i __attribute__((ext_vector_type(4)));
typedef int   v8i __attribute__((ext_vector_type(8)));
typedef float v8f __attribute__((ext_vector_type(8)));
// card 141 (sparse-fp16): half-precision lane vectors, same ext_vector_type
// convention already used for f16 WMMA fragments elsewhere in this driver
// (mma.cuh's halfx8_t/halfx16_t).
typedef _Float16 v8h  __attribute__((ext_vector_type(8)));
typedef _Float16 v16h __attribute__((ext_vector_type(16)));

// Sparse-index format invariant (ISA doc sec 7.12.3): 2 bits/index, 2 indices/group
// of 4 K-columns, 4 groups' worth (16 bits) packed into the low half of the 32-bit
// `sparsity_idx` lane operand for the K=32 forms (Table 43: S=0.5 VGPR/lane).
static_assert(sizeof(unsigned) == 4, "sparsity_idx operand must be a 32-bit lane register");
#define GGML_SWMMAC24_IDX_BITS_PER_ENTRY 2
#define GGML_SWMMAC24_ENTRIES_PER_GROUP  2
#define GGML_SWMMAC24_GROUPS_PER_LANE    4
static_assert(GGML_SWMMAC24_IDX_BITS_PER_ENTRY * GGML_SWMMAC24_ENTRIES_PER_GROUP * GGML_SWMMAC24_GROUPS_PER_LANE == 16,
              "sparse index packing must fill exactly the ISA-documented 16 meaningful bits (S=0.5 VGPR)");

struct Loc { int lane, vgpr, startbit; };

// A-Matrix 16x16 (row 0..15, col 0..15 = PHYSICAL PACKED column -- this is the
// pre-expansion storage for the sparse forms' A operand, doc-confirmed identical
// footprint to a dense 16x16 tile of the same dataSize per ISA Table 43).
static __host__ __device__ __forceinline__ Loc swmmac24_a_loc(int dataSizeBits, int row, int col) {
    const int r = row & 0xF;
    if (dataSizeBits == 16) {
        // card 141 (sparse-fp16): DERIVED, not doc-given (same induction method
        // the file header describes for swmmac24_b32_loc_8bit -- see there for
        // the general rule: lane keeps col[3] as its "half" bit; the remaining
        // col[2:0] splits between vgpr-select and startPosn by how many
        // dataSizeBits-wide values fit in one 32-bit dword, floor(32/16)=2 ->
        // 1 startPosn bit (col[0]) + 2 vgpr-select bits (col[2:1]), vs. the
        // 8-bit case's 2 startPosn bits + 1 vgpr bit and the 4-bit case's 3
        // startPosn bits + 0 vgpr bits -- a mechanical function of dataSize,
        // exactly the pattern the 8-bit B-matrix case extrapolated from the
        // 4-bit doc-given case. HARDWARE-VALIDATED via
        // ggml_cuda_swmmac24_selftest()'s test_f16_swmmac_24 before any
        // real-model kernel trusts it (same discipline as the 8-bit B case).
        return { (((col >> 3) & 1) << 4) | r, (col >> 1) & 3, (col & 1) * 16 };
    }
    if (dataSizeBits == 8) {
        // doc: lane={col[3],row[3:0]}  vgpr=col[2]  startPosn=col[1:0]
        return { (((col >> 3) & 1) << 4) | r, (col >> 2) & 1, (col & 3) * 8 };
    }
    // dataSizeBits == 4: lane={col[3],row[3:0]}  vgpr=0  startPosn=col[2:0]
    return { (((col >> 3) & 1) << 4) | r, 0, (col & 7) * 4 };
}

// B-Matrix 32x16 (row 0..31 = K, col 0..15 = N), dataSizeBits==4 (DOC-GIVEN).
static __host__ __device__ __forceinline__ Loc swmmac24_b32_loc_4bit(int row, int col) {
    // doc: lane={row[4],col[3:0]}  vgpr=row[3]  startPosn=row[2:0]
    return { (((row >> 4) & 1) << 4) | (col & 0xF), (row >> 3) & 1, (row & 7) * 4 };
}

// B-Matrix 32x16 (row 0..31 = K, col 0..15 = N), dataSizeBits==8 (DERIVED + hardware-
// validated -- see file header). Induction: the new top row-address bit (row[4])
// becomes the new "lane" tag bit (displacing the prior top-lane bit down into vgpr);
// startPosn is unchanged from B-16x16's 8-bit case (a pure function of dataSize).
static __host__ __device__ __forceinline__ Loc swmmac24_b32_loc_8bit(int row, int col) {
    const int lane = (((row >> 4) & 1) << 4) | (col & 0xF);
    const int vgpr = (((row >> 3) & 1) << 1) | ((row >> 2) & 1);
    const int startPosn = row & 3;
    return { lane, vgpr, startPosn * 8 };
}

// B-Matrix 32x16 (row 0..31 = K, col 0..15 = N), dataSizeBits==16 (card 141,
// DERIVED + hardware-validated -- see swmmac24_a_loc's dataSizeBits==16
// branch for the general induction rule). lane keeps the same {row[4],col[3:0]}
// tag as the 4-bit/8-bit forms; the remaining row[3:0] (4 bits, since row
// needs 5 bits total and row[4] moved to lane) splits floor(32/16)=2 values
// per dword -> 1 startPosn bit (row[0]) + 3 vgpr-select bits (row[3:1]),
// covering all 8 dwords (v8i / v16h) the ISA's f16 B operand needs.
static __host__ __device__ __forceinline__ Loc swmmac24_b32_loc_16bit(int row, int col) {
    const int lane = (((row >> 4) & 1) << 4) | (col & 0xF);
    const int vgpr = (row >> 1) & 7;
    const int startPosn = row & 1;
    return { lane, vgpr, startPosn * 16 };
}

// C/D-Matrix 16x16, 32-bit output (row 0..15, col 0..15). doc:
// matrix[row][col] -> VGPR[(row/8)*16+col][row%8]  (cross-validated 3 independent
// ways in the doc: bit-field table, prose formula, worked wave32 example).
static __host__ __device__ __forceinline__ Loc swmmac24_d_loc(int row, int col) {
    return { (((row >> 3) & 1) << 4) | (col & 0xF), row & 7, 0 };
}

static inline void swmmac24_put_bits(std::vector<std::vector<uint32_t>>& regs, const Loc& loc, uint32_t value, int width) {
    const uint32_t mask = (width >= 32) ? 0xFFFFFFFFu : ((1u << width) - 1u);
    regs[loc.lane][loc.vgpr] &= ~(mask << loc.startbit);
    regs[loc.lane][loc.vgpr] |= (value & mask) << loc.startbit;
}

// ---------------------------------------------------------------------------
// Device kernels: per-lane distinct operands read from device arrays (each of the
// 32 threads in a single wave32 launch supplies exactly the registers the ISA doc
// says that lane should hold).
// ---------------------------------------------------------------------------
static __global__ void k_swmmac_iu4_24_perlane(const int * __restrict__ a, const v2i * __restrict__ b,
                                         const unsigned * __restrict__ idx, v8i * __restrict__ dout) {
#if defined(RDNA4)
    v8i c = {0,0,0,0,0,0,0,0};
    dout[threadIdx.x] = __builtin_amdgcn_swmmac_i32_16x16x32_iu4_w32(1, a[threadIdx.x], 1, b[threadIdx.x], c, idx[threadIdx.x], 0);
#else
    // Host pass / non-RDNA4 device pass: the V_SWMMAC_I32_16X16X32_IU4
    // instruction this targets doesn't exist here. Never actually launched
    // off RDNA4 (ggml_cuda_swmmac24_selftest() runtime-gates on cc first).
    GGML_UNUSED(a);
    GGML_UNUSED(b);
    GGML_UNUSED(idx);
    GGML_UNUSED(dout);
    NO_DEVICE_CODE;
#endif // defined(RDNA4)
}

static __global__ void k_swmmac_fp8_24_perlane(const v2i * __restrict__ a, const v4i * __restrict__ b,
                                         const unsigned * __restrict__ idx, v8f * __restrict__ dout) {
#if defined(RDNA4)
    v8f c = {0,0,0,0,0,0,0,0};
    dout[threadIdx.x] = __builtin_amdgcn_swmmac_f32_16x16x32_fp8_fp8_w32(a[threadIdx.x], b[threadIdx.x], c, idx[threadIdx.x]);
#else
    // Host pass / non-RDNA4 device pass: the V_SWMMAC_F32_16X16X32_FP8_FP8
    // instruction this targets doesn't exist here. Never actually launched
    // off RDNA4 (ggml_cuda_swmmac24_selftest() runtime-gates on cc first).
    GGML_UNUSED(a);
    GGML_UNUSED(b);
    GGML_UNUSED(idx);
    GGML_UNUSED(dout);
    NO_DEVICE_CODE;
#endif // defined(RDNA4)
}

// card 141 (sparse-fp16): V_SWMMAC_F32_16X16X32_F16_F16 -- fp16 A/B (native,
// no per-block scale needed), fp32 accumulate, same "wmma-128b-insts,
// wavefrontsize32" feature gate as the fp8 form above (confirmed present in
// clang's BuiltinsAMDGPU.inc for gfx1201, NOT gated to gfx1250-only like the
// newer K=64/K=128 SWMMAC forms).
static __global__ void k_swmmac_f16_24_perlane(const v8h * __restrict__ a, const v16h * __restrict__ b,
                                         const unsigned * __restrict__ idx, v8f * __restrict__ dout) {
#if defined(RDNA4)
    v8f c = {0,0,0,0,0,0,0,0};
    dout[threadIdx.x] = __builtin_amdgcn_swmmac_f32_16x16x32_f16_w32(a[threadIdx.x], b[threadIdx.x], c, idx[threadIdx.x]);
#else
    // Host pass / non-RDNA4 device pass: the V_SWMMAC_F32_16X16X32_F16
    // instruction this targets doesn't exist here. Never actually launched
    // off RDNA4 (ggml_cuda_swmmac24_selftest() runtime-gates on cc first).
    GGML_UNUSED(a);
    GGML_UNUSED(b);
    GGML_UNUSED(idx);
    GGML_UNUSED(dout);
    NO_DEVICE_CODE;
#endif // defined(RDNA4)
}

} // namespace ggml_cuda_swmmac24

#endif // defined(GGML_USE_HIP)

// Reachable regardless of arch (no-op / not-applicable off RDNA4): returns true if
// either (a) not RDNA4 (nothing to test, vacuously fine) or (b) RDNA4 and the
// 2:4-sparse SWMMAC self-test passed. Returns false only on an actual correctness
// or launch failure on RDNA4 hardware. Does not touch any model/quant/graph path --
// purely a standalone instruction-level self-test, invoked only when opted into via
// GGML_HIP_SWMMAC24_SELFTEST (see ggml-cuda.cu).
bool ggml_cuda_swmmac24_selftest();

// T162 int4-2:4 pivot: standalone idx-encoding-fixed iu4 sparse SWMMAC
// self-test (swmmac24_iu4_fixed.cu). Does not touch/modify the
// selftest above. Opt-in via GGML_HIP_SWMMAC24_IU4_FIXED_SELFTEST.
bool ggml_cuda_swmmac24_iu4_fixed_selftest();
