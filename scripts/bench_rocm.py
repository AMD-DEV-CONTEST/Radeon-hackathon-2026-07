#!/usr/bin/env python3
"""Benchmark local Transformers latency on AMD Radeon / ROCm (Track 2 scoring)."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    print("=== PrivateLocalAgent · ROCm latency bench ===")
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        print("torch missing:", exc)
        return

    print(f"torch={torch.__version__}")
    print(f"cuda_available={torch.cuda.is_available()}")
    if hasattr(torch.version, "hip"):
        print(f"hip={torch.version.hip}")
    if not torch.cuda.is_available():
        print("No GPU — skip local bench.")
        return

    print(f"device0={torch.cuda.get_device_name(0)}")

    # Matmul microbench
    warm = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
    for _ in range(5):
        _ = warm @ warm
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    times = []
    for _ in range(10):
        a = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
        t0 = time.perf_counter()
        b = a @ a
        torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)
        del b
    print(f"fp16_matmul_2048_avg_ms={statistics.mean(times)*1000:.2f}")

    # Optional LLM roundtrip (uses project config)
    from src.config import load_settings
    from src.llm.backend import build_llm

    settings = load_settings()
    if settings.llm.backend != "local_transformers":
        print("llm.backend is not local_transformers; skip LLM latency.")
        return

    print(f"loading {settings.llm.local_model_id} ...")
    t_load = time.perf_counter()
    llm = build_llm(settings.llm)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    print(f"llm_load_s={time.perf_counter()-t_load:.2f}")

    prompt = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "用一句话介绍 PrivateLocalAgent。"},
    ]
    # warmup
    _ = llm.chat(prompt, max_tokens=64)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    lat = []
    for i in range(3):
        t0 = time.perf_counter()
        out = llm.chat(prompt, max_tokens=64)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        lat.append(dt)
        print(f"llm_round_{i+1}_s={dt:.2f} chars={len(out)}")
    print(f"llm_avg_s={statistics.mean(lat):.2f}")
    if torch.cuda.is_available():
        mem = torch.cuda.max_memory_allocated() / (1024**3)
        print(f"peak_vram_gb={mem:.2f}")
    print("[ok] bench done — paste numbers into docs/AMD_ROCM_OPTIMIZATION.md")


if __name__ == "__main__":
    main()
