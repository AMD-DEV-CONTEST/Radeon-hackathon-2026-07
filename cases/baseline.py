"""
Baseline workload: non-coalesced memory access pattern.

This simulates a naive HIP port where the thread indexing reads data in
column-major (strided) order. On AMD Radeon hardware, each wavefront of 64
threads issues 64 separate VRAM transactions instead of one coalesced burst.

This is the SLOW version. The agent should diagnose this and propose candidate.py.

Run directly: python baseline.py
Reports: OMNIKERNEL_BENCH_METRICS:{latency_ms, throughput_items_per_sec}
"""

import json
import time

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


def strided_transform_cpu(x: "torch.Tensor") -> "torch.Tensor":
    """
    Element-wise transform with column-major (strided) access pattern.
    Each output[i, j] reads input[j, i] — transposed read with non-contiguous access.
    This is the naive port: works correctly, but inefficient on GPU.
    """
    N, M = x.shape
    out = torch.empty(M, N, device=x.device, dtype=x.dtype)
    for i in range(N):
        for j in range(M):
            out[j, i] = x[i, j] * 1.0  # element-wise no-op transform
    return out


def strided_transform_torch(x: "torch.Tensor") -> "torch.Tensor":
    """
    GPU version using non-contiguous strided operations.
    x.T accesses memory across non-contiguous strides, forcing uncoalesced VRAM fetches.
    """
    x_t = x.T
    return (x_t + x_t).sum(dim=1)


def run_workload(size: int = 2048, warmup: int = 3, runs: int = 10):
    if not HAS_TORCH:
        raise RuntimeError("torch not installed")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    x = torch.randn(size, size, device=device)

    # Warmup
    for _ in range(warmup):
        _ = strided_transform_torch(x)
        if device == "cuda":
            torch.cuda.synchronize()

    # Timed runs
    latencies = []
    for _ in range(runs):
        if device == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()
        out = strided_transform_torch(x)
        if device == "cuda":
            torch.cuda.synchronize()
        end = time.perf_counter()
        latencies.append((end - start) * 1000.0)

    latencies.sort()
    median_ms = latencies[len(latencies) // 2]
    throughput = (size * size) / (median_ms / 1000.0) / 1e9  # Gelems/s

    return median_ms, throughput


if __name__ == "__main__":
    import sys
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
    try:
        latency_ms, throughput = run_workload(size=size)
    except Exception as e:
        print(f"Error: {e}")
        latency_ms, throughput = 0.0, 0.0

    # Emit metrics for the benchmark sandbox to parse
    print("OMNIKERNEL_BENCH_METRICS:" + json.dumps({
        "latency_ms": round(latency_ms, 3),
        "throughput_items_per_sec": round(throughput, 4),
    }))
