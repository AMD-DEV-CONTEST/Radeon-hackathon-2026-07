#!/usr/bin/env python3
"""Sample rocm-smi every POLL_S seconds, log: epoch_ts  vram_used_B  gpu_util_pct.

Run in background; Ctrl-C / kill stops it. Output: one line per sample, easy to
parse for peak VRAM and avg/max GPU utilization over a window.
"""
import json, subprocess, sys, time, os

POLL_S = float(os.environ.get("POLL_S", "2"))
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/notes/gpu_poll.log"
t0 = time.time()
with open(OUT, "w") as f:
    f.write("elapsed_s\tvram_used_B\tgpu_util_pct\n")
    while True:
        try:
            out = subprocess.check_output(
                ["rocm-smi", "--showmeminfo", "vram", "--showuse", "--json"],
                stderr=subprocess.DEVNULL, text=True,
            )
            d = json.loads(out)
            card = d.get("card0", {})
            vram = int(card.get("VRAM Total Used Memory (B)", "0"))
            gpu = int(card.get("GPU use (%)", "0"))
        except Exception as e:
            vram, gpu = -1, -1
        el = time.time() - t0
        f.write(f"{el:.1f}\t{vram}\t{gpu}\n")
        f.flush()
        time.sleep(POLL_S)
