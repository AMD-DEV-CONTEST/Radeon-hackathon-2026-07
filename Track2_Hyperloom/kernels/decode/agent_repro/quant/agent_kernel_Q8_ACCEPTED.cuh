__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb)
{
    extern __shared__ float sd[];
    int tid = threadIdx.x;
    int row = blockIdx.x;

    float thread_sum = 0.0f;

    for (int64_t c = tid; c < Kb; c += 64) {
        const block_lowbit* blk = &w[(int64_t)row * Kb + c];
        float s = 0.0f;
        const int8_t* qs = blk->qs;
        const float* act_c = &act[(size_t)c * 32];
        for (int k = 0; k < 32; ++k) {
            s += (float)qs[k] * act_c[k];
        }
        float scale = __half2float(blk->d);
        thread_sum += s * scale;
    }

    sd[tid] = thread_sum;
    __syncthreads();

    for (int stride = 32; stride > 0; stride >>= 1) {
        if (tid < stride) {
            sd[tid] += sd[tid + stride];
        }
        __syncthreads();
    }

    if (tid == 0) {
        dst[row] = sd[0];
    }
}
