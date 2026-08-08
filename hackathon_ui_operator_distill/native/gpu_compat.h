#pragma once

// Screen-AI GPU compatibility shim.
//
// Methodology:
// - Keep vendor differences here.
// - Keep backend algorithm code vendor-neutral.
// - CPU remains the default path.
//
// This is a scaffold for the later native backend. The current hackathon
// runtime still uses Python/OpenCV/ONNXRuntime first.

#if defined(SCREENAI_USE_HIP) && defined(SCREENAI_USE_CUDA)
#error "SCREENAI_USE_HIP and SCREENAI_USE_CUDA are mutually exclusive"
#endif

#if defined(SCREENAI_USE_HIP)
  #include <hip/hip_runtime.h>
  #define screenaiGpuMalloc hipMalloc
  #define screenaiGpuFree hipFree
  #define screenaiGpuMemcpy hipMemcpy
  #define screenaiGpuMemcpyHostToDevice hipMemcpyHostToDevice
  #define screenaiGpuMemcpyDeviceToHost hipMemcpyDeviceToHost
  #define screenaiGpuDeviceSynchronize hipDeviceSynchronize
  #define screenaiGpuGetLastError hipGetLastError
  #define screenaiGpuGetErrorString hipGetErrorString
  #define SCREENAI_GLOBAL __global__
  #define SCREENAI_SHARED __shared__
  #define SCREENAI_SYNC __syncthreads
#elif defined(SCREENAI_USE_CUDA)
  #include <cuda_runtime.h>
  #define screenaiGpuMalloc cudaMalloc
  #define screenaiGpuFree cudaFree
  #define screenaiGpuMemcpy cudaMemcpy
  #define screenaiGpuMemcpyHostToDevice cudaMemcpyHostToDevice
  #define screenaiGpuMemcpyDeviceToHost cudaMemcpyDeviceToHost
  #define screenaiGpuDeviceSynchronize cudaDeviceSynchronize
  #define screenaiGpuGetLastError cudaGetLastError
  #define screenaiGpuGetErrorString cudaGetErrorString
  #define SCREENAI_GLOBAL __global__
  #define SCREENAI_SHARED __shared__
  #define SCREENAI_SYNC __syncthreads
#else
  #define SCREENAI_CPU_ONLY 1
#endif

