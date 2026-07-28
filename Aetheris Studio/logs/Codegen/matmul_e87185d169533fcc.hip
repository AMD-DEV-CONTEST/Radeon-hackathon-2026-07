#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Cabe o maior in_features usado no modelo (feed_forward_length=8960); para
// embedding_length=1536 (a maioria dos matmuls) sobra espaço, sem problema.
#define MATMUL_SHARED_MAX 8960

extern "C" __global__ void matmul_kernel(
    const void* input_ptr,
    const void* weight_ptr,
    void* output_ptr,
    int batch,
    int seq_len,
    int in_features,
    int out_features,
    const void* bias_ptr,      // opcional: nullptr quando a projeção não tem bias
    const void* residual_ptr,  // Epilogue Fusion: out += residual[row] (nullptr = sem)
    float residual_scale       // Granite: 0.22, escala a SAÍDA deste sub-bloco
                                // ANTES de somar ao residual (confirmado em
                                // granite.cpp: ggml_scale(cur) antes do
                                // ggml_add(cur, inpSA/ffn_inp)). Default 1.0.
) {
    // A linha de entrada (A_row) é IDÊNTICA para todas as threads deste bloco
    // (todas computam a mesma linha m, colunas n diferentes). Sem isso, cada
    // uma das até ~150 mil threads do LM head releria os mesmos 1536+
    // elementos direto da VRAM global. Carregando uma vez para a LDS
    // (memória compartilhada do bloco) e reaproveitando entre as 256 threads
    // do bloco, corta esse tráfego de memória global em ~256x.
    __shared__ __half A_shared[MATMUL_SHARED_MAX];

    int n = blockIdx.x * blockDim.x + threadIdx.x;
    int m = blockIdx.y; // Assumindo blockDim.y == 1
    int tid = threadIdx.x;

    // Checagem uniforme por bloco (todas as threads do bloco compartilham o
    // mesmo blockIdx.y) — seguro retornar aqui, antes do __syncthreads().
    if (m >= batch * seq_len) return;

    // Pesos já chegam dequantizados para FP16 puro (weight_loader.py converte
    // Q4_K/Q6_K/F32 -> FP16 no host antes do upload), então o layout do peso
    // é simplesmente (out_features, in_features) em FP16 contíguo.
    const __half* A_row = ((const __half*)input_ptr) + m * in_features;

    // Carregamento cooperativo: cada thread carrega uma fatia de A_row.
    for (int i = tid; i < in_features; i += blockDim.x) {
        A_shared[i] = A_row[i];
    }
    __syncthreads();

    // Checagem divergente entre threads — só é segura DEPOIS do
    // __syncthreads() acima, para que nenhuma thread saia antes da barreira.
    if (n >= out_features) return;

    const __half* W_row = ((const __half*)weight_ptr) + n * in_features;

    float sum = 0.0f;
    for (int k = 0; k < in_features; k++) {
        sum += __half2float(A_shared[k]) * __half2float(W_row[k]);
    }

    // Qwen2.5 aplica bias em q_proj/k_proj/v_proj (o bias de K chega a
    // magnitude ~300 — omiti-lo destrói a atenção). Projeções sem bias
    // (o_proj, gate, up, down, lm_head) passam bias_ptr = nullptr.
    if (bias_ptr != nullptr) {
        sum += __half2float(((const __half*)bias_ptr)[n]);
    }
    sum *= residual_scale;
    if (residual_ptr != nullptr) {
        sum += __half2float(((const __half*)residual_ptr)[m * out_features + n]);
    }

    ((__half*)output_ptr)[m * out_features + n] = __float2half(sum);
}
