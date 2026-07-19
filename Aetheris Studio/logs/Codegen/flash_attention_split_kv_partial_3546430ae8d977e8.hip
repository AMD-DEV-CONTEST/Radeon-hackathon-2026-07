#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Split-KV (Flash-Decoding) — Passo 1/2: atenção PARCIAL por chunk do KV
// cache. Motivação (medida, não suposição): o flash_attention_kernel
// original lança grid=(batch, num_q_heads, 1) -- em decode batch=1 isso é
// só 12 blocos, contra 32 CUs na RX 7600 (20 ociosas). O laço sobre as
// posições do KV cache é inteiramente SERIAL dentro de cada bloco, então o
// custo cresce linear com kv_offset sem nunca usar mais CUs -- confirmado:
// 6.9µs em kv_offset=1 vs 211µs em kv_offset=300 (1 camada isolada, ~0.7µs
// por posição extra, estável — não é bug de complexidade, é ocupância).
//
// Aqui o mesmo trabalho é dividido em blocos de SPLIT_KV_CHUNK_SIZE
// posições cada. Em kv_offset=250 isso sobe de 12 para 12 * ceil(251/32) =
// 12*8 = 96 blocos -- usa a GPU inteira em vez de 3/8 dela. Cada bloco
// roda EXATAMENTE o mesmo algoritmo de online softmax do kernel original,
// só que sobre uma fatia [chunk_start, chunk_end) em vez do histórico
// inteiro, e grava seus acumuladores parciais (m, l, o) num scratchpad em
// vez de normalizar e escrever a saída final -- a normalização e a fusão
// entre chunks acontecem no passo 2 (flash_attention_split_kv_reduce).
//
// Como o grid é fixado na captura do HIP Graph mas kv_offset cresce a cada
// token, `max_chunks` é dimensionado para o `context_length` runtime
// inteiro -- a maioria dos blocos em posições iniciais (kv_offset pequeno)
// cai no caminho "fora do alcance causal" abaixo e retorna quase
// imediatamente, gravando um estado neutro (m=-inf, l=0) que o passo de
// redução ignora corretamente.

#define SPLIT_KV_CHUNK_SIZE 32

extern "C" __global__ void flash_attention_split_kv_partial_kernel(
    const __half* __restrict__ q,          // [batch, num_q_heads, head_dim]
    const __half* __restrict__ k_cache,    // [batch, max_seq, num_kv_heads, head_dim]
    const __half* __restrict__ v_cache,    // [batch, max_seq, num_kv_heads, head_dim]
    float* __restrict__ partial_m,         // [batch, num_q_heads, max_chunks]
    float* __restrict__ partial_l,         // [batch, num_q_heads, max_chunks]
    float* __restrict__ partial_o,         // [batch, num_q_heads, max_chunks, head_dim]
    int num_q_heads,
    int num_kv_heads,
    int head_dim,
    float scale,
    const int* __restrict__ kv_cache_offset_ptr,  // array de `batch` ints
    int kv_batch_stride,                            // elementos __half entre sequências no K/V cache
    int max_chunks
) {
    int batch_idx = blockIdx.x;
    int q_head = blockIdx.y;
    int chunk_idx = blockIdx.z;
    int tid = threadIdx.x;
    if (tid >= head_dim) return;

    int kv_offset = kv_cache_offset_ptr[batch_idx];
    int total = kv_offset + 1;              // posições causais válidas: 0..kv_offset

    int stat_idx = (batch_idx * num_q_heads + q_head) * max_chunks + chunk_idx;
    int o_base = stat_idx * head_dim;

    int chunk_start = chunk_idx * SPLIT_KV_CHUNK_SIZE;
    if (chunk_start >= total) {
        // Chunk fora do histórico causal atual (comum no início da geração,
        // quando kv_offset ainda é pequeno mas max_chunks cobre todo o
        // context_length) -- grava estado neutro para a redução ignorar.
        if (tid == 0) {
            partial_m[stat_idx] = -1e30f;
            partial_l[stat_idx] = 0.0f;
        }
        partial_o[o_base + tid] = 0.0f;
        return;
    }
    int chunk_end = min(chunk_start + SPLIT_KV_CHUNK_SIZE, total);

    int gqa_ratio = num_q_heads / num_kv_heads;
    int kv_head = q_head / gqa_ratio;

    const __half* q_batch = q + (size_t)batch_idx * num_q_heads * head_dim;
    const __half* k_cache_batch = k_cache + (size_t)batch_idx * kv_batch_stride;
    const __half* v_cache_batch = v_cache + (size_t)batch_idx * kv_batch_stride;

    extern __shared__ float smem[];
    float* q_sh = smem;                     // head_dim floats
    float* red = smem + head_dim;           // head_dim floats

    int q_base = q_head * head_dim;
    q_sh[tid] = __half2float(q_batch[q_base + tid]);
    __syncthreads();

    // Online softmax idêntico ao kernel original, restrito a [chunk_start, chunk_end).
    float m = -1e30f;
    float l = 0.0f;
    float o = 0.0f;

    for (int j = chunk_start; j < chunk_end; j++) {
        int kbase = (j * num_kv_heads + kv_head) * head_dim;

        red[tid] = q_sh[tid] * __half2float(k_cache_batch[kbase + tid]);
        __syncthreads();
        for (int stride = head_dim >> 1; stride > 0; stride >>= 1) {
            if (tid < stride) red[tid] += red[tid + stride];
            __syncthreads();
        }
        float score = red[0] * scale;

        float m_new = fmaxf(m, score);
        float corr = __expf(m - m_new);
        float p = __expf(score - m_new);
        l = l * corr + p;

        float vd = __half2float(v_cache_batch[kbase + tid]);
        o = o * corr + p * vd;
        m = m_new;

        __syncthreads();
    }

    if (tid == 0) {
        partial_m[stat_idx] = m;
        partial_l[stat_idx] = l;
    }
    partial_o[o_base + tid] = o;
}
