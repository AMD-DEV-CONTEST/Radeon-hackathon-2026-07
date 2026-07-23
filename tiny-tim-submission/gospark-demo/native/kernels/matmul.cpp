#include <hip/hip_runtime.h>
#include "hip_check.h"

extern "C" {

// DEVICE code — runs on the GPU. Each thread computes exactly one
// output element C[row][col], using the same row-major flat-indexing
// convention we've used throughout (a[i*n+k], matching core/tensor.go).
__global__ void matmulKernel(double* a, double* b, double* c, int m, int n, int p) {
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;

    if (row < m && col < p) {
        double sum = 0;
        for (int k = 0; k < n; k++) {
            sum += a[row * n + k] * b[k * p + col];
        }
        c[row * p + col] = sum;
    }
}

// HOST code — manages GPU memory and launches the kernel across a 2D
// grid of threads, sized so every output element gets exactly one
// thread (rounding up to cover the whole matrix).
int gpu_matmul(double* a, double* b, double* result, int m, int n, int p) {
    double *d_a, *d_b, *d_c;
    size_t sizeA = m * n * sizeof(double);
    size_t sizeB = n * p * sizeof(double);
    size_t sizeC = m * p * sizeof(double);

    HIP_CHECK(hipMalloc(&d_a, sizeA));
    HIP_CHECK(hipMalloc(&d_b, sizeB));
    HIP_CHECK(hipMalloc(&d_c, sizeC));

    HIP_CHECK(hipMemcpy(d_a, a, sizeA, hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(d_b, b, sizeB, hipMemcpyHostToDevice));

    dim3 threadsPerBlock(16, 16);
    dim3 blocks((p + 15) / 16, (m + 15) / 16);
    matmulKernel<<<blocks, threadsPerBlock>>>(d_a, d_b, d_c, m, n, p);
    HIP_CHECK(hipDeviceSynchronize());

    HIP_CHECK(hipMemcpy(result, d_c, sizeC, hipMemcpyDeviceToHost));

    hipFree(d_a);
    hipFree(d_b);
    hipFree(d_c);

    return 0;
}

}