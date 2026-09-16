#!/usr/bin/env python3
"""Timed T2V benchmark against a running ComfyUI MiniMax H3 server.

Usage:
    python app/bench_t2v.py --width 864 --height 480 --duration 2 --seed 42
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from comfy_client import build_prompt, _http_json, API_BASE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=864)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--prompt", default=(
        "Cinematic drone shot flying over a neon cyberpunk city at dusk, "
        "rain-slick streets reflecting holographic signs, volumetric fog, "
        "slow sweeping camera, subtle wind and distant traffic sound."
    ))
    args = ap.parse_args()

    p = build_prompt(
        args.prompt, mode="t2v", width=args.width, height=args.height,
        duration_s=args.duration, seed=args.seed,
    )
    pid = _http_json(f"{API_BASE}/prompt", {"prompt": p}, timeout=30)["prompt_id"]
    start = time.time()
    while True:
        try:
            h = _http_json(f"{API_BASE}/history/{pid}", timeout=30)
        except Exception:
            time.sleep(5)
            continue
        if pid in h:
            st = h[pid].get("status", {})
            elapsed = round(time.time() - start, 1)
            print(f"status={st.get('status_str')} elapsed_s={elapsed}")
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
