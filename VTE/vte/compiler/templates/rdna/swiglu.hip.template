#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

extern "C" __global__ void swiglu_kernel(
    const __half* __restrict__ gate,  // Input temporário vindo do MatMul Gate
    const __half* __restrict__ up,    // Input temporário vindo do MatMul Up
    __half* __restrict__ out,         // Output intermediário para o DownProj
    int total_elements
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= total_elements) return;

    // Leitura em meia precisão convertida para FP32 para estabilidade matemática
    float g = __half2float(gate[idx]);
    float u = __half2float(up[idx]);

    // Aplicação da ativação SiLU estável: g * sigmoid(g)
    float sigmoid = 1.0f / (1.0f + expf(-g));
    float silu = g * sigmoid;

    // Gating elementwise: SiLU(Gate) * Up
    float res = silu * u;

    // Escrita segura convertendo de volta para FP16
    out[idx] = __float2half(res);
}
