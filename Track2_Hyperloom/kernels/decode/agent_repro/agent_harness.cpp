#include <vector>
#include <random>
#include <cmath>
#include <cstdio>

float decode_e4m3(uint8_t b) {
    if ((b & 0x7F) == 0x7F) {
        return 0.0f;
    }
    int sign = (b >> 7) & 1;
    int exponent = (b >> 3) & 0x0F;
    int mantissa = b & 0x07;
    float value;
    if (exponent == 0) {
        value = (float)mantissa * (1.0f / 512.0f);
    } else {
        value = (1.0f + (float)mantissa * (1.0f / 8.0f)) * exp2f((float)(exponent - 7));
    }
    if (sign) {
        value = -value;
    }
    return value;
}

int main() {
    int N = 1024;
    int K = 4096;
    int Kb = K / QK;

    std::mt19937 gen(12345);

    auto generate_valid_byte = [&gen]() -> uint8_t {
        uint8_t b;
        do {
            b = (uint8_t)(gen() & 0xFF);
        } while ((b & 0x7F) == 0x7F);
        return b;
    };

    size_t num_blocks = (size_t)N * Kb;
    std::vector<block_f8e4m3> h_weights(num_blocks);
    std::vector<block_a_fp8> h_acts(num_blocks);

    for (size_t i = 0; i < num_blocks; ++i) {
        h_weights[i].d = __float2half(0.01f);
        for (int j = 0; j < QK; ++j) {
            h_weights[i].qs[j] = generate_valid_byte();
        }
        h_acts[i].ds = __float2half2_rn(0.02f);
        for (int j = 0; j < QK; ++j) {
            h_acts[i].qs[j] = generate_valid_byte();
        }
    }

    block_f8e4m3 *d_weights = nullptr;
    block_a_fp8 *d_acts = nullptr;
    float *d_dst = nullptr;

    hipMalloc(&d_weights, num_blocks * sizeof(block_f8e4m3));
    hipMalloc(&d_acts, num_blocks * sizeof(block_a_fp8));
    hipMalloc(&d_dst, N * sizeof(float));

    hipMemcpy(d_weights, h_weights.data(), num_blocks * sizeof(block_f8e4m3), hipMemcpyHostToDevice);
    hipMemcpy(d_acts, h_acts.data(), num_blocks * sizeof(block_a_fp8), hipMemcpyHostToDevice);

    std::vector<float> h_dst(N, 0.0f);

    for (int i = 0; i < N; ++i) {
        float row_sum = 0.0f;
        for (int k = 0; k < Kb; ++k) {
            size_t block_idx = (size_t)i * Kb + k;
            float block_prod_sum = 0.0f;
            const uint8_t *w_qs = h_weights[block_idx].qs;
            const uint8_t *a_qs = h_acts[block_idx].qs;
            for (int j = 0; j < QK; ++j) {
                float w_val = decode_e4m3(w_qs[j]);
                float a_val = decode_e4m3(a_qs[j]);
                block_prod_sum += w_val * a_val;
            }
            float w_scale = __half2float(h_weights[block_idx].d);
            float a_scale = __half2float(__low2half(h_acts[block_idx].ds));
            row_sum += block_prod_sum * w_scale * a_scale;
        }
        h_dst[i] = row_sum;
    }

    int stride = Kb * sizeof(block_f8e4m3);
    kernel_under_test<<<N, 64, 64*sizeof(float)>>>( (const char*)d_weights, d_acts, d_dst, (int64_t)Kb, (int64_t)stride);
    hipDeviceSynchronize();

    std::vector<float> g_dst(N);
    hipMemcpy(g_dst.data(), d_dst, N * sizeof(float), hipMemcpyDeviceToHost);

    float max_rel_err = 0.0f;
    bool fail = false;

    for (int i = 0; i < N; ++i) {
        float got = g_dst[i];
        float want = h_dst[i];
        if (!std::isfinite(got)) {
            fail = true;
            max_rel_err = 1e30f;
            break;
        }
        float rel_err;
        if (std::fabs(want) > 1e-6) {
            rel_err = std::fabs(got - want) / std::fabs(want);
        } else {
            rel_err = std::fabs(got - want);
        }
        if (rel_err > max_rel_err) {
            max_rel_err = rel_err;
        }
    }

    if (fail || max_rel_err > 1e-2) {
        printf("max_rel_err=%e VERDICT=FAIL\n", max_rel_err);
        return 1;
    } else {
        printf("max_rel_err=%e VERDICT=PASS\n", max_rel_err);
        return 0;
    }
}
