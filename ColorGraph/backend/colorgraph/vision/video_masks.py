from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from colorgraph.config import settings
from colorgraph.domain.grade_graph import ColorSpace, GradeGraph, MaskAsset, SpatialKind
from colorgraph.grading.mask_integrity import (
    MASK_ASSET_SCHEMA,
    MissingFramePolicy,
    inspect_mask_sequence,
    inspect_mask_video,
)
from colorgraph.media.color_conversion import log_rgb_array_for_display
from colorgraph.vision.base import MaskPrediction
from colorgraph.vision.depth import DEPTH_TARGETS, DepthMaskProvider
from colorgraph.vision.semantic import SemanticMaskProvider

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class MaskGenerationResult:
    graph: GradeGraph
    frame_count: int
    inference_frames: int
    targets: list[str]


def _resize_for_inference(
    frame_rgb: np.ndarray,
    maximum_edge: int,
) -> np.ndarray:
    height, width = frame_rgb.shape[:2]
    scale = min(1.0, maximum_edge / max(height, width))
    if scale == 1:
        return frame_rgb
    return cv2.resize(
        frame_rgb,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _calculate_backward_flow(
    previous_gray: np.ndarray,
    current_gray: np.ndarray,
) -> np.ndarray:
    return cv2.calcOpticalFlowFarneback(
        current_gray,
        previous_gray,
        None,
        0.5,
        3,
        21,
        3,
        5,
        1.2,
        0,
    )


def _propagate_mask(
    previous_mask: np.ndarray,
    backward_flow: np.ndarray,
) -> np.ndarray:
    height, width = previous_mask.shape
    if backward_flow.shape != (height, width, 2):
        raise ValueError(
            f"backward flow has shape {backward_flow.shape}; "
            f"expected {(height, width, 2)}"
        )
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    propagated = cv2.remap(
        previous_mask,
        grid_x + backward_flow[..., 0],
        grid_y + backward_flow[..., 1],
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return cv2.GaussianBlur(propagated, (0, 0), 0.65).clip(0, 1)


def _save_mask(
    path: Path,
    mask: np.ndarray,
    *,
    bit_depth: Literal[8, 16],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if bit_depth == 16:
        encoded = np.round(mask.clip(0, 1) * 65535).astype(np.uint16)
    else:
        encoded = np.round(mask.clip(0, 1) * 255).astype(np.uint8)
    if not cv2.imwrite(str(path), encoded):
        raise RuntimeError(f"failed to save mask {path}")


def _unlink_with_retry(path: Path, *, attempts: int = 8) -> None:
    delay_seconds = 0.025
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32} or attempt == attempts - 1:
                raise
            time.sleep(delay_seconds)
            delay_seconds *= 2


def _encode_mask_video(
    root: Path,
    target: str,
    fps: float,
    *,
    bit_depth: Literal[8, 16],
) -> Path:
    destination = root / f"{target}.mkv"
    completed = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            f"{fps:.8f}",
            "-i",
            str(root / target / "%06d.png"),
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "gray16le" if bit_depth == 16 else "gray",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"failed to encode {target} mask video: {completed.stderr.strip()}")
    return destination


class VideoMaskGenerator:
    def __init__(
        self,
        semantic: SemanticMaskProvider,
        depth: DepthMaskProvider,
    ) -> None:
        self.semantic = semantic
        self.depth = depth

    def generate(
        self,
        source: str | Path,
        graph: GradeGraph,
        output_root: str | Path,
        *,
        targets: list[str] | None = None,
        inference_interval_seconds: float = 1.5,
        maximum_edge: int = 640,
        storage_bit_depth: Literal[8, 16] = 16,
        retain_mask_sequence: bool = False,
        progress: ProgressCallback | None = None,
    ) -> MaskGenerationResult:
        if storage_bit_depth not in {8, 16}:
            raise ValueError("storage_bit_depth must be 8 or 16")
        requested = targets or [
            "sky",
            "vegetation",
            "water",
            "mountain",
            "depth_far",
        ]
        if len(requested) != len(set(requested)):
            raise ValueError("mask targets must be unique")
        unsupported = set(requested) - (
            self.semantic.supported_targets | self.depth.supported_targets
        )
        if unsupported:
            raise ValueError(f"unsupported mask targets: {sorted(unsupported)}")

        root = Path(output_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for target in requested:
            target_root = root / target
            target_root.mkdir(parents=True, exist_ok=True)
            # A regenerated target is a new complete sequence. Stale frames
            # from a longer previous source would invalidate its checksum and
            # can cause FFmpeg to encode frames outside the current project.
            for stale_frame in target_root.glob("*.png"):
                _unlink_with_retry(stale_frame)

        capture = cv2.VideoCapture(str(Path(source).resolve()))
        if not capture.isOpened():
            raise RuntimeError(f"OpenCV could not open {source}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0:
            capture.release()
            raise RuntimeError("video does not report a valid frame rate")
        fps_tolerance = max(0.01, graph.media.fps * 0.001)
        if abs(fps - graph.media.fps) > fps_tolerance:
            capture.release()
            raise ValueError(
                f"decoded source fps {fps} does not match graph fps {graph.media.fps}"
            )
        inference_interval = max(1, round(fps * inference_interval_seconds))
        shot_start_ids = {
            max(0, round(shot.time_range.start_seconds * fps)): shot.id
            for shot in graph.shots
        }
        shot_start_frames = set(shot_start_ids)

        previous_gray: np.ndarray | None = None
        previous_masks: dict[str, np.ndarray] = {}
        confidence_sums = {target: 0.0 for target in requested}
        confidence_counts = {target: 0 for target in requested}
        score_semantics: dict[str, str] = {}
        prediction_evidence: dict[str, dict[str, object]] = {}
        frame_index = 0
        inference_frames = 0

        try:
            while True:
                success, frame_bgr = capture.read()
                if not success:
                    break
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                working = _resize_for_inference(frame_rgb, maximum_edge)
                gray = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY)
                is_anchor = (
                    previous_gray is None
                    or frame_index in shot_start_frames
                    or frame_index % inference_interval == 0
                )

                propagated: dict[str, np.ndarray] = {}
                if (
                    previous_gray is not None
                    and previous_masks
                    and frame_index not in shot_start_frames
                ):
                    backward_flow = _calculate_backward_flow(previous_gray, gray)
                    propagated = {
                        target: _propagate_mask(
                            previous_masks[target],
                            backward_flow,
                        )
                        for target in requested
                    }

                if is_anchor:
                    inference_rgb = working
                    if graph.media.input_color_space == ColorSpace.LOG:
                        inference_rgb = log_rgb_array_for_display(
                            working,
                            self.semantic.backend,
                            graph.media.source_log_profile,
                        )
                    image = Image.fromarray(inference_rgb, mode="RGB")
                    semantic_targets = [
                        target for target in requested if target not in DEPTH_TARGETS
                    ]
                    depth_targets = [target for target in requested if target in DEPTH_TARGETS]
                    predictions: dict[str, MaskPrediction] = {}
                    if semantic_targets:
                        predictions.update(self.semantic.predict_many(image, semantic_targets))
                    if depth_targets:
                        if frame_index in shot_start_ids:
                            self.depth.reset_shot(shot_start_ids[frame_index])
                        predictions.update(self.depth.predict_many(image, depth_targets))
                    missing_predictions = set(requested) - predictions.keys()
                    if missing_predictions:
                        raise RuntimeError(
                            "mask providers omitted requested targets: "
                            f"{sorted(missing_predictions)}"
                        )
                    inference_frames += 1
                    current_masks = {}
                    for target, prediction in predictions.items():
                        fresh = prediction.mask
                        if target in propagated and frame_index not in shot_start_frames:
                            fresh = (fresh * 0.82 + propagated[target] * 0.18).clip(0, 1)
                        current_masks[target] = fresh
                        confidence_sums[target] += prediction.confidence
                        confidence_counts[target] += 1
                        score_semantics.setdefault(target, prediction.score_semantics)
                        prediction_evidence.setdefault(
                            target,
                            dict(prediction.metadata),
                        )
                else:
                    current_masks = propagated

                if set(current_masks) != set(requested):
                    raise RuntimeError(
                        "tracked mask set is incomplete at frame "
                        f"{frame_index}: {sorted(set(requested) - current_masks.keys())}"
                    )
                for target in requested:
                    mask = current_masks[target]
                    if mask.ndim != 2 or mask.shape != gray.shape:
                        raise ValueError(
                            f"mask {target!r} frame {frame_index} has shape "
                            f"{mask.shape}; expected {gray.shape}"
                        )
                    if not np.isfinite(mask).all():
                        raise ValueError(
                            f"mask {target!r} frame {frame_index} contains non-finite values"
                        )
                    _save_mask(
                        root / target / f"{frame_index:06d}.png",
                        mask,
                        bit_depth=storage_bit_depth,
                    )

                previous_gray = gray
                previous_masks = current_masks
                frame_index += 1
                if progress and (
                    frame_index == 1
                    or frame_index % max(1, round(fps)) == 0
                    or frame_index == expected_frames
                ):
                    progress(frame_index, expected_frames, "Generating tracked masks")
        finally:
            capture.release()
            for provider in (self.semantic, self.depth):
                release_model = getattr(provider, "release_model", None)
                if callable(release_model):
                    release_model()

        if frame_index <= 0:
            raise RuntimeError("source video decoded zero frames")
        if expected_frames > 0 and frame_index != expected_frames:
            raise RuntimeError(
                f"source decoder produced {frame_index} frames; "
                f"OpenCV reported {expected_frames}"
            )
        if graph.media.frame_count > 0 and frame_index != graph.media.frame_count:
            raise RuntimeError(
                f"source decoder produced {frame_index} frames; "
                f"Grade Graph declares {graph.media.frame_count}"
            )
        if previous_gray is None:
            raise RuntimeError("mask generation completed without a decoded frame")
        mask_height, mask_width = previous_gray.shape
        sequence_inspections = {
            target: inspect_mask_sequence(
                root / target,
                expected_frame_count=frame_index,
                expected_width=mask_width,
                expected_height=mask_height,
                expected_bit_depth=storage_bit_depth,
                missing_frame_policy=MissingFramePolicy.ERROR,
            )
            for target in requested
        }
        video_paths = {
            target: _encode_mask_video(
                root,
                target,
                fps,
                bit_depth=storage_bit_depth,
            )
            for target in requested
        }
        video_inspections = {
            target: inspect_mask_video(
                video_paths[target],
                expected_frame_count=frame_index,
            expected_width=mask_width,
            expected_height=mask_height,
            expected_fps=fps,
            expected_pixel_format=(
                "gray16le" if storage_bit_depth == 16 else "gray"
            ),
        )
            for target in requested
        }
        if not retain_mask_sequence:
            for target in requested:
                for sequence_frame in (root / target).glob("*.png"):
                    _unlink_with_retry(sequence_frame)
        assets = [
            MaskAsset(
                id=f"mask_{target}",
                kind=(SpatialKind.DEPTH if target in DEPTH_TARGETS else SpatialKind.SEMANTIC),
                target=target,
                path=str(root / target),
                confidence=(
                    confidence_sums[target] / confidence_counts[target]
                    if confidence_counts[target]
                    else 0.0
                ),
                frame_count=frame_index,
                metadata={
                    "schema": MASK_ASSET_SCHEMA,
                    "target": target,
                    "target_aliases": [target, f"mask_{target}"],
                    "confidence_semantics": score_semantics.get(
                        target,
                        "provider_defined_confidence_not_accuracy",
                    ),
                    "confidence_is_accuracy": False,
                    "prediction_evidence": prediction_evidence.get(target, {}),
                    **{
                        key: prediction_evidence.get(target, {})[key]
                        for key in (
                            "model_revision",
                            "checkpoint_sha256",
                            "checkpoint_hash_kind",
                        )
                        if key in prediction_evidence.get(target, {})
                    },
                    "file_pattern": (
                        "{frame_index:06d}.png"
                        if retain_mask_sequence
                        else None
                    ),
                    "storage": {
                        "primary": (
                            "png_sequence"
                            if retain_mask_sequence
                            else "ffv1_video"
                        ),
                        "sequence_format": "png",
                        "sample_dtype": (
                            "uint16" if storage_bit_depth == 16 else "uint8"
                        ),
                        "bit_depth": storage_bit_depth,
                        "quantization_levels": 1 << storage_bit_depth,
                        "maximum_quantization_error": (
                            sequence_inspections[target].maximum_quantization_error
                        ),
                        "preferred_decode": (
                            "sequence"
                            if retain_mask_sequence
                            else "video_ffmpeg"
                        ),
                        "sequence_retained": retain_mask_sequence,
                        "video_pixel_format": (
                            video_inspections[target].pixel_format
                        ),
                        "video_bits_per_raw_sample": (
                            video_inspections[target].bits_per_raw_sample
                        ),
                    },
                    "video_path": str(video_paths[target]),
                    "video_codec": "ffv1",
                    "frame_count": frame_index,
                    "file_count": (
                        sequence_inspections[target].file_count
                        if retain_mask_sequence
                        else 0
                    ),
                    "width": mask_width,
                    "height": mask_height,
                    "fps": fps,
                    "sequence_sha256": (
                        sequence_inspections[target].sha256
                        if retain_mask_sequence
                        else None
                    ),
                    "transient_sequence_sha256": (
                        sequence_inspections[target].sha256
                    ),
                    "video_sha256": video_inspections[target].sha256,
                    "decode_verified": True,
                    "missing_frame_policy": MissingFramePolicy.ERROR.value,
                    "tracking": {
                        "algorithm": "farneback_backward_flow_warp",
                        "flow_direction": "current_to_previous",
                        "reanchor": "periodic_model_inference",
                        "anchor_model_weight": 0.82,
                        "anchor_propagated_weight": 0.18,
                        "bidirectional_consistency": False,
                    },
                    "inference_interval_seconds": inference_interval_seconds,
                    "inference_interval_frames": inference_interval,
                    "provider": (
                        self.depth.provider_id
                        if target in DEPTH_TARGETS
                        else self.semantic.provider_id
                    ),
                },
            )
            for target in requested
        ]
        updated = graph.model_copy(
            update={
                "masks": [
                    asset for asset in graph.masks if asset.id not in {item.id for item in assets}
                ]
                + assets
            },
            deep=True,
        )
        return MaskGenerationResult(
            graph=updated,
            frame_count=frame_index,
            inference_frames=inference_frames,
            targets=requested,
        )
