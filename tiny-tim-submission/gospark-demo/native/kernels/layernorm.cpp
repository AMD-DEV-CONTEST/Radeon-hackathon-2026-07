#include <hip/hip_runtime.h>
#include "hip_check.h"

extern "C" {

// One thread per row, matching softmax.cpp's pattern. Outputs the final
// result, plus xhat (normalized values before Gamma/Beta) and stdInv
// per row — both needed for backward to match core/layernorm.go's
// existing gradient formula exactly.
__global__ void layerNormKernel(double* x, double* gamma, double* beta,
                                  double* output, double* xhatOut, double* stdInvOut,
                                  int rows, int cols, double eps) {
    int row = blockIdx.x * blockDim.x + threadIdx.x;
    if (row < rows) {
        double mean = 0;
        for (int c = 0; c < cols; c++) {
            mean += x[row * cols + c];
        }
        mean /= cols;

        double variance = 0;
        for (int c = 0; c < cols; c++) {
            double d = x[row * cols + c] - mean;
            variance += d * d;
        }
        variance /= cols;
        double stdInv = 1.0 / sqrt(variance + eps);
        stdInvOut[row] = stdInv;

        for (int c = 0; c < cols; c++) {
            double xhat = (x[row * cols + c] - mean) * stdInv;
            xhatOut[row * cols + c] = xhat;
            output[row * cols + c] = xhat * gamma[c] + beta[c];
        }
    }
}

int gpu_layernorm(double* x, double* gamma, double* beta,
                    double* output, double* xhatOut, double* stdInvOut,
                    int rows, int cols, double eps) {
    double *d_x, *d_gamma, *d_beta, *d_output, *d_xhat, *d_stdinv;
    size_t xSize = rows * cols * sizeof(double);
    size_t gbSize = cols * sizeof(double);
    size_t stdinvSize = rows * sizeof(double);

    HIP_CHECK(hipMalloc(&d_x, xSize));
    HIP_CHECK(hipMalloc(&d_gamma, gbSize));
    HIP_CHECK(hipMalloc(&d_beta, gbSize));
    HIP_CHECK(hipMalloc(&d_output, xSize));
    HIP_CHECK(hipMalloc(&d_xhat, xSize));
    HIP_CHECK(hipMalloc(&d_stdinv, stdinvSize));

    HIP_CHECK(hipMemcpy(d_x, x, xSize, hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(d_gamma, gamma, gbSize, hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(d_beta, beta, gbSize, hipMemcpyHostToDevice));

    int threadsPerBlock = 256;
    int blocks = (rows + threadsPerBlock - 1) / threadsPerBlock;
    layerNormKernel<<<blocks, threadsPerBlock>>>(d_x, d_gamma, d_beta, d_output, d_xhat, d_stdinv, rows, cols, eps);
    HIP_CHECK(hipDeviceSynchronize());

    HIP_CHECK(hipMemcpy(output, d_output, xSize, hipMemcpyDeviceToHost));
    HIP_CHECK(hipMemcpy(xhatOut, d_xhat, xSize, hipMemcpyDeviceToHost));
    HIP_CHECK(hipMemcpy(stdInvOut, d_stdinv, stdinvSize, hipMemcpyDeviceToHost));

    hipFree(d_x);
    hipFree(d_gamma);
    hipFree(d_beta);
    hipFree(d_output);
    hipFree(d_xhat);
    hipFree(d_stdinv);

    return 0;
}

}