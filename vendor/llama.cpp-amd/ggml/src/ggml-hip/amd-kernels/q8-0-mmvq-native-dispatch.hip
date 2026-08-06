#include "q8-0-mmvq-native.hpp"

#include "../../ggml-cuda/vecdotq.cuh"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace fastagentfactory::amd_kernels {
namespace {

constexpr const char * wave_mode_environment = "AGENTFACTORY_AMD_Q8_MMVQ_WAVE_MODE";

int ceil_div(int64_t value, int divisor) noexcept {
    return static_cast<int>((value + divisor - 1) / divisor);
}

int reduction_stages(int wave_size) noexcept {
    int stages = 0;
    for (int remaining = wave_size; remaining > 1; remaining /= 2) {
        ++stages;
    }
    return stages;
}

double estimated_variant_cost(
        const q8_0_mmvq_native_launch_config & config,
        const q8_0_mmvq_kernel_resources & resources,
        int compute_units) noexcept {
    constexpr int lanes_per_quantization_block =
        QK8_1 / (sizeof(int) * VDR_Q8_0_Q8_1_MMVQ);
    const int blocks_per_wave =
        resources.logical_lanes_per_output / lanes_per_quantization_block;
    const int weight_blocks = static_cast<int>(config.input_columns / QK8_0);
    const int dot_rounds = ceil_div(weight_blocks, blocks_per_wave);
    const int workgroups = ceil_div(config.output_rows, resources.output_rows_per_workgroup);
    const int concurrent_workgroups = std::max(
        1,
        compute_units * resources.active_workgroups_per_compute_unit);
    const int scheduling_rounds = ceil_div(workgroups, concurrent_workgroups);
    const int instruction_rounds =
        dot_rounds * VDR_Q8_0_Q8_1_MMVQ +
        reduction_stages(resources.logical_lanes_per_output);
    return static_cast<double>(scheduling_rounds) * instruction_rounds;
}

q8_0_mmvq_dispatch_decision forced_decision(
        q8_0_mmvq_wave_mode mode,
        const q8_0_mmvq_native_launch_config & config) noexcept {
    if (mode == q8_0_mmvq_wave_mode::official || !supports_q8_0_mmvq_native(config)) {
        return {};
    }
    return {
        mode,
        mode == q8_0_mmvq_wave_mode::wave64
            ? q8_0_mmvq_native_wave64_kernel_id
            : q8_0_mmvq_native_wave32_kernel_id,
        0.0,
    };
}

} // namespace

bool supports_q8_0_mmvq_native(
        const q8_0_mmvq_native_launch_config & config) noexcept {
    if (config.quantized_weights == nullptr || config.quantized_activation == nullptr ||
            config.output == nullptr || config.output_rows <= 0 || config.input_columns <= 0 ||
            config.output_rows > std::numeric_limits<uint32_t>::max() ||
            config.input_columns > std::numeric_limits<int32_t>::max() ||
            config.input_columns % QK8_0 != 0 ||
            config.weight_row_stride < config.input_columns / QK8_0) {
        return false;
    }
    int max_shared_memory = 0;
    int device = 0;
    if (hipGetDevice(&device) != hipSuccess ||
            hipDeviceGetAttribute(
                &max_shared_memory,
                hipDeviceAttributeMaxSharedMemoryPerBlock,
                device) != hipSuccess) {
        return false;
    }
    const std::size_t shared_memory_bytes =
        static_cast<std::size_t>(config.input_columns / QK8_1) * sizeof(block_q8_1);
    return shared_memory_bytes <= static_cast<std::size_t>(max_shared_memory);
}

q8_0_mmvq_wave_mode configured_q8_0_mmvq_wave_mode() noexcept {
    const char * value = std::getenv(wave_mode_environment);
    if (value == nullptr || std::strcmp(value, "auto") == 0) {
        return q8_0_mmvq_wave_mode::automatic;
    }
    if (std::strcmp(value, "official") == 0) {
        return q8_0_mmvq_wave_mode::official;
    }
    if (std::strcmp(value, "wave32") == 0) {
        return q8_0_mmvq_wave_mode::wave32;
    }
    if (std::strcmp(value, "wave64") == 0) {
        return q8_0_mmvq_wave_mode::wave64;
    }
    return q8_0_mmvq_wave_mode::automatic;
}

q8_0_mmvq_dispatch_decision select_q8_0_mmvq_native_variant(
        const q8_0_mmvq_native_launch_config & config) noexcept {
    const q8_0_mmvq_wave_mode configured_mode = configured_q8_0_mmvq_wave_mode();
    if (configured_mode != q8_0_mmvq_wave_mode::automatic) {
        return forced_decision(configured_mode, config);
    }
    if (!supports_q8_0_mmvq_native(config)) {
        return {};
    }

    const std::size_t shared_memory_bytes =
        static_cast<std::size_t>(config.input_columns / QK8_1) * sizeof(block_q8_1);
    q8_0_mmvq_kernel_resources wave32_resources;
    q8_0_mmvq_kernel_resources wave64_resources;
    if (query_q8_0_mmvq_wave32_resources(shared_memory_bytes, wave32_resources) != hipSuccess ||
            query_q8_0_mmvq_wave64_resources(shared_memory_bytes, wave64_resources) != hipSuccess) {
        return forced_decision(q8_0_mmvq_wave_mode::wave32, config);
    }

    int device = 0;
    hipDeviceProp_t properties{};
    if (hipGetDevice(&device) != hipSuccess || hipGetDeviceProperties(&properties, device) != hipSuccess) {
        return forced_decision(q8_0_mmvq_wave_mode::wave32, config);
    }
    const double wave32_cost = estimated_variant_cost(
        config,
        wave32_resources,
        properties.multiProcessorCount);
    const double wave64_cost = estimated_variant_cost(
        config,
        wave64_resources,
        properties.multiProcessorCount);
    if (wave64_cost < wave32_cost) {
        return {
            q8_0_mmvq_wave_mode::wave64,
            q8_0_mmvq_native_wave64_kernel_id,
            wave64_cost,
        };
    }
    return {
        q8_0_mmvq_wave_mode::wave32,
        q8_0_mmvq_native_wave32_kernel_id,
        wave32_cost,
    };
}

} // namespace fastagentfactory::amd_kernels
