__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb)
{
    extern __shared__ float sd[];

    int tid = threadIdx.x;
    int row = blockIdx.x;

    float thread_sum = 0.0f;
    for (int64_t c = tid; c < Kb; c += 64) {
        block_lowbit w_block = w[(int64_t)row * Kb + c];
        float s = 0.0f;
        const uint8_t* qs = w_block.qs;
        for (int b = 0; b < 16; ++b) {
            uint8_t byte = qs[b];
            float a0 = act[c * 128 + b * 8 + 0];
            float a1 = act[c * 128 + b * 8 + 1];
            float a2 = act[c * 128 + b * 8 + 2];
            float a3 = act[c * 128 + b * 8 + 3];
            float a4 = act[c * 128 + b * 8 + 4];
            float a5 = act[c * 128 + b * 8 + 5];
            float a6 = act[c * 128 + b * 8 + 6];
            float a7 = act[c * 128 + b * 8 + 7];

            if (byte & (1 << 0)) s += a0; else s -= a0;
            if (byte & (1 << 1)) s += a1; else s -= a1;
            if (byte & (1 << 2)) s += a2; else s -= a2;
            if (byte & (1 << 3)) s += a3; else s -= a3;
            if (byte & (1 << 4)) s += a4; else s -= a4;
            if (byte & (1 << 5)) s += a5; else s -= a5;
            if (byte & (1 << 6)) s += a6; else s -= a6;
            if (byte & (1 << 7)) s += a7; else s -= a7;
        }
        thread_sum += s * __half2float(w_block.d);
    }

    sd[tid] = thread_sum;
    __syncthreads();

    if (tid < 32) sd[tid] += sd[tid + 32];
    __syncthreads();

    if (tid < 16) sd[tid] += sd[tid + 16];
    __syncthreads();

    if (tid < 8) sd[tid] += sd[tid + 8];
    __syncthreads();

    if (tid < 4) sd[tid] += sd[tid + 4];
    __syncthreads();

    if (tid < 2) sd[tid] += sd[tid + 2];
    __syncthreads();

    if (tid < 1) sd[tid] += sd[tid + 1];
    __syncthreads();

    if (tid == 0) {
        dst[row] = sd[0];
    }
}
