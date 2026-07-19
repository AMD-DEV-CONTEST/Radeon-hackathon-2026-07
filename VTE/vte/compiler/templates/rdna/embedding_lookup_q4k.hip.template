#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// Embedding lookup para token_embd.weight cru em Q4_K (suporte ao Qwen2.5 7B).
//
// O Qwen2.5 7B guarda token_embd.weight em Q4_K (vocab=152064 x hidden=3584):
// dequantizar para FP16 no load custaria ~1GB de VRAM residente (o modelo
// inteiro tem só ~4.4GB no arquivo). Mantendo cru em Q4_K e dequantizando a
// linha do token sob demanda aqui, o mesmo tensor ocupa ~306MB. Ao contrário
// do Qwen2.5 1.5B (token_embd em Q6_K e TIED ao lm_head), no 7B o token_embd
// só serve ao embedding lookup (output.weight é um tensor Q6_K separado), então
// este kernel é o único consumidor -- custo trivial (1 linha de hidden_size por
// posição, 1x por token, fora do caminho quente).
//
// Mesma matemática de desquant Q4_K do gemv_q4k (espelha dequantizer.py,
// validado ~gguf), mas sem produto interno/redução: cada thread reconstrói e
// escreve seu próprio elemento.
//
// LAYOUT Q4_K (super-bloco de 256 pesos, 144 bytes):
//   [0:2]d(fp16) [2:4]dmin(fp16) [4:16]scales(12) [16:144]qs(128).
//   4 grupos de 64 (mblk). Dentro do mblk, os 32 primeiros pesos usam o nibble
//   BAIXO e os 32 seguintes o nibble ALTO do MESMO byte qs[32*mblk + pos].
//   sub-bloco = 2*mblk (nibble baixo) ou 2*mblk+1 (alto). get_scale_min_k4
//   idêntico ao Python/gemv_q4k.

extern "C" __global__ void embedding_lookup_q4k_kernel(
    const int* __restrict__ token_ids,       // (seq_len,)
    const void* __restrict__ embed_weight,   // Q4_K cru (vocab_size linhas)
    __half* __restrict__ output,             // (seq_len, hidden_size) FP16
    int seq_len,
    int hidden_size,
    float embedding_scale                    // Default 1.0 (Qwen não usa).
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total_elements = seq_len * hidden_size;
    if (idx >= total_elements) return;

    int s = idx / hidden_size;
    int d = idx % hidden_size;
    int token_id = token_ids[s];

    int n_sb = hidden_size / 256;
    const unsigned char* row = ((const unsigned char*)embed_weight) + (size_t)token_id * n_sb * 144;

    int sb = d / 256;
    int i = d % 256;              // 0..255, posição dentro do super-bloco
    const unsigned char* blk = row + (size_t)sb * 144;

    float dscale = __half2float(*reinterpret_cast<const __half*>(blk + 0));
    float dmin = __half2float(*reinterpret_cast<const __half*>(blk + 2));
    const unsigned char* sc_bytes = blk + 4;

    int mblk = i >> 6;           // 0..3
    int local = i & 63;          // 0..63
    int pos = local & 31;        // 0..31 (byte dentro do bloco de 32)
    int is_high = local >> 5;    // 0 = nibble baixo, 1 = alto
    int sub = 2 * mblk + is_high;

    // get_scale_min_k4(sub, sc_bytes) -- idêntico a gemv_q4k/dequantizer.py.
    int sc, mn;
    if (sub < 4) {
        sc = sc_bytes[sub] & 63;
        mn = sc_bytes[sub + 4] & 63;
    } else {
        sc = (sc_bytes[sub + 4] & 0x0F) | ((sc_bytes[sub - 4] >> 6) << 4);
        mn = (sc_bytes[sub + 4] >> 4) | ((sc_bytes[sub] >> 6) << 4);
    }

    const unsigned char* qs = blk + 16;
    unsigned char byte = qs[32 * mblk + pos];
    int nibble = is_high ? (byte >> 4) : (byte & 0x0F);

    float w = dscale * (float)sc * (float)nibble - dmin * (float)mn;
    output[idx] = __float2half(w * embedding_scale);
}
