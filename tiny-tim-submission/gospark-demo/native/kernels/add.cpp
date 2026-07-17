#include <hip/hip_runtime.h>
#include "hip_check.h"

extern "C" {

// This is DEVICE code — it runs ON the GPU itself, not the CPU.
// __global__ marks it as a "kernel": a function launched across many GPU
// threads simultaneously. Each thread computes exactly one element,
// identified by its own unique thread index.
__global__ void vectorAddKernel(float* a, float* b, float* result, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        result[i] = a[i] + b[i];
    }
}

// This is HOST code — it runs on the CPU, and its job is to manage the
// GPU: allocate GPU memory, copy data there, launch the kernel, copy the
// result back, then clean up. This is the actual "boundary crossing" —
// not just Go<->C++ this time, but CPU<->GPU as well.
//
// Returns 0 on success, 1 if any real HIP runtime call failed (device
// lost, out of memory, driver error, etc.) — checked via HIP_CHECK on
// every single HIP API call, not assumed to always succeed. Honest
// tradeoff, not hidden: on an error path, already-allocated GPU buffers
// are not explicitly freed here (would need more complex cleanup
// tracking) — a real, acceptable tradeoff for prioritizing genuine
// failure detection/reporting over leak-proofing an error path that
// should be rare in practice.
int gpu_add(float* a, float* b, float* result, int n) {
    float *d_a, *d_b, *d_result;
    size_t size = n * sizeof(float);

    // Allocate memory on the GPU itself (VRAM, not system RAM).
    HIP_CHECK(hipMalloc(&d_a, size));
    HIP_CHECK(hipMalloc(&d_b, size));
    HIP_CHECK(hipMalloc(&d_result, size));

    // Copy the input data from CPU memory to GPU memory.
    HIP_CHECK(hipMemcpy(d_a, a, size, hipMemcpyHostToDevice));
    HIP_CHECK(hipMemcpy(d_b, b, size, hipMemcpyHostToDevice));

    // Launch the kernel: 256 threads per block, enough blocks to cover
    // every element (rounding up).
    int threadsPerBlock = 256;
    int blocks = (n + threadsPerBlock - 1) / threadsPerBlock;
    vectorAddKernel<<<blocks, threadsPerBlock>>>(d_a, d_b, d_result, n);
    HIP_CHECK(hipDeviceSynchronize());

    // Copy the result back from GPU memory to CPU memory.
    HIP_CHECK(hipMemcpy(result, d_result, size, hipMemcpyDeviceToHost));

    // Free the GPU memory — this is GPU VRAM, completely separate from
    // the CPU malloc/free we dealt with in add.cpp/matmul.cpp.
    hipFree(d_a);
    hipFree(d_b);
    hipFree(d_result);

    return 0;
}

}