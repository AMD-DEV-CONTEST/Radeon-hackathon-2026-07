// golden_gen.cu — produce the reference the agent will be graded against.
//
// Runs the HUMAN-WRITTEN fp8 kernel (decode_fp8.hip's decode_fp8_dot4) on fixed
// seeds, and writes the inputs and the outputs to disk. The agent never sees
// this file, the kernel it contains, or the .bin it produces — it only receives
// a written specification of the data format and the maths.
//
// This is the layer-5 rig: the harness owns the reference, so "the agent's
// kernel agrees with the agent's own idea of correct" is not something that can
// happen here.
//
//   hipcc --offload-arch=gfx1201 -O3 golden_gen.cu -o golden_gen && ./golden_gen

#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <random>

#define QK 32
struct block_f8e4m3 { __half  d;  uint8_t qs[QK]; };
struct block_a_fp8  { __half2 ds; uint8_t qs[QK]; };

// The committed kernel, verbatim from decode_fp8.hip.
__global__ void golden_kernel(const char* __restrict__ vw,
                              const block_a_fp8* __restrict__ act,
                              float* __restrict__ dst,
                              int64_t Kb, int64_t stride)
{
    const int64_t row = blockIdx.x;
    const int     tid = threadIdx.x;
    float partial = 0.0f;
    const block_f8e4m3* wrow = (const block_f8e4m3*)(vw + row * stride);
    for (int64_t c = tid; c < Kb; c += blockDim.x) {
        const uint32_t* wq = (const uint32_t*)wrow[c].qs;
        const uint32_t* aq = (const uint32_t*)act[c].qs;
        float sumf = 0.0f;
        #pragma unroll
        for (int i = 0; i < QK / 4; ++i)
            sumf = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], sumf);
        partial += sumf * __half2float(wrow[c].d) * __low2float(act[c].ds);
    }
    extern __shared__ float sd[];
    sd[tid] = partial;
    __syncthreads();
    for (int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (tid < s) sd[tid] += sd[tid + s];
        __syncthreads();
    }
    if (tid == 0) dst[row] = sd[0];
}

static uint8_t finite_e4m3(std::mt19937& rng) {
    std::uniform_int_distribution<int> b(0, 255);
    uint8_t v;
    do { v = (uint8_t)b(rng); } while ((v & 0x7F) == 0x7F);   // no NaN encodings
    return v;
}

int main() {
    const int N = 4096, K = 4096;
    const int64_t Kb = K / QK, wb = (int64_t)N * Kb * sizeof(block_f8e4m3);

    std::mt19937 rng(20260806);                 // fixed seed: reproducible
    std::vector<block_f8e4m3> hW((size_t)N * Kb);
    std::vector<block_a_fp8>  hA(Kb);
    for (auto& x : hW) { x.d  = __float2half(0.01f);     for (auto& q : x.qs) q = finite_e4m3(rng); }
    for (auto& x : hA) { x.ds = __float2half2_rn(0.02f); for (auto& q : x.qs) q = finite_e4m3(rng); }

    char* dW; block_a_fp8* dA; float* dO;
    hipMalloc(&dW, wb); hipMalloc(&dA, Kb * sizeof(block_a_fp8)); hipMalloc(&dO, (size_t)N * 4);
    hipMemcpy(dW, hW.data(), wb, hipMemcpyHostToDevice);
    hipMemcpy(dA, hA.data(), Kb * sizeof(block_a_fp8), hipMemcpyHostToDevice);
    golden_kernel<<<N, 64, 64 * sizeof(float)>>>(dW, dA, dO, Kb, Kb * sizeof(block_f8e4m3));
    hipDeviceSynchronize();

    std::vector<float> out(N);
    hipMemcpy(out.data(), dO, (size_t)N * 4, hipMemcpyDeviceToHost);

    FILE* f = fopen("golden_in_w.bin","wb");  fwrite(hW.data(), sizeof(block_f8e4m3), hW.size(), f); fclose(f);
    f = fopen("golden_in_a.bin","wb");        fwrite(hA.data(), sizeof(block_a_fp8),  hA.size(), f); fclose(f);
    f = fopen("golden_out.bin","wb");         fwrite(out.data(), sizeof(float), out.size(), f);      fclose(f);
    printf("golden: N=%d K=%d  first=%.6f last=%.6f\n", N, K, out[0], out[N-1]);
    return 0;
}
