#pragma once

namespace fastagentfactory::amd_kernels {

inline constexpr const char * q6_k_mmvq_kernel_id = "amd.q6_k_q8_1_mmvq";

#if defined(GGML_USE_HIP) && defined(RDNA3)

static_assert(QR6_K == 2);
static_assert(QI6_K == 32);

__device__ __forceinline__ int mixed_unsigned_signed_dot4(int q6, int q8) {
    return __builtin_amdgcn_sudot4(false, q6, true, q8, 0, false);
}

__device__ __forceinline__ float corrected_q6_q8_1_dot4(
        int q6_values,
        const block_q8_1 * __restrict__ q8,
        int iqs) {
    constexpr int packed_ones = 0x01010101;
    const int q8_values = get_int_b4(q8->qs, iqs % QI8_1);
    const int q8_sum = mixed_unsigned_signed_dot4(packed_ones, q8_values);
    const int centered_dot = __builtin_amdgcn_sudot4(
        false, q6_values, true, q8_values, -32 * q8_sum, false);
    return __low2float(q8->ds) * static_cast<float>(centered_dot);
}

__device__ __forceinline__ float vec_dot_q6_k_q8_1_rdna3(
        const void * __restrict__ weights,
        const block_q8_1 * __restrict__ q8,
        int weight_block_index,
        int iqs) {
    const auto * q6 = static_cast<const block_q6_K *>(weights) + weight_block_index;
    const int q8_offset =
        2 * QR6_K * (iqs / (QI6_K / 2)) +
        (iqs % (QI6_K / 2)) / (QI6_K / 4);
    const int scale_offset =
        (QI6_K / 4) * (iqs / (QI6_K / 2)) +
        (iqs % (QI6_K / 2)) / (QI6_K / 8);
    const int q6_high_shift =
        2 * ((iqs % (QI6_K / 2)) / (QI6_K / 4));
    const int q6_high_index =
        (QI6_K / 4) * (iqs / (QI6_K / 2)) +
        iqs % (QI6_K / 4);

    const int ql = get_int_b2(q6->ql, iqs);
    const int qh = get_int_b2(q6->qh, q6_high_index) >> q6_high_shift;
    const int q6_low = (ql & 0x0F0F0F0F) | ((qh << 4) & 0x30303030);
    float sum = static_cast<float>(q6->scales[scale_offset]) *
        corrected_q6_q8_1_dot4(q6_low, q8 + q8_offset, iqs);

    const int q6_high = ((ql >> 4) & 0x0F0F0F0F) | (qh & 0x30303030);
    sum += static_cast<float>(q6->scales[scale_offset + 4]) *
        corrected_q6_q8_1_dot4(q6_high, q8 + q8_offset + 2, iqs);

    return __half2float(q6->d) * sum;
}

#elif defined(GGML_USE_HIP)

__device__ __forceinline__ float vec_dot_q6_k_q8_1_rdna3(
        const void * __restrict__,
        const block_q8_1 * __restrict__,
        int,
        int) {
    return 0.0f;
}

#endif

} // namespace fastagentfactory::amd_kernels
