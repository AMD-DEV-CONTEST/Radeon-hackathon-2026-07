from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from argparse import Namespace
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional

from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.vision.model_lifecycle import torch_model_state_sha256


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--torch-home", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--maximum-pairs", type=int)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_frames(
    video: Path,
    maximum_pairs: int | None,
) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise OSError(f"OpenCV could not open {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    maximum_frames = (
        maximum_pairs + 1 if maximum_pairs is not None else None
    )
    frames: list[np.ndarray] = []
    try:
        while maximum_frames is None or len(frames) < maximum_frames:
            success, frame_bgr = capture.read()
            if not success:
                break
            frames.append(
                cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            )
    finally:
        capture.release()
    if fps <= 0 or len(frames) <= 1:
        raise ValueError("SEA-RAFT runtime video has invalid timing or frames")
    return frames, fps


def _inference_pair(
    model: torch.nn.Module,
    arguments: Namespace,
    first: np.ndarray,
    second: np.ndarray,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    image1 = (
        torch.from_numpy(np.ascontiguousarray(first))
        .permute(2, 0, 1)
        .float()
        .unsqueeze(0)
        .to(device)
    )
    image2 = (
        torch.from_numpy(np.ascontiguousarray(second))
        .permute(2, 0, 1)
        .float()
        .unsqueeze(0)
        .to(device)
    )
    scale_factor = 2**arguments.scale
    if scale_factor != 1:
        image1 = functional.interpolate(
            image1,
            scale_factor=scale_factor,
            mode="bilinear",
            align_corners=False,
        )
        image2 = functional.interpolate(
            image2,
            scale_factor=scale_factor,
            mode="bilinear",
            align_corners=False,
        )
    output = model(
        image1,
        image2,
        iters=arguments.iters,
        test_mode=True,
    )
    flow = output["flow"][-1]
    info = output["info"][-1]
    inverse_scale = 1 / scale_factor
    if inverse_scale != 1:
        flow = (
            functional.interpolate(
                flow,
                scale_factor=inverse_scale,
                mode="bilinear",
                align_corners=False,
            )
            * inverse_scale
        )
        info = functional.interpolate(
            info,
            scale_factor=inverse_scale,
            mode="area",
        )
    return flow, info


def _expected_laplace_scale(
    info: torch.Tensor,
    arguments: Namespace,
) -> torch.Tensor:
    raw_log_scale = info[:, 2:]
    log_scale = torch.zeros_like(raw_log_scale)
    log_scale[:, 0] = raw_log_scale[:, 0].clamp(
        min=0,
        max=arguments.var_max,
    )
    log_scale[:, 1] = raw_log_scale[:, 1].clamp(
        min=arguments.var_min,
        max=0,
    )
    mixture_weight = info[:, :2].softmax(dim=1)
    return torch.exp(
        (log_scale * mixture_weight).sum(dim=1, keepdim=True)
    )


def _forward_backward_occlusion(
    forward: torch.Tensor,
    backward: torch.Tensor,
) -> torch.Tensor:
    _, _, height, width = forward.shape
    dtype = forward.dtype
    device = forward.device
    grid_y, grid_x = torch.meshgrid(
        torch.arange(height, device=device, dtype=dtype),
        torch.arange(width, device=device, dtype=dtype),
        indexing="ij",
    )
    destination_x = grid_x.unsqueeze(0) + forward[:, 0]
    destination_y = grid_y.unsqueeze(0) + forward[:, 1]
    valid = (
        (destination_x >= 0)
        & (destination_x <= max(width - 1, 0))
        & (destination_y >= 0)
        & (destination_y <= max(height - 1, 0))
    )
    normalized_x = (
        destination_x * (2 / max(width - 1, 1)) - 1
    )
    normalized_y = (
        destination_y * (2 / max(height - 1, 1)) - 1
    )
    sampling_grid = torch.stack(
        (normalized_x, normalized_y),
        dim=-1,
    )
    sampled_backward = functional.grid_sample(
        backward,
        sampling_grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=True,
    )
    residual = torch.linalg.vector_norm(
        forward + sampled_backward,
        dim=1,
    )
    flow_magnitude = torch.linalg.vector_norm(forward, dim=1)
    threshold = 0.5 + 0.05 * flow_magnitude
    return ((~valid) | (residual > threshold)).float()


def main() -> int:
    requested = _arguments()
    repository = Path(requested.repository).resolve()
    snapshot = Path(requested.snapshot).resolve()
    config_file = Path(requested.config).resolve()
    video = Path(requested.video).resolve()
    torch_home = Path(requested.torch_home).resolve()
    output = Path(requested.output).resolve()
    for required in (repository, snapshot, config_file, video, torch_home):
        if not required.exists():
            raise FileNotFoundError(required)
    if requested.maximum_pairs is not None and requested.maximum_pairs <= 0:
        raise ValueError("maximum-pairs must be positive")
    checkpoint = snapshot / "model.safetensors"
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)

    os.environ["TORCH_HOME"] = str(torch_home)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(repository / "core"))
    from raft import RAFT

    model_arguments = Namespace(
        **json.loads(config_file.read_text(encoding="utf-8"))
    )
    frames, fps = _decode_frames(video, requested.maximum_pairs)
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
    model = RAFT.from_pretrained(
        str(snapshot),
        args=model_arguments,
        local_files_only=True,
    )
    checkpoint_state_sha256 = torch_model_state_sha256(model)
    model.to(device)
    model.eval()
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    model_load_seconds = time.perf_counter() - load_started

    flows: list[np.ndarray] = []
    uncertainties: list[np.ndarray] = []
    occlusions: list[np.ndarray] = []
    pair_seconds: list[float] = []
    inference_started = time.perf_counter()
    with torch.inference_mode():
        for index in range(len(frames) - 1):
            pair_started = time.perf_counter()
            forward, forward_info = _inference_pair(
                model,
                model_arguments,
                frames[index],
                frames[index + 1],
                device,
            )
            backward, _ = _inference_pair(
                model,
                model_arguments,
                frames[index + 1],
                frames[index],
                device,
            )
            uncertainty = _expected_laplace_scale(
                forward_info,
                model_arguments,
            )
            occlusion = _forward_backward_occlusion(
                forward,
                backward,
            )
            if accelerator_enabled:
                torch.cuda.synchronize(device)
            pair_seconds.append(time.perf_counter() - pair_started)
            flows.append(
                forward[0].float().cpu().numpy().astype(
                    np.float32,
                    copy=False,
                )
            )
            uncertainties.append(
                uncertainty[0, 0].float().cpu().numpy().astype(
                    np.float32,
                    copy=False,
                )
            )
            occlusions.append(
                occlusion[0].float().cpu().numpy().astype(
                    np.float32,
                    copy=False,
                )
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

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        flows=np.stack(flows, axis=0),
        uncertainties=np.stack(uncertainties, axis=0),
        occlusions=np.stack(occlusions, axis=0),
        pair_seconds=np.asarray(pair_seconds, dtype=np.float64),
        source_fps=np.asarray(fps, dtype=np.float64),
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
        checkpoint_file_sha256=np.asarray(_sha256(checkpoint)),
        checkpoint_state_sha256=np.asarray(
            checkpoint_state_sha256
        ),
        config_sha256=np.asarray(_sha256(config_file)),
        precision=np.asarray("float32"),
        runtime=np.asarray(device.type),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
