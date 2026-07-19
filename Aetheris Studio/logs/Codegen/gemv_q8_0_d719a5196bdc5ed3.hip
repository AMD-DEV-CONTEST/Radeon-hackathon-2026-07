#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// GEMV Q8_0 in-kernel — mesmo design "No-Sync Direct Unpack" de gemv_q4k/
// gemv_q6k (Etapa C.3): os pesos NÃO tocam a LDS e não há __syncthreads
// dentro do loop de acumulação — só no final, para combinar as somas
// parciais entre wavefronts (mesmo padrão dos outros dois).
//
// Q8_0 é o formato de quantização MAIS SIMPLES dos três: bloco de 32
// elementos / 34 bytes (2 bytes de escala fp16 `d` + 32 valores int8 `q[i]`,
// simétrico em torno de zero) — sem hierarquia de min/escala-de-escala como
// Q4_K/Q6_K. Layout confirmado empiricamente contra os bytes reais do GGUF
// do Granite (gguf.GGUFReader, comparando contra hipóteses concorrentes de
// tamanho), não a partir de documentação de terceiros:
//   w[i] = d * q[i]
//
// Mapeamento: cada thread processa uma fatia estrided de blocos de 32
// elementos (tid, tid+blockDim.x, tid+2*blockDim.x, ...), igual ao "1 bloco
// = 1 unidade de trabalho" do gemv_q6k, mas sem meio-bloco/nibble — aqui um
// bloco Q8_0 já é uma unidade completa e independente.
//
// ABI de 9 args idêntica a gemv_q4k/gemv_q6k. block=64. in_features % 32 == 0
// (block Q8_0 = 32 elementos; Granite: hidden=2560, ffn=8192, ambos múltiplos
// de 32).

extern "C" __global__ void gemv_q8_0_kernel(
    const void* __restrict__ input_ptr,
    const void* __restrict__ weight_ptr,
    void* __restrict__ output_ptr,
    int batch,
    int seq_len,
    int in_features,
    int out_features,
    const void* __restrict__ bias_ptr,
    const void* __restrict__ residual_ptr,  // Epilogue Fusion: out += residual[row]
    float residual_scale                    // Granite: 0.22 -- escala a SAÍDA
                                             // deste sub-bloco ANTES de somar ao
                                             // residual (confirmado em
                                             // granite.cpp: ggml_scale(cur) antes
                                             // do ggml_add(cur, inpSA/ffn_inp),
                                             // NÃO o residual em si). Default 1.0.
) {
    __shared__ float warp_sums[32];

    int row = blockIdx.x;
    int m = blockIdx.y;
    if (row >= out_features || m >= batch * seq_len) return;

    int tid = threadIdx.x;
    int bs = blockDim.x;
    int lane = tid % warpSize;
    int warp = tid / warpSize;

    const __half* X = ((const __half*)input_ptr) + (size_t)m * in_features;
    int n_blk = in_features / 32;
    const unsigned char* row_q8 =
        ((const unsigned char*)weight_ptr) + (size_t)row * n_blk * 34;

    float acc = 0.0f;

    for (int b = tid; b < n_blk; b += bs) {
        const unsigned char* blk = row_q8 + (size_t)b * 34;
        float d = __half2float(*reinterpret_cast<const __half*>(blk));
        const signed char* q = reinterpret_cast<const signed char*>(blk + 2);

        int xbase = b * 32;
        #pragma unroll
        for (int i = 0; i < 32; i++) {
            float w = d * (float)q[i];
            acc = fmaf(w, __half2float(X[xbase + i]), acc);
        }
    }

    for (int off = warpSize / 2; off > 0; off >>= 1) {
        acc += __shfl_down(acc, off);
    }
    if (lane == 0) warp_sums[warp] = acc;
    __syncthreads();

    if (tid == 0) {
        int nwarps = (bs + warpSize - 1) / warpSize;
        float total = 0.0f;
        for (int w = 0; w < nwarps; w++) total += warp_sums[w];
        if (bias_ptr != nullptr) {
            total += __half2float(((const __half*)bias_ptr)[row]);
        }
        total *= residual_scale;
        if (residual_ptr != nullptr) {
            total += __half2float(((const __half*)residual_ptr)[(size_t)m * out_features + row]);
        }
        ((__half*)output_ptr)[(size_t)m * out_features + row] = __float2half(total);
    }
}
