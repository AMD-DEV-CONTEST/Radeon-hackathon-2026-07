// decode_fp8.hip — fp8 (E4M3) decode via v_dot4_f32_fp8_fp8 on gfx1201.
//
// This is the fp8 counterpart to decode_mmvq_iu4.hip. RDNA4 exposes a native
// 4-wide fp8 dot product, __builtin_amdgcn_dot4_f32_fp8_fp8, which our ISA
// sweep found present on gfx1201 and unexploited (results/gfx1201-isa-map.md).
// The kernel below is the shape that survived: one block per row, each thread
// walking a strided slice of the row, finishing with a shared-memory tree
// reduction.
//
// Two rules this file follows, both learned by getting them wrong first:
//
//   1. CORRECTNESS BEFORE TIMING. The gate runs first, against a CPU reference
//      that decodes E4M3 by hand. If it fails, the program exits and prints no
//      throughput number at all. An earlier version of this benchmark reported
//      627 GB/s with no gate whatsoever -- and because it seeded weights with
//      uniform random bytes, some of those bytes were the E4M3 NaN encodings
//      (0x7F / 0xFF). It was quite possibly timing a kernel producing NaN, and
//      nothing in the output would have said so. The generator below excludes
//      those two encodings, and the gate would catch it now regardless.
//
//   2. WORKING SET IS REPORTED, AND CACHE-RESIDENT RUNS SELF-FLAG. gfx1201 has
//      a 64 MiB Infinity Cache. A shape whose weights fit inside it reports a
//      bandwidth above the 631 GB/s measured DRAM roofline, which does not mean
//      the kernel is fast -- it means the measurement is not of DRAM. Any such
//      line is marked, not celebrated.
//
// Build:  hipcc --offload-arch=gfx1201 -O3 decode_fp8.hip -o decode_fp8
// Run:    HIP_VISIBLE_DEVICES=0 ./decode_fp8 [N K]

#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <random>

#define QK 32
static double ROOFLINE_GBS = 631.0;   // measured streaming DRAM read, GB/s
// 631 GB/s is THIS machine (R9700, gfx1201, discrete GDDR6). The roofline is a
// property of the box, not a constant: a Strix Halo APU on unified LPDDR5X is
// nearer 256 GB/s, and grading against 631 there would flag every good result
// INVALID. Override with ROOFLINE_GBS=<n> in the environment, and measure it
// on the target rather than trusting a spec sheet.
static const double CACHE_MIB    = 64.0;    // Infinity Cache

struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };
struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };

// ---------------------------------------------------------------- device ---
// THIS KERNEL WAS WRITTEN BY THE LOCAL MODEL, not by a human.
//
// Qwen-AgentWorld-35B-A3B, served by Lemonade on the R9700, produced it from a
// written specification: the block layout, the E4M3 encoding, the arithmetic,
// the available intrinsic, and the required signature. It was given neither a
// reference implementation nor the expected outputs.
//
// It is here because it earned the place. Graded blind against a golden
// reference it never saw, it came back max_rel_err = 0.000000e+00 -- bit-exact
// across 4096 rows -- on the first attempt, and the compiled binary contains 8
// emissions of v_dot4_f32_fp8_fp8, so it really uses the hardware instruction.
// The rig that established that is in agent_repro/ and can be re-run.
//
// The division of labour is worth being exact about: the model wrote the kernel
// below. The human wrote everything around it -- the CPU E4M3 reference, the
// correctness gate that runs before any timing, the working-set accounting and
// the roofline check. Neither half is the interesting one on its own.
//
// One honest note on quality: it hardcodes the block width (`c += 64`) and the
// reduction start (`stride_sh = 32`) where a human would more likely write
// blockDim.x and blockDim.x/2. That is correct for the launch configuration it
// was given and specified against, but it is less general than it could be. We
// have left it exactly as written rather than tidying it, because a kernel that
// has been quietly edited is no longer evidence of anything.

__global__ void decode_fp8_dot4(const char* __restrict__ vw,
                             const block_a_fp8* __restrict__ act,
                             float* __restrict__ dst,
                             int64_t Kb, int64_t stride) {
    extern __shared__ float sd[];
    int tid = threadIdx.x;
    int row = blockIdx.x;

    float thread_sum = 0.0f;

    const block_f8e4m3* row_weights = (const block_f8e4m3*)(vw + row * stride);

    for (int64_t c = tid; c < Kb; c += 64) {
        const block_f8e4m3* wblk = &row_weights[c];
        const block_a_fp8* ablk = &act[c];

        const uint32_t* wq = (const uint32_t*)wblk->qs;
        const uint32_t* aq = (const uint32_t*)ablk->qs;

        float s = 0.0f;
        for (int i = 0; i < 8; ++i) {
            s = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], s);
        }

        float scale_w = __half2float(wblk->d);
        float scale_a = __low2float(ablk->ds);

        thread_sum += s * scale_w * scale_a;
    }

    sd[tid] = thread_sum;
    __syncthreads();

    for (int stride_sh = 32; stride_sh > 0; stride_sh >>= 1) {
        if (tid < stride_sh) {
            sd[tid] += sd[tid + stride_sh];
        }
        __syncthreads();
    }

    if (tid == 0) {
        dst[row] = sd[0];
    }
}

// ------------------------------------------------------------------- host ---
// OCP E4M3: 1 sign / 4 exponent / 3 mantissa, bias 7, no infinities.
// 0x7F and 0xFF are NaN. Max finite magnitude is 448.
static float e4m3_to_float(uint8_t v)
{
    const int s = (v >> 7) & 0x1;
    const int e = (v >> 3) & 0xF;
    const int m =  v       & 0x7;
    const float sign = s ? -1.0f : 1.0f;
    if (e == 0)                return sign * ldexpf((float)m / 8.0f, -6);   // subnormal
    if (e == 15 && m == 7)     return NAN;                                  // NaN
    return sign * ldexpf(1.0f + (float)m / 8.0f, e - 7);
}

// CPU reference. Mirrors the device accumulation order exactly (per-block sum
// of 32 products, then scaled) so the comparison is tight rather than merely
// plausible.
static void reference(const std::vector<block_f8e4m3>& W,
                      const std::vector<block_a_fp8>&  A,
                      std::vector<float>& out, int N, int64_t Kb)
{
    for (int row = 0; row < N; ++row) {
        double total = 0.0;
        for (int64_t c = 0; c < Kb; ++c) {
            const block_f8e4m3& wb = W[(size_t)row * Kb + c];
            const block_a_fp8&  ab = A[c];
            float sumf = 0.0f;
            for (int i = 0; i < QK; ++i)
                sumf += e4m3_to_float(wb.qs[i]) * e4m3_to_float(ab.qs[i]);
            total += (double)sumf * __half2float(wb.d) * __low2float(ab.ds);
        }
        out[row] = (float)total;
    }
}

static uint8_t finite_e4m3(std::mt19937& rng)
{
    std::uniform_int_distribution<int> b(0, 255);
    uint8_t v;
    do { v = (uint8_t)b(rng); } while ((v & 0x7F) == 0x7F);   // reject NaN encodings
    return v;
}

static void fill(std::vector<block_f8e4m3>& W, std::vector<block_a_fp8>& A,
                 std::mt19937& rng)
{
    for (auto& x : W) { x.d  = __float2half(0.01f);      for (auto& q : x.qs) q = finite_e4m3(rng); }
    for (auto& x : A) { x.ds = __float2half2_rn(0.02f);  for (auto& q : x.qs) q = finite_e4m3(rng); }
}

static double run(int N, int K, bool timed, double* out_gbs, double* out_mib)
{
    const int64_t Kb = K / QK;
    const int64_t wb = (int64_t)N * Kb * sizeof(block_f8e4m3);
    const int64_t st = Kb * sizeof(block_f8e4m3);

    std::mt19937 rng(1);
    std::vector<block_f8e4m3> hW((size_t)N * Kb);
    std::vector<block_a_fp8>  hA(Kb);
    fill(hW, hA, rng);

    char* dW; block_a_fp8* dA; float* dO;
    hipMalloc(&dW, wb); hipMalloc(&dA, Kb * sizeof(block_a_fp8)); hipMalloc(&dO, (size_t)N * 4);
    hipMemcpy(dW, hW.data(), wb, hipMemcpyHostToDevice);
    hipMemcpy(dA, hA.data(), Kb * sizeof(block_a_fp8), hipMemcpyHostToDevice);

    const int    blk = 64;
    const size_t shm = blk * sizeof(float);

    double max_rel = 0.0;
    if (!timed) {                       // correctness gate
        decode_fp8_dot4<<<N, blk, shm>>>(dW, dA, dO, Kb, st);
        hipDeviceSynchronize();
        std::vector<float> got(N), want(N);
        hipMemcpy(got.data(), dO, (size_t)N * 4, hipMemcpyDeviceToHost);
        reference(hW, hA, want, N, Kb);
        for (int i = 0; i < N; ++i) {
            const double d = fabs((double)got[i] - (double)want[i]);
            const double s = fabs((double)want[i]);
            if (!std::isfinite(got[i])) { max_rel = INFINITY; break; }
            const double rel = s > 1e-6 ? d / s : d;
            if (rel > max_rel) max_rel = rel;
        }
    } else {
        for (int w = 0; w < 5; ++w) decode_fp8_dot4<<<N, blk, shm>>>(dW, dA, dO, Kb, st);
        hipDeviceSynchronize();
        hipEvent_t s, e; hipEventCreate(&s); hipEventCreate(&e);
        const int it = 100;
        hipEventRecord(s);
        for (int i = 0; i < it; ++i) decode_fp8_dot4<<<N, blk, shm>>>(dW, dA, dO, Kb, st);
        hipEventRecord(e); hipEventSynchronize(e);
        float ms = 0; hipEventElapsedTime(&ms, s, e); ms /= it;
        *out_gbs = wb / (ms * 1e6);
        *out_mib = wb / (1024.0 * 1024.0);
    }

    hipFree(dW); hipFree(dA); hipFree(dO);
    return max_rel;
}

static void roofline_from_env(void) {
    const char* e = getenv("ROOFLINE_GBS");
    if (e && atof(e) > 0.0) {
        ROOFLINE_GBS = atof(e);
        printf("  roofline overridden from environment: %.1f GB/s\n", ROOFLINE_GBS);
    }
}

int main(int argc, char** argv)
{
    roofline_from_env();
    printf("=== fp8 E4M3 decode via v_dot4_f32_fp8_fp8 (gfx1201) ===\n\n");

    // ---- 1. correctness gate, before any timing is printed ----------------
    printf("correctness gate (vs CPU E4M3 reference)\n");
    const double tol = 1e-3;
    const double err = run(256, 4096, false, nullptr, nullptr);
    printf("  N=256 K=4096   max_rel_err = %.3e   tol = %.0e   %s\n\n",
           err, tol, err <= tol ? "PASS" : "FAIL");
    if (!(err <= tol)) {
        printf("GATE FAILED -- no throughput number will be reported.\n");
        return 1;
    }

    // ---- 2. throughput, DRAM-honest by default ----------------------------
    int shapes[][2] = {{65536, 4096}, {16384, 14336}};
    int custom[1][2];
    int nsh = 2;
    if (argc >= 3) { custom[0][0] = atoi(argv[1]); custom[0][1] = atoi(argv[2]); nsh = 1; }

    printf("throughput vs %.0f GB/s measured DRAM roofline\n", ROOFLINE_GBS);
    for (int i = 0; i < nsh; ++i) {
        const int N = (argc >= 3) ? custom[0][0] : shapes[i][0];
        const int K = (argc >= 3) ? custom[0][1] : shapes[i][1];
        double gbs = 0, mib = 0;
        run(N, K, true, &gbs, &mib);
        const bool cache_resident = mib < CACHE_MIB;
        printf("  N=%-6d K=%-6d | %7.1f MiB %-18s | %4.0f GB/s | %3.0f%% of roofline%s\n",
               N, K, mib,
               cache_resident ? "(CACHE-RESIDENT!)" : "(DRAM-honest)",
               gbs, 100.0 * gbs / ROOFLINE_GBS,
               gbs > ROOFLINE_GBS
                 ? (cache_resident ? "  <-- INVALID: above roofline, working set fits cache"
                                   : "  <-- INVALID: above roofline, cause unknown -- check the roofline value")
                 : "");
    }
    return 0;
}
