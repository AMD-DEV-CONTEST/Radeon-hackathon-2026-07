// Measure achievable streaming read bandwidth on GPU0 = the decode-GEMV ceiling.
// Our GEMV kernels stream the weight matrix once (M=1), so their effective GB/s
// cannot exceed this. Tells us how much headroom is left => is anything better possible.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <vector>

__global__ void stream_read(const float4* __restrict__ in, float* __restrict__ out, size_t n4) {
    size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    size_t stride = (size_t)gridDim.x * blockDim.x;
    float4 acc = {0,0,0,0};
    for (; i < n4; i += stride) { float4 v = in[i]; acc.x+=v.x; acc.y+=v.y; acc.z+=v.z; acc.w+=v.w; }
    if (acc.x==-1.0f) out[0]=acc.x+acc.y+acc.z+acc.w;   // keep, prevent DCE
}

int main() {
    size_t bytes = (size_t)512*1024*1024;   // 512 MB
    size_t n4 = bytes / sizeof(float4);
    float4* d_in; float* d_out;
    hipMalloc(&d_in, bytes); hipMalloc(&d_out, 16);
    hipMemset(d_in, 1, bytes);
    int th = 256, bl = 4096;
    for (int w=0; w<5; ++w) stream_read<<<bl,th>>>(d_in, d_out, n4);
    hipDeviceSynchronize();
    hipEvent_t s,e; hipEventCreate(&s); hipEventCreate(&e);
    int it = 50; hipEventRecord(s);
    for (int i=0;i<it;++i) stream_read<<<bl,th>>>(d_in, d_out, n4);
    hipEventRecord(e); hipEventSynchronize(e);
    float ms=0; hipEventElapsedTime(&ms,s,e); ms/=it;
    printf("Streaming READ: %.3f ms for %zu MB => %.0f GB/s (achievable roofline)\n",
           ms, bytes>>20, bytes/(ms*1e6));
    return 0;
}
