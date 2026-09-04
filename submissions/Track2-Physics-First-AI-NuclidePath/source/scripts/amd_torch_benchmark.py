#!/usr/bin/env python3
"""Small reproducible ROCm/PyTorch benchmark for NuclidePath evidence."""
import json
import platform
import statistics
import time
from datetime import datetime, timezone

import torch

assert torch.cuda.is_available(), "ROCm GPU is not available through PyTorch"
device = torch.device("cuda")
props = torch.cuda.get_device_properties(0)
total_memory = getattr(props, "total_memory", getattr(props, "total_mem", None))


def bench_matmul(n: int, dtype: torch.dtype, repeats: int = 7) -> dict:
    a = torch.randn((n, n), dtype=dtype, device=device)
    b = torch.randn((n, n), dtype=dtype, device=device)
    for _ in range(2):
        torch.mm(a, b)
    torch.cuda.synchronize()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        torch.mm(a, b)
        torch.cuda.synchronize()
        samples.append(time.perf_counter() - start)
    median_s = statistics.median(samples)
    return {
        "operation": "matmul",
        "n": n,
        "dtype": str(dtype).removeprefix("torch."),
        "repeats": repeats,
        "median_ms": median_s * 1000,
        "min_ms": min(samples) * 1000,
        "effective_tflops": (2 * n**3) / median_s / 1e12,
    }


result = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "platform": platform.platform(),
    "python": platform.python_version(),
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "gpu": torch.cuda.get_device_name(0),
    "vram_gb_decimal": total_memory / 1e9 if total_memory else None,
    "benchmarks": [
        bench_matmul(4096, torch.float32),
        bench_matmul(2048, torch.float64),
    ],
}
print(json.dumps(result, indent=2))
