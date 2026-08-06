#!/usr/bin/env python3
"""ROCm hard-evidence smoke for BotverseX (gfx1151 / Strix Halo).

Must be run AFTER:
  source apps/realtime/rocm_env.sh

Expected green output ends with:  SMOKE OK
"""
from __future__ import annotations

import sys
import time


def main() -> int:
    try:
        import torch
    except Exception as e:
        print(f"FAIL: cannot import torch: {e}")
        return 1

    ver = getattr(torch, "__version__", "?")
    hip = getattr(getattr(torch, "version", None), "hip", None)
    print(f"torch    : {ver}")
    print(f"hip      : {hip}")

    if "rocm" not in str(ver).lower() and not hip:
        print("FAIL: this is not a ROCm torch wheel (looks like CUDA/CPU).")
        print("      Reinstall with index https://download.pytorch.org/whl/rocm7.0")
        return 2

    avail = bool(torch.cuda.is_available())
    print(f"available: {avail}")
    if not avail:
        print("FAIL: torch.cuda.is_available() is False.")
        print("      Check: /opt/rocm exists, user in 'render' group, LD_PRELOAD set via rocm_env.sh")
        return 3

    n = torch.cuda.device_count()
    print(f"devices  : {n}")
    name = torch.cuda.get_device_name(0)
    props = torch.cuda.get_device_properties(0)
    arch = getattr(props, "gcnArchName", None) or getattr(props, "name", "?")
    mem_gb = props.total_memory / (1024**3)
    print(f"name     : {name}")
    print(f"gcnArch  : {arch}")
    print(f"memory   : {mem_gb:.1f} GB")

    # Real kernel launch — this is where gfx1151 used to SIGSEGV without LD_PRELOAD.
    a = torch.randn(2048, 2048, device="cuda", dtype=torch.float32)
    b = torch.randn(2048, 2048, device="cuda", dtype=torch.float32)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    iters = 20
    for _ in range(iters):
        c = a @ b
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / iters
    flops = 2 * (2048**3) / dt / 1e9
    print(f"matmul 2048^2 x{iters} = {dt * 1000:.2f} ms/iter  ({flops:.1f} GFLOPs)")
    print(f"result checksum: {float(c[0, 0]):.6f}")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
