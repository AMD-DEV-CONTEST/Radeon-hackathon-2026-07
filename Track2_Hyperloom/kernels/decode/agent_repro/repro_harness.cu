// repro_harness.cu — grade an agent-written kernel against a golden reference.
//
// The agent supplies ONE file, agent_kernel.cuh, containing a kernel with the
// fixed signature below. It does not supply inputs, does not supply the
// reference, and does not perform the comparison. All three belong to this
// harness, which is the point: an agent that owns its own reference can only
// prove self-consistency, never correctness.
//
//   hipcc --offload-arch=gfx1201 -O3 repro_harness.cu -o repro && ./repro

#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>

#define QK 32
struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };
struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };

// The agent's kernel must define:
//   __global__ void agent_kernel(const char* vw, const block_a_fp8* act,
//                                float* dst, int64_t Kb, int64_t stride)
// launched as <<<N, 64, 64*sizeof(float)>>>.
#include "agent_kernel.cuh"

static std::vector<char> slurp(const char* path, size_t expect) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "missing %s -- run ./golden_gen first\n", path); exit(2); }
    std::vector<char> v(expect);
    size_t got = fread(v.data(), 1, expect, f);
    fclose(f);
    if (got != expect) { fprintf(stderr, "%s: short read\n", path); exit(2); }
    return v;
}

int main() {
    const int N = 4096, K = 4096;
    const int64_t Kb = K / QK;
    const int64_t wb = (int64_t)N * Kb * sizeof(block_f8e4m3);
    const int64_t ab = Kb * sizeof(block_a_fp8);

    auto hW = slurp("golden_in_w.bin", wb);
    auto hA = slurp("golden_in_a.bin", ab);
    auto hG = slurp("golden_out.bin", (size_t)N * sizeof(float));
    const float* golden = (const float*)hG.data();

    char* dW; block_a_fp8* dA; float* dO;
    hipMalloc(&dW, wb); hipMalloc(&dA, ab); hipMalloc(&dO, (size_t)N * 4);
    hipMemcpy(dW, hW.data(), wb, hipMemcpyHostToDevice);
    hipMemcpy(dA, hA.data(), ab, hipMemcpyHostToDevice);

    agent_kernel<<<N, 64, 64 * sizeof(float)>>>(dW, dA, dO, Kb,
                                                Kb * sizeof(block_f8e4m3));
    hipError_t e = hipDeviceSynchronize();
    if (e != hipSuccess) { printf("LAUNCH FAILED: %s\n", hipGetErrorString(e)); return 1; }

    std::vector<float> got(N);
    hipMemcpy(got.data(), dO, (size_t)N * 4, hipMemcpyDeviceToHost);

    double worst = 0.0; int bad = 0;
    for (int i = 0; i < N; ++i) {
        if (!std::isfinite(got[i])) { bad++; worst = INFINITY; continue; }
        const double d = fabs((double)got[i] - (double)golden[i]);
        const double s = fabs((double)golden[i]);
        const double rel = s > 1e-6 ? d / s : d;
        if (rel > worst) worst = rel;
    }
    printf("rows=%d  non_finite=%d  max_rel_err=%.6e\n", N, bad, worst);
    printf("golden[0]=%.6f agent[0]=%.6f | golden[%d]=%.6f agent[%d]=%.6f\n",
           golden[0], got[0], N-1, golden[N-1], N-1, got[N-1]);
    return 0;
}
