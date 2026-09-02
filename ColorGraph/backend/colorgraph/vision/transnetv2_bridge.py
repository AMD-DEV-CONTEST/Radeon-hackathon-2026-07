from __future__ import annotations

import argparse
import hashlib
import importlib.util
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.vision.model_lifecycle import torch_model_state_sha256


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_model_type(repository: Path):
    code = repository / "inference-pytorch" / "transnetv2_pytorch.py"
    if not code.is_file():
        raise FileNotFoundError(code)
    specification = importlib.util.spec_from_file_location(
        "colorgraph_official_transnetv2",
        code,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load official TransNetV2 PyTorch code")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.TransNetV2


def _decode_frames(video: Path) -> tuple[np.ndarray, float]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise OSError(f"OpenCV could not open {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[np.ndarray] = []
    try:
        while True:
            success, frame_bgr = capture.read()
            if not success:
                break
            resized = cv2.resize(
                frame_bgr,
                (48, 27),
                interpolation=cv2.INTER_AREA,
            )
            frames.append(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    if fps <= 0 or len(frames) <= 1:
        raise ValueError("TransNetV2 video has invalid timing or frames")
    return np.stack(frames).astype(np.uint8, copy=False), fps


def _windows(frames: np.ndarray):
    remainder = len(frames) % 50
    end_padding = 25 + 50 - (remainder if remainder else 50)
    padded = np.concatenate(
        (
            np.repeat(frames[:1], 25, axis=0),
            frames,
            np.repeat(frames[-1:], end_padding, axis=0),
        ),
        axis=0,
    )
    pointer = 0
    while pointer + 100 <= len(padded):
        yield padded[pointer : pointer + 100][None]
        pointer += 50


def _positive_run_peaks(
    probabilities: np.ndarray,
    threshold: float,
) -> np.ndarray:
    positive = np.asarray(probabilities > threshold, dtype=bool)
    boundaries: list[int] = []
    index = 0
    while index < len(positive):
        if not positive[index]:
            index += 1
            continue
        end = index + 1
        while end < len(positive) and positive[end]:
            end += 1
        peak = index + int(np.argmax(probabilities[index:end]))
        boundaries.append(peak)
        index = end
    return np.asarray(boundaries, dtype=np.int32)


def main() -> int:
    requested = _arguments()
    repository = Path(requested.repository).resolve()
    checkpoint = Path(requested.checkpoint).resolve()
    video = Path(requested.video).resolve()
    output = Path(requested.output).resolve()
    if not 0 < requested.threshold < 1:
        raise ValueError("threshold must be between zero and one")
    for required in (repository, checkpoint, video):
        if not required.exists():
            raise FileNotFoundError(required)

    frames, source_fps = _decode_frames(video)
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
    model_type = _load_model_type(repository)
    model = model_type()
    state_dict = torch.load(
        checkpoint,
        map_location="cpu",
        weights_only=True,
    )
    model.load_state_dict(state_dict, strict=True)
    checkpoint_state_sha256 = torch_model_state_sha256(model)
    model = model.to(device).eval()
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    model_load_seconds = time.perf_counter() - load_started

    single_predictions: list[np.ndarray] = []
    all_predictions: list[np.ndarray] = []
    batch_seconds: list[float] = []
    inference_started = time.perf_counter()
    with torch.inference_mode():
        for window in _windows(frames):
            batch_started = time.perf_counter()
            inputs = torch.from_numpy(window).to(device)
            single_logits, auxiliary = model(inputs)
            single = torch.sigmoid(single_logits)[0, 25:75, 0]
            many = torch.sigmoid(auxiliary["many_hot"])[0, 25:75, 0]
            if accelerator_enabled:
                torch.cuda.synchronize(device)
            batch_seconds.append(time.perf_counter() - batch_started)
            single_predictions.append(
                single.float().cpu().numpy().astype(
                    np.float32,
                    copy=False,
                )
            )
            all_predictions.append(
                many.float().cpu().numpy().astype(
                    np.float32,
                    copy=False,
                )
            )
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    inference_seconds = time.perf_counter() - inference_started
    single_probability = np.concatenate(single_predictions)[: len(frames)]
    all_probability = np.concatenate(all_predictions)[: len(frames)]
    boundaries = _positive_run_peaks(
        single_probability,
        requested.threshold,
    )
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
        single_frame_probability=single_probability,
        all_frame_probability=all_probability,
        predicted_boundaries=boundaries,
        batch_seconds=np.asarray(batch_seconds, dtype=np.float64),
        source_fps=np.asarray(source_fps, dtype=np.float64),
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
        runtime=np.asarray(device.type),
        device_name=np.asarray(
            torch.cuda.get_device_name(device)
            if accelerator_enabled
            else "CPU"
        ),
        precision=np.asarray("float32"),
        threshold=np.asarray(requested.threshold, dtype=np.float64),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
