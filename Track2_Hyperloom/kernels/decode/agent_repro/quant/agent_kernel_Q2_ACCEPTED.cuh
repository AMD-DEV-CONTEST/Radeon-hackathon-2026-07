__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb) {
    extern __shared__ float sd[];
    int tid = threadIdx.x;
    int row = blockIdx.x;

    float thread_sum = 0.0f;

    for (int64_t c = tid; c < Kb; c += 64) {
        block_lowbit blk = w[(int64_t)row * Kb + c];
        float s = 0.0f;
        const uint8_t* qs = blk.qs;
        for (int k = 0; k < 128; ++k) {
            uint8_t qbyte = qs[k >> 2];
            uint8_t code = (qbyte >> ((k & 3) << 1)) & 3u;
            float w_val = (float)((int)code - 1);
            s += w_val * act[(size_t)c * 128 + k];
        }
        thread_sum += s * __half2float(blk.d);
    }

    sd[tid] = thread_sum;
    __syncthreads();

    if (tid == 0) {
        float result = 0.0f;
        for (int i = 0; i < 64; ++i) {
            result += sd[i];
        }
        dst[row] = result;
    }
}
