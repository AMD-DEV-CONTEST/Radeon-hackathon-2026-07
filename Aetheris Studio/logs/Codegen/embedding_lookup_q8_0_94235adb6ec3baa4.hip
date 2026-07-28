#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Embedding lookup para token_embd.weight cru em Q8_0 (Granite, tied
// embeddings) -- análogo a embedding_lookup_q6k, mas com o layout mais
// simples do Q8_0: bloco de 32 elementos / 34 bytes (2 bytes fp16 de escala
// `d` + 32 int8 `q[i]`, simétrico), sem hierarquia de min/escala.
//
// Com embeddings amarrados (sem output.weight separado no GGUF), o mesmo
// tensor token_embd.weight serve de peso do lm_head (via gemv_q8_0) E do
// embedding lookup (aqui) -- mantendo-o cru em Q8_0 evita uma cópia FP16
// duplicada residente em VRAM (mesmo raciocínio do Q6_K tied embedding do
// Qwen).

extern "C" __global__ void embedding_lookup_q8_0_kernel(
    const int* __restrict__ token_ids,       // (seq_len,)
    const void* __restrict__ embed_weight,   // Q8_0 cru (vocab_size linhas)
    __half* __restrict__ output,             // (seq_len, hidden_size) FP16
    int seq_len,
    int hidden_size,
    float embedding_scale                    // Granite: 12.0 -- multiplica a
                                              // saída do lookup ANTES da camada 0
                                              // (confirmado em llama-graph.cpp:
                                              // build_inp_embd, não suposto).
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total_elements = seq_len * hidden_size;
    if (idx >= total_elements) return;

    int s = idx / hidden_size;
    int d = idx % hidden_size;
    int token_id = token_ids[s];

    int n_blk = hidden_size / 32;
    const unsigned char* row = ((const unsigned char*)embed_weight) + (size_t)token_id * n_blk * 34;

    int b = d / 32;
    int i = d % 32;
    const unsigned char* blk = row + (size_t)b * 34;

    float dscale = __half2float(*reinterpret_cast<const __half*>(blk));
    const signed char* q = reinterpret_cast<const signed char*>(blk + 2);

    float w = dscale * (float)q[i];
    output[idx] = __float2half(w * embedding_scale);
}
