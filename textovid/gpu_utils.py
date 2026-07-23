"""
Textovid — GPU Utilities
Detect GPU, show info, run benchmarks for the 20-point AMD optimization score.
"""

import time
import torch
from typing import Optional, Callable


def get_gpu_info() -> dict:
    """Return a dict with GPU hardware info."""
    info = {
        "cuda_available": torch.cuda.is_available(),
        "device_name": "CPU (no GPU detected)",
        "device_count": 0,
        "vram_total_gb": 0,
        "vram_free_gb": 0,
        "rocm_version": "N/A",
    }
    if torch.cuda.is_available():
        info["device_count"] = torch.cuda.device_count()
        info["device_name"] = torch.cuda.get_device_name(0)
        try:
            props = torch.cuda.get_device_properties(0)
            info["vram_total_gb"] = round(props.total_mem / 1e9, 2)
        except Exception:
            pass
        try:
            info["vram_free_gb"] = round(
                torch.cuda.mem_get_info(0)[0] / 1e9, 2
            )
        except Exception:
            pass
        try:
            info["rocm_version"] = torch.version.hip or "N/A"
        except Exception:
            pass
    return info


def benchmark_image_generation(
    pipeline,
    prompt: str = "a dramatic comic panel, epic lighting, masterpiece",
    negative_prompt: str = "blurry, low quality",
    width: int = 1024,
    height: int = 1024,
    num_images: int = 3,
    steps: int = 25,
    callback: Optional[Callable] = None,
) -> dict:
    """
    Benchmark SDXL inference on the current GPU.
    Returns timing stats.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    generator = torch.Generator(device=device).manual_seed(42)

    # Warm-up run
    if callback:
        callback("Benchmark: warm-up run...")
    t0 = time.time()
    _ = pipeline(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width, height=height,
        num_inference_steps=steps,
        generator=generator,
    )
    warmup_time = time.time() - t0

    # Timed runs
    times = []
    peak_vram = 0
    for i in range(num_images):
        if callback:
            callback(f"Benchmark: run {i+1}/{num_images}...")
        torch.cuda.reset_peak_memory_stats(device) if device == "cuda" else None
        gen = torch.Generator(device=device).manual_seed(42 + i)
        t0 = time.time()
        _ = pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width, height=height,
            num_inference_steps=steps,
            generator=gen,
        )
        elapsed = time.time() - t0
        times.append(elapsed)
        if device == "cuda":
            try:
                pmem = torch.cuda.max_memory_allocated(device) / 1e9
                peak_vram = max(peak_vram, pmem)
            except Exception:
                pass

    return {
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "warmup_seconds": round(warmup_time, 2),
        "runs": num_images,
        "individual_times": [round(t, 2) for t in times],
        "avg_seconds": round(sum(times) / len(times), 2),
        "min_seconds": round(min(times), 2),
        "max_seconds": round(max(times), 2),
        "throughput_img_per_min": round(60 / (sum(times) / len(times)), 2),
        "peak_vram_gb": round(peak_vram, 2),
    }


def format_gpu_status() -> str:
    """Return a human-readable GPU status string for the UI."""
    info = get_gpu_info()
    if not info["cuda_available"]:
        return "⚠️ **No AMD GPU detected** — running on CPU (slow)"

    lines = [
        f"**GPU:** {info['device_name']}",
        f"**VRAM:** {info['vram_free_gb']:.1f} GB free / {info['vram_total_gb']:.1f} GB total",
        f"**ROCm:** {info['rocm_version']}",
    ]
    return "\n".join(lines)