__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb)
{
    int64_t row = (int64_t)blockIdx.x;
    int tid = threadIdx.x;

    extern __shared__ float sd[];

    float thread_sum = 0.0f;
    int64_t Kb_blocks = Kb;

    for (int64_t c = tid; c < Kb_blocks; c += 64) {
        int64_t w_idx = row * Kb_blocks + c;
        const block_lowbit* wb = &w[w_idx];
        float scale = __half2float(wb->d);
        const uint8_t* qs = wb->qs;
        float s = 0.0f;
        int act_base = (int)(c * 32);
        for (int j = 0; j < 16; ++j) {
            uint8_t q = qs[j];
            int v0 = (int)(q & 0x0F) - 8;
            int v1 = (int)((q >> 4) & 0x0F) - 8;
            s += v0 * act[act_base + j] + v1 * act[act_base + j + 16];
        }
        thread_sum += s * scale;
    }

    sd[tid] = thread_sum;
    __syncthreads();

    if (tid == 0) {
        float total = 0.0f;
        for (int i = 0; i < 64; ++i) {
            total += sd[i];
        }
        dst[row] = total;
    }
}
