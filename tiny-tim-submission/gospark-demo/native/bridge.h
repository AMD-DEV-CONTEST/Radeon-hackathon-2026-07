#ifndef GOSPARK_DEMO_BRIDGE_H
#define GOSPARK_DEMO_BRIDGE_H

// Real C ABI declarations for the AMD-history demo trainer's HIP
// kernels. Note a real, preserved inconsistency from the original
// kernels: gpu_add uses float, everything else uses double -- kept
// exactly as the real, proven kernels already work, not "fixed" for
// cosmetic consistency.

#ifdef __cplusplus
extern "C" {
#endif

int gpu_add(float* a, float* b, float* result, int n);

int gpu_matmul(double* a, double* b, double* result, int m, int n, int p);

int gpu_relu(double* input, double* result, int n);

int gpu_softmax(double* input, double* result, int rows, int cols);

int gpu_layernorm(double* x, double* gamma, double* beta,
                   double* output, double* xhatOut, double* stdInvOut,
                   int rows, int cols, double eps);

#ifdef __cplusplus
}
#endif

#endif