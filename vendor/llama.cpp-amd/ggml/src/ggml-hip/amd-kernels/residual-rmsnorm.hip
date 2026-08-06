#include "residual-rmsnorm.hpp"

#include <cstdint>

#include <hip/hip_runtime.h>

namespace fastagentfactory::amd_kernels {
namespace {

constexpr int wave_size = 32;
constexpr int vector_width = 4;
constexpr int min_block_size = 128;
constexpr int preferred_block_size = 256;
constexpr int max_vectors_per_thread = 8;

__device__ __forceinline__ float wave32_reduce_sum(float value) {
#pragma unroll
    for (int offset = wave_size / 2; offset > 0; offset /= 2) {
        value += __shfl_down(value, offset, wave_size);
    }
    return value;
}

template<int block_size, int vectors_per_thread>
__global__ __launch_bounds__(block_size, 2)
void amd_residual_rms_norm_f32_vector_kernel(
        const float4 * residual_input,
        const float4 * residual_skip,
        const float4 * norm_weight,
        float4 * residual_output,
        float4 * normalized_output,
        float epsilon) {
    static_assert(block_size % wave_size == 0);
    static_assert(vectors_per_thread > 0);

    constexpr int vectors_per_row = block_size * vectors_per_thread;
    constexpr int columns_per_row = vectors_per_row * vector_width;
    constexpr int waves_per_block = block_size / wave_size;

    const int64_t row = blockIdx.x;
    const int thread = threadIdx.x;
    const int lane = thread % wave_size;
    const int wave = thread / wave_size;
    const int64_t row_vector_offset = row * vectors_per_row;

    residual_input += row_vector_offset;
    residual_skip += row_vector_offset;
    residual_output += row_vector_offset;
    normalized_output += row_vector_offset;

    float4 residual[vectors_per_thread];
    float4 square_sums = make_float4(0.0f, 0.0f, 0.0f, 0.0f);

#pragma unroll
    for (int item = 0; item < vectors_per_thread; ++item) {
        const int vector_index = thread + item * block_size;
        const float4 input = residual_input[vector_index];
        const float4 skip = residual_skip[vector_index];
        const float4 value = make_float4(
            input.x + skip.x,
            input.y + skip.y,
            input.z + skip.z,
            input.w + skip.w);
        residual[item] = value;
        residual_output[vector_index] = value;
        square_sums.x = fmaf(value.x, value.x, square_sums.x);
        square_sums.y = fmaf(value.y, value.y, square_sums.y);
        square_sums.z = fmaf(value.z, value.z, square_sums.z);
        square_sums.w = fmaf(value.w, value.w, square_sums.w);
    }

    float square_sum = (square_sums.x + square_sums.y) + (square_sums.z + square_sums.w);
    square_sum = wave32_reduce_sum(square_sum);

    __shared__ float wave_sums[waves_per_block];
    if (lane == 0) {
        wave_sums[wave] = square_sum;
    }
    __syncthreads();

    if (wave == 0) {
        float block_sum = lane < waves_per_block ? wave_sums[lane] : 0.0f;
        block_sum = wave32_reduce_sum(block_sum);
        if (lane == 0) {
            wave_sums[0] = rsqrtf(block_sum / static_cast<float>(columns_per_row) + epsilon);
        }
    }
    __syncthreads();

    const float inverse_rms = wave_sums[0];
#pragma unroll
    for (int item = 0; item < vectors_per_thread; ++item) {
        const int vector_index = thread + item * block_size;
        const float4 value = residual[item];
        const float4 weight = norm_weight[vector_index];
        normalized_output[vector_index] = make_float4(
            value.x * inverse_rms * weight.x,
            value.y * inverse_rms * weight.y,
            value.z * inverse_rms * weight.z,
            value.w * inverse_rms * weight.w);
    }
}

bool is_aligned_vector_pointer(const void * pointer) noexcept {
    return reinterpret_cast<uintptr_t>(pointer) % alignof(float4) == 0;
}

bool supports_vector_partition(int64_t vector_columns) noexcept {
    const auto supported_by = [vector_columns](int block_size) {
        return vector_columns >= block_size &&
            vector_columns % block_size == 0 &&
            vector_columns / block_size <= max_vectors_per_thread;
    };
    return supported_by(preferred_block_size) || supported_by(min_block_size);
}

template<int block_size>
hipError_t launch_vector_partition(
        int vectors_per_thread,
        const float4 * residual_input,
        const float4 * residual_skip,
        const float4 * norm_weight,
        float4 * residual_output,
        float4 * normalized_output,
        int64_t rows,
        float epsilon,
        hipStream_t stream) {
    const dim3 grid(static_cast<uint32_t>(rows));
    const dim3 block(block_size);

#define LAUNCH_VECTOR_VARIANT(VECTORS_PER_THREAD) \
    hipLaunchKernelGGL( \
        HIP_KERNEL_NAME(amd_residual_rms_norm_f32_vector_kernel<block_size, VECTORS_PER_THREAD>), \
        grid, \
        block, \
        0, \
        stream, \
        residual_input, \
        residual_skip, \
        norm_weight, \
        residual_output, \
        normalized_output, \
        epsilon)

    switch (vectors_per_thread) {
        case 1: LAUNCH_VECTOR_VARIANT(1); break;
        case 2: LAUNCH_VECTOR_VARIANT(2); break;
        case 3: LAUNCH_VECTOR_VARIANT(3); break;
        case 4: LAUNCH_VECTOR_VARIANT(4); break;
        case 5: LAUNCH_VECTOR_VARIANT(5); break;
        case 6: LAUNCH_VECTOR_VARIANT(6); break;
        case 7: LAUNCH_VECTOR_VARIANT(7); break;
        case 8: LAUNCH_VECTOR_VARIANT(8); break;
        default: return hipErrorInvalidValue;
    }

#undef LAUNCH_VECTOR_VARIANT

    return hipGetLastError();
}

} // namespace

bool supports_residual_rms_norm_f32(
        const float * residual_input,
        const float * residual_skip,
        const float * norm_weight,
        const float * residual_output,
        const float * normalized_output,
        int64_t columns,
        int64_t rows) noexcept {
    if (residual_input == nullptr || residual_skip == nullptr || norm_weight == nullptr ||
            residual_output == nullptr || normalized_output == nullptr ||
            columns <= 0 || rows <= 0 || columns % vector_width != 0) {
        return false;
    }
    if (!is_aligned_vector_pointer(residual_input) ||
            !is_aligned_vector_pointer(residual_skip) ||
            !is_aligned_vector_pointer(norm_weight) ||
            !is_aligned_vector_pointer(residual_output) ||
            !is_aligned_vector_pointer(normalized_output)) {
        return false;
    }
    return supports_vector_partition(columns / vector_width);
}

hipError_t launch_residual_rms_norm_f32(
        const float * residual_input,
        const float * residual_skip,
        const float * norm_weight,
        float * residual_output,
        float * normalized_output,
        int64_t columns,
        int64_t rows,
        float epsilon,
        hipStream_t stream) {
    if (!supports_residual_rms_norm_f32(
            residual_input,
            residual_skip,
            norm_weight,
            residual_output,
            normalized_output,
            columns,
            rows)) {
        return hipErrorInvalidValue;
    }

    const int64_t vector_columns = columns / vector_width;
    const auto * input4 = reinterpret_cast<const float4 *>(residual_input);
    const auto * skip4 = reinterpret_cast<const float4 *>(residual_skip);
    const auto * weight4 = reinterpret_cast<const float4 *>(norm_weight);
    auto * residual4 = reinterpret_cast<float4 *>(residual_output);
    auto * normalized4 = reinterpret_cast<float4 *>(normalized_output);

    if (vector_columns % preferred_block_size == 0 &&
            vector_columns / preferred_block_size <= max_vectors_per_thread) {
        return launch_vector_partition<preferred_block_size>(
            static_cast<int>(vector_columns / preferred_block_size),
            input4,
            skip4,
            weight4,
            residual4,
            normalized4,
            rows,
            epsilon,
            stream);
    }

    return launch_vector_partition<min_block_size>(
        static_cast<int>(vector_columns / min_block_size),
        input4,
        skip4,
        weight4,
        residual4,
        normalized4,
        rows,
        epsilon,
        stream);
}

} // namespace fastagentfactory::amd_kernels
