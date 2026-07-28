#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// GEMV Q4_K in-kernel — design "No-Sync Direct Unpack" (Etapa C.3), com
// cabeçalho de superbloco compartilhado via __shfl (Tese V6, Fase B1).
//
// Chave de performance: os pesos Q4_K NUNCA tocam a LDS e NÃO há __syncthreads
// dentro do loop K. Cada lane puxa seu próprio pedaço do super-bloco direto da
// VRAM para VGPR (global_load_b128), desempacota nos registradores e acumula.
// Como global_load e a ALU (bit-extract + fmaf) usam unidades diferentes da CU,
// o agendador da AMD sobrepõe a memória de uma iteração com o cálculo da
// anterior (ILP puro) — é aqui que a economia de banda do Q4 vira TPS.
//
// Mapeamento (1 bloco = 1 neurônio; block = 64 threads):
//   Cada thread possui um chunk de 16 bytes de qs (um uint4) = 32 pesos.
//   O super-bloco tem 128 bytes de qs = 8 chunks. tid -> (chunk = tid&7,
//   sbgroup = tid>>3): 8 super-blocos processados em paralelo por iteração.
//   Loop sobre sb_base += 8 até cobrir os n_sb super-blocos da linha.
//   Reduções: uma única __shfl_down + combinação inter-wavefront no fim.
//
// Cabeçalho compartilhado (Fase B1, ver docs/PERFORMANCE.md "Investigation:
// pushing past ~100 tok/s"): os 8 threads de um mesmo sbgroup (chunk=0..7,
// tid = sbgroup*8..sbgroup*8+7) processam o MESMO superbloco -- antes, cada
// um lia independentemente os 16 bytes de cabeçalho (d/dmin/scales),
// 8 leituras pequenas e redundantes por superbloco. Como sbgroup*8 é sempre
// múltiplo de 8 e 8 divide 32, esse grupo de 8 threads nunca cruza fronteira
// de wavefront (wave32) -- só o thread chunk==0 lê o cabeçalho inteiro num
// único uint4 alinhado, e os outros 7 recebem via __shfl (registrador ->
// registrador, sem tráfego de memória extra). Medido via
// tools/bench_gemv_q4k_bandwidth.py: gemv_q4k saturava só ~76.5% da banda
// alcançável por um kernel de mesma topologia sem esse desperdício.
//
// LAYOUT Q4_K (espelha dequantizer.py, validado ~gguf):
//   [0:2]d(fp16) [2:4]dmin(fp16) [4:16]scales(12) [16:144]qs(128).
//   4 grupos de 64 (mblk). qs[32*mblk .. +32]: nibble BAIXO -> peso
//   64*mblk+pos (sub 2*mblk); nibble ALTO -> peso 64*mblk+32+pos (sub 2*mblk+1).
//   w = (d*sc)*nibble - (dmin*min).  get_scale_min_k4 idêntico ao Python.
//
// ABI de 8 args idêntica. block=64. in_features % 256 == 0. Todos os offsets
// (row*n_sb*144, sb*144, 16, mblk*32, off16) são múltiplos de 16 -> uint4 OK.

// Extrai o byte `n` (0..11) do array de 12 bytes de scales, dado como 3
// palavras de 32 bits (h1/h2/h3 = bytes[4:8]/[8:12]/[12:16] do cabeçalho).
// Só SELECT (ternário entre registradores) + shift por quantidade variável
// -- ambos ALU puro, sem endereçamento -- de propósito: indexar `s[n]` como
// array local (mesmo com n em registrador) força o compilador a alocar
// scratch memory pro array, porque acesso dinâmico a memória local (ao
// contrário de global) não existe em hardware sem endereço real. Medido:
// trocar de array-indexing pra isto tirou ScratchSize de 32 bytes/lane
// (spill) para 0.
__device__ __forceinline__ unsigned int q4k_header_sbyte(unsigned int h1, unsigned int h2, unsigned int h3, int n) {
    unsigned int w = (n < 4) ? h1 : ((n < 8) ? h2 : h3);
    return (w >> (8 * (n & 3))) & 0xFFu;
}

extern "C" __global__ void gemv_q4k_kernel(
    const void* __restrict__ input_ptr,
    const void* __restrict__ weight_ptr,
    void* __restrict__ output_ptr,
    int batch,
    int seq_len,
    int in_features,
    int out_features,
    const void* __restrict__ bias_ptr,
    const void* __restrict__ residual_ptr,  // Epilogue Fusion: out += residual[row]
    float residual_scale                    // Granite: 0.22 (ver gemv_q8_0.hip.template). Default 1.0.
) {
    __shared__ float warp_sums[32];

    int row = blockIdx.x;
    int m = blockIdx.y;
    if (row >= out_features || m >= batch * seq_len) return;

    int tid = threadIdx.x;          // 0..63
    int bs = blockDim.x;            // = 64
    int lane = tid % warpSize;
    int warp = tid / warpSize;

    const __half* X = ((const __half*)input_ptr) + (size_t)m * in_features;
    int n_sb = in_features / 256;
    const unsigned char* row_q4k =
        ((const unsigned char*)weight_ptr) + (size_t)row * n_sb * 144;

    int chunk = tid & 7;            // 0..7  (qual uint4 de qs)
    int sbgroup = tid >> 3;         // 0..7  (qual super-bloco do grupo)
    int mblk = chunk >> 1;          // 0..3
    int off16 = (chunk & 1) * 16;   // 0 ou 16 (metade do bloco de 32 bytes)

    float acc = 0.0f;

    int header_src_lane = lane & ~7;  // posição (relativa ao wavefront) do chunk==0 deste sbgroup

    for (int sb_base = 0; sb_base < n_sb; sb_base += 8) {
        int sb = sb_base + sbgroup;
        if (sb >= n_sb) continue;

        const unsigned char* blk = row_q4k + (size_t)sb * 144;

        // Um único load de 16 bytes alinhado (chunk==0) em vez de 8 leituras
        // pequenas redundantes -- os outros 7 threads do sbgroup recebem via
        // __shfl (ver comentário do cabeçalho do arquivo). Palavras separadas
        // (h0/h1/h2/h3), não um uint4 struct, e sem tomar endereço de nada
        // além de h0 (só em offsets ESTÁTICOS 0/2, ver extração de d/dmin
        // abaixo) -- mantém tudo em registrador, ver q4k_header_sbyte acima.
        unsigned int h0 = 0, h1 = 0, h2 = 0, h3 = 0;
        if (chunk == 0) {
            uint4 hv = *reinterpret_cast<const uint4*>(blk);
            h0 = hv.x; h1 = hv.y; h2 = hv.z; h3 = hv.w;
        }
        h0 = __shfl((int)h0, header_src_lane);
        h1 = __shfl((int)h1, header_src_lane);
        h2 = __shfl((int)h2, header_src_lane);
        h3 = __shfl((int)h3, header_src_lane);

        float d = __half2float(*reinterpret_cast<const __half*>(&h0));
        float dmin = __half2float(*(reinterpret_cast<const __half*>(&h0) + 1));

        // get_scale_min_k4 para os 2 sub-blocos deste mblk (em registrador).
        int sub0 = 2 * mblk, sub1 = 2 * mblk + 1;
        int sc0, mn0, sc1, mn1;
        // sub0 = 2*mblk é sempre < 8; ramo j<4 vs j>=4:
        if (sub0 < 4) { sc0 = q4k_header_sbyte(h1, h2, h3, sub0) & 63; mn0 = q4k_header_sbyte(h1, h2, h3, sub0 + 4) & 63; }
        else { sc0 = (q4k_header_sbyte(h1, h2, h3, sub0 + 4) & 0x0F) | ((q4k_header_sbyte(h1, h2, h3, sub0 - 4) >> 6) << 4);
               mn0 = (q4k_header_sbyte(h1, h2, h3, sub0 + 4) >> 4) | ((q4k_header_sbyte(h1, h2, h3, sub0) >> 6) << 4); }
        if (sub1 < 4) { sc1 = q4k_header_sbyte(h1, h2, h3, sub1) & 63; mn1 = q4k_header_sbyte(h1, h2, h3, sub1 + 4) & 63; }
        else { sc1 = (q4k_header_sbyte(h1, h2, h3, sub1 + 4) & 0x0F) | ((q4k_header_sbyte(h1, h2, h3, sub1 - 4) >> 6) << 4);
               mn1 = (q4k_header_sbyte(h1, h2, h3, sub1 + 4) >> 4) | ((q4k_header_sbyte(h1, h2, h3, sub1) >> 6) << 4); }

        float d0 = d * (float)sc0, o0 = dmin * (float)mn0;
        float d1 = d * (float)sc1, o1 = dmin * (float)mn1;

        // Carga direta VRAM->VGPR do chunk de 16 bytes (32 pesos 4-bit).
        const uint4* qptr = reinterpret_cast<const uint4*>(blk + 16 + mblk * 32 + off16);
        uint4 qv = *qptr;
        const unsigned char* qb = reinterpret_cast<const unsigned char*>(&qv);

        int xbase = sb * 256 + 64 * mblk + off16;
        #pragma unroll
        for (int bl = 0; bl < 16; bl++) {
            int lo = qb[bl] & 0x0F;
            int hi = qb[bl] >> 4;
            float wlo = d0 * (float)lo - o0;
            float whi = d1 * (float)hi - o1;
            acc = fmaf(wlo, __half2float(X[xbase + bl]), acc);
            acc = fmaf(whi, __half2float(X[xbase + 32 + bl]), acc);
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
