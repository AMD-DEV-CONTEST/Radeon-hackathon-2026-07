#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Split-KV (Flash-Decoding) — Passo 2/2: funde os `max_chunks` resultados
// parciais (m_local, l_local, o_local) de flash_attention_split_kv_partial
// num único resultado final, com a correção de online-softmax padrão
// (rescala pelo máximo global antes de somar). 1 bloco por (batch, q_head).
//
// `corr[c] = exp(m_local[c] - m_global)` é computado uma vez por chunk e
// cacheado em LDS -- sem isso, cada uma das `head_dim` threads recalcularia
// a mesma exponencial para cada chunk (head_dim * max_chunks exponenciais
// redundantes por bloco).

extern "C" __global__ void flash_attention_split_kv_reduce_kernel(
    const float* __restrict__ partial_m,   // [batch, num_q_heads, max_chunks]
    const float* __restrict__ partial_l,   // [batch, num_q_heads, max_chunks]
    const float* __restrict__ partial_o,   // [batch, num_q_heads, max_chunks, head_dim]
    __half* __restrict__ output,           // [batch, num_q_heads, head_dim]
    int num_q_heads,
    int head_dim,
    int max_chunks
) {
    int batch_idx = blockIdx.x;
    int q_head = blockIdx.y;
    int tid = threadIdx.x;

    extern __shared__ float smem[];
    float* corr_sh = smem;                  // max_chunks floats
    __shared__ float m_global;
    __shared__ float l_global;

    int stat_base = (batch_idx * num_q_heads + q_head) * max_chunks;

    if (tid == 0) {
        float m = -1e30f;
        for (int c = 0; c < max_chunks; c++) {
            float mc = partial_m[stat_base + c];
            if (mc > m) m = mc;
        }
        m_global = m;
    }
    __syncthreads();

    for (int c = tid; c < max_chunks; c += blockDim.x) {
        corr_sh[c] = __expf(partial_m[stat_base + c] - m_global);
    }
    __syncthreads();

    if (tid == 0) {
        float l = 0.0f;
        for (int c = 0; c < max_chunks; c++) {
            l += partial_l[stat_base + c] * corr_sh[c];
        }
        l_global = fmaxf(l, 1e-20f);  // guarda contra divisão por zero (todo o histórico vazio, não deve ocorrer em produção)
    }
    __syncthreads();

    if (tid >= head_dim) return;

    int o_base = stat_base * head_dim;
    float o_acc = 0.0f;
    for (int c = 0; c < max_chunks; c++) {
        o_acc += partial_o[o_base + c * head_dim + tid] * corr_sh[c];
    }

    output[(batch_idx * num_q_heads + q_head) * head_dim + tid] = __float2half(o_acc / l_global);
}
