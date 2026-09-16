#!/usr/bin/env python3
"""Reproducible MiniMax H3 benchmark against a running ComfyUI server.

Measures wall time and (optionally) container/process peak memory for each
generation mode. Writes results to a JSON file for reproducible reporting.

Usage:
    python app/bench.py --mode t2v --width 864 --height 480 --duration 5
    python app/bench.py --mode i2v --image assets/frame_1.jpg
    python app/bench.py --mode r2v --image assets/frame_1.jpg assets/frame_2.jpg
    python app/bench.py --all --out benchmarks/run.json

No GPU is required to run: graphs are built and validated against the server's
node registry; if ComfyUI is not reachable the script still validates graph
construction and reports the error clearly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comfy_client import build_prompt, _http_json, API_BASE  # noqa: E402


def _monitor_peak_mem(pid: int, stop: threading.Event, bucket: list) -> None:
    """Sample /proc/<pid>/status VmRSS until stop is set; keep the max in bucket."""
    peak = 0
    while not stop.is_set():
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        peak = max(peak, kb)
                        break
        except Exception:
            pass
        time.sleep(0.2)
    bucket[0] = peak / 1024 / 1024  # GB


def _load_image(path: str) -> np.ndarray:
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def run_one(mode: str, width: int, height: int, duration: float, seed: int,
            images: list, out: str, skip_queue: bool) -> dict:
    kwargs = dict(prompt="benchmark", mode=mode, width=width, height=height,
                  duration_s=duration, seed=seed)
    if mode == "i2v" and images:
        kwargs["first_frame"] = _load_image(images[0])
        if len(images) > 1:
            kwargs["last_frame"] = _load_image(images[1])
    if mode == "r2v" and images:
        kwargs["ref_images"] = [_load_image(im) for im in images]

    graph = build_prompt(**kwargs)

    result = {
        "mode": mode, "width": width, "height": height,
        "duration_s": duration, "seed": seed,
        "graph_nodes": len(graph),
        "frame_length": graph["5"]["inputs"]["length"],
        "status": "graph-built", "wall_s": None, "peak_ram_gb": None,
    }

    # Validate graph against the live server (node registry check) if reachable.
    try:
        stats = _http_json(f"{API_BASE}/system_stats", timeout=10)
        result["comfyui"] = stats["system"]["comfyui_version"]
        # validate by checking node types exist
        registry = _http_json(f"{API_BASE}/object_info", timeout=30)
        node_types = {n["class_type"] for n in graph.values()}
        missing = [t for t in node_types if t not in registry]
        if missing:
            result["status"] = f"missing-nodes: {missing}"
            return result
        result["status"] = "nodes-validated"
    except Exception as e:
        result["status"] = f"server-unreachable ({e})"
        if skip_queue:
            return result

    if skip_queue:
        return result

    pid = os.getpid()
    bucket: list = []
    stop = threading.Event()
    monitor = threading.Thread(target=_monitor_peak_mem, args=(pid, stop, bucket))
    monitor.start()
    t0 = time.time()
    try:
        pid_resp = _http_json(f"{API_BASE}/prompt", {"prompt": graph}, timeout=30)["prompt_id"]
        while True:
            try:
                h = _http_json(f"{API_BASE}/history/{pid_resp}", timeout=30)
            except Exception:
                time.sleep(5)
                continue
            if pid_resp in h:
                st = h[pid_resp].get("status", {})
                result["status"] = st.get("status_str")
                break
            time.sleep(5)
    finally:
        result["wall_s"] = round(time.time() - t0, 1)
        stop.set()
        monitor.join(timeout=3)
        result["peak_ram_gb"] = round(bucket[0], 2) if bucket else None

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["t2v", "i2v", "r2v"])
    ap.add_argument("--width", type=int, default=864)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=556589502035082)
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--all", action="store_true", help="run all three modes")
    ap.add_argument("--out", default=None, help="write results JSON")
    ap.add_argument("--skip-queue", action="store_true",
                    help="validate graphs only, do not submit generation")
    args = ap.parse_args()

    modes = ["t2v", "i2v", "r2v"] if args.all else [args.mode]
    results = []
    for m in modes:
        print(f"--- {m} ({args.width}x{args.height}, {args.duration}s) ---")
        r = run_one(m, args.width, args.height, args.duration, args.seed,
                    args.image, args.out, args.skip_queue)
        print(json.dumps(r, indent=2))
        results.append(r)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
