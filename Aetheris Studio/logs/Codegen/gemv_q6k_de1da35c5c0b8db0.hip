#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

// GEMV Q6_K in-kernel — design "No-Sync Direct Unpack" (Etapa C.3).
//
// Como no gemv_q4k: os pesos NÃO tocam a LDS e NÃO há __syncthreads dentro do
// loop K. Cada thread lê os bytes de que precisa direto da VRAM (cached),
// desempacota em registrador e acumula — deixando o agendador sobrepor memória
// e ALU (ILP). Ao contrário do Q4_K, o bloco de 210 bytes não é múltiplo de 16
// (rows desalinham), então NÃO se usa uint4; as leituras são escalares (byte/
// half), mas o ganho real veio de remover a sincronização, não da largura.
//
// Mapeamento: 1 bloco = 1 neurônio; block=64; cada thread desquantiza 4 pesos
// (i = tid + 64*ii, ii=0..3), sem staging cooperativo.
//
// LAYOUT Q6_K (espelha dequantizer.py, validado ~gguf):
//   [0:128]ql [128:192]qh [192:208]scales(int8) [208:210]d(fp16).
//   Por metade half∈{0,1}, l∈0..31, group∈0..3 (is_=l/16):
//     q = ( ql_nib | (((qh>>(2*group))&3)<<4) ) - 32 ; w = d*sc*q
//     ql byte = half*64 + (group&1? l+32 : l); nibble baixo se group<2 senão alto
//     qh byte = half*32 + l ; scale idx = half*8 + is_ + 2*group
//
// ABI de 8 args idêntica. block=64. in_features % 256 == 0.

extern "C" __global__ void gemv_q6k_kernel(
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
    int bs = blockDim.x;
    int lane = tid % warpSize;
    int warp = tid / warpSize;

    const __half* X = ((const __half*)input_ptr) + (size_t)m * in_features;
    int n_sb = in_features / 256;
    const unsigned char* row_q6k =
        ((const unsigned char*)weight_ptr) + (size_t)row * n_sb * 210;

    float acc = 0.0f;

    for (int sb = 0; sb < n_sb; sb++) {
        const unsigned char* blk = row_q6k + (size_t)sb * 210;
        float d = __half2float(*reinterpret_cast<const __half*>(blk + 208));
        const unsigned char* ql_all = blk;          // [0:128]
        const unsigned char* qh_all = blk + 128;    // [128:192]
        const signed char* sc_all = reinterpret_cast<const signed char*>(blk + 192);  // [192:208]

        #pragma unroll
        for (int ii = 0; ii < 4; ii++) {
            int i = tid + ii * 64;      // 0..255
            int half = i >> 7;
            int within = i & 127;
            int group = within >> 5;
            int l = within & 31;
            int is_ = l >> 4;

            const unsigned char* ql = ql_all + half * 64;
            const unsigned char* qh = qh_all + half * 32;
            const signed char* sc = sc_all + half * 8;

            int qlbyte = (group & 1) ? (l + 32) : l;
            int nib = (group < 2) ? (ql[qlbyte] & 0x0F) : (ql[qlbyte] >> 4);
            int qhbits = (qh[l] >> (group * 2)) & 3;
            int q = (nib | (qhbits << 4)) - 32;

            float w = d * (float)sc[is_ + 2 * group] * (float)q;
            acc = fmaf(w, __half2float(X[sb * 256 + i]), acc);
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
