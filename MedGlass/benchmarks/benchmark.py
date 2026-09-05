#!/usr/bin/env python3
"""MedGlass GPU benchmark: CPU vs GPU wall-clock for each pipeline stage.

Produces:
    benchmarks/cpu_vs_gpu.json      - all measured timings
    benchmarks/gpu_utilization.png  - GPU VRAM used over time via rocm-smi (if ROCm)
    benchmarks/README.md            - reproducibility notes

Usage:
    python benchmarks/benchmark.py            # full suite
    python benchmarks/benchmark.py --only whisper
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import CONFIG  # noqa: E402
from utils import Timer, detect_gpu, setup_logging, write_json  # noqa: E402

setup_logging()

BENCH_DIR = Path(__file__).resolve().parent

SYNTHETIC_AUDIO = b"\x00\x00" * CONFIG["sample_rate"] * 180  # 180s of silence
DUMMY_IMAGE = None


def speech_like_pcm(seconds: int = 120, sample_rate: int = 16000) -> bytes:
    """Frequency-modulated audio that exercises the full whisper encoder path
    without needing a speech recording (deterministic + fast to generate)."""
    import numpy as np
    t = np.arange(sample_rate * seconds) / sample_rate
    freq = 220 + 80 * np.sin(2 * np.pi * 0.5 * t)
    x = 0.35 * np.sin(2 * np.pi * np.cumsum(freq) / sample_rate)
    x += 0.2 * np.sin(2 * np.pi * 330 * t + np.pi / 3)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def load_dummy_image() -> None:
    global DUMMY_IMAGE
    import cv2
    import numpy as np
    DUMMY_IMAGE = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(DUMMY_IMAGE, (100, 100), (300, 300), (255, 255, 255), -1)


def bench_whisper(label: str) -> dict:
    from audio_handler import WhisperTranscriber
    cfg = dict(CONFIG)
    cfg["whisper_hipblas"] = label == "gpu"
    audio = speech_like_pcm()  # 120s, exercises the full encoder/decoder path
    try:
        t = WhisperTranscriber(cfg)
    except Exception as exc:
        return {"status": "skipped", "reason": str(exc)[:200]}
    results: dict = {}
    with Timer(results, "wall_ms"):
        text = t.transcribe(audio)
    return {"status": "ok", "wall_ms": results["wall_ms"],
            "real_time_factor": round(results["wall_ms"] / (len(audio) // 2) * 1000 / CONFIG["sample_rate"], 3),
            "text_len": len(text)}


def bench_yolo(label: str) -> dict:
    if label == "gpu" and not _rocm_ep_available():
        return {"status": "unavailable",
                "reason": "ROCMExecutionProvider not available "
                          "(onnxruntime-rocm needs libroctracer64.so.4)"}
    from video_handler import VideoProcessor
    import numpy as np
    cfg = dict(CONFIG)
    cfg["yolo_rocm"] = label == "gpu"
    vp = VideoProcessor(cfg)
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    n = 30
    results: dict = {}
    with Timer(results, "total_ms"):
        for _ in range(n):
            vp.process_frame(frame)
    return {"status": "ok", "frames": n,
            "ms_per_frame": round(results["total_ms"] / n, 3),
            "total_ms": results["total_ms"]}


def _rocm_ep_available() -> bool:
    try:
        import onnxruntime as ort
        return "ROCMExecutionProvider" in ort.get_available_providers()
    except ImportError:
        return False


def bench_ocr(label: str) -> dict:
    from video_handler import VideoProcessor
    import numpy as np
    cfg = dict(CONFIG)
    cfg["ocr_rocm"] = label == "gpu"
    vp = VideoProcessor(cfg)
    img = np.zeros((200, 400, 3), dtype=np.uint8)
    try:
        out = vp._read_label(img, (10, 10, 390, 190))
        return {"status": "ok", "text": out[:80]}
    except Exception as exc:
        return {"status": "skipped", "reason": str(exc)[:200]}


def bench_llm(label: str) -> dict:
    from llm_handler import LLMHandler
    cfg = dict(CONFIG)
    # Real CPU vs GPU comparison through the native llama.cpp HIP build:
    # CPU = -ngl 0, GPU = all layers offloaded to the R9700.
    cfg["llm_backend"] = "cli"
    cfg["llama_n_gpu_layers"] = 0 if label == "cpu" else 999
    cfg["llama_max_tokens"] = 128  # keep the CPU run tractable
    cfg["llama_temperature"] = 0.2
    results: dict = {}
    with Timer(results, "wall_ms"):
        try:
            note = LLMHandler(cfg).generate(
                "Doctor: What brings you in? Patient: Headache for 3 days.")
        except Exception as exc:
            return {"status": "skipped", "reason": str(exc)[:200]}
    chars = len(note)
    return {"status": "ok", "wall_ms": results["wall_ms"],
            "gpu_layers": cfg["llama_n_gpu_layers"],
            "tokens_per_sec": round(chars / (results["wall_ms"] / 1000) / 4, 2),
            "note_chars": chars}


def run(only: str | None) -> dict:
    load_dummy_image()
    out: dict = {"gpu": detect_gpu(), "timestamp": time.time(),
                 "stages": {}}
    stages = ["whisper", "yolo", "ocr", "llm"]
    funcs = {"whisper": bench_whisper, "yolo": bench_yolo,
             "ocr": bench_ocr, "llm": bench_llm}
    for stage in stages:
        if only and stage != only:
            continue
        out["stages"][stage] = {}
        for label in ("cpu", "gpu"):
            print(f"[bench] {stage} [{label}]")
            out["stages"][stage][label] = funcs[stage](label)
    return out


def sample_gpu_utilization(seconds: float = 20.0, interval: float = 1.0) -> list[float]:
    """Sample rocm-smi VRAM usage in GiB; returns list. Empty if no ROCm.

    The Radeon AI PRO R9700 (RDNA4/Navi 48) driver does not expose a GPU-busy
    counter (``rocm-smi`` GPU use% stays flat and ``gpu_busy_percent`` returns
    "Operation not supported"), so VRAM used is the reliable live metric.
    """
    import shutil
    import re
    if not shutil.which("rocm-smi"):
        return []
    samples: list[float] = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            out = subprocess.run(["rocm-smi", "-u", "--showmeminfo", "vram"],
                                 capture_output=True, text=True, timeout=5)
            for line in out.stdout.splitlines():
                m = re.search(r"VRAM Total Used Memory \(B\):\s*(\d+)", line)
                if m:
                    samples.append(int(m.group(1)) / (1024 ** 3))
                    break
        except (subprocess.SubprocessError, OSError):
            pass
        time.sleep(interval)
    return samples


def plot_utilization(samples: list[float]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(samples, label="GPU VRAM used", color="#0e7c66", lw=2)
    ax.set_xlabel("sample (1 s apart)")
    ax.set_ylabel("VRAM used (GiB)")
    ax.set_title("MedGlass on ROCm — GPU VRAM used over time")
    ax.legend()
    fig.tight_layout()
    fig.savefig(BENCH_DIR / "gpu_utilization.png", dpi=150)
    print(f"[plot] saved {BENCH_DIR / 'gpu_utilization.png'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MedGlass benchmarks")
    parser.add_argument("--only", choices=["whisper", "yolo", "ocr", "llm"])
    parser.add_argument("--samples", type=float, default=0,
                        help="seconds to sample GPU utilization (0=skip)")
    args = parser.parse_args()

    results = run(args.only)
    out_file = BENCH_DIR / "cpu_vs_gpu.json"
    write_json(out_file, results)
    print(f"[save] {out_file}")

    if args.samples:
        samples = sample_gpu_utilization(args.samples)
        if samples:
            plot_utilization(samples)
        else:
            print("[plot] rocm-smi unavailable; skipped")

    # Quick summary table.
    print("\nSummary (CPU vs GPU):")
    for stage, pair in results["stages"].items():
        cpu = pair.get("cpu", {})
        gpu = pair.get("gpu", {})
        if cpu.get("status") == "ok" and gpu.get("status") == "ok":
            key = "ms_per_frame" if stage == "yolo" else "wall_ms"
            c, g = cpu.get(key), gpu.get(key)
            if c and g:
                speedup = c / g if g else float("inf")
                print(f"  {stage:8s} cpu={c:>9}  gpu={g:>9}  speedup={speedup:5.1f}x")
            else:
                print(f"  {stage:8s} cpu={cpu.get('status')} gpu={gpu.get('status')} "
                      f"(no timing; see JSON)")
        else:
            print(f"  {stage:8s} cpu={cpu.get('status')}  gpu={gpu.get('status')}"
                  f" {gpu.get('reason','')[:40]}")


if __name__ == "__main__":
    main()
