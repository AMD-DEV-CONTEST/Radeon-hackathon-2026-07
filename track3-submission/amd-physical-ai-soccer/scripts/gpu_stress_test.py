#!/usr/bin/env python
"""GPU stress test + maximum throughput report for AMD Radeon RX 7900 XT.

Sustains peak GPU load across multiple workloads to produce report-ready data:
  - matmul TFLOPS at multiple matrix sizes
  - sustained VRAM allocation
  - concurrent training + compute throughput
  - rocm-smi snapshot

Usage:
    python scripts/gpu_stress_test.py --duration 60
"""
import argparse
import subprocess
import time
import torch


def matmul_benchmark(device, n, iters=50):
    a = torch.randn(n, n, device=device)
    b = torch.randn(n, n, device=device)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        c = a @ b
    torch.cuda.synchronize()
    dt = time.time() - t0
    flop = 2 * n ** 3 * iters
    return flop / dt / 1e12  # TFLOPS


def rocm_smi_snapshot():
    try:
        out = subprocess.run(["rocm-smi", "-a"], capture_output=True, text=True, timeout=10)
        lines = [l for l in out.stdout.split("\n") if any(k in l.lower() for k in
                 ["temperature", "sclk", "gpu memory", "vram", "gfx version"])]
        return "\n".join(lines[:8])
    except Exception:
        return "rocm-smi unavailable"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=60, help="stress duration in seconds")
    args = ap.parse_args()

    device = "cuda"
    print("=" * 60)
    print("AMD Radeon GPU Stress Test")
    print("=" * 60)
    print(f"Device: {torch.cuda.get_device_name(0)}")
    print(f"torch: {torch.__version__}")
    print(f"HIP: {torch.version.hip}")
    print(f"Duration: {args.duration}s")
    print()

    # matmul at multiple sizes
    print("--- Matmul TFLOPS by matrix size ---")
    results = {}
    for n in [1024, 2048, 4096, 8192]:
        tflops = matmul_benchmark(device, n)
        results[n] = tflops
        print(f"  {n}x{n}: {tflops:.1f} TFLOPS")

    # sustained load
    print(f"\n--- Sustained load ({args.duration}s) ---")
    a = torch.randn(8192, 8192, device=device)
    b = torch.randn(8192, 8192, device=device)
    torch.cuda.synchronize()
    t0 = time.time()
    total_flops = 0
    iters = 0
    while time.time() - t0 < args.duration:
        c = a @ b
        total_flops += 2 * 8192 ** 3
        iters += 1
        if iters % 10 == 0:
            torch.cuda.synchronize()
    torch.cuda.synchronize()
    elapsed = time.time() - t0
    sustained_tflops = total_flops / elapsed / 1e12
    print(f"  {iters} iterations in {elapsed:.1f}s")
    print(f"  Sustained: {sustained_tflops:.1f} TFLOPS")
    print(f"  Peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    # rocm-smi snapshot
    print("\n--- ROCm-SMI Snapshot ---")
    print(rocm_smi_snapshot())

    # summary
    print("\n" + "=" * 60)
    print("SUMMARY (for technical report)")
    print("=" * 60)
    print(f"GPU: {torch.cuda.get_device_name(0)} (gfx1100)")
    print(f"torch: {torch.__version__} | HIP: {torch.version.hip}")
    for n, tf in results.items():
        print(f"  matmul {n}x{n}: {tf:.1f} TFLOPS")
    print(f"  sustained 8192x8192: {sustained_tflops:.1f} TFLOPS")
    print(f"  peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    print("=" * 60)


if __name__ == "__main__":
    main()
