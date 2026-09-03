// T187 follow-up: is the 22.2 vs 25.5 Ginstr/s SWMMAC-vs-WMMA issue-rate gap
// (bench.hip) a fundamental per-instruction issue cost, or an artifact of
// the ORIGINAL single-accumulator DEPENDENT chain stalling on 2:4-index-
// decode latency? Test: give each thread N INDEPENDENT accumulator chains
// (N=1,2,4,8), fully unrolled, no inter-chain dependency, so the matrix
// pipe can issue back-to-back and hide any per-instruction decode latency.
// Apply the SAME ILP treatment to K16 iu8 WMMA and K32 iu4 dense WMMA as a
// DIAGNOSTIC control (are they already issue-rate-bound, or do they ALSO
// speed up with ILP -- which would mean bench.hip's whole baseline was
// latency-limited, not just the SWMMAC number).
//
// Also sweeps waves/block (occupancy: 1,2,4,8 waves/block, same total wave
// count each time) to test whether latency hides across concurrently
// resident waves too, independent of intra-thread ILP.
//
// CORRECTNESS: closed-form gate on the EXACT kernel variant used for the
// throughput measurement (not a proxy) -- the WMMA/SWMMAC accumulate op is
// linear/additive (c_new = c_old + dot), so after `iters` iterations of a
// chain fed constant uniform operands (A=3, B=5 broadcast into every bit
// slot), every output element of every chain must equal
// `iters * K * 3 * 5` exactly. Verified for every N and every instruction
// BEFORE any throughput number from that kernel is trusted.
//
// COMPILE:
//   source /home/jmonk/rocky/quark-env.sh
//   $SDK/lib/llvm/bin/clang++ -O3 -x hip --offload-arch=gfx1201 \
//     -D__AMDGCN_WAVEFRONT_SIZE=32 -D__HIP_PLATFORM_AMD__ \
//     --rocm-path=$SDK -isystem $SDK/include bench_ilp.hip -o bench_ilp \
//     -L$SDK/lib -lamdhip64
//   HIP_VISIBLE_DEVICES=0 ./bench_ilp     # GPU0 ONLY. never GPU1.

#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <algorithm>

typedef int   v2i __attribute__((ext_vector_type(2)));
typedef int   v4i __attribute__((ext_vector_type(4)));
typedef int   v8i __attribute__((ext_vector_type(8)));

#define HIP_CHECK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "HIP error %s:%d: %s\n", __FILE__, __LINE__, hipGetErrorString(e_)); exit(1); } } while (0)

// ============================================================================
// K16 iu8 WMMA, N-way ILP
// ============================================================================
namespace k16_iu8 {

template <int N>
__global__ void kernel(v2i a, v2i b, v8i * __restrict__ out /*[N] per lane, lane0 only*/, int iters) {
    v8i c[N];
#pragma unroll
    for (int n = 0; n < N; ++n) c[n] = {0,0,0,0,0,0,0,0};
    for (int i = 0; i < iters; ++i) {
#pragma unroll
        for (int n = 0; n < N; ++n) {
            c[n] = __builtin_amdgcn_wmma_i32_16x16x16_iu8_w32_gfx12(true, a, true, b, c[n], true);
        }
    }
    if (threadIdx.x == 0 && blockIdx.x == 0) {
#pragma unroll
        for (int n = 0; n < N; ++n) out[n] = c[n];
    }
}

constexpr int K = 16;

} // namespace k16_iu8

// ============================================================================
// K32 iu4 dense WMMA, N-way ILP
// ============================================================================
namespace k32_iu4 {

template <int N>
__global__ void kernel(v2i a, v2i b, v8i * __restrict__ out, int iters) {
    v8i c[N];
#pragma unroll
    for (int n = 0; n < N; ++n) c[n] = {0,0,0,0,0,0,0,0};
    for (int i = 0; i < iters; ++i) {
#pragma unroll
        for (int n = 0; n < N; ++n) {
            c[n] = __builtin_amdgcn_wmma_i32_16x16x32_iu4_w32_gfx12(true, a, true, b, c[n], true);
        }
    }
    if (threadIdx.x == 0 && blockIdx.x == 0) {
#pragma unroll
        for (int n = 0; n < N; ++n) out[n] = c[n];
    }
}

constexpr int K = 32;

} // namespace k32_iu4

// ============================================================================
// K64 iu4 2:4-sparse SWMMAC, N-way ILP
// ============================================================================
namespace k64_swmmac_iu4 {

template <int N>
__global__ void kernel(v2i a, v4i b, unsigned idx, v8i * __restrict__ out, int iters) {
    v8i c[N];
#pragma unroll
    for (int n = 0; n < N; ++n) c[n] = {0,0,0,0,0,0,0,0};
    for (int i = 0; i < iters; ++i) {
#pragma unroll
        for (int n = 0; n < N; ++n) {
            c[n] = __builtin_amdgcn_swmmac_i32_16x16x64_iu4_w32(1, a, 1, b, c[n], idx, 0);
        }
    }
    if (threadIdx.x == 0 && blockIdx.x == 0) {
#pragma unroll
        for (int n = 0; n < N; ++n) out[n] = c[n];
    }
}

constexpr int K = 64; // K_effective convention

} // namespace k64_swmmac_iu4

// ============================================================================
// Generic correctness gate: closed form iters*K*3*5 for every chain (small iters).
// ============================================================================
template <int N>
static bool check_k16(int iters) {
    uint32_t aw = 0x03030303u, bw = 0x05050505u;
    v2i a_arg = { (int)aw, (int)aw }, b_arg = { (int)bw, (int)bw };
    v8i *d_out; HIP_CHECK(hipMalloc(&d_out, N*sizeof(v8i)));
    hipLaunchKernelGGL((k16_iu8::kernel<N>), dim3(1), dim3(32), 0, 0, a_arg, b_arg, d_out, iters);
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<v8i> out(N); HIP_CHECK(hipMemcpy(out.data(), d_out, N*sizeof(v8i), hipMemcpyDeviceToHost));
    HIP_CHECK(hipFree(d_out));
    const long expect = (long)iters * k16_iu8::K * 3 * 5;
    long max_err = 0;
    for (int n = 0; n < N; ++n) { int tmp[8]; memcpy(tmp, &out[n], sizeof(tmp));
        for (int r = 0; r < 8; ++r) max_err = std::max(max_err, (long) llabs((long long)tmp[r] - expect)); }
    printf("[K16 iu8 WMMA  N=%d] closed-form gate: iters=%d expect=%ld max_abs_err=%ld -> %s\n",
           N, iters, expect, max_err, max_err == 0 ? "PASS" : "FAIL");
    return max_err == 0;
}

template <int N>
static bool check_k32(int iters) {
    uint32_t aw = 0, bw = 0;
    for (int n = 0; n < 8; ++n) { aw |= (0x3u << (4*n)); bw |= (0x5u << (4*n)); }
    v2i a_arg = { (int)aw, (int)aw }, b_arg = { (int)bw, (int)bw };
    v8i *d_out; HIP_CHECK(hipMalloc(&d_out, N*sizeof(v8i)));
    hipLaunchKernelGGL((k32_iu4::kernel<N>), dim3(1), dim3(32), 0, 0, a_arg, b_arg, d_out, iters);
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<v8i> out(N); HIP_CHECK(hipMemcpy(out.data(), d_out, N*sizeof(v8i), hipMemcpyDeviceToHost));
    HIP_CHECK(hipFree(d_out));
    const long expect = (long)iters * k32_iu4::K * 3 * 5;
    long max_err = 0;
    for (int n = 0; n < N; ++n) { int tmp[8]; memcpy(tmp, &out[n], sizeof(tmp));
        for (int r = 0; r < 8; ++r) max_err = std::max(max_err, (long) llabs((long long)tmp[r] - expect)); }
    printf("[K32 iu4 WMMA  N=%d] closed-form gate: iters=%d expect=%ld max_abs_err=%ld -> %s\n",
           N, iters, expect, max_err, max_err == 0 ? "PASS" : "FAIL");
    return max_err == 0;
}

template <int N>
static bool check_k64(int iters) {
    uint32_t aw = 0, bw = 0;
    for (int n = 0; n < 8; ++n) aw |= (0x3u << (4*n));
    for (int n = 0; n < 8; ++n) bw |= (0x5u << (4*n));
    v2i a_arg = { (int)aw, (int)aw };
    v4i b_arg = { (int)bw, (int)bw, (int)bw, (int)bw };
    unsigned idx_arg = 0x44444444u;
    v8i *d_out; HIP_CHECK(hipMalloc(&d_out, N*sizeof(v8i)));
    hipLaunchKernelGGL((k64_swmmac_iu4::kernel<N>), dim3(1), dim3(32), 0, 0, a_arg, b_arg, idx_arg, d_out, iters);
    HIP_CHECK(hipDeviceSynchronize());
    std::vector<v8i> out(N); HIP_CHECK(hipMemcpy(out.data(), d_out, N*sizeof(v8i), hipMemcpyDeviceToHost));
    HIP_CHECK(hipFree(d_out));
    // 2:4 sparsity -> 32 of 64 logical K survive per instruction.
    const long expect = (long)iters * 32 * 3 * 5;
    long max_err = 0;
    for (int n = 0; n < N; ++n) { int tmp[8]; memcpy(tmp, &out[n], sizeof(tmp));
        for (int r = 0; r < 8; ++r) max_err = std::max(max_err, (long) llabs((long long)tmp[r] - expect)); }
    printf("[K64 iu4 SWMMAC N=%d] closed-form gate: iters=%d expect=%ld max_abs_err=%ld -> %s\n",
           N, iters, expect, max_err, max_err == 0 ? "PASS" : "FAIL");
    return max_err == 0;
}

// ============================================================================
// Throughput harness (median-of-6, warmup discarded)
// ============================================================================
static double median_ms(std::vector<double> & v) {
    std::sort(v.begin(), v.end());
    return v[v.size()/2];
}

struct Result { double ms; double ginstr_s; };

template <int N, typename LaunchFn>
static Result time_variant(LaunchFn launch, long total_instr_per_thread, int blocks, int threads) {
    hipEvent_t s, e; HIP_CHECK(hipEventCreate(&s)); HIP_CHECK(hipEventCreate(&e));
    launch(); HIP_CHECK(hipDeviceSynchronize()); // warmup
    std::vector<double> times;
    for (int r = 0; r < 6; ++r) {
        HIP_CHECK(hipEventRecord(s));
        launch();
        HIP_CHECK(hipEventRecord(e));
        HIP_CHECK(hipEventSynchronize(e));
        float ms; HIP_CHECK(hipEventElapsedTime(&ms, s, e));
        times.push_back(ms);
    }
    double ms = median_ms(times);
    // total instructions issued = blocks * (threads/32 waves/block, but WMMA is per-wave-32,
    // i.e. one instruction issue PER WAVE, not per-thread) * total_instr_per_thread(==per-wave chain length)
    long waves = (long)blocks * (threads / 32);
    double ginstr_s = (double) waves * total_instr_per_thread / (ms * 1e-3) / 1e9;
    return { ms, ginstr_s };
}

int main() {
    HIP_CHECK(hipSetDevice(0));
    hipDeviceProp_t prop; HIP_CHECK(hipGetDeviceProperties(&prop, 0));
    printf("Device 0: %s\n\n", prop.name);

    // ---- correctness gate on the EXACT ILP kernel variants, N=1,2,4,8, small iters ----
    bool ok = true;
    const int CHECK_ITERS = 17;
    ok &= check_k16<1>(CHECK_ITERS); ok &= check_k16<2>(CHECK_ITERS); ok &= check_k16<4>(CHECK_ITERS); ok &= check_k16<8>(CHECK_ITERS);
    ok &= check_k32<1>(CHECK_ITERS); ok &= check_k32<2>(CHECK_ITERS); ok &= check_k32<4>(CHECK_ITERS); ok &= check_k32<8>(CHECK_ITERS);
    ok &= check_k64<1>(CHECK_ITERS); ok &= check_k64<2>(CHECK_ITERS); ok &= check_k64<4>(CHECK_ITERS); ok &= check_k64<8>(CHECK_ITERS);
    if (!ok) { fprintf(stderr, "CORRECTNESS GATE FAILED on an ILP variant -- refusing to report throughput.\n"); return 1; }
    printf("\n== ALL ILP-VARIANT CORRECTNESS GATES PASSED (N=1,2,4,8, all 3 instructions) ==\n\n");

    // ---- throughput: ILP sweep N=1,2,4,8 at 1 wave/block (occupancy baseline) ----
    const int BLOCKS = 8192;
    const int THREADS_1W = 32;
    const long ITERS_TOTAL = 400000; // total instr/chain issued per wave (same total work regardless of N)

    uint32_t aw8 = 0x03030303u, bw8 = 0x05050505u;
    v2i a16 = { (int)aw8, (int)aw8 }, b16 = { (int)bw8, (int)bw8 };
    uint32_t aw4 = 0, bw4 = 0; for (int n=0;n<8;++n){ aw4 |= (0x3u<<(4*n)); bw4 |= (0x5u<<(4*n)); }
    v2i a32 = { (int)aw4, (int)aw4 }, b32 = { (int)bw4, (int)bw4 };
    v2i a64 = { (int)aw4, (int)aw4 }; v4i b64 = { (int)bw4,(int)bw4,(int)bw4,(int)bw4 }; unsigned idx64 = 0x44444444u;

    v8i *d16, *d32, *d64;
    HIP_CHECK(hipMalloc(&d16, 8*sizeof(v8i)));
    HIP_CHECK(hipMalloc(&d32, 8*sizeof(v8i)));
    HIP_CHECK(hipMalloc(&d64, 8*sizeof(v8i)));

    printf("== ILP SWEEP (1 wave/block, BLOCKS=%d, %ld instr/chain/wave) ==\n", BLOCKS, ITERS_TOTAL);
    printf("%-6s %-22s %-22s %-22s\n", "N", "K16 iu8 (Ginstr/s)", "K32 iu4 dense (Ginstr/s)", "K64 iu4 SWMMAC (Ginstr/s)");

    double g16[4], g32[4], g64[4]; // indices: 0->N1,1->N2,2->N4,3->N8
    int Ns[4] = {1,2,4,8};
    for (int idx = 0; idx < 4; ++idx) {
        int N = Ns[idx];
        long iters_per_chain = ITERS_TOTAL / N; // keep total instr/wave constant across N
        Result r16, r32, r64;
        switch (N) {
            case 1:
                r16 = time_variant<1>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<1>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*1, BLOCKS, THREADS_1W);
                r32 = time_variant<1>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<1>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*1, BLOCKS, THREADS_1W);
                r64 = time_variant<1>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<1>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*1, BLOCKS, THREADS_1W);
                break;
            case 2:
                r16 = time_variant<2>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<2>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*2, BLOCKS, THREADS_1W);
                r32 = time_variant<2>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<2>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*2, BLOCKS, THREADS_1W);
                r64 = time_variant<2>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<2>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*2, BLOCKS, THREADS_1W);
                break;
            case 4:
                r16 = time_variant<4>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<4>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*4, BLOCKS, THREADS_1W);
                r32 = time_variant<4>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<4>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*4, BLOCKS, THREADS_1W);
                r64 = time_variant<4>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<4>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*4, BLOCKS, THREADS_1W);
                break;
            case 8:
                r16 = time_variant<8>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<8>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*8, BLOCKS, THREADS_1W);
                r32 = time_variant<8>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<8>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*8, BLOCKS, THREADS_1W);
                r64 = time_variant<8>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<8>), dim3(BLOCKS), dim3(THREADS_1W), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*8, BLOCKS, THREADS_1W);
                break;
        }
        g16[idx]=r16.ginstr_s; g32[idx]=r32.ginstr_s; g64[idx]=r64.ginstr_s;
        printf("%-6d %-22.2f %-22.2f %-22.2f\n", N, r16.ginstr_s, r32.ginstr_s, r64.ginstr_s);
    }

    // pick best N per instruction for the summary
    auto best = [](double *g){ int bi=0; for(int i=1;i<4;++i) if (g[i]>g[bi]) bi=i; return bi; };
    int b16i = best(g16), b32i = best(g32), b64i = best(g64);
    printf("\nBest-N issue rate: K16=%.2f Ginstr/s (N=%d)  K32=%.2f Ginstr/s (N=%d)  K64=%.2f Ginstr/s (N=%d)\n",
           g16[b16i], Ns[b16i], g32[b32i], Ns[b32i], g64[b64i], Ns[b64i]);
    printf("Best-N SWMMAC-vs-K16 issue-rate ratio: %.3fx\n", g64[b64i]/g16[b16i]);
    // K_effective TOPS at best N
    double tops16 = g16[b16i]*1e9 * (16.0*16.0*16.0) * 2.0 / 1e12;
    double tops32 = g32[b32i]*1e9 * (16.0*16.0*32.0) * 2.0 / 1e12;
    double tops64 = g64[b64i]*1e9 * (16.0*16.0*64.0) * 2.0 / 1e12;
    printf("Best-N TOP/s (K_eff conv.): K16=%.1f  K32=%.1f (%.3fx K16)  K64=%.1f (%.3fx K16, %.3fx K32)\n",
           tops16, tops32, tops32/tops16, tops64, tops64/tops16, tops64/tops32);

    // ---- occupancy sweep at the best-found N for K64 (and same N for K16/K32 for apples-to-apples) ----
    int Nbest = Ns[b64i];
    printf("\n== OCCUPANCY SWEEP (N=%d, same total wave count=%d, waves/block swept) ==\n", Nbest, BLOCKS);
    printf("%-10s %-22s %-22s %-22s\n", "waves/blk", "K16 (Ginstr/s)", "K32 (Ginstr/s)", "K64 (Ginstr/s)");
    int waveOpts[4] = {1,2,4,8};
    for (int w : waveOpts) {
        int threads = 32*w;
        int blocks = BLOCKS / w; // keep total wave count constant = BLOCKS
        long iters_per_chain = ITERS_TOTAL / Nbest;
        Result r16, r32, r64;
        if (Nbest == 1) {
            r16 = time_variant<1>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<1>), dim3(blocks), dim3(threads), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*1, blocks, threads);
            r32 = time_variant<1>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<1>), dim3(blocks), dim3(threads), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*1, blocks, threads);
            r64 = time_variant<1>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<1>), dim3(blocks), dim3(threads), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*1, blocks, threads);
        } else if (Nbest == 2) {
            r16 = time_variant<2>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<2>), dim3(blocks), dim3(threads), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*2, blocks, threads);
            r32 = time_variant<2>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<2>), dim3(blocks), dim3(threads), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*2, blocks, threads);
            r64 = time_variant<2>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<2>), dim3(blocks), dim3(threads), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*2, blocks, threads);
        } else if (Nbest == 4) {
            r16 = time_variant<4>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<4>), dim3(blocks), dim3(threads), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*4, blocks, threads);
            r32 = time_variant<4>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<4>), dim3(blocks), dim3(threads), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*4, blocks, threads);
            r64 = time_variant<4>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<4>), dim3(blocks), dim3(threads), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*4, blocks, threads);
        } else {
            r16 = time_variant<8>([&](){ hipLaunchKernelGGL((k16_iu8::kernel<8>), dim3(blocks), dim3(threads), 0, 0, a16, b16, d16, (int)iters_per_chain); }, iters_per_chain*8, blocks, threads);
            r32 = time_variant<8>([&](){ hipLaunchKernelGGL((k32_iu4::kernel<8>), dim3(blocks), dim3(threads), 0, 0, a32, b32, d32, (int)iters_per_chain); }, iters_per_chain*8, blocks, threads);
            r64 = time_variant<8>([&](){ hipLaunchKernelGGL((k64_swmmac_iu4::kernel<8>), dim3(blocks), dim3(threads), 0, 0, a64, b64, idx64, d64, (int)iters_per_chain); }, iters_per_chain*8, blocks, threads);
        }
        printf("%-10d %-22.2f %-22.2f %-22.2f\n", w, r16.ginstr_s, r32.ginstr_s, r64.ginstr_s);
    }

    HIP_CHECK(hipFree(d16)); HIP_CHECK(hipFree(d32)); HIP_CHECK(hipFree(d64));
    return 0;
}
