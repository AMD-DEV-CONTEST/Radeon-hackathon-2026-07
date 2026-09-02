from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.vision.model_lifecycle import torch_model_state_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", required=True, type=float)
    parser.add_argument("--input-size", required=True, type=int)
    arguments = parser.parse_args()

    repository = Path(arguments.repository).resolve()
    sys.path.insert(0, str(repository))
    from video_depth_anything.video_depth import VideoDepthAnything

    with np.load(Path(arguments.input).resolve(), allow_pickle=False) as payload:
        frames = np.asarray(payload["frames"], dtype=np.uint8)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    accelerator_enabled = device.type == "cuda"
    if accelerator_enabled:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
        torch.cuda.synchronize(device)
        baseline_allocated = torch.cuda.memory_allocated(device)
    else:
        baseline_allocated = 0

    load_started = time.perf_counter()
    model = VideoDepthAnything(
        encoder="vits",
        features=64,
        out_channels=[48, 96, 192, 384],
    )
    state = torch.load(
        Path(arguments.checkpoint).resolve(),
        map_location="cpu",
        weights_only=True,
    )
    model.load_state_dict(state, strict=True)
    model = model.to(device).eval()
    checkpoint_state_sha256 = torch_model_state_sha256(model)
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    model_load_seconds = time.perf_counter() - load_started

    inference_started = time.perf_counter()
    depths, _ = model.infer_video_depth(
        frames,
        arguments.fps,
        input_size=arguments.input_size,
        device=str(device),
        fp32=device.type == "cpu",
    )
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    inference_seconds = time.perf_counter() - inference_started
    peak_gpu_memory_mb = (
        float(torch.cuda.max_memory_allocated(device) / (1024 * 1024))
        if accelerator_enabled
        else 0.0
    )
    memory_growth_mb = (
        float(
            max(
                0,
                torch.cuda.memory_allocated(device) - baseline_allocated,
            )
            / (1024 * 1024)
        )
        if accelerator_enabled
        else 0.0
    )
    np.savez_compressed(
        Path(arguments.output).resolve(),
        depths=np.asarray(depths, dtype=np.float32),
        model_load_seconds=np.asarray(
            model_load_seconds,
            dtype=np.float64,
        ),
        inference_seconds=np.asarray(
            inference_seconds,
            dtype=np.float64,
        ),
        peak_cpu_memory_mb=np.asarray(
            process_peak_memory_mb(),
            dtype=np.float64,
        ),
        peak_gpu_memory_mb=np.asarray(
            peak_gpu_memory_mb,
            dtype=np.float64,
        ),
        memory_growth_mb=np.asarray(
            memory_growth_mb,
            dtype=np.float64,
        ),
        checkpoint_state_sha256=np.asarray(
            checkpoint_state_sha256
        ),
        runtime=np.asarray(device.type),
        device_name=np.asarray(
            torch.cuda.get_device_name(device)
            if accelerator_enabled
            else "CPU"
        ),
        precision=np.asarray(
            "float16-autocast"
            if accelerator_enabled
            else "float32"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
