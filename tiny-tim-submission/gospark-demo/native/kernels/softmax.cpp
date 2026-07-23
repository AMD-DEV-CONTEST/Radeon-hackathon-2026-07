#include <hip/hip_runtime.h>
#include "hip_check.h"

extern "C" {

// DEVICE code — one GPU thread per row, each thread sequentially doing
// the full max-find/exp-sum/normalize sequence for its row. This is a
// direct, honest translation of core/tensor.go's existing CPU Softmax
// algorithm (same max-subtraction numerical-stability trick), just
// moved to run on the GPU.
//
// KNOWN LIMITATION, documented deliberately: this does not use
// cooperative/parallel reduction within a row (multiple threads sharing
// work via shared memory) -- each row's work is fully sequential within
// its one thread. This is genuinely correct GPU execution, just not the
// maximally-parallel version. Real libraries (cuDNN, PyTorch) don't use
// one universal kernel either -- they pick between multiple
// implementations based on row width. A cooperative-reduction version
// (Version 2) is real, scoped future work once row widths are large
// enough for it to actually matter.
__global__ void softmaxKernel(double* input, double* output, int rows, int cols) {
    int row = blockIdx.x * blockDim.x + threadIdx.x;
    if (row < rows) {
        double maxVal = input[row * cols];
        for (int c = 1; c < cols; c++) {
            if (input[row * cols + c] > maxVal) {
                maxVal = input[row * cols + c];
            }
        }

        double sum = 0;
        for (int c = 0; c < cols; c++) {
            double e = exp(input[row * cols + c] - maxVal);
            output[row * cols + c] = e;
            sum += e;
        }

        for (int c = 0; c < cols; c++) {
            output[row * cols + c] /= sum;
        }
    }
}

// HOST code — standard allocate/copy/launch/copy-back/free pattern,
// same as every other kernel tonight.
int gpu_softmax(double* input, double* result, int rows, int cols) {
    double *d_input, *d_output;
    size_t size = rows * cols * sizeof(double);

    HIP_CHECK(hipMalloc(&d_input, size));
    HIP_CHECK(hipMalloc(&d_output, size));

    HIP_CHECK(hipMemcpy(d_input, input, size, hipMemcpyHostToDevice));

    int threadsPerBlock = 256;
    int blocks = (rows + threadsPerBlock - 1) / threadsPerBlock;
    softmaxKernel<<<blocks, threadsPerBlock>>>(d_input, d_output, rows, cols);
    HIP_CHECK(hipDeviceSynchronize());

    HIP_CHECK(hipMemcpy(result, d_output, size, hipMemcpyDeviceToHost));

    hipFree(d_input);
    hipFree(d_output);

    return 0;
}

}