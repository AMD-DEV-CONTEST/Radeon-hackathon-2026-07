#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>

#define BLOCK_SIZE {{ tile_size }}

extern "C" __global__ void rmsnorm_kernel(
    const __half* __restrict__ x,
    const __half* __restrict__ weight,
    __half* __restrict__ output,
    int hidden_size,
    float eps
) {
    int tid = threadIdx.x;
    int row = blockIdx.x;
    
    const __half* x_row = x + row * hidden_size;
    __half* out_row = output + row * hidden_size;
    
    float sum_sq = 0.0f;
    
    // OTIMIZACAO VTE: Carregamento Vetorial 128-bit (uint4)
    // uint4 tem 16 bytes. Cada __half tem 2 bytes. 
    // Portanto, carregamos 8x __half nativos de uma vez.
    // Isso alinha com a cache line da AMD e reduz a pressao no pipeline de memoria.
    int vec_hidden = hidden_size / 8;
    const uint4* x_row_vec = reinterpret_cast<const uint4*>(x_row);
    
    for (int i = tid; i < vec_hidden; i += blockDim.x) {
        uint4 vals = x_row_vec[i];
        
        // Reinterpreta os 4 words de 32-bit em 4 pares de __half2
        __half2 h1 = *reinterpret_cast<__half2*>(&vals.x);
        __half2 h2 = *reinterpret_cast<__half2*>(&vals.y);
        __half2 h3 = *reinterpret_cast<__half2*>(&vals.z);
        __half2 h4 = *reinterpret_cast<__half2*>(&vals.w);
        
        sum_sq += (float)h1.x * (float)h1.x + (float)h1.y * (float)h1.y;
        sum_sq += (float)h2.x * (float)h2.x + (float)h2.y * (float)h2.y;
        sum_sq += (float)h3.x * (float)h3.x + (float)h3.y * (float)h3.y;
        sum_sq += (float)h4.x * (float)h4.x + (float)h4.y * (float)h4.y;
    }
    
    // Lidar com o resto (se hidden_size não for divisível por 8)
    for (int i = vec_hidden * 8 + tid; i < hidden_size; i += blockDim.x) {
        float val = (float)x_row[i];
        sum_sq += val * val;
    }
    
    // 2. Redução em Árvore na Wavefront (Nativo AMD)
    #pragma unroll
    for (int offset = warpSize / 2; offset > 0; offset /= 2) {
        sum_sq += __shfl_down(sum_sq, offset);
    }
    
    // 3. Sincronização via LDS (Shared Memory)
    __shared__ float shared_sum[32]; 
    int lane = tid % warpSize;
    int wid = tid / warpSize;
    
    if (lane == 0) shared_sum[wid] = sum_sq;
    __syncthreads();
    
    if (wid == 0) {
        int num_waves = (blockDim.x + warpSize - 1) / warpSize;
        float val = (lane < num_waves) ? shared_sum[lane] : 0.0f;
        #pragma unroll
        for (int offset = warpSize / 2; offset > 0; offset /= 2) {
            val += __shfl_down(val, offset);
        }
        if (lane == 0) shared_sum[0] = val;
    }
    __syncthreads();
    
    // 4. Escala e Escrita Vetorial
    float mean_sq = shared_sum[0] / (float)hidden_size;
    float rms_inv = rsqrtf(mean_sq + eps);
    
    uint4* out_row_vec = reinterpret_cast<uint4*>(out_row);
    const uint4* weight_vec = reinterpret_cast<const uint4*>(weight);
    
    for (int i = tid; i < vec_hidden; i += blockDim.x) {
        uint4 x_vals = x_row_vec[i];
        uint4 w_vals = weight_vec[i];
        
        __half2* xh1 = reinterpret_cast<__half2*>(&x_vals.x);
        __half2* xh2 = reinterpret_cast<__half2*>(&x_vals.y);
        __half2* xh3 = reinterpret_cast<__half2*>(&x_vals.z);
        __half2* xh4 = reinterpret_cast<__half2*>(&x_vals.w);
        
        const __half2* wh1 = reinterpret_cast<const __half2*>(&w_vals.x);
        const __half2* wh2 = reinterpret_cast<const __half2*>(&w_vals.y);
        const __half2* wh3 = reinterpret_cast<const __half2*>(&w_vals.z);
        const __half2* wh4 = reinterpret_cast<const __half2*>(&w_vals.w);
        
        // Multiplica, aplica o RMS e salva
        xh1->x = __float2half((float)xh1->x * rms_inv * (float)wh1->x);
        xh1->y = __float2half((float)xh1->y * rms_inv * (float)wh1->y);
        
        xh2->x = __float2half((float)xh2->x * rms_inv * (float)wh2->x);
        xh2->y = __float2half((float)xh2->y * rms_inv * (float)wh2->y);
        
        xh3->x = __float2half((float)xh3->x * rms_inv * (float)wh3->x);
        xh3->y = __float2half((float)xh3->y * rms_inv * (float)wh3->y);
        
        xh4->x = __float2half((float)xh4->x * rms_inv * (float)wh4->x);
        xh4->y = __float2half((float)xh4->y * rms_inv * (float)wh4->y);
        
        out_row_vec[i] = x_vals; // Escrita vetorial de volta para VRAM
    }
    
    // Resto da escrita
    for (int i = vec_hidden * 8 + tid; i < hidden_size; i += blockDim.x) {
        float val = (float)x_row[i];
        float w = (float)weight[i];
        out_row[i] = __float2half(val * rms_inv * w);
    }
}
