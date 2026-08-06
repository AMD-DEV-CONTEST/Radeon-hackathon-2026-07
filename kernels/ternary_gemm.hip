#include <hip/hip_runtime.h>
#include <cstdio>
#include <cmath>

/*
 * Ternary GEMM: Y = X * W where W in {-1, 0, +1}
 *
 * Weights are packed into a compact 2-bit representation:
 *   00 -> 0
 *   01 -> +1
 *   10 -> -1
 *   11 -> reserved / padding
 * Four ternary weights are packed into one uint8_t, LSB-first.
 *
 * This kernel is optimized for AMD GPUs (ROCm/HIP):
 * - Coalesced loads for activations X
 * - Shared-memory cached tiles
 * - 2-bit weight unpacking in registers to avoid high-precision expansion
 * - Grid-stride loops for large matrices
 */

#define TILE_M 64
#define TILE_N 64
#define TILE_K 32
#define WARP_SIZE 64

__device__ __forceinline__ int unpack_ternary(uint8_t packed, int lane) {
    // lane in [0, 3] selects one of the four 2-bit fields.
    int shift = lane * 2;
    int val = (packed >> shift) & 0x3;
    if (val == 0) return 0;
    if (val == 1) return 1;
    return -1;
}

__global__ void ternary_gemm_kernel(
    const float* __restrict__ X,
    const uint8_t* __restrict__ W_packed,
    float* __restrict__ Y,
    int M,
    int N,
    int K,
    const float* __restrict__ scales)
{
    __shared__ float sX[TILE_M][TILE_K];
    __shared__ uint8_t sW[TILE_K][TILE_N / 4];

    int bx = blockIdx.x;  // N tile
    int by = blockIdx.y;  // M tile
    int tx = threadIdx.x; // within tile
    int ty = threadIdx.y;

    int row = by * TILE_M + ty;
    int col = bx * TILE_N + tx;

    float acc = 0.0f;

    for (int kt = 0; kt < K; kt += TILE_K) {
        // Load X tile into shared memory (M x K)
        for (int i = ty; i < TILE_M; i += blockDim.y) {
            for (int j = tx; j < TILE_K; j += blockDim.x) {
                int x_row = by * TILE_M + i;
                int x_col = kt + j;
                sX[i][j] = (x_row < M && x_col < K) ? X[x_row * K + x_col] : 0.0f;
            }
        }

        // Load W packed tile into shared memory (K x N/4)
        for (int i = ty; i < TILE_K; i += blockDim.y) {
            for (int j = tx; j < TILE_N / 4; j += blockDim.x) {
                int w_row = kt + i;
                int w_col = (bx * TILE_N) / 4 + j;
                sW[i][j] = (w_row < K && w_col < N / 4) ? W_packed[w_row * (N / 4) + w_col] : 0;
            }
        }

        __syncthreads();

        // Compute partial dot product using ternary weights
        for (int kk = 0; kk < TILE_K; ++kk) {
            float x_val = sX[ty][kk];
            // Each thread owns a column; fetch its packed weights.
            uint8_t packed = sW[kk][tx / 4];
            int lane = tx % 4;
            int w_val = unpack_ternary(packed, lane);
            acc += x_val * static_cast<float>(w_val);
        }

        __syncthreads();
    }

    if (row < M && col < N) {
        float scale = scales[col];
        Y[row * N + col] = acc * scale;
    }
}

extern "C" __global__ void ternary_gemm(
    const float* X,
    const uint8_t* W_packed,
    float* Y,
    int M,
    int N,
    int K,
    const float* scales)
{
    ternary_gemm_kernel(X, W_packed, Y, M, N, K, scales);
}

/*
 * Host-side launch helper. Called from Python via ctypes/hiprtc or via a
 * PyTorch C++ extension wrapper.
 */
extern "C" void launch_ternary_gemm(
    const float* d_X,
    const uint8_t* d_W,
    float* d_Y,
    int M,
    int N,
    int K,
    const float* d_scales,
    hipStream_t stream)
{
    dim3 block(16, 16);
    dim3 grid((N + TILE_N - 1) / TILE_N, (M + TILE_M - 1) / TILE_M);
    hipLaunchKernelGGL(
        ternary_gemm_kernel,
        grid,
        block,
        0,
        stream,
        d_X, d_W, d_Y, M, N, K, d_scales);
}
