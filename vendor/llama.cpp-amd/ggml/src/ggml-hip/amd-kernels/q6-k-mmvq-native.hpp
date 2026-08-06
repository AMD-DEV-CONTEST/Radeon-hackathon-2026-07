#pragma once

#include <hip/hip_runtime.h>

#include <cstdint>

namespace fastagentfactory::amd_kernels {

inline constexpr const char * q6_k_mmvq_native_kernel_id = "amd.q6_k_q8_1_mmvq_native_rdna3";

struct q6_k_mmvq_native_launch_config {
    const void * quantized_weights = nullptr;
    const void * quantized_activation = nullptr;
    float * output = nullptr;
    int64_t output_rows = 0;
    int64_t input_columns = 0;
    int64_t weight_row_stride = 0;
};

bool supports_q6_k_mmvq_native_rdna3(
    const q6_k_mmvq_native_launch_config & config) noexcept;

hipError_t launch_q6_k_mmvq_native_rdna3(
    const q6_k_mmvq_native_launch_config & config,
    hipStream_t stream);

} // namespace fastagentfactory::amd_kernels
