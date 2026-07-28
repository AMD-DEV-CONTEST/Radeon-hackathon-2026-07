#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Split-KV (Flash-Decoding): escreve o K/V do token atual no cache, separado
// do cálculo de atenção. No design anterior (flash_attention.hip.template)
// essa escrita acontecia dentro do próprio kernel de atenção, redundante mas
// idempotente entre os blocos de cada head do mesmo grupo GQA. Agora que a
// atenção é dividida em múltiplos blocos por CHUNK do KV cache (para ocupar
// mais CUs), fazer a escrita lá exigiria uma guarda condicional em cada
// chunk-bloco para não escrever fora de posição -- mais simples e mais barato
// isolar num kernel próprio, disparado 1x por token (grid pequeno, O(1)).

extern "C" __global__ void kv_cache_append_kernel(
    const __half* __restrict__ k,          // [batch, num_kv_heads, head_dim] (token atual)
    const __half* __restrict__ v,          // [batch, num_kv_heads, head_dim] (token atual)
    __half* __restrict__ k_cache,          // [batch, max_seq, num_kv_heads, head_dim]
    __half* __restrict__ v_cache,          // [batch, max_seq, num_kv_heads, head_dim]
    int num_kv_heads,
    int head_dim,
    const int* __restrict__ kv_cache_offset_ptr,  // array de `batch` ints
    int kv_batch_stride                            // elementos __half entre sequências no K/V cache
) {
    int batch_idx = blockIdx.x;
    int kv_head = blockIdx.y;
    int tid = threadIdx.x;
    if (tid >= head_dim) return;

    int kv_offset = kv_cache_offset_ptr[batch_idx];

    const __half* k_batch = k + (size_t)batch_idx * num_kv_heads * head_dim;
    const __half* v_batch = v + (size_t)batch_idx * num_kv_heads * head_dim;
    __half* k_cache_batch = k_cache + (size_t)batch_idx * kv_batch_stride;
    __half* v_cache_batch = v_cache + (size_t)batch_idx * kv_batch_stride;

    int in_base = kv_head * head_dim;
    int cache_base = (kv_offset * num_kv_heads + kv_head) * head_dim;
    k_cache_batch[cache_base + tid] = k_batch[in_base + tid];
    v_cache_batch[cache_base + tid] = v_batch[in_base + tid];
}
