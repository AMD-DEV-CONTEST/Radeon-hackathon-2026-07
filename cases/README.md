# Signature Demo Case: Memory Coalescing Cliff

## Bottleneck Description

This case demonstrates a **non-coalesced global memory access pattern** — one of the
most common and impactful performance issues when porting CUDA kernels to ROCm/HIP.

### The Setup

A simple custom matrix operation that applies an element-wise transformation.
The naive port has each thread reading a column-major strided element, causing
every wavefront to issue 64 separate memory transactions instead of one coalesced burst.

### Why This Is a Good Demo Case

1. **Non-obvious**: The kernel *looks* correct. It produces the right result.
   The performance issue is purely in the memory access pattern, not the logic.
2. **Measurable**: The speedup from fixing it is consistent and significant (1.5–3x
   depending on tensor size and GPU memory bandwidth).
3. **Arguable**: A developer could reasonably push back — "GPU utilization looks
   fine at 70%, how is this memory-bound?" — giving the agent an opportunity
   to re-examine and explain the difference between utilization and efficiency.
4. **Concise diff**: The fix is one line in the driver code + one index swap in
   the kernel, making it easy to demo the diff proposer.

### Files

| File | Description |
|---|---|
| `baseline.py` | Naive port — strided (column-major) access, slow |
| `candidate.py` | Optimized — row-major coalesced access, fast |
| `hip_kernel_baseline.cpp` | HIP C++ kernel (slow version, for reference) |
| `hip_kernel_candidate.cpp` | HIP C++ kernel (fixed version, for reference) |

### Expected Results on Radeon Hardware

| Configuration | Latency | Throughput |
|---|---|---|
| Baseline (strided) | ~8–12ms for 4096×4096 | Low (memory stalls) |
| Candidate (coalesced) | ~2–4ms for 4096×4096 | ~2–4x higher |

*(Actual numbers depend on Radeon GPU model and VRAM bandwidth)*

### Demo Script

```
You: My HIP matrix kernel is 3x slower than the CUDA version after porting.
     rocm-smi shows 65% GPU utilization.

OmniKernel: [diagnoses memory coalescing]

You: But GPU utilization is 65%! That doesn't seem memory-bound.

OmniKernel: [re-examines] Good pushback. High utilization doesn't rule out
             memory-boundedness — it means the GPU is *busy*, but busy doing
             redundant memory transactions. The profiler shows aten::copy_
             taking 58% of CUDA time with x64 calls per wavefront iteration,
             which is the signature of uncoalesced access: 64 separate cache
             line fetches where 1 would suffice.
```
