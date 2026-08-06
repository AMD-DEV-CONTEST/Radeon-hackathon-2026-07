#include "q6-k-mmvq-native.hpp"

#include "../../ggml-cuda/common.cuh"
#include "../../ggml-cuda/vecdotq.cuh"
#include "q6-k-mmvq.cuh"

#include <cstddef>
#include <cstdint>
#include <limits>

namespace fastagentfactory::amd_kernels {
namespace {

constexpr int wave_size = 32;
constexpr int waves_per_workgroup = 4;
constexpr int threads_per_workgroup = wave_size * waves_per_workgroup;
constexpr std::size_t rdna3_workgroup_lds_limit_bytes = 64U * 1024U;

__global__ __launch_bounds__(threads_per_workgroup, 2)
void mul_mat_vec_q(
        const block_q6_K * __restrict__ weights,
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

    const int weight_blocks = input_columns / QK_K;
    float even_partial = 0.0f;
    float odd_partial = 0.0f;
    for (int weight_block = 0; weight_block < weight_blocks; weight_block += 2) {
        const int activation_block = weight_block * (QK_K / QK8_1);
        even_partial += vec_dot_q6_k_q8_1_rdna3(
            weights,
            shared_activation + activation_block,
            output_row * weight_row_stride + weight_block,
            lane);
        if (weight_block + 1 < weight_blocks) {
            odd_partial += vec_dot_q6_k_q8_1_rdna3(
                weights,
                shared_activation + activation_block + QK_K / QK8_1,
                output_row * weight_row_stride + weight_block + 1,
                lane);
        }
    }

    float result = warp_reduce_sum<wave_size>(even_partial + odd_partial);
    if (lane == 0) {
        output[output_row] = result;
    }
}

} // namespace

bool supports_q6_k_mmvq_native_rdna3(
        const q6_k_mmvq_native_launch_config & config) noexcept {
    if (config.quantized_weights == nullptr || config.quantized_activation == nullptr ||
            config.output == nullptr || config.output_rows <= 0 || config.input_columns <= 0 ||
            config.output_rows > std::numeric_limits<uint32_t>::max() ||
            config.input_columns > std::numeric_limits<int32_t>::max() ||
            config.input_columns % QK_K != 0 ||
            config.weight_row_stride < config.input_columns / QK_K) {
        return false;
    }
    const std::size_t shared_memory_bytes =
        static_cast<std::size_t>(config.input_columns / QK8_1) * sizeof(block_q8_1);
    return shared_memory_bytes <= rdna3_workgroup_lds_limit_bytes;
}

hipError_t launch_q6_k_mmvq_native_rdna3(
        const q6_k_mmvq_native_launch_config & config,
        hipStream_t stream) {
    if (!supports_q6_k_mmvq_native_rdna3(config)) {
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
        mul_mat_vec_q,
        grid,
        block,
        shared_memory_bytes,
        stream,
        static_cast<const block_q6_K *>(config.quantized_weights),
        static_cast<const block_q8_1 *>(config.quantized_activation),
        config.output,
        config.output_rows,
        config.input_columns,
        config.weight_row_stride);
    return hipGetLastError();
}

} // namespace fastagentfactory::amd_kernels
