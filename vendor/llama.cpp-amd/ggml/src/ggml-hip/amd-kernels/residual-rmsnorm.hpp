#pragma once

#include <cstdint>

#include <hip/hip_runtime.h>

namespace fastagentfactory::amd_kernels {

inline constexpr const char * residual_rms_norm_kernel_id = "amd.residual_rms_norm_f32";

bool supports_residual_rms_norm_f32(
    const float * residual_input,
    const float * residual_skip,
    const float * norm_weight,
    const float * residual_output,
    const float * normalized_output,
    int64_t columns,
    int64_t rows) noexcept;

hipError_t launch_residual_rms_norm_f32(
    const float * residual_input,
    const float * residual_skip,
    const float * norm_weight,
    float * residual_output,
    float * normalized_output,
    int64_t columns,
    int64_t rows,
    float epsilon,
    hipStream_t stream);

} // namespace fastagentfactory::amd_kernels
