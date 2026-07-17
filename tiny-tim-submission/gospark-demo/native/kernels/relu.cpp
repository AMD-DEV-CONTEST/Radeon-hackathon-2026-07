#include <hip/hip_runtime.h>
#include "hip_check.h"

extern "C" {

// DEVICE code — genuinely simple compared to Softmax: every element is
// fully independent (no reduction needed at all), one thread per
// element, exactly matching Add/MatMul's structure. Direct port of
// core/tensor.go's existing ReLU algorithm (max(0,x)) onto the GPU.
__global__ void reluKernel(double* input, double* output, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        output[i] = input[i] > 0 ? input[i] : 0;
    }
}

// HOST code — standard allocate/copy/launch/copy-back/free pattern.
int gpu_relu(double* input, double* result, int n) {
    double *d_input, *d_output;
    size_t size = n * sizeof(double);

    HIP_CHECK(hipMalloc(&d_input, size));
    HIP_CHECK(hipMalloc(&d_output, size));

    HIP_CHECK(hipMemcpy(d_input, input, size, hipMemcpyHostToDevice));

    int threadsPerBlock = 256;
    int blocks = (n + threadsPerBlock - 1) / threadsPerBlock;
    reluKernel<<<blocks, threadsPerBlock>>>(d_input, d_output, n);
    HIP_CHECK(hipDeviceSynchronize());

    HIP_CHECK(hipMemcpy(result, d_output, size, hipMemcpyDeviceToHost));

    hipFree(d_input);
    hipFree(d_output);

    return 0;
}

}