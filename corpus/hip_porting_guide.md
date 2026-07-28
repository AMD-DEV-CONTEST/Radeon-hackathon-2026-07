# HIP Porting Guide: CUDA to HIP API Mapping and Key Differences

## Overview

HIP (Heterogeneous-Compute Interface for Portability) provides a C++ runtime API
that runs on AMD Radeon GPUs via ROCm. Most CUDA code can be ported mechanically
using the `hipify` tool, but performance-equivalent ports require understanding
the architectural differences between NVIDIA and AMD hardware.

---

## CUDA → HIP API Mapping (Common Patterns)

| CUDA | HIP | Notes |
|---|---|---|
| `cudaMalloc` | `hipMalloc` | Identical semantics |
| `cudaMemcpy` | `hipMemcpy` | Identical semantics |
| `cudaFree` | `hipFree` | Identical semantics |
| `__syncthreads()` | `__syncthreads()` | Same — synchronizes a block |
| `threadIdx`, `blockIdx`, `blockDim` | Same | Identical |
| `__shared__` | `__shared__` | Identical |
| `atomicAdd` | `atomicAdd` | Identical |
| `cudaDeviceSynchronize` | `hipDeviceSynchronize` | Identical |
| `CUDA_VISIBLE_DEVICES` | `ROCR_VISIBLE_DEVICES` | Env var changes! |
| `cudaEventRecord` | `hipEventRecord` | Identical semantics |
| `cudaStreamCreate` | `hipStreamCreate` | Identical |

---

## Critical Architectural Difference: Warp vs. Wavefront Size

**This is the #1 source of silent performance regressions after porting.**

| Property | NVIDIA GPU | AMD RDNA/CDNA |
|---|---|---|
| SIMD execution unit | Warp (32 threads) | Wavefront (64 threads) |
| Threads per unit | 32 | 64 |

### What this means for your kernels

Code that assumes 32-thread warps will be functionally correct on AMD but may
underperform. Common patterns that silently break:

**1. Warp-level primitives:**
```cpp
// CUDA (warp = 32 threads)
__shfl_down_sync(0xffffffff, val, 16);  // reduce across 32

// HIP (wavefront = 64 threads) — must use full mask
__shfl_down(val, 32);  // reduce across 64
```

**2. Block sizes that are multiples of 32 but not 64:**
```cpp
// This leaves half a wavefront idle on AMD:
dim3 block(32, 1, 1);  // NVIDIA: full warp | AMD: half wavefront

// Better for AMD:
dim3 block(64, 1, 1);  // full wavefront utilization
```

**3. Shared memory sizing:**
Designs that allocate exactly 32 elements per warp for reductions need to
be doubled for AMD (64 elements per wavefront).

---

## Memory Coalescing on AMD CDNA/RDNA

Memory coalescing means adjacent threads in the same wavefront access adjacent
memory addresses, so the hardware can serve the entire wavefront with one (or
few) cache line fetches.

### Coalesced (fast):
```cpp
// Thread i accesses element i — stride 1
int idx = blockIdx.x * blockDim.x + threadIdx.x;
output[idx] = input[idx] * scale;  // ✓ coalesced
```

### Non-coalesced (slow):
```cpp
// Each thread accesses a different row — stride = width
int row = threadIdx.x;
int col = blockIdx.x;
output[col * height + row] = input[col * height + row];  // ✗ column-major
```

### The fix (for PyTorch-level code):
```python
# Non-contiguous (causes uncoalesced kernel reads):
x_t = x.T  # view — memory layout unchanged

# Contiguous (coalesced):
x_t = x.T.contiguous()  # materializes row-major layout
```

### Rule of thumb:
If your kernel reads a 2D tensor column-by-column (varying the first dimension
fastest), it will be non-coalesced. Restructure so threadIdx.x maps to the
fastest-varying dimension of the array.

---

## LDS (Local Data Share) Bank Conflicts

LDS is the AMD equivalent of NVIDIA shared memory. On AMD RDNA/CDNA, LDS is
organized into **32 banks** (on most hardware). If multiple threads in the same
wavefront access the same bank simultaneously, the accesses are **serialized**.

### Conflict-free access:
```cpp
// Each thread accesses a different bank:
__shared__ float smem[64];
int tid = threadIdx.x;
smem[tid] = input[...];  // thread 0→bank0, thread1→bank1, ... ✓
```

### Bank conflict (32-way):
```cpp
// All 32 threads in the same half-wavefront access the same bank:
__shared__ float smem[32];
int tid = threadIdx.x;
smem[tid * 32 % 32] = ...;  // all map to bank 0 → serialized ✗
```

### Fix — add padding:
```cpp
// Add +1 padding to stride accesses across banks:
__shared__ float smem[64][33];  // +1 avoids bank conflicts for 32-wide access
// Instead of:
__shared__ float smem[64][32];
```

---

## Occupancy and Wavefront Scheduling

**Occupancy** = (active wavefronts on CU) / (maximum wavefronts on CU)

High occupancy allows the GPU to hide memory latency by switching between
ready wavefronts. Low occupancy means the GPU stalls waiting for memory.

### Occupancy limiters (in priority order):

1. **Register usage per thread**: More registers → fewer wavefronts can be
   resident simultaneously. Check with `rocprof --stats`.

2. **LDS (shared memory) per block**: More LDS per block → fewer blocks per CU.

3. **Block size**: Very small blocks (< 64 threads) waste wavefront slots.

### Checking occupancy:
```bash
rocprof --stats -o output.csv python workload.py
# Look for: Occupancy, VGPR (vector registers), LDS usage
```

### The `__launch_bounds__` hint:
```cpp
// Tell the compiler to limit register usage to increase occupancy:
__global__ __launch_bounds__(256, 4)  // maxThreadsPerBlock=256, minBlocksPerCU=4
void my_kernel(...) { ... }
```

---

## Common ROCm Port Checklist

- [ ] Replace all `cuda*` prefixes with `hip*`
- [ ] Change `CUDA_VISIBLE_DEVICES` to `ROCR_VISIBLE_DEVICES`
- [ ] Audit block sizes: prefer multiples of 64 (wavefront size), not 32
- [ ] Check shared memory array sizes: may need doubling for 64-thread wavefronts
- [ ] Audit __shfl_* calls: update masks from 0xffffffff (32-bit) to full 64-thread mask
- [ ] Check for `.T` (transpose) operations followed by GPU kernels — add `.contiguous()`
- [ ] Run with `rocprof --stats` to check occupancy before/after
