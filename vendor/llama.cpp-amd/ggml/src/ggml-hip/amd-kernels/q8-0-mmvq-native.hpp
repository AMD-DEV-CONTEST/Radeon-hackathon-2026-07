#pragma once

#include <hip/hip_runtime.h>

#include <cstddef>
#include <cstdint>

namespace fastagentfactory::amd_kernels {

inline constexpr const char * q8_0_mmvq_native_wave32_kernel_id =
    "amd.q8_0_q8_1_mmvq_native_rdna3.wave32";
inline constexpr const char * q8_0_mmvq_native_wave64_kernel_id =
    "amd.q8_0_q8_1_mmvq_native_rdna3.wave64";

enum class q8_0_mmvq_wave_mode {
    official,
    wave32,
    wave64,
    automatic,
};

struct q8_0_mmvq_native_launch_config {
    const void * quantized_weights = nullptr;
    const void * quantized_activation = nullptr;
    float * output = nullptr;
    int64_t output_rows = 0;
    int64_t input_columns = 0;
    int64_t weight_row_stride = 0;
};

struct q8_0_mmvq_kernel_resources {
    int wave_size = 0;
    int logical_lanes_per_output = 0;
    int waves_per_workgroup = 0;
    int output_rows_per_workgroup = 0;
    int threads_per_workgroup = 0;
    int registers_per_thread = 0;
    int static_shared_memory_bytes = 0;
    int active_workgroups_per_compute_unit = 0;
};

struct q8_0_mmvq_dispatch_decision {
    q8_0_mmvq_wave_mode mode = q8_0_mmvq_wave_mode::official;
    const char * kernel_id = nullptr;
    double estimated_cost = 0.0;

    [[nodiscard]] bool uses_native_kernel() const noexcept {
        return kernel_id != nullptr;
    }
};

bool supports_q8_0_mmvq_native(
    const q8_0_mmvq_native_launch_config & config) noexcept;

q8_0_mmvq_wave_mode configured_q8_0_mmvq_wave_mode() noexcept;

q8_0_mmvq_dispatch_decision select_q8_0_mmvq_native_variant(
    const q8_0_mmvq_native_launch_config & config) noexcept;

hipError_t query_q8_0_mmvq_wave32_resources(
    std::size_t dynamic_shared_memory_bytes,
    q8_0_mmvq_kernel_resources & resources) noexcept;

hipError_t query_q8_0_mmvq_wave64_resources(
    std::size_t dynamic_shared_memory_bytes,
    q8_0_mmvq_kernel_resources & resources) noexcept;

hipError_t launch_q8_0_mmvq_native_wave32(
    const q8_0_mmvq_native_launch_config & config,
    hipStream_t stream);

hipError_t launch_q8_0_mmvq_native_wave64(
    const q8_0_mmvq_native_launch_config & config,
    hipStream_t stream);

} // namespace fastagentfactory::amd_kernels
