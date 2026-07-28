# ROCm Performance Optimization Patterns: Before/After Case Studies

A curated collection of real ROCm/HIP kernel optimization patterns with
before/after analysis. Each case includes the bottleneck signature, the fix,
and the expected performance impact.

---

## Case 1: Memory Coalescing — Matrix Transpose Kernel

### Problem
A naive matrix transpose kernel has each thread read a row and write a column
(or vice versa). This means either the reads or the writes are non-coalesced.

### Signature
- `torch.profiler`: High proportion of time in memory copy operations
- `rocm-smi`: Low GPU utilization (40–60%) despite high memory bandwidth consumption
- `rocprof`: Low L2 cache hit rate, high FETCH_SIZE relative to tensor size

### Before (slow — non-coalesced write):
```cpp
__global__ void transpose_naive(float* out, const float* in, int N, int M) {
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;
    if (row < N && col < M) {
        out[col * N + row] = in[row * M + col];  // ✗ write is non-coalesced
    }
}
```

### After (fast — tiled transpose with shared memory):
```cpp
#define TILE 32
__global__ void transpose_tiled(float* out, const float* in, int N, int M) {
    __shared__ float tile[TILE][TILE + 1];  // +1 avoids bank conflicts
    int x = blockIdx.x * TILE + threadIdx.x;
    int y = blockIdx.y * TILE + threadIdx.y;
    if (x < M && y < N) tile[threadIdx.y][threadIdx.x] = in[y * M + x];
    __syncthreads();
    x = blockIdx.y * TILE + threadIdx.x;
    y = blockIdx.x * TILE + threadIdx.y;
    if (x < N && y < M) out[y * N + x] = tile[threadIdx.x][threadIdx.y];  // ✓ coalesced
}
```

### Impact
- Speedup: 3–8x depending on matrix size and GPU model
- Why: Both reads and writes are now coalesced; the shared memory tile
  handles the data reorganization without VRAM round-trips

---

## Case 2: LDS Bank Conflict — Reduction Kernel

### Problem
A parallel reduction using shared memory where the access stride equals the
bank width, causing all threads to hit the same bank.

### Signature
- `rocprof LDS_BANK_CONFLICT`: High count relative to LDS accesses
- `VALU_STALL_CYCLES`: High (stalled on LDS serialization)
- Performance: Much slower than bandwidth would predict

### Before (bank conflicts on every stride):
```cpp
__global__ void reduce_conflict(float* out, float* in, int n) {
    __shared__ float smem[256];
    int tid = threadIdx.x;
    smem[tid] = in[blockIdx.x * blockDim.x + tid];
    __syncthreads();
    for (int stride = 1; stride < blockDim.x; stride *= 2) {
        if (tid % (2 * stride) == 0) {
            smem[tid] += smem[tid + stride];  // ✗ bank conflicts when stride=32
        }
        __syncthreads();
    }
}
```

### After (sequential addressing eliminates conflicts):
```cpp
__global__ void reduce_no_conflict(float* out, float* in, int n) {
    __shared__ float smem[256];
    int tid = threadIdx.x;
    smem[tid] = in[blockIdx.x * blockDim.x + tid];
    __syncthreads();
    for (int stride = blockDim.x / 2; stride > 0; stride >>= 1) {
        if (tid < stride) {
            smem[tid] += smem[tid + stride];  // ✓ sequential — no conflicts
        }
        __syncthreads();
    }
}
```

### Impact
- Speedup: 1.5–3x for reduction-heavy workloads
- Why: Sequential addressing ensures threads always access different banks

---

## Case 3: Occupancy — Reducing Register Pressure

### Problem
A kernel uses many local variables, causing the compiler to allocate a large
number of vector general-purpose registers (VGPRs). On AMD CDNA2, using
>32 VGPRs per thread reduces wavefront occupancy from 10 to 8 per SIMD.

### Signature
- `rocprof VGPR_USED`: > 32 per thread
- `Occupancy`: < 0.8
- Performance plateaus with larger batch sizes (memory latency not hidden)

### Fix
```cpp
// Add launch bounds hint to guide compiler:
__global__ __launch_bounds__(256, 4)  // max 256 threads/block, min 4 blocks/CU
void my_kernel(float* out, const float* in, int n) {
    // Compiler now knows to limit VGPR usage to maintain this occupancy target
    // ...
}
```

Alternatively, restructure the kernel to reuse variables:
```cpp
// Before: separate variables keep registers alive simultaneously
float a = compute_a(x);
float b = compute_b(x);
float c = compute_c(x);
float result = combine(a, b, c);

// After: compute-and-use avoids keeping all alive at once
float result = combine(compute_a(x), compute_b(x), compute_c(x));
```

### Impact
- Speedup: 1.2–1.8x for memory-latency-bound workloads
- Why: More wavefronts in flight means the GPU can switch to a ready
  wavefront when one stalls on memory, hiding the latency

---

## Case 4: Batch Size Threshold — Memory Bandwidth Cliff

### Problem
Throughput scales well with batch size up to a point, then suddenly degrades.
This happens when the working set exceeds the L2 cache size, causing the
kernel to go from L2-bound to HBM-bound.

### Signature
- `torch.profiler`: Same kernel, same time per element below threshold,
  then significantly higher time per element above it
- `rocm-smi`: VRAM bandwidth saturates (check with `rocprof FETCH_SIZE`)
- Threshold typically aligns with L2 cache size (usually 4–32 MB depending on GPU)

### Investigation:
```python
# Sweep batch sizes to find the cliff:
for size in [256, 512, 1024, 2048, 4096, 8192]:
    latency = measure_kernel_latency(size)
    throughput = size / latency
    print(f"size={size:6d}: {latency:.2f}ms, {throughput:.1f} items/ms")

# Output pattern:
# size=  256:  0.12ms, 2133.3 items/ms
# size=  512:  0.24ms, 2133.3 items/ms  <- linear scaling
# size= 1024:  0.51ms, 2007.8 items/ms  <- slight degradation (L2 pressure)
# size= 2048:  1.82ms, 1124.2 items/ms  <- cliff! L2 eviction dominant
# size= 4096:  7.34ms,  558.0 items/ms  <- fully HBM-bound
```

### Fix — Options:
1. Reduce working set per kernel launch (tile/chunk the input)
2. Fuse adjacent kernels to avoid re-reading from VRAM
3. Restructure data layout for better L2 locality

---

## Case 5: Wavefront Divergence — Branch in Hot Path

### Problem
Conditional branches inside a kernel where threads in the same wavefront take
different paths. All paths execute serially (threads not taking a path are masked).

### Signature
- `rocprof VALU_OPS`: Higher than expected for the amount of useful work
- Performance lower than arithmetic intensity would suggest

### Before:
```cpp
__global__ void process(float* out, const float* in, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (in[i] > 0.0f) {         // ✗ divergent branch
        out[i] = sqrtf(in[i]);  //   half the wavefront takes this
    } else {
        out[i] = 0.0f;          //   other half takes this
    }
}
```

### After (branch-free, both paths execute but no divergence penalty):
```cpp
__global__ void process(float* out, const float* in, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    float val = in[i];
    float result = (val > 0.0f) ? sqrtf(val) : 0.0f;  // ✓ no divergence
    out[i] = result;
}
```

Or sort input data so all "positive" values are processed by one set of blocks
and all "negative" values by another (branch coherence).

### Impact
- Varies widely — can be 1.1x to 4x depending on how unbalanced the branches are

---

## Summary: Pattern → Diagnostic Signal Mapping

| Pattern | rocm-smi Signal | rocprof Signal | torch.profiler Signal |
|---|---|---|---|
| Memory coalescing | Low GPU util (40–70%) | Low L2 hit rate | High copy/memcpy ops |
| LDS bank conflicts | Normal util | High LDS_BANK_CONFLICT | Reduction kernels slow |
| Low occupancy | Utilization plateaus | Low WAVES_IN_FLIGHT, high VGPR | Latency doesn't scale |
| Batch size cliff | GPU util drops at threshold | FETCH_SIZE jumps | Per-element time spikes |
| Wavefront divergence | Moderate util | High VALU_OPS vs useful work | Kernel slower than expected |
