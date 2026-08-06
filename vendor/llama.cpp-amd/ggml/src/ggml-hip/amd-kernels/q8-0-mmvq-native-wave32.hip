#include "q8-0-mmvq-native.hpp"

#include "../../ggml-cuda/common.cuh"
#include "../../ggml-cuda/vecdotq.cuh"

#include <cstddef>
#include <cstdint>

namespace fastagentfactory::amd_kernels {
namespace {

constexpr int wave_size = 32;
constexpr int q8_lanes_per_block = QK8_1 / (sizeof(int) * VDR_Q8_0_Q8_1_MMVQ);
constexpr int blocks_per_wave = wave_size / q8_lanes_per_block;
constexpr int waves_per_workgroup = 4;
constexpr int threads_per_workgroup = wave_size * waves_per_workgroup;

static_assert(q8_lanes_per_block == 4);
static_assert(wave_size % q8_lanes_per_block == 0);

__global__ __launch_bounds__(threads_per_workgroup, 2)
void mul_mat_vec_q8_0_wave32(
        const block_q8_0 * __restrict__ weights,
        const block_q8_1 * __restrict__ activation,
        float * __restrict__ output,
        int64_t output_rows,
        int64_t input_columns,
        int64_t weight_row_stride) {
    const int lane = threadIdx.x;
    const int wave = threadIdx.y;
    const int linear_thread = wave * wave_size + lane;
    const int activation_blocks = input_columns / QK8_1;

    extern __shared__ __align__(16) unsigned char shared_storage[];
    auto * shared_activation = reinterpret_cast<block_q8_1 *>(shared_storage);
    for (int block = linear_thread; block < activation_blocks; block += threads_per_workgroup) {
        shared_activation[block] = activation[block];
    }
    __syncthreads();

    const int64_t output_row = static_cast<int64_t>(blockIdx.x) * waves_per_workgroup + wave;
    if (output_row >= output_rows) {
        return;
    }

    const int subgroup = lane / q8_lanes_per_block;
    const int subgroup_lane = VDR_Q8_0_Q8_1_MMVQ * (lane % q8_lanes_per_block);
    const int weight_blocks = input_columns / QK8_0;
    float even_partial = 0.0f;
    float odd_partial = 0.0f;
    int sequence = 0;
    for (int weight_block = subgroup; weight_block < weight_blocks;
            weight_block += blocks_per_wave, ++sequence) {
        const float partial = vec_dot_q8_0_q8_1(
            weights,
            shared_activation + weight_block,
            static_cast<int>(output_row * weight_row_stride + weight_block),
            subgroup_lane);
        if ((sequence & 1) == 0) {
            even_partial += partial;
        } else {
            odd_partial += partial;
        }
    }

    const float result = warp_reduce_sum<wave_size>(even_partial + odd_partial);
    if (lane == 0) {
        output[output_row] = result;
    }
}

} // namespace

hipError_t query_q8_0_mmvq_wave32_resources(
        std::size_t dynamic_shared_memory_bytes,
        q8_0_mmvq_kernel_resources & resources) noexcept {
    hipFuncAttributes attributes{};
    hipError_t status = hipFuncGetAttributes(
        &attributes,
        reinterpret_cast<const void *>(mul_mat_vec_q8_0_wave32));
    if (status != hipSuccess) {
        return status;
    }
    int active_workgroups = 0;
    status = hipOccupancyMaxActiveBlocksPerMultiprocessor(
        &active_workgroups,
        mul_mat_vec_q8_0_wave32,
        threads_per_workgroup,
        dynamic_shared_memory_bytes);
    if (status != hipSuccess) {
        return status;
    }
    resources = {
        wave_size,
        wave_size,
        waves_per_workgroup,
        waves_per_workgroup,
        threads_per_workgroup,
        attributes.numRegs,
        static_cast<int>(attributes.sharedSizeBytes),
        active_workgroups,
    };
    return hipSuccess;
}

hipError_t launch_q8_0_mmvq_native_wave32(
        const q8_0_mmvq_native_launch_config & config,
        hipStream_t stream) {
    if (!supports_q8_0_mmvq_native(config)) {
        return hipErrorInvalidValue;
    }
    const dim3 grid(
        static_cast<uint32_t>((config.output_rows + waves_per_workgroup - 1) / waves_per_workgroup),
        1,
        1);
    const dim3 block(wave_size, waves_per_workgroup, 1);
    const std::size_t shared_memory_bytes =
        static_cast<std::size_t>(config.input_columns / QK8_1) * sizeof(block_q8_1);
    hipLaunchKernelGGL(
        mul_mat_vec_q8_0_wave32,
        grid,
        block,
        shared_memory_bytes,
        stream,
        static_cast<const block_q8_0 *>(config.quantized_weights),
        static_cast<const block_q8_1 *>(config.quantized_activation),
        config.output,
        config.output_rows,
        config.input_columns,
        config.weight_row_stride);
    return hipGetLastError();
}

} // namespace fastagentfactory::amd_kernels
