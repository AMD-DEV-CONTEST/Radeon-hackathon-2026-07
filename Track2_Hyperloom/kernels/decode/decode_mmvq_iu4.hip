// PRODUCTION int4 decode GEMV — the kernel that actually ships in the roc9
// llama.cpp fork (k_mmvq_dot8_iu4, mmvq_iu4.cu, T170).
//
// Structure that matters: ONE BLOCK PER ROW, threads stride along K
// (c += blockDim.x, so adjacent lanes read adjacent blocks = coalesced),
// then a shared-memory reduction. Launch is <<<N, 64>>>.
//
// Contrast with decode_dot8.hip / decode_dp4a.hip in this directory, which are
// one-thread-per-row. Those isolate the INSTRUCTION (dot8 vs dp4a) with the
// memory path held constant, but adjacent lanes there land row_stride bytes
// apart — uncoalesced. That is invisible while the weights fit in the 64 MiB
// Infinity Cache and catastrophic once they do not. See benchmarks/README.md.
//
// This harness therefore does two things the route benchmarks do not:
//   1. sizes the working set PAST the cache so the number is DRAM-honest, and
//   2. prints the working set + % of the measured 631 GB/s roofline, so a
//      >100% reading (i.e. "you measured cache") is self-evident.
//
// Correctness-gates against a CPU reference before reporting any throughput.
#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <random>

#define QK_IU4 32
struct block_iu4 { __half d; uint8_t qs[QK_IU4/2]; };   // 2 + 16 = 18 bytes

// Measured streaming DRAM roofline for this board (RVS babel + bw_roofline.cu,
// cross-checked 2026-08-03: 598-635 GB/s depending on access mix).
static double ROOFLINE_GBS = 631.0;
// 631 GB/s is THIS machine (R9700, gfx1201, discrete GDDR6). The roofline is a
// property of the box, not a constant: a Strix Halo APU on unified LPDDR5X is
// nearer 256 GB/s, and grading against 631 there would flag every good result
// INVALID. Override with ROOFLINE_GBS=<n> in the environment, and measure it
// on the target rather than trusting a spec sheet.

// ---- verbatim committed kernel -------------------------------------------
static __global__ void k_mmvq_dot8_iu4(
        const char* __restrict__ vweight, const block_iu4* __restrict__ act,
        float* __restrict__ dst, int64_t Kblocks, int64_t row_stride_bytes) {
    const int64_t row = blockIdx.x; const int tid = threadIdx.x;
    float partial = 0.0f;
    const block_iu4* wrow = (const block_iu4*)(vweight + row * row_stride_bytes);
    for (int64_t c = tid; c < Kblocks; c += blockDim.x) {
        uint32_t ww[4], xw[4];
        memcpy(ww, wrow[c].qs, 16); memcpy(xw, act[c].qs, 16);
        int sumi = 0;
        #pragma unroll
        for (int i = 0; i < 4; ++i)
            sumi = __builtin_amdgcn_sudot8(true, (int)ww[i], true, xw[i], sumi, false);
        partial += (float)sumi * __half2float(wrow[c].d) * __half2float(act[c].d);
    }
    extern __shared__ float sdata[]; sdata[tid] = partial; __syncthreads();
    for (int s = blockDim.x/2; s > 0; s >>= 1) { if (tid < s) sdata[tid] += sdata[tid+s]; __syncthreads(); }
    if (tid == 0) dst[row] = sdata[0];
}

// ---- CPU reference --------------------------------------------------------
static inline int sext4(uint32_t v){ int x = v & 0xF; return x >= 8 ? x - 16 : x; }

static void cpu_ref(const std::vector<block_iu4>& W, const std::vector<block_iu4>& A,
                    std::vector<float>& out, int N, int64_t Kb) {
    for (int n = 0; n < N; ++n) {
        double acc = 0.0;
        const block_iu4* wrow = &W[(size_t)n * Kb];
        for (int64_t c = 0; c < Kb; ++c) {
            int sumi = 0;
            for (int b = 0; b < QK_IU4/2; ++b) {
                sumi += sext4(wrow[c].qs[b] & 0xF)  * sext4(A[c].qs[b] & 0xF);
                sumi += sext4(wrow[c].qs[b] >> 4)   * sext4(A[c].qs[b] >> 4);
            }
            acc += (double)sumi * __half2float(wrow[c].d) * __half2float(A[c].d);
        }
        out[n] = (float)acc;
    }
}

static void roofline_from_env(void) {
    const char* e = getenv("ROOFLINE_GBS");
    if (e && atof(e) > 0.0) {
        ROOFLINE_GBS = atof(e);
        printf("  roofline overridden from environment: %.1f GB/s\n", ROOFLINE_GBS);
    }
}

int main(int argc, char** argv) {
    roofline_from_env();
    // Default shapes are DRAM-honest on a 64 MiB-Infinity-Cache board.
    // Override: ./decode_mmvq_iu4 N K
    std::vector<std::pair<int,int>> shapes = {{65536,4096},{16384,14336}};
    if (argc == 3) shapes = {{atoi(argv[1]), atoi(argv[2])}};

    printf("=== PRODUCTION k_mmvq_dot8_iu4 (block-per-row + shared-mem reduction) ===\n");
    printf("    roofline reference: %.0f GB/s measured streaming DRAM\n", ROOFLINE_GBS);
    printf("    NOTE: >100%% of roofline means the working set fit in cache,\n");
    printf("          not that the kernel beat DRAM. Check the MiB column.\n\n");

    std::mt19937 rng(1); std::uniform_int_distribution<int> b(0,255);
    int rc = 0;
    for (auto& sh : shapes) {
        int N = sh.first, K = sh.second; int64_t Kb = K / QK_IU4;
        int64_t wbytes = (int64_t)N * Kb * (int64_t)sizeof(block_iu4);
        double wmib = wbytes / 1048576.0;

        std::vector<block_iu4> hW((size_t)N*Kb), hA(Kb);
        for (auto& blk : hW){ blk.d=__float2half(0.01f); for(auto&q:blk.qs)q=b(rng);}
        for (auto& blk : hA){ blk.d=__float2half(0.01f); for(auto&q:blk.qs)q=b(rng);}

        char* dW; block_iu4* dA; float* dO;
        hipMalloc(&dW, wbytes); hipMalloc(&dA, Kb*sizeof(block_iu4)); hipMalloc(&dO, (size_t)N*4);
        hipMemcpy(dW, hW.data(), wbytes, hipMemcpyHostToDevice);
        hipMemcpy(dA, hA.data(), Kb*sizeof(block_iu4), hipMemcpyHostToDevice);

        int blk_sz = 64; dim3 grid(N), block(blk_sz); size_t shm = blk_sz*sizeof(float);
        int64_t stride = Kb*sizeof(block_iu4);

        // ---- correctness gate BEFORE any throughput is reported ----
        k_mmvq_dot8_iu4<<<grid,block,shm>>>(dW,dA,dO,Kb,stride);
        hipDeviceSynchronize();
        std::vector<float> gpu((size_t)N); std::vector<float> ref((size_t)N);
        hipMemcpy(gpu.data(), dO, (size_t)N*4, hipMemcpyDeviceToHost);
        int ncheck = N < 512 ? N : 512;          // reference is O(N*K); spot-check rows
        std::vector<block_iu4> Wsub(hW.begin(), hW.begin() + (size_t)ncheck*Kb);
        std::vector<float> refsub((size_t)ncheck);
        cpu_ref(Wsub, hA, refsub, ncheck, Kb);
        double worst = 0.0;
        for (int i = 0; i < ncheck; ++i) {
            double den = std::fabs(refsub[i]) > 1e-6 ? std::fabs(refsub[i]) : 1.0;
            worst = std::fmax(worst, std::fabs(gpu[i]-refsub[i]) / den);
        }
        bool ok = worst < 1e-3;
        if (!ok) {
            printf("N=%-6d K=%-6d | CORRECTNESS FAIL (max_rel_err=%.3e over %d rows)\n",
                   N, K, worst, ncheck);
            rc = 1; hipFree(dW);hipFree(dA);hipFree(dO); continue;
        }

        for (int w=0; w<5; ++w) k_mmvq_dot8_iu4<<<grid,block,shm>>>(dW,dA,dO,Kb,stride);
        hipDeviceSynchronize();
        hipEvent_t s,e; hipEventCreate(&s); hipEventCreate(&e);
        int it=100; hipEventRecord(s);
        for (int i=0;i<it;++i) k_mmvq_dot8_iu4<<<grid,block,shm>>>(dW,dA,dO,Kb,stride);
        hipEventRecord(e); hipEventSynchronize(e);
        float ms=0; hipEventElapsedTime(&ms,s,e); ms/=it;
        double gbs = wbytes/(ms*1e6);

        printf("N=%-6d K=%-6d | %7.1f MiB %-14s | %.4f ms | %3.0f GB/s | %2.0f%% of roofline | max_rel_err=%.1e PASS\n",
               N, K, wmib, wmib > 64.0 ? "(DRAM-honest)" : "(CACHE-RESIDENT!)",
               ms, gbs, 100.0*gbs/ROOFLINE_GBS, worst);
        hipFree(dW);hipFree(dA);hipFree(dO);
    }
    return rc;
}
