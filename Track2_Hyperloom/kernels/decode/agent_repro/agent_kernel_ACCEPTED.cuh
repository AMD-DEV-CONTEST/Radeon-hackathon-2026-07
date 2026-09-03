__global__ void agent_kernel(const char* __restrict__ vw,
                             const block_a_fp8* __restrict__ act,
                             float* __restrict__ dst,
                             int64_t Kb, int64_t stride) {
    extern __shared__ float sd[];
    int tid = threadIdx.x;
    int row = blockIdx.x;

    float thread_sum = 0.0f;

    const block_f8e4m3* row_weights = (const block_f8e4m3*)(vw + row * stride);

    for (int64_t c = tid; c < Kb; c += 64) {
        const block_f8e4m3* wblk = &row_weights[c];
        const block_a_fp8* ablk = &act[c];

        const uint32_t* wq = (const uint32_t*)wblk->qs;
        const uint32_t* aq = (const uint32_t*)ablk->qs;

        float s = 0.0f;
        for (int i = 0; i < 8; ++i) {
            s = __builtin_amdgcn_dot4_f32_fp8_fp8(wq[i], aq[i], s);
        }

        float scale_w = __half2float(wblk->d);
        float scale_a = __low2float(ablk->ds);

        thread_sum += s * scale_w * scale_a;
    }

    sd[tid] = thread_sum;
    __syncthreads();

    for (int stride_sh = 32; stride_sh > 0; stride_sh >>= 1) {
        if (tid < stride_sh) {
            sd[tid] += sd[tid + stride_sh];
        }
        __syncthreads();
    }

    if (tid == 0) {
        dst[row] = sd[0];
    }
}
