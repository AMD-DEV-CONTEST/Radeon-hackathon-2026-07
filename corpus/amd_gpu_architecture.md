# AMD Radeon GPU Architecture Overview for ROCm Developers

## CDNA vs RDNA Architecture

AMD ships two GPU architectures relevant to ROCm compute workloads:

| Architecture | Target | Examples | Key Feature |
|---|---|---|---|
| CDNA (Compute DNA) | Data center / ML | Instinct MI250X, MI300X | HBM memory, high VRAM bandwidth |
| RDNA (Radeon DNA) | Consumer / Gaming | RX 7900 XTX, RX 7800 XT | GDDR6, lower VRAM bandwidth than CDNA |

For hackathon purposes, Radeon Cloud instances typically use CDNA or high-end RDNA GPUs.

---

## Compute Unit (CU) Structure

Each Compute Unit contains:
- **4 SIMD units** (each executes one wavefront of 64 threads simultaneously)
- **256 KB LDS** (Local Data Share / shared memory) per CU
- **L1 cache**: 16–32 KB per CU
- **Scalar and vector register files**

A single GPU has many CUs (e.g., MI250X has 104 CUs per GCD, 208 total).

### Wavefront Scheduling

The CU hardware maintains a pool of ready wavefronts. When one wavefront
stalls on a memory access, the scheduler immediately switches to another
ready wavefront with zero overhead. This is how GPUs hide memory latency.

**Key insight**: To hide 300ns VRAM latency at 1GHz clock = 300 stall cycles.
If your wavefront uses 100 instructions, you need ~3 other wavefronts ready
to fill those stall cycles. This is why occupancy matters.

---

## Memory Hierarchy

| Level | Size (typical) | Latency | Bandwidth |
|---|---|---|---|
| Vector registers | Per-thread | 1 cycle | Near-infinite |
| LDS (shared memory) | 64 KB per CU (configurable) | ~4–6 cycles | High |
| L1 cache | 16–32 KB per CU | ~10–20 cycles | High |
| L2 cache | 4–32 MB (shared) | ~100–200 cycles | Medium-high |
| HBM/GDDR (VRAM) | 16–192 GB | ~300–800 cycles | High bandwidth, high latency |

### The Roofline Model

A kernel is either:
1. **Compute-bound**: ALU throughput is the bottleneck. Optimization target: reduce arithmetic operations.
2. **Memory-bound**: VRAM bandwidth is the bottleneck. Optimization target: reduce memory traffic (cache better, reduce redundant reads).

To determine which: arithmetic intensity = (FLOPs per byte of VRAM traffic).
- If arithmetic intensity > ridge point → compute-bound
- If arithmetic intensity < ridge point → memory-bound

**AMD CDNA2 (MI250X)**: Ridge point ≈ 200 FLOPs/byte (HBM2e bandwidth)
**AMD RDNA3 (RX 7900 XTX)**: Ridge point ≈ 50–80 FLOPs/byte (GDDR6)

---

## HBM vs GDDR: What Changes Your Optimization Strategy

| Property | HBM (CDNA) | GDDR6 (RDNA) |
|---|---|---|
| Bandwidth | 1–3.2 TB/s | 400–800 GB/s |
| Latency | Slightly lower | Slightly higher |
| Capacity | High (32–192 GB) | Lower (8–24 GB) |

HBM's much higher bandwidth means:
- The ridge point is higher → more kernels are compute-bound on CDNA
- Memory coalescing still matters (non-coalesced access wastes all that bandwidth)
- Occupancy matters less (the GPU can issue more outstanding memory requests)

On RDNA consumer GPUs, memory coalescing and bandwidth efficiency matter more.

---

## Key ROCm-Specific Performance Facts

### 1. Wavefront size = 64 (not 32)
All AMD RDNA/CDNA GPUs execute 64 threads per wavefront. Code tuned for
NVIDIA warps (32 threads) will be functionally correct but potentially
half-occupancy efficient on AMD.

### 2. LDS bank count = 32
LDS is divided into 32 banks. Access patterns that cause multiple threads
in the same wavefront to hit the same bank are serialized.

### 3. Register file is per-thread
VGPR (Vector GP registers) are allocated per thread. Using > 32 VGPRs/thread
reduces the number of wavefronts that can be resident simultaneously.

### 4. Async memory copies
HIP supports asynchronous memory copies between host and device, and between
device memory regions. Use `hipMemcpyAsync` with streams to overlap compute
and memory transfer.

### 5. Unified memory
AMD supports unified memory (accessible from both CPU and GPU) via
`hipMallocManaged`. Performance is generally lower than explicit device
allocation for compute-intensive kernels.

---

## Performance Tuning Checklist for AMD GPU

```
□ Block size is a multiple of 64 (full wavefront utilization)
□ No __shfl operations with NVIDIA 32-thread assumptions
□ Shared memory arrays have padding to avoid bank conflicts
□ Tensors are contiguous before kernel launch
□ VGPR count < 32 per thread for full occupancy (check with rocprof)
□ L2 working set fits within L2 cache for latency-sensitive kernels
□ No synchronization-heavy patterns (each __syncthreads() costs cycles)
□ Kernel fusion applied where two kernels access the same data
□ Async copies used where host-device transfers overlap with compute
```
