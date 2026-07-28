#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Fase I (Batched Decode): blockIdx.y = batch_idx explícito (grid vira
// (grid_x, batch, 1)). Q/K recebem stride de batch (max_q/k_elements por
// sequência, tamanho já usado para batch=1). kv_cache_offset_ptr vira um
// array de `batch` ints — cada sequência do batch pode estar em uma posição
// diferente do KV cache (mesmo em lockstep isso evita uma classe de bug
// quando prompts tiverem tamanhos diferentes no futuro).
//
// cos_cache/sin_cache NÃO recebem stride de batch: são uma tabela GLOBAL
// read-only indexada por posição absoluta, compartilhada entre todas as
// sequências do batch (cada uma consulta a mesma tabela em posições
// potencialmente diferentes via kv_cache_offset_ptr[batch_idx], mas a
// tabela em si não tem cópia por sequência).

extern "C" __global__ void rope_kernel(
    __half* __restrict__ q,
    __half* __restrict__ k,
    const __half* __restrict__ cos_cache,
    const __half* __restrict__ sin_cache,
    int seq_len,
    int num_q_heads,
    int num_kv_heads,
    int head_dim,
    const int* __restrict__ kv_cache_offset_ptr,  // agora array de `batch` ints
    int rope_type,  // 0 = NEOX/split-half (Qwen2); 1 = NORM/intercalado
                    // (Granite); 2 = NEOX parcial (Qwen3.5 -- ver abaixo).
    int rotary_dim  // canais realmente rotacionados (rope_type==2 apenas;
                    // ignorado nos outros dois tipos, que sempre giram
                    // head_dim inteiro). Qwen3.5: 64 de um head_dim=256
                    // (partial_rotary_factor=0.25, confirmado no código-
                    // fonte real do HF, modeling_qwen3_5.py) -- os canais
                    // de rotary_dim até head_dim-1 passam sem rotação
                    // nenhuma. cos_cache/sin_cache têm stride rotary_dim
                    // por posição neste modo (não head_dim).
) {
    int batch_idx = blockIdx.y;

    int max_q_elements = seq_len * num_q_heads * head_dim;
    int max_k_elements = seq_len * num_kv_heads * head_dim;

    // Ponteiros deslocados para o início da sequência deste item do batch.
    __half* q_b = q + (size_t)batch_idx * max_q_elements;
    __half* k_b = k + (size_t)batch_idx * max_k_elements;
    int kv_cache_offset = kv_cache_offset_ptr[batch_idx];

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int half_dim = head_dim / 2;

    // Processa Q
    if (idx < max_q_elements) {
        int token_idx = idx / (num_q_heads * head_dim);
        int absolute_pos = kv_cache_offset + token_idx;
        int head_offset = idx % head_dim;

        if (rope_type == 1) {
            if ((head_offset & 1) == 0) {
                int i = head_offset / 2;
                float x0 = __half2float(q_b[idx]);
                float x1 = __half2float(q_b[idx + 1]);
                float c = __half2float(cos_cache[absolute_pos * head_dim + i]);
                float s = __half2float(sin_cache[absolute_pos * head_dim + i]);
                q_b[idx] = __float2half(x0 * c - x1 * s);
                q_b[idx + 1] = __float2half(x0 * s + x1 * c);
            }
        } else if (rope_type == 2) {
            // NEOX split-half, mas só dentro dos primeiros `rotary_dim`
            // canais -- de rotary_dim até head_dim-1 fica intocado (nem
            // lido nem escrito aqui). half_rot = rotary_dim/2: canal j
            // (j < half_rot) pareia com j+half_rot, exatamente como o
            // rope_type==0, só que restrito a essa janela menor.
            int half_rot = rotary_dim / 2;
            if (head_offset < half_rot) {
                float q1 = __half2float(q_b[idx]);
                float q2 = __half2float(q_b[idx + half_rot]);
                float cos_val = __half2float(cos_cache[absolute_pos * rotary_dim + head_offset]);
                float sin_val = __half2float(sin_cache[absolute_pos * rotary_dim + head_offset]);
                q_b[idx] = __float2half(q1 * cos_val - q2 * sin_val);
                q_b[idx + half_rot] = __float2half(q1 * sin_val + q2 * cos_val);
            }
        } else if (head_offset < half_dim) {
            float q1 = __half2float(q_b[idx]);
            float q2 = __half2float(q_b[idx + half_dim]);

            // O cache (RoPECacheBuilder) grava head_dim elementos por posição
            // (as duas metades são idênticas, padrão "sliced"/rotate-half) —
            // o stride de indexação aqui PRECISA ser head_dim, não half_dim,
            // senão cada posição > 0 lê os ângulos da posição/deslocamento
            // errado, misturando cos/sin de posições adjacentes e destruindo
            // a informação posicional para qualquer token além do primeiro.
            float cos_val = __half2float(cos_cache[absolute_pos * head_dim + head_offset]);
            float sin_val = __half2float(sin_cache[absolute_pos * head_dim + head_offset]);

            q_b[idx] = __float2half(q1 * cos_val - q2 * sin_val);
            q_b[idx + half_dim] = __float2half(q1 * sin_val + q2 * cos_val);
        }
    }

    // Processa K
    if (idx < max_k_elements) {
        int token_idx = idx / (num_kv_heads * head_dim);
        int absolute_pos = kv_cache_offset + token_idx;
        int head_offset = idx % head_dim;

        if (rope_type == 1) {
            if ((head_offset & 1) == 0) {
                int i = head_offset / 2;
                float x0 = __half2float(k_b[idx]);
                float x1 = __half2float(k_b[idx + 1]);
                float c = __half2float(cos_cache[absolute_pos * head_dim + i]);
                float s = __half2float(sin_cache[absolute_pos * head_dim + i]);
                k_b[idx] = __float2half(x0 * c - x1 * s);
                k_b[idx + 1] = __float2half(x0 * s + x1 * c);
            }
        } else if (rope_type == 2) {
            int half_rot = rotary_dim / 2;
            if (head_offset < half_rot) {
                float k1 = __half2float(k_b[idx]);
                float k2 = __half2float(k_b[idx + half_rot]);
                float cos_val = __half2float(cos_cache[absolute_pos * rotary_dim + head_offset]);
                float sin_val = __half2float(sin_cache[absolute_pos * rotary_dim + head_offset]);
                k_b[idx] = __float2half(k1 * cos_val - k2 * sin_val);
                k_b[idx + half_rot] = __float2half(k1 * sin_val + k2 * cos_val);
            }
        } else if (head_offset < half_dim) {
            float k1 = __half2float(k_b[idx]);
            float k2 = __half2float(k_b[idx + half_dim]);

            float cos_val = __half2float(cos_cache[absolute_pos * head_dim + head_offset]);
            float sin_val = __half2float(sin_cache[absolute_pos * head_dim + head_offset]);

            k_b[idx] = __float2half(k1 * cos_val - k2 * sin_val);
            k_b[idx + half_dim] = __float2half(k1 * sin_val + k2 * cos_val);
        }
    }
}
