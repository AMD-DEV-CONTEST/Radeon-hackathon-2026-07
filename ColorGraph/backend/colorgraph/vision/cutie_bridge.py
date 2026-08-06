from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf, open_dict
from PIL import Image
from torchvision.transforms.functional import to_tensor

from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.vision.model_lifecycle import torch_model_state_sha256


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--resnet-directory", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--anchor-mask", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--maximum-frames", type=int)
    parser.add_argument("--maximum-internal-size", type=int, default=480)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_frames(
    video: Path,
    maximum_frames: int | None,
) -> tuple[list[Image.Image], float]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise OSError(f"OpenCV could not open {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[Image.Image] = []
    try:
        while maximum_frames is None or len(frames) < maximum_frames:
            success, frame_bgr = capture.read()
            if not success:
                break
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(frame_rgb, mode="RGB"))
    finally:
        capture.release()
    if fps <= 0 or len(frames) <= 1:
        raise ValueError("Cutie runtime video has invalid timing or frames")
    return frames, fps


def _configured_model(
    repository: Path,
    weights: Path,
    resnet_directory: Path,
    maximum_internal_size: int,
):
    sys.path.insert(0, str(repository))
    from cutie.inference.inference_core import InferenceCore
    from cutie.inference.utils.args_utils import get_dataset_cfg
    from cutie.model.cutie import CUTIE

    config_directory = repository / "cutie" / "config"
    with initialize_config_dir(
        version_base="1.3.2",
        config_dir=str(config_directory),
        job_name="colorgraph-cutie-runtime",
    ):
        config = compose(config_name="eval_config")
    with open_dict(config):
        config.dataset = "generic"
        config.weights = str(weights)
        config.amp = True
        config.max_internal_size = maximum_internal_size
        config.model.resnet_model_path = str(resnet_directory)
    get_dataset_cfg(config)
    return config, CUTIE, InferenceCore


def main() -> int:
    requested = _arguments()
    repository = Path(requested.repository).resolve()
    weights = Path(requested.weights).resolve()
    resnet_directory = Path(requested.resnet_directory).resolve()
    video = Path(requested.video).resolve()
    anchor_path = Path(requested.anchor_mask).resolve()
    output = Path(requested.output).resolve()
    if requested.maximum_frames is not None and requested.maximum_frames <= 1:
        raise ValueError("maximum-frames must be greater than one")
    if requested.maximum_internal_size <= 0:
        raise ValueError("maximum-internal-size must be positive")
    for required in (
        repository,
        weights,
        resnet_directory,
        video,
        anchor_path,
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
    frames, source_fps = _decode_frames(video, requested.maximum_frames)
    anchor_mask = np.load(anchor_path, allow_pickle=False)
    expected_shape = (frames[0].height, frames[0].width)
    if anchor_mask.shape != expected_shape:
        raise ValueError(
            f"Cutie anchor shape {anchor_mask.shape} != {expected_shape}"
        )
    anchor_mask = np.asarray(anchor_mask >= 0.5, dtype=np.uint8)
    if not 0.001 <= float(anchor_mask.mean()) <= 0.999:
        raise ValueError("Cutie anchor is empty or nearly full-frame")

    config, cutie_type, inference_core_type = _configured_model(
        repository,
        weights,
        resnet_directory,
        requested.maximum_internal_size,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    accelerator_enabled = device.type == "cuda"
    precision = "float16-autocast" if accelerator_enabled else "float32"
    if accelerator_enabled:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
        torch.cuda.synchronize(device)
        baseline_allocated = torch.cuda.memory_allocated(device)
    else:
        baseline_allocated = 0

    load_started = time.perf_counter()
    model = cutie_type(config).to(device).eval()
    state_dict = torch.load(
        weights,
        map_location="cpu",
        weights_only=True,
    )
    model.load_weights(state_dict)
    checkpoint_state_sha256 = torch_model_state_sha256(model)
    if accelerator_enabled:
        torch.cuda.synchronize(device)
    model_load_seconds = time.perf_counter() - load_started
    processor = inference_core_type(model, cfg=config)

    probabilities: list[np.ndarray] = []
    frame_seconds: list[float] = []
    inference_started = time.perf_counter()
    with torch.inference_mode():
        for index, frame in enumerate(frames):
            frame_started = time.perf_counter()
            image = to_tensor(frame).to(device=device, dtype=torch.float32)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.float16,
                enabled=accelerator_enabled,
            ):
                if index == 0:
                    output_probability = processor.step(
                        image,
                        torch.from_numpy(anchor_mask).to(device),
                        objects=[1],
                    )
                else:
                    output_probability = processor.step(
                        image,
                        end=index == len(frames) - 1,
                    )
            if accelerator_enabled:
                torch.cuda.synchronize(device)
            frame_seconds.append(time.perf_counter() - frame_started)
            if output_probability.shape[0] != 2:
                raise RuntimeError(
                    "Cutie single-object propagation returned unexpected "
                    "probability channels"
                )
            probabilities.append(
                output_probability[1]
                .float()
                .clamp(0, 1)
                .cpu()
                .numpy()
                .astype(np.float32, copy=False)
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

    eval_config = repository / "cutie" / "config" / "eval_config.yaml"
    base_config = repository / "cutie" / "config" / "model" / "base.yaml"
    configuration_digest = hashlib.sha256(
        (
            _sha256(eval_config)
            + _sha256(base_config)
            + OmegaConf.to_yaml(config, resolve=True)
        ).encode("utf-8")
    ).hexdigest()
    resnet18 = resnet_directory / "resnet18-5c106cde.pth"
    resnet50 = resnet_directory / "resnet50-19c8e357.pth"
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        masks=np.stack(probabilities, axis=0).astype(
            np.float32,
            copy=False,
        ),
        frame_seconds=np.asarray(frame_seconds, dtype=np.float64),
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
        checkpoint_file_sha256=np.asarray(_sha256(weights)),
        checkpoint_file_md5=np.asarray(_md5(weights)),
        checkpoint_state_sha256=np.asarray(
            checkpoint_state_sha256
        ),
        configuration_sha256=np.asarray(configuration_digest),
        resnet18_sha256=np.asarray(_sha256(resnet18)),
        resnet50_sha256=np.asarray(_sha256(resnet50)),
        maximum_internal_size=np.asarray(
            requested.maximum_internal_size,
            dtype=np.int32,
        ),
        precision=np.asarray(precision),
        runtime=np.asarray(device.type),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
