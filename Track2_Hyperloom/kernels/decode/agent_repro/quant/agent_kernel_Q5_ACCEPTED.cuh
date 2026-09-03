__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb) {
    extern __shared__ float sd[];
    int row = blockIdx.x;
    int t = threadIdx.x;

    float thread_sum = 0.0f;

    const block_lowbit* w_row = &w[(int64_t)row * Kb];

    for (int c = t; c < Kb; c += 64) {
        const block_lowbit* blk = &w_row[c];
        float scale = __half2float(blk->d);

        float s = 0.0f;
        const float* act_ptr = &act[(int64_t)c * 32];

        for (int k = 0; k < 32; ++k) {
            uint8_t nibble;
            if (k < 16) {
                nibble = blk->qs[k] & 0x0F;
            } else {
                nibble = (blk->qs[k-16] >> 4) & 0x0F;
            }
            int qh_byte_idx = k >> 3;
            int qh_bit_idx = k & 7;
            uint8_t fifth_bit = (blk->qh[qh_byte_idx] >> qh_bit_idx) & 1;
            int val = (int)(nibble | (fifth_bit << 4)) - 16;
            s += (float)val * act_ptr[k];
        }

        thread_sum += s * scale;
    }

    sd[t] = thread_sum;
    __syncthreads();

    for (int stride = 32; stride > 0; stride >>= 1) {
        if (t < stride) {
            sd[t] += sd[t + stride];
        }
        __syncthreads();
    }

    if (t == 0) {
        dst[row] = sd[0];
    }
}
