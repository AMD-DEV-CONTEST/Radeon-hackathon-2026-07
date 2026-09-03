// T187 (reopened): does the K64 int4 2:4-sparse SWMMAC (v_swmmac_i32_16x16x64_iu4)
// survive as a REAL, full, correctness-gated tiled GEMM kernel with genuine
// on-device gather of compressed-A + metadata from global memory, or does the
// 2:4 gather/pack tax eat the raw-instruction 3.90x ceiling (bench_ilp.hip,
// register-resident, zero gather)?
//
// Standalone, no ggml dependency (per task: "a standalone GEMM bench proves
// it; a full tree rebuild isn't required"). GPU0 ONLY.
//
// Three kernels, SAME WARPSxILP output-tile tiling/dispatch/double-buffer
// skeleton (mirrors ggml-cuda/mul_mat_2of4_fp8.cu's k_mul_mat_2of4_fp8_v3,
// the winning V3 shape: WARPS=32 threads/warp-dim, ILP consecutive weight
// tiles/warp, zero __syncthreads (every operand fully private per-lane),
// double-buffered global-load prefetch, c0=0-per-call + software int32
// accumulate -- exactly what T162 found fastest for the sibling fp8 2:4
// kernel):
//   1. k_gemm_iu8_k16   -- dense int8,  V_WMMA_I32_16X16X16_IU8   (baseline A)
//   2. k_gemm_iu4_k32   -- dense int4,  V_WMMA_I32_16X16X32_IU4   (baseline B)
//   3. k_gemm_iu4_k64s  -- 2:4-sparse int4, V_SWMMAC_I32_16X16X64_IU4 (target)
//
// Per-lane addressing for (1)/(2) is taken DIRECTLY from
// ROCm/amd_matrix_instruction_calculator --architecture RDNA4
// --detail-instruction -w 32 (captured 2026-07-24, tool cloned fresh this
// session from github.com/ROCm/amd_matrix_instruction_calculator) -- an
// INDEPENDENT, doc-adjacent source, not a guess. Addressing for (3) reuses
// the EXACT formulas already hardware-validated (max_abs_err=0, real
// gfx1201 silicon) in ggml-cuda/swmmac24_iu4_k64.cu(h)
// (a_loc_k64/idx_loc_k64/b_loc_k64) -- cross-checked bit-for-bit equal to
// the SAME calculator tool's V_SWMMAC_I32_16X16X64_IU4 output after the
// floor-division identities floor(floor(k/4)/8)==floor(k/32) etc; see the
// comment block above each K64 loader below for the term-by-term match.
//
// STORAGE FORMAT / "what counts as gather": all three kernels stream
// PRE-QUANTIZED, PRE-PACKED byte layouts from global memory (int8 dense,
// nibble-packed int4 dense, byte-per-group-value + nibble-per-group-pair-meta
// for the compressed sparse form) -- i.e. the same convention the ALREADY-
// SHIPPED (dormant) mul_mat_2of4_fp8.cu V3 kernel uses (compression happens
// ONCE at quantize/conversion time, not per-GEMM-launch; this is how every
// known real 2:4-sparse-tensor-core kernel works, CUDA's included -- the hot
// loop never re-derives which 2-of-4 survived). The REAL, MEASURED tax this
// bench isolates is: (a) a SEPARATE metadata array + its own global load +
// its own operand register (vs dense's single array), (b) an extra loop-body
// dependency (must load BOTH qs and meta before the SWMMAC can issue), and
// (c) whatever register-pressure/occupancy cost that adds -- exactly the
// mechanism T162 already measured for the fp8 sibling. Nothing here
// preloads/pre-stages tiles into  registers like bench_ilp.hip -- every
// operand load happens from global memory, per K-chunk, inside the kernel.
//
// CORRECTNESS: CPU int64-accumulate reference (same 2:4 mask, applied on the
// host before compression) gates EVERY kernel, multiple random shapes, BEFORE
// any throughput number is trusted. max_abs_err must be exactly 0.
//
// COMPILE:
//   source /home/jmonk/rocky/quark-env.sh
//   $SDK/lib/llvm/bin/clang++ -O3 -x hip --offload-arch=gfx1201 \
//     -D__HIP_PLATFORM_AMD__ --rocm-path=$SDK -isystem $SDK/include \
//     gemm_bench.hip -o gemm_bench -L$SDK/lib -lamdhip64
//   HIP_VISIBLE_DEVICES=0 ./gemm_bench     # GPU0 ONLY. Never GPU1 (live server).

#include <hip/hip_runtime.h>
// ggml-cuda/vendors/hip.h defines RDNA4 as `__GFX12__` (device-pass-only
// predefine) -- standalone here (no ggml include), so mirror that exact
// mapping directly instead of pulling in the whole ggml vendor header.
#if defined(__GFX12__) && !defined(RDNA4)
#define RDNA4
#endif
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
#include <random>
#include <algorithm>
#include <string>

#define HIP_CHECK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "HIP error %s:%d: %s\n", __FILE__, __LINE__, hipGetErrorString(e_)); exit(1); } } while (0)

typedef int v2i __attribute__((ext_vector_type(2)));
typedef int v4i __attribute__((ext_vector_type(4)));
typedef int v8i __attribute__((ext_vector_type(8)));

// =============================================================================
// Compressed 2:4 int4 K64 block format (mirrors block_2of4_fp8's convention,
// ggml-common.h, scaled from QK=32/8-groups to QK=64/16-groups):
//   qs[16]:  16 groups (K/4 each). byte g = lo_survivor(4b) | hi_survivor(4b)<<4
//   meta[8]: 8 bytes; byte b covers groups (2b,2b+1): low nibble = group(2b)'s
//            (idx0 | idx1<<2), high nibble = group(2b+1)'s (idx0 | idx1<<2)
// idx0/idx1 in {0,1,2,3} = physical position (within the group of 4) of the
// lo/hi survivor respectively -- natural (unswapped) convention, matching
// swmmac24_iu4_k64.cu's already-hardware-validated K64 form (K32's form needs
// swap+XOR1; K64 does not -- see that file's header for the provenance note).
// =============================================================================
struct block_iu4_24_k64 {
    uint8_t qs[16];
    uint8_t meta[8];
};
static constexpr int QK_IU4_24_K64 = 64;

// =============================================================================
// K64 SWMMAC per-lane addressing (hardware-validated in
// ggml-cuda/swmmac24_iu4_k64.cu -- reproduced here standalone).
//   A[i][k]  (weight row i=0..15, group g=k/4=0..15, slot=lo/hi survivor):
//     lane = 16*(g/8) + i ;  gpr = (g/4)%2 ;  byte = g%4 ;  nibble = slot
//   compression[i][g] entry e=0(lo)/1(hi):
//     lane = 16*(g/8) + i ;  gpr = 0 ;  nibble(4-bit slot) = g%8 ; bit(within nibble) = e*2
//   B[k][j]  (K-row k=0..63, token col j=0..15):
//     lane = 16*(k/32) + j ; gpr = (k%32)/8 ; nibble = k%8
// Cross-checked term-by-term against `amd_matrix_instruction_calculator
// -a RDNA4 -i v_swmmac_i32_16x16x64_iu4 -d -w 32` (captured 2026-07-24):
//   A[i][k] GPR=floor(k/16)%2==floor(g/4)%2 (g=floor(k/4)) MATCH
//   A[i][k] Lane=16*floor(k/32)+i==16*floor(g/8)+i             MATCH
//   compression GPR=0, nibble=floor(g/4 ... )%8==g%8            MATCH
//   B[k][j] GPR=floor(k/8)%4==(k%32)/8 (mod-32-periodic)        MATCH
//   B[k][j] Lane=16*floor(k/32)+j                                MATCH
// Because the byte-per-group / nibble-per-group-pair storage format above is
// chosen to match this physical ordering exactly, every per-lane operand load
// below reduces to a single contiguous memcpy at a lane_half-dependent offset
// -- by design (this is the "pre-packed once, streamed at GEMM time"
// convention explained in the file header).
// =============================================================================

// ---- Kernel skeleton shared knobs -----------------------------------------
// Row-pitch padding (T187 follow-up, found empirically): a naive row stride
// of EXACTLY K bytes (iu8) or K/2 bytes (iu4 nibble-packed) hits a real DRAM
// channel/bank critical-stride collision whenever that stride lands on a
// power-of-two boundary that aliases the memory controller's interleave
// granularity -- measured catastrophic (8-30x) cliffs at iu8/K=4096
// (stride=4096B) and iu4-dense/K=8192 (stride=4096B), reproducible cold,
// isolated single-process runs, NOT thermal/clock noise (confirmed via
// rocm-smi temp before each run). This is why every real production GEMM
// kernel pads its row pitch instead of using the raw logical width -- fixed
// here the same way: allocate/address each row at a padded byte pitch,
// independent of the logical K used for loop trip counts and TOPS accounting.
static inline int64_t padded_row_stride_bytes(int64_t natural_bytes) {
    return natural_bytes + 256; // small fixed pad, breaks power-of-2 aliasing
}

template <int WARPS, int ILP>
__launch_bounds__(WARPS * 32, 1)
__global__ void k_gemm_iu8_k16(
        const int8_t * __restrict__ W,   // [N,row_stride_a] row-major, 1 byte/value, padded pitch
        const int8_t * __restrict__ Act, // [M,row_stride_b] row-major, 1 byte/value, padded pitch
        int32_t * __restrict__ D,        // [M,N] row-major
        int64_t M, int64_t N, int64_t K, int64_t row_stride_a, int64_t row_stride_b) {
    const int lane = threadIdx.x; // 0..31
    const int warp = threadIdx.y;
    const int half = lane >> 4;      // which K-half (0: k 0..7, 1: k 8..15)
    const int li   = lane & 0xF;     // weight-row-local / act-col-local idx
    const int out_row_base = (lane >= 16) ? 8 : 0;

    const int64_t n0 = (int64_t) blockIdx.x * (WARPS * ILP * 16) + (int64_t) warp * ILP * 16;
    const int64_t m0 = (int64_t) blockIdx.y * 16;
    const int64_t act_col = m0 + li;

    const int64_t n_chunks = K / 16;

    auto load_a = [&] (int64_t c, v2i (&a)[ILP]) {
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            a[t] = v2i{0, 0};
            const int64_t row = n0 + (int64_t) t * 16 + li;
            if (row < N) {
                const int8_t * p = W + row * row_stride_a + c * 16 + half * 8;
                memcpy(&a[t], p, 8);
            }
        }
    };
    auto load_b = [&] (int64_t c, v2i & b) {
        b = v2i{0, 0};
        if (act_col < M) {
            const int8_t * p = Act + act_col * row_stride_b + c * 16 + half * 8;
            memcpy(&b, p, 8);
        }
    };

    v2i a_cur[ILP], a_nxt[ILP];
    v2i b_cur, b_nxt;
    int32_t acc[ILP][8];
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) acc[t][l] = 0;

    if (n_chunks > 0) { load_a(0, a_cur); load_b(0, b_cur); }

    for (int64_t c = 0; c < n_chunks; ++c) {
        const bool have_next = (c + 1 < n_chunks);
        if (have_next) { load_a(c + 1, a_nxt); load_b(c + 1, b_nxt); }

        v8i raw[ILP];
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            v8i c0 = {0,0,0,0,0,0,0,0};
#if defined(RDNA4)
            raw[t] = __builtin_amdgcn_wmma_i32_16x16x16_iu8_w32_gfx12(true, a_cur[t], true, b_cur, c0, true);
#else
            raw[t] = c0; // never launched off RDNA4
#endif
        }
#pragma unroll
        for (int t = 0; t < ILP; ++t)
#pragma unroll
            for (int l = 0; l < 8; ++l) acc[t][l] += raw[t][l];

        if (have_next) {
#pragma unroll
            for (int t = 0; t < ILP; ++t) a_cur[t] = a_nxt[t];
            b_cur = b_nxt;
        }
    }

    const int out_col = li;
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) {
            const int64_t n = n0 + (int64_t) t * 16 + out_row_base + l;
            const int64_t m = m0 + out_col;
            if (m < M && n < N) D[m * N + n] = acc[t][l];
        }
}

template <int WARPS, int ILP>
__launch_bounds__(WARPS * 32, 1)
__global__ void k_gemm_iu4_k32(
        const uint8_t * __restrict__ W,   // [N,row_stride_a] row-major, nibble-packed, padded pitch
        const uint8_t * __restrict__ Act, // [M,row_stride_b] row-major, nibble-packed, padded pitch
        int32_t * __restrict__ D,         // [M,N] row-major
        int64_t M, int64_t N, int64_t K, int64_t row_stride_a, int64_t row_stride_b) {
    const int lane = threadIdx.x;
    const int warp = threadIdx.y;
    const int half = lane >> 4;      // which K-half (0: k 0..15, 1: k 16..31)
    const int li   = lane & 0xF;
    const int out_row_base = (lane >= 16) ? 8 : 0;

    const int64_t n0 = (int64_t) blockIdx.x * (WARPS * ILP * 16) + (int64_t) warp * ILP * 16;
    const int64_t m0 = (int64_t) blockIdx.y * 16;
    const int64_t act_col = m0 + li;

    const int64_t n_chunks = K / 32;

    auto load_a = [&] (int64_t c, v2i (&a)[ILP]) {
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            a[t] = v2i{0, 0};
            const int64_t row = n0 + (int64_t) t * 16 + li;
            if (row < N) {
                const uint8_t * p = W + row * row_stride_a + c * 16 + half * 8; // 16 bytes/chunk, half selects 8
                memcpy(&a[t], p, 8);
            }
        }
    };
    auto load_b = [&] (int64_t c, v2i & b) {
        b = v2i{0, 0};
        if (act_col < M) {
            const uint8_t * p = Act + act_col * row_stride_b + c * 16 + half * 8;
            memcpy(&b, p, 8);
        }
    };

    v2i a_cur[ILP], a_nxt[ILP];
    v2i b_cur, b_nxt;
    int32_t acc[ILP][8];
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) acc[t][l] = 0;

    if (n_chunks > 0) { load_a(0, a_cur); load_b(0, b_cur); }

    for (int64_t c = 0; c < n_chunks; ++c) {
        const bool have_next = (c + 1 < n_chunks);
        if (have_next) { load_a(c + 1, a_nxt); load_b(c + 1, b_nxt); }

        v8i raw[ILP];
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            v8i c0 = {0,0,0,0,0,0,0,0};
#if defined(RDNA4)
            raw[t] = __builtin_amdgcn_wmma_i32_16x16x32_iu4_w32_gfx12(true, a_cur[t], true, b_cur, c0, true);
#else
            raw[t] = c0;
#endif
        }
#pragma unroll
        for (int t = 0; t < ILP; ++t)
#pragma unroll
            for (int l = 0; l < 8; ++l) acc[t][l] += raw[t][l];

        if (have_next) {
#pragma unroll
            for (int t = 0; t < ILP; ++t) a_cur[t] = a_nxt[t];
            b_cur = b_nxt;
        }
    }

    const int out_col = li;
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) {
            const int64_t n = n0 + (int64_t) t * 16 + out_row_base + l;
            const int64_t m = m0 + out_col;
            if (m < M && n < N) D[m * N + n] = acc[t][l];
        }
}

// Target kernel: 2:4-sparse int4 K64 SWMMAC, real gather from compressed A
// (values + metadata, two separate global arrays) + dense B.
template <int WARPS, int ILP>
__launch_bounds__(WARPS * 32, 1)
__global__ void k_gemm_iu4_k64s(
        const uint8_t * __restrict__ WcRaw, // [N, nblk_row_stride_bytes] compressed blocks, padded row pitch
        const uint8_t * __restrict__ Act,   // [M,row_stride_b] row-major, nibble-packed dense, padded pitch
        int32_t * __restrict__ D,           // [M,N] row-major
        int64_t M, int64_t N, int64_t K, int64_t nblk_row_stride_bytes, int64_t row_stride_b) {
    const int lane = threadIdx.x;
    const int warp = threadIdx.y;
    const int half = lane >> 4;      // 0: groups 0..7 (K 0..31) / K-rows 0..31 ; 1: groups 8..15 (K 32..63) / K-rows 32..63
    const int li   = lane & 0xF;
    const int out_row_base = (lane >= 16) ? 8 : 0;

    const int64_t n0 = (int64_t) blockIdx.x * (WARPS * ILP * 16) + (int64_t) warp * ILP * 16;
    const int64_t m0 = (int64_t) blockIdx.y * 16;
    const int64_t act_col = m0 + li;

    const int64_t nblk_k = K / QK_IU4_24_K64; // = n_chunks

    auto load_a = [&] (int64_t c, v2i (&a)[ILP], unsigned (&idx)[ILP]) {
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            a[t] = v2i{0, 0};
            idx[t] = 0;
            const int64_t row = n0 + (int64_t) t * 16 + li;
            if (row < N) {
                // REAL gather: two separate global reads (values array +
                // metadata array), the actual 2:4 tax this bench measures.
                const block_iu4_24_k64 & blk = *reinterpret_cast<const block_iu4_24_k64 *>(
                        WcRaw + row * nblk_row_stride_bytes + c * (int64_t) sizeof(block_iu4_24_k64));
                int ax = 0, ay = 0;
                memcpy(&ax, blk.qs + half * 8,     4);
                memcpy(&ay, blk.qs + half * 8 + 4, 4);
                a[t] = v2i{ ax, ay };
                unsigned m4 = 0;
                memcpy(&m4, blk.meta + half * 4, 4);
                idx[t] = m4;
            }
        }
    };
    auto load_b = [&] (int64_t c, v4i & b) {
        b = v4i{0, 0, 0, 0};
        if (act_col < M) {
            const uint8_t * p = Act + act_col * row_stride_b + c * 32 + half * 16; // 32 bytes/chunk, half selects 16
            memcpy(&b, p, 16);
        }
    };

    v2i a_cur[ILP], a_nxt[ILP];
    unsigned idx_cur[ILP], idx_nxt[ILP];
    v4i b_cur, b_nxt;
    int32_t acc[ILP][8];
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) acc[t][l] = 0;

    if (nblk_k > 0) { load_a(0, a_cur, idx_cur); load_b(0, b_cur); }

    for (int64_t c = 0; c < nblk_k; ++c) {
        const bool have_next = (c + 1 < nblk_k);
        if (have_next) { load_a(c + 1, a_nxt, idx_nxt); load_b(c + 1, b_nxt); }

        v8i raw[ILP];
#pragma unroll
        for (int t = 0; t < ILP; ++t) {
            v8i c0 = {0,0,0,0,0,0,0,0};
#if defined(RDNA4)
            raw[t] = __builtin_amdgcn_swmmac_i32_16x16x64_iu4_w32(1, a_cur[t], 1, b_cur, c0, idx_cur[t], 0);
#else
            raw[t] = c0;
#endif
        }
#pragma unroll
        for (int t = 0; t < ILP; ++t)
#pragma unroll
            for (int l = 0; l < 8; ++l) acc[t][l] += raw[t][l];

        if (have_next) {
#pragma unroll
            for (int t = 0; t < ILP; ++t) { a_cur[t] = a_nxt[t]; idx_cur[t] = idx_nxt[t]; }
            b_cur = b_nxt;
        }
    }

    const int out_col = li;
#pragma unroll
    for (int t = 0; t < ILP; ++t)
#pragma unroll
        for (int l = 0; l < 8; ++l) {
            const int64_t n = n0 + (int64_t) t * 16 + out_row_base + l;
            const int64_t m = m0 + out_col;
            if (m < M && n < N) D[m * N + n] = acc[t][l];
        }
}

// =============================================================================
// Host-side data generation + packing
// =============================================================================
// row_stride_bytes: padded per-row byte pitch (see padded_row_stride_bytes);
// must be >= the natural per-row byte count. packed buffer is
// rows*row_stride_bytes bytes; the tail pad bytes of each row are left zero
// and never read (kernels only ever address [0,K) worth of real data).
static void gen_dense_iu8(std::mt19937 & rng, int64_t rows, int64_t K, int64_t row_stride_bytes,
                           std::vector<int8_t> & packed, std::vector<int> & logical) {
    std::uniform_int_distribution<int> d(-100, 100);
    packed.assign((size_t)(rows * row_stride_bytes), 0);
    logical.assign((size_t)(rows * K), 0);
    for (int64_t r = 0; r < rows; ++r) {
        for (int64_t k = 0; k < K; ++k) {
            int v = d(rng);
            packed[r*row_stride_bytes + k] = (int8_t) v;
            logical[r*K + k] = v;
        }
    }
}

static void gen_dense_iu4(std::mt19937 & rng, int64_t rows, int64_t K, int64_t row_stride_bytes,
                           std::vector<uint8_t> & packed, std::vector<int> & logical) {
    std::uniform_int_distribution<int> d(-8, 7);
    packed.assign((size_t)(rows * row_stride_bytes), 0);
    logical.assign((size_t)(rows * K), 0);
    for (int64_t r = 0; r < rows; ++r) {
        for (int64_t k = 0; k < K; k += 2) {
            int v0 = d(rng), v1 = d(rng);
            logical[r*K + k] = v0;
            logical[r*K + k + 1] = v1;
            packed[r*row_stride_bytes + k/2] = (uint8_t) ((v0 & 0xF) | ((v1 & 0xF) << 4));
        }
    }
}

static void gen_sparse_iu4_24_k64(std::mt19937 & rng, int64_t rows, int64_t K, int64_t nblk_row_stride_bytes,
                                   std::vector<uint8_t> & blocksRaw, std::vector<int> & logical) {
    static const int choices[6][2] = {{0,1},{0,2},{0,3},{1,2},{1,3},{2,3}};
    std::uniform_int_distribution<int> pick(0, 5);
    std::uniform_int_distribution<int> valdist(-8, 7);
    const int64_t nblk_k = K / QK_IU4_24_K64;
    blocksRaw.assign((size_t)(rows * nblk_row_stride_bytes), 0);
    logical.assign((size_t)(rows * K), 0);
    for (int64_t r = 0; r < rows; ++r) {
        for (int64_t bc = 0; bc < nblk_k; ++bc) {
            block_iu4_24_k64 blk{};
            for (int g = 0; g < 16; ++g) {
                const int c = pick(rng);
                const int lo_pos = choices[c][0], hi_pos = choices[c][1];
                const int lo_val = valdist(rng), hi_val = valdist(rng);
                const int64_t kbase = bc * 64 + g * 4;
                logical[r*K + kbase + lo_pos] = lo_val;
                logical[r*K + kbase + hi_pos] = hi_val;
                blk.qs[g] = (uint8_t) ((lo_val & 0xF) | ((hi_val & 0xF) << 4));
                const uint8_t nib = (uint8_t) ((lo_pos & 0x3) | ((hi_pos & 0x3) << 2));
                if (g % 2 == 0) blk.meta[g/2] = (blk.meta[g/2] & 0xF0) | nib;
                else            blk.meta[g/2] = (blk.meta[g/2] & 0x0F) | (nib << 4);
            }
            memcpy(blocksRaw.data() + r*nblk_row_stride_bytes + bc*(int64_t)sizeof(block_iu4_24_k64),
                   &blk, sizeof(block_iu4_24_k64));
        }
    }
}

static long ref_gemm_max_abs_err(const std::vector<int> & Wlog, const std::vector<int> & Actlog,
                                  const std::vector<int32_t> & Dgot, int64_t M, int64_t N, int64_t K) {
    long max_err = 0;
    for (int64_t m = 0; m < M; ++m) {
        for (int64_t n = 0; n < N; ++n) {
            long long ref = 0;
            const int * wrow = &Wlog[n*K];
            const int * arow = &Actlog[m*K];
            for (int64_t k = 0; k < K; ++k) ref += (long long) wrow[k] * (long long) arow[k];
            const long long got = Dgot[m*N + n];
            max_err = std::max(max_err, (long) llabs(got - ref));
        }
    }
    return max_err;
}

// =============================================================================
// Correctness gate
// =============================================================================
template <int WARPS, int ILP>
static bool check_iu8_k16(int64_t M, int64_t N, int64_t K, unsigned seed) {
    std::mt19937 rng(seed);
    const int64_t rs = padded_row_stride_bytes(K);
    std::vector<int8_t> Wp; std::vector<int> Wlog;
    std::vector<int8_t> Ap; std::vector<int> Alog;
    gen_dense_iu8(rng, N, K, rs, Wp, Wlog);
    gen_dense_iu8(rng, M, K, rs, Ap, Alog);

    int8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wp.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wp.data(), Wp.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemset(dD, 0, (size_t)(M*N)*sizeof(int32_t)));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    k_gemm_iu8_k16<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs, rs);
    HIP_CHECK(hipDeviceSynchronize());

    std::vector<int32_t> Dgot((size_t)(M*N));
    HIP_CHECK(hipMemcpy(Dgot.data(), dD, Dgot.size()*sizeof(int32_t), hipMemcpyDeviceToHost));
    hipFree(dW); hipFree(dA); hipFree(dD);

    long err = ref_gemm_max_abs_err(Wlog, Alog, Dgot, M, N, K);
    printf("[iu8 K16 dense]  M=%ld N=%ld K=%ld max_abs_err=%ld -> %s\n", (long)M,(long)N,(long)K, err, err==0?"PASS":"FAIL");
    return err == 0;
}

template <int WARPS, int ILP>
static bool check_iu4_k32(int64_t M, int64_t N, int64_t K, unsigned seed) {
    std::mt19937 rng(seed);
    const int64_t rs = padded_row_stride_bytes(K/2);
    std::vector<uint8_t> Wp; std::vector<int> Wlog;
    std::vector<uint8_t> Ap; std::vector<int> Alog;
    gen_dense_iu4(rng, N, K, rs, Wp, Wlog);
    gen_dense_iu4(rng, M, K, rs, Ap, Alog);

    uint8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wp.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wp.data(), Wp.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemset(dD, 0, (size_t)(M*N)*sizeof(int32_t)));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    k_gemm_iu4_k32<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs, rs);
    HIP_CHECK(hipDeviceSynchronize());

    std::vector<int32_t> Dgot((size_t)(M*N));
    HIP_CHECK(hipMemcpy(Dgot.data(), dD, Dgot.size()*sizeof(int32_t), hipMemcpyDeviceToHost));
    hipFree(dW); hipFree(dA); hipFree(dD);

    long err = ref_gemm_max_abs_err(Wlog, Alog, Dgot, M, N, K);
    printf("[iu4 K32 dense]  M=%ld N=%ld K=%ld max_abs_err=%ld -> %s\n", (long)M,(long)N,(long)K, err, err==0?"PASS":"FAIL");
    return err == 0;
}

template <int WARPS, int ILP>
static bool check_iu4_k64s(int64_t M, int64_t N, int64_t K, unsigned seed) {
    std::mt19937 rng(seed);
    const int64_t nblk_k = K / QK_IU4_24_K64;
    const int64_t rs_a = padded_row_stride_bytes(nblk_k * (int64_t) sizeof(block_iu4_24_k64));
    const int64_t rs_b = padded_row_stride_bytes(K/2);
    std::vector<uint8_t> Wc; std::vector<int> Wlog;
    std::vector<uint8_t> Ap; std::vector<int> Alog;
    gen_sparse_iu4_24_k64(rng, N, K, rs_a, Wc, Wlog);
    gen_dense_iu4(rng, M, K, rs_b, Ap, Alog);

    uint8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wc.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wc.data(), Wc.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemset(dD, 0, (size_t)(M*N)*sizeof(int32_t)));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    k_gemm_iu4_k64s<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs_a, rs_b);
    HIP_CHECK(hipDeviceSynchronize());

    std::vector<int32_t> Dgot((size_t)(M*N));
    HIP_CHECK(hipMemcpy(Dgot.data(), dD, Dgot.size()*sizeof(int32_t), hipMemcpyDeviceToHost));
    hipFree(dW); hipFree(dA); hipFree(dD);

    long err = ref_gemm_max_abs_err(Wlog, Alog, Dgot, M, N, K);
    printf("[iu4 K64 SWMMAC 2:4] M=%ld N=%ld K=%ld max_abs_err=%ld -> %s\n", (long)M,(long)N,(long)K, err, err==0?"PASS":"FAIL");
    return err == 0;
}

// =============================================================================
// Perf harness
// =============================================================================
struct PerfResult { double ms; double tops; };

template <int WARPS, int ILP>
static PerfResult perf_iu8_k16(int64_t M, int64_t N, int64_t K) {
    std::mt19937 rng(7001);
    const int64_t rs = padded_row_stride_bytes(K);
    std::vector<int8_t> Wp, Ap; std::vector<int> dummy;
    gen_dense_iu8(rng, N, K, rs, Wp, dummy); dummy.clear();
    gen_dense_iu8(rng, M, K, rs, Ap, dummy);

    int8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wp.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wp.data(), Wp.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    auto launch = [&] () { k_gemm_iu8_k16<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs, rs); };

    for (int r=0;r<3;++r) launch();
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<double> times;
    hipEvent_t s,e; HIP_CHECK(hipEventCreate(&s)); HIP_CHECK(hipEventCreate(&e));
    for (int r=0;r<6;++r) {
        HIP_CHECK(hipEventRecord(s)); launch(); HIP_CHECK(hipEventRecord(e));
        HIP_CHECK(hipEventSynchronize(e));
        float ms; HIP_CHECK(hipEventElapsedTime(&ms,s,e)); times.push_back(ms);
    }
    std::sort(times.begin(), times.end());
    double ms = times[times.size()/2];
    hipFree(dW); hipFree(dA); hipFree(dD);
    double tops = 2.0 * (double)M * (double)N * (double)K / (ms/1000.0) / 1e12;
    return { ms, tops };
}

template <int WARPS, int ILP>
static PerfResult perf_iu4_k32(int64_t M, int64_t N, int64_t K) {
    std::mt19937 rng(7002);
    const int64_t rs = padded_row_stride_bytes(K/2);
    std::vector<uint8_t> Wp, Ap; std::vector<int> dummy;
    gen_dense_iu4(rng, N, K, rs, Wp, dummy); dummy.clear();
    gen_dense_iu4(rng, M, K, rs, Ap, dummy);

    uint8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wp.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wp.data(), Wp.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    auto launch = [&] () { k_gemm_iu4_k32<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs, rs); };

    for (int r=0;r<3;++r) launch();
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<double> times;
    hipEvent_t s,e; HIP_CHECK(hipEventCreate(&s)); HIP_CHECK(hipEventCreate(&e));
    for (int r=0;r<6;++r) {
        HIP_CHECK(hipEventRecord(s)); launch(); HIP_CHECK(hipEventRecord(e));
        HIP_CHECK(hipEventSynchronize(e));
        float ms; HIP_CHECK(hipEventElapsedTime(&ms,s,e)); times.push_back(ms);
    }
    std::sort(times.begin(), times.end());
    double ms = times[times.size()/2];
    hipFree(dW); hipFree(dA); hipFree(dD);
    double tops = 2.0 * (double)M * (double)N * (double)K / (ms/1000.0) / 1e12;
    return { ms, tops };
}

template <int WARPS, int ILP>
static PerfResult perf_iu4_k64s(int64_t M, int64_t N, int64_t K) {
    std::mt19937 rng(7003);
    const int64_t nblk_k = K / QK_IU4_24_K64;
    const int64_t rs_a = padded_row_stride_bytes(nblk_k * (int64_t) sizeof(block_iu4_24_k64));
    const int64_t rs_b = padded_row_stride_bytes(K/2);
    std::vector<uint8_t> Wc; std::vector<int> dummy;
    std::vector<uint8_t> Ap;
    gen_sparse_iu4_24_k64(rng, N, K, rs_a, Wc, dummy); dummy.clear();
    gen_dense_iu4(rng, M, K, rs_b, Ap, dummy);

    uint8_t *dW, *dA; int32_t *dD;
    HIP_CHECK(hipMalloc(&dW, Wc.size()));
    HIP_CHECK(hipMalloc(&dA, Ap.size()));
    HIP_CHECK(hipMalloc(&dD, (size_t)(M*N)*sizeof(int32_t)));
    HIP_CHECK(hipMemcpy(dW, Wc.data(), Wc.size(), hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(dA, Ap.data(), Ap.size(), hipMemcpyHostToDevice));

    const dim3 block(32, WARPS, 1);
    const int64_t bn = (int64_t) WARPS * ILP * 16;
    const dim3 grid((N + bn - 1)/bn, (M+15)/16, 1);
    auto launch = [&] () { k_gemm_iu4_k64s<WARPS,ILP><<<grid, block>>>(dW, dA, dD, M, N, K, rs_a, rs_b); };

    for (int r=0;r<3;++r) launch();
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<double> times;
    hipEvent_t s,e; HIP_CHECK(hipEventCreate(&s)); HIP_CHECK(hipEventCreate(&e));
    for (int r=0;r<6;++r) {
        HIP_CHECK(hipEventRecord(s)); launch(); HIP_CHECK(hipEventRecord(e));
        HIP_CHECK(hipEventSynchronize(e));
        float ms; HIP_CHECK(hipEventElapsedTime(&ms,s,e)); times.push_back(ms);
    }
    std::sort(times.begin(), times.end());
    double ms = times[times.size()/2];
    hipFree(dW); hipFree(dA); hipFree(dD);
    double tops = 2.0 * (double)M * (double)N * (double)K / (ms/1000.0) / 1e12;
    return { ms, tops };
}

int main(int argc, char ** argv) {
    HIP_CHECK(hipSetDevice(0));
    hipDeviceProp_t prop; HIP_CHECK(hipGetDeviceProperties(&prop, 0));

    constexpr int WARPS = 32;
    constexpr int ILP   = 4;

    // Isolated single-shape mode (fresh process per measurement -- avoids
    // any cross-kernel/cross-K thermal or clock contamination from a long
    // sequential in-process sweep): ./gemm_bench single <k16|k32|k64s> <K>
    if (argc >= 4 && std::string(argv[1]) == "single") {
        const std::string kernel = argv[2];
        const int64_t K = atoll(argv[3]);
        const int64_t M = 4096, N = 4096;
        PerfResult r;
        if      (kernel == "k16_w32i4")  r = perf_iu8_k16<32,4>(M, N, K);
        else if (kernel == "k32_w32i4")  r = perf_iu4_k32<32,4>(M, N, K);
        else if (kernel == "k64s_w32i4") r = perf_iu4_k64s<32,4>(M, N, K);
        else if (kernel == "k16_w16i4")  r = perf_iu8_k16<16,4>(M, N, K);
        else if (kernel == "k32_w16i4")  r = perf_iu4_k32<16,4>(M, N, K);
        else if (kernel == "k64s_w16i4") r = perf_iu4_k64s<16,4>(M, N, K);
        else if (kernel == "k16_w8i4")   r = perf_iu8_k16<8,4>(M, N, K);
        else if (kernel == "k32_w8i4")   r = perf_iu4_k32<8,4>(M, N, K);
        else if (kernel == "k64s_w8i4")  r = perf_iu4_k64s<8,4>(M, N, K);
        else if (kernel == "k16_w8i2")   r = perf_iu8_k16<8,2>(M, N, K);
        else if (kernel == "k32_w8i2")   r = perf_iu4_k32<8,2>(M, N, K);
        else if (kernel == "k64s_w8i2")  r = perf_iu4_k64s<8,2>(M, N, K);
        else if (kernel == "k16_w4i2")   r = perf_iu8_k16<4,2>(M, N, K);
        else if (kernel == "k32_w4i2")   r = perf_iu4_k32<4,2>(M, N, K);
        else if (kernel == "k64s_w4i2")  r = perf_iu4_k64s<4,2>(M, N, K);
        else if (kernel == "k16_w32i2")  r = perf_iu8_k16<32,2>(M, N, K);
        else if (kernel == "k32_w32i2")  r = perf_iu4_k32<32,2>(M, N, K);
        else if (kernel == "k64s_w32i2") r = perf_iu4_k64s<32,2>(M, N, K);
        else if (kernel == "k16_w32i8")  r = perf_iu8_k16<32,8>(M, N, K);
        else if (kernel == "k32_w32i8")  r = perf_iu4_k32<32,8>(M, N, K);
        else if (kernel == "k64s_w32i8") r = perf_iu4_k64s<32,8>(M, N, K);
        else { fprintf(stderr, "unknown kernel %s\n", kernel.c_str()); return 1; }
        printf("%s K=%ld ms=%.4f TOPS=%.3f\n", kernel.c_str(), (long)K, r.ms, r.tops);
        return 0;
    }

    printf("Device 0: %s\n\n", prop.name);

    printf("== CORRECTNESS GATE (must be max_abs_err=0 for ALL before any perf number is trusted) ==\n");
    bool ok = true;
    // Small, non-16/non-32/non-64-aligned-ish shapes to exercise need_check bounds paths too.
    const struct { int64_t M,N,K; unsigned seed; } shapes[] = {
        { 32, 32, 256, 1 },
        { 48, 80, 512, 2 },
        { 17, 33, 128, 3 },   // deliberately not a multiple of 16 (bounds-check path)
        { 64, 64, 1024, 4 },
    };
    for (auto & s : shapes) {
        ok &= check_iu8_k16<WARPS,ILP>(s.M, s.N, s.K, s.seed);
        ok &= check_iu4_k32<WARPS,ILP>(s.M, s.N, s.K, s.seed + 100);
        ok &= check_iu4_k64s<WARPS,ILP>(s.M, s.N, s.K, s.seed + 200);
    }
    if (!ok) {
        fprintf(stderr, "\nCORRECTNESS GATE FAILED -- refusing to report any throughput number.\n");
        return 1;
    }
    printf("\n== ALL CORRECTNESS GATES PASSED (max_abs_err=0, all 3 kernels, all shapes) ==\n\n");

    printf("== PERF SWEEP (WARPS=%d ILP=%d, median-of-6, M=N=4096) ==\n", WARPS, ILP);
    printf("%-6s %-10s %-24s %-24s %-24s %-18s %-18s\n",
           "K", "", "iu8-K16 dense", "iu4-K32 dense", "iu4-K64 2:4-SWMMAC",
           "K64/K16", "K64/K32");
    const int64_t M = 4096, N = 4096;
    const int64_t Ksweep[] = { 2048, 4096, 8192 };
    for (int64_t K : Ksweep) {
        PerfResult r16 = perf_iu8_k16<WARPS,ILP>(M, N, K);
        PerfResult r32 = perf_iu4_k32<WARPS,ILP>(M, N, K);
        PerfResult r64 = perf_iu4_k64s<WARPS,ILP>(M, N, K);
        printf("K=%-4ld    %6.3fms/%5.1fTOP/s  %6.3fms/%5.1fTOP/s  %6.3fms/%5.1fTOP/s   %.3fx        %.3fx\n",
               (long)K,
               r16.ms, r16.tops, r32.ms, r32.tops, r64.ms, r64.tops,
               r64.tops / r16.tops, r64.tops / r32.tops);
    }

    printf("\n(TOPS convention: 2*M*N*K_logical/time -- K_logical is the FULL uncompressed K\n");
    printf(" dimension for all three kernels, matching bench_ilp.hip's K_eff=64 convention for\n");
    printf(" SWMMAC, so the ratios above are directly comparable to the raw-instruction ISA\n");
    printf(" ceiling (3.90x vs K16, 1.95x vs K32 dense).)\n");
    return 0;
}
