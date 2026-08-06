#!/usr/bin/env python3
"""SDXL 1024x1024 text-to-image benchmark via ComfyUI API.

POSTs the SDXL workflow to the running ComfyUI instance, waits for the
generation to finish, and reports per-run wall time plus peak VRAM usage
sampled from `rocm-smi` during inference.

Usage:
    python sdxl_benchmark.py [runs] [--url http://127.0.0.1:8188] [--workflow ...]
"""
import argparse
import json
import subprocess
import threading
import time
import urllib.request


def api_post(url, path, payload):
    req = urllib.request.Request(url + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get(url, path):
    with urllib.request.urlopen(url + path) as resp:
        return json.loads(resp.read())


def vram_used_bytes():
    out = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "Used Memory" in line:
            return int(line.split(":")[-1].strip().replace(",", ""))
    return 0


def vram_monitor(stop, result):
    peak = 0
    while not stop.is_set():
        try:
            peak = max(peak, vram_used_bytes())
        except Exception:
            pass
        time.sleep(0.2)
    result.append(peak)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", type=int, nargs="?", default=3)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--workflow", default="/workspace/sdxl_project/workflows/sdxl_base_1.0_workflow.json")
    args = ap.parse_args()

    with open(args.workflow) as f:
        workflow = json.load(f)

    print(f"ComfyUI: {args.url}")
    print(f"Workflow: {args.workflow} (SDXL base 1.0, 1024x1024, 20 steps)")
    print("=" * 60)

    times, peaks = [], []
    base_seed = int(time.time() * 1000) % 2147483647
    for i in range(args.runs):
        workflow["3"]["inputs"]["seed"] = base_seed + i
        prompt_id = api_post(args.url, "/prompt", {"prompt": workflow})["prompt_id"]

        stop = threading.Event()
        peak_out = []
        t = threading.Thread(target=vram_monitor, args=(stop, peak_out))
        t.start()

        start = time.time()
        while True:
            hist = api_get(args.url, f"/history/{prompt_id}")
            if prompt_id in hist and hist[prompt_id].get("status", {}).get("completed"):
                break
            time.sleep(0.5)
        elapsed = time.time() - start

        stop.set()
        t.join()
        peak = peak_out[0] if peak_out else 0
        times.append(elapsed)
        peaks.append(peak)
        print(f"run {i+1}: {elapsed:.2f}s  peak VRAM {peak / 1024**3:.2f} GB")

    print("=" * 60)
    print(f"average time : {sum(times) / len(times):.2f}s")
    print(f"max time     : {max(times):.2f}s")
    print(f"min time     : {min(times):.2f}s")
    print(f"peak VRAM    : {max(peaks) / 1024**3:.2f} GB")
    print(f"VRAM idle    : {vram_used_bytes() / 1024**3:.2f} GB")


if __name__ == "__main__":
    main()
