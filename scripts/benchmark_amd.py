#!/usr/bin/env python3
"""
AMD Radeon / ROCm performance benchmark for the Indie Game Asset Studio.

Submits W1-W6 jobs through the real web API (FastAPI -> ComfyUI), polls them to
completion, and samples ROCm GPU metrics (utilization / VRAM / temp / power)
every second while each workflow runs.

Usage:
    API=http://127.0.0.1:8000 \
    ROCM_SMI=rocm-smi \
    python3 scripts/benchmark_amd.py [--out deliverables/perf/benchmark.json]

Requires: the web backend and ComfyUI to be running, and httpx in the venv.
"""
import argparse
import json
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
POLL_SECONDS = 1.5
SAMPLE_SECONDS = 1.0

ROOT = Path(__file__).resolve().parents[1]
DEMO_BATCH = ROOT / "assets" / "demo" / "废土酒吧_演示批次"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def submit_job(client: httpx.Client, workflow: str, params: dict, batch: str, image_path: Path | None = None):
    files = {}
    data = {"workflow": workflow, "params": json.dumps(params, ensure_ascii=False), "batch": batch}
    if image_path is not None:
        files["image"] = ("input.png", image_path.read_bytes(), "image/png")
    resp = client.post(f"{API}/api/jobs", data=data, files=files, timeout=120)
    resp.raise_for_status()
    return resp.json()


def poll_until_done(client: httpx.Client, job_id: str) -> dict:
    while True:
        resp = client.get(f"{API}/api/jobs/{job_id}", timeout=60)
        resp.raise_for_status()
        job = resp.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(POLL_SECONDS)


def exact_execution_time(client: httpx.Client, prompt_id: str) -> float | None:
    """Use ComfyUI /history timestamps for exact GPU execution wall time."""
    try:
        resp = client.get(f"{API.replace(':8000', ':8188')}/history/{prompt_id}", timeout=30)
        item = resp.json().get(prompt_id)
        if not item:
            return None
        stamps = {}
        for msg in item.get("status", {}).get("messages", []):
            if msg[0] in ("execution_start", "execution_success", "execution_error"):
                stamps[msg[0]] = msg[1].get("timestamp", 0)
        if "execution_start" in stamps and ("execution_success" in stamps or "execution_error" in stamps):
            end = stamps.get("execution_success") or stamps.get("execution_error")
            return (end - stamps["execution_start"]) / 1000.0
    except Exception:
        return None
    return None


class RocmSampler:
    def __init__(self, rocm_smi: str):
        self.rocm_smi = rocm_smi
        self.samples = []
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.samples = []
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                out = subprocess.run(
                    shlex.split(self.rocm_smi)
                    + ["--showuse", "--showmeminfo", "vram", "--showtemp", "--showpower"],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                self.samples.append({"t": now_iso(), "raw": out.strip()})
            except Exception:
                pass
            time.sleep(max(0.0, SAMPLE_SECONDS - (time.monotonic() - t0)))

    def stop(self) -> list[dict]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)
        return self.samples

    def summarize(self) -> dict:
        gpu_use, vram_used, temp, power = [], [], [], []
        for s in self.samples:
            try:
                gpu_use.append(float(s["raw"].split("GPU use (%):")[1].split()[0]))
            except Exception:
                pass
            try:
                vram_used.append(int(s["raw"].split("VRAM Total Used Memory (B):")[1].split()[0]))
            except Exception:
                pass
            try:
                temp.append(float(s["raw"].split("Temperature (Sensor edge) (C):")[1].split()[0]))
            except Exception:
                pass
            try:
                power.append(float(s["raw"].split("Average Graphics Package Power (W):")[1].split()[0]))
            except Exception:
                pass
        return {
            "gpu_use_pct": {"max": max(gpu_use) if gpu_use else None, "avg": round(sum(gpu_use) / len(gpu_use), 1) if gpu_use else None},
            "vram_used_bytes": {"max": max(vram_used) if vram_used else None},
            "temperature_c": {"max": max(temp) if temp else None},
            "power_w": {"max": max(power) if power else None},
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "deliverables" / "perf" / "benchmark.json"))
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--rocm-smi", default="rocm-smi")
    args = ap.parse_args()
    global API
    API = args.api

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_path.with_suffix(".log")
    log = open(log_path, "w", encoding="utf-8")

    def log_line(text: str):
        line = f"[{now_iso()}] {text}"
        print(line)
        log.write(line + "\n")
        log.flush()

    client = httpx.Client(timeout=120)
    sampler = RocmSampler(args.rocm_smi)
    results = {"started_at": now_iso(), "api": API, "jobs": [], "system": {}}

    try:
        stats = client.get("http://127.0.0.1:8188/system_stats", timeout=10).json()
        results["system"] = {"devices": stats.get("devices"), "system": stats.get("system")}
    except Exception as exc:
        log_line(f"WARN: could not read ComfyUI stats: {exc}")

    # (workflow, params, batch, image) - character sheet feeds W2/W3/W6
    char_sheet = DEMO_BATCH / "06_角色设定图_W1.png"
    runs = [
        ("W1", {"text": "interior of a wasteland style bar, post-apocalyptic saloon, dark moody atmosphere, neon signs glow, metal bar counter with rusty pipes, dusty glass bottles, makeshift furniture, cinematic rim lighting, gritty textures, highly detailed 2d game concept art background", "negative": "blurry, low quality, deformed, watermark, text, oversaturated, cartoon", "width": 1024, "height": 1024, "seed": 20260806, "steps": 25, "cfg": 7}, "perf_benchmark", None),
        ("W2", {"resolution": 512}, "perf_benchmark", char_sheet),
        ("W3", {"resolution": 512, "strength": 2.0, "roughness_scale": 1.0, "metalness": 0.6}, "perf_benchmark", char_sheet),
        ("W4", {"prompt": "dark ambient electronic music, industrial, heavy metal clanking percussion, ominous, slow tempo, underground bar atmosphere", "duration": 8.0, "seed": 777}, "perf_benchmark", None),
        ("W5", {"kind": "glass_clink", "duration": 4.0, "seed": 123}, "perf_benchmark", None),
        ("W6", {"text": "full body 2d game character sprite, side view, running action pose, clean background, cel shading, game asset, consistent character design", "negative": "blurry, low quality, deformed, watermark, text, multiple characters, extra limbs", "action": "run", "frames": 8, "width": 512, "height": 512, "seed": 20260808, "steps": 20, "cfg": 7, "denoise": 0.55, "strength": 0.85}, "perf_benchmark", char_sheet),
    ]

    for workflow, params, batch, image in runs:
        log_line(f"=== {workflow} starting: {json.dumps(params, ensure_ascii=False)[:120]}")
        sampler.start()
        t_start = time.monotonic()
        wall_start = now_iso()
        job = submit_job(client, workflow, params, batch, image)
        job_id = job["id"]
        log_line(f"{workflow} job_id={job_id} prompt_id={job.get('prompt_id')} submitted")
        done = poll_until_done(client, job_id)
        wall_seconds = time.monotonic() - t_start
        gpu_samples = sampler.stop()
        gpu_summary = sampler.summarize()
        exec_seconds = exact_execution_time(client, done.get("prompt_id") or "")
        log_line(f"{workflow} status={done['status']} wall={wall_seconds:.1f}s exec={exec_seconds} outputs={len(done.get('outputs') or [])}")
        if done["status"] == "error":
            log_line(f"{workflow} ERROR: {done.get('error')}")
        results["jobs"].append({
            "workflow": workflow,
            "job_id": job_id,
            "prompt_id": done.get("prompt_id"),
            "params": params,
            "status": done["status"],
            "error": done.get("error"),
            "wall_seconds": round(wall_seconds, 1),
            "execution_seconds": exec_seconds,
            "wall_start": wall_start,
            "outputs": done.get("outputs", []),
            "gpu": gpu_summary,
            "samples": gpu_samples,
        })
        json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    results["finished_at"] = now_iso()
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log_line(f"Benchmark complete -> {out_path}")
    log.close()


if __name__ == "__main__":
    main()
