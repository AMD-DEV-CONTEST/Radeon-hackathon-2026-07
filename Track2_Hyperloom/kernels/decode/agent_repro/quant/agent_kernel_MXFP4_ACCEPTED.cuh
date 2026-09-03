__global__ void agent_kernel(const block_lowbit* __restrict__ w,
                             const float* __restrict__ act,
                             float* __restrict__ dst, int64_t Kb) {
    extern __shared__ float sd[];
    int row = blockIdx.x;
    int tid = threadIdx.x;

    const block_lowbit* w_row = &w[(int64_t)row * Kb];

    float thread_sum = 0.0f;

    for (int64_t c = tid; c < Kb; c += 64) {
        const block_lowbit* wc_ptr = &w_row[c];
        uint8_t e = wc_ptr->e;
        float scale = ldexpf(1.0f, (int)e - 127);

        float block_sum = 0.0f;
        const uint8_t* qs = wc_ptr->qs;

        for (int j = 0; j < 16; ++j) {
            uint8_t byte = qs[j];

            {
                uint8_t n = byte & 0x0F;
                int s = (n >> 3) & 1;
                int e2 = (n >> 1) & 3;
                int m = n & 1;
                float val;
                if (e2 == 0) {
                    val = (float)(m ? 0.5f : 0.0f);
                } else {
                    val = ldexpf(1.0f + (float)m * 0.5f, e2 - 1);
                }
                if (s) val = -val;

                float a = act[c * 32 + j];
                block_sum += val * a;
            }

            {
                uint8_t n = (byte >> 4) & 0x0F;
                int s = (n >> 3) & 1;
                int e2 = (n >> 1) & 3;
                int m = n & 1;
                float val;
                if (e2 == 0) {
                    val = (float)(m ? 0.5f : 0.0f);
                } else {
                    val = ldexpf(1.0f + (float)m * 0.5f, e2 - 1);
                }
                if (s) val = -val;

                float a = act[c * 32 + (j + 16)];
                block_sum += val * a;
            }
        }

        thread_sum += block_sum * scale;
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
