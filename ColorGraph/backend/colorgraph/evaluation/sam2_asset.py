from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import torch
from PIL import Image
from pydantic import Field, model_validator

from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    MaskAsset,
    SpatialKind,
)
from colorgraph.evaluation.formal_model_sources import (
    FormalModelCandidate,
    FormalModelSourceManifest,
)
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.evaluation.sam2_runtime import (
    SAM2_CANDIDATE_ID,
    SAM2_MODEL_ID,
    Sam2Runner,
    Sam2RunnerFactory,
    Sam2VideoRun,
    TransformersSam2VideoRunner,
)
from colorgraph.evaluation.semantic_runtime import (
    SEMANTIC_RUNTIME_MODEL_IDS,
    SemanticRuntimeCandidateId,
)
from colorgraph.grading.mask_integrity import (
    MASK_ASSET_SCHEMA,
    MaskSequenceInspection,
    MaskVideoInspection,
    MissingFramePolicy,
    inspect_mask_sequence,
    inspect_mask_video,
)
from colorgraph.media.color_conversion import log_rgb_array_for_display
from colorgraph.vision.semantic import (
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
)
from colorgraph.vision.video_masks import (
    _encode_mask_video,
    _resize_for_inference,
    _save_mask,
    _unlink_with_retry,
)

SAM2_MASK_ASSET_VERSION = "colorgraph.sam2-windowed-mask-asset/v1"

SemanticProviderFactory = Callable[..., SemanticMaskProvider]
MaskVideoEncoder = Callable[..., Path]
MaskVideoInspector = Callable[..., MaskVideoInspection]
MaskSequenceInspector = Callable[..., MaskSequenceInspection]
ProgressCallback = Callable[[int, int, str], None]


class Sam2MaskWindowEvidence(StrictEvaluationModel):
    window_index: int = Field(ge=0)
    shot_id: str = Field(min_length=1)
    input_start_frame: int = Field(ge=0)
    input_end_frame_inclusive: int = Field(ge=0)
    output_start_frame: int = Field(ge=0)
    output_end_frame_inclusive: int = Field(ge=0)
    input_frame_count: int = Field(gt=0)
    output_frame_count: int = Field(gt=0)
    anchor_source: Literal["semantic_model", "previous_window_mask"]
    model_load_seconds: float = Field(ge=0)
    propagation_seconds: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)
    memory_growth_mb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> Sam2MaskWindowEvidence:
        if (
            self.input_end_frame_inclusive < self.input_start_frame
            or self.output_end_frame_inclusive < self.output_start_frame
            or self.input_frame_count
            != self.input_end_frame_inclusive
            - self.input_start_frame
            + 1
            or self.output_frame_count
            != self.output_end_frame_inclusive
            - self.output_start_frame
            + 1
        ):
            raise ValueError("SAM 2 asset window ranges are inconsistent")
        expected_output_count = self.input_frame_count
        if self.anchor_source == "previous_window_mask":
            expected_output_count -= 1
        if self.output_frame_count != expected_output_count:
            raise ValueError(
                "overlapped SAM 2 windows must discard exactly one output"
            )
        return self


class Sam2MaskAssetObservation(StrictEvaluationModel):
    schema_version: str = SAM2_MASK_ASSET_VERSION
    created_at: datetime
    status: Literal["completed"]
    source_registry_path: str
    source_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1)
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_repository_path: str
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_license_id: str = Field(min_length=1)
    code_license_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_candidate_id: SemanticRuntimeCandidateId
    semantic_model_id: str = Field(min_length=1)
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    semantic_checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_checkpoint_hash_kind: str = Field(min_length=1)
    semantic_anchor_count: int = Field(gt=0)
    semantic_anchor_selected_fractions: list[float] = Field(min_length=1)
    sam_model_id: str = SAM2_MODEL_ID
    sam_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    sam_checkpoint_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sam_checkpoint_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sam_checkpoint_hash_kind: Literal["colorgraph.torch-state-dict/v1"]
    weights_license_id: str = Field(min_length=1)
    weights_commercial_use_allowed: bool
    weights_redistribution_allowed: bool
    target: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    maximum_edge: int = Field(gt=0)
    window_frames: int = Field(gt=1)
    window_overlap_frames: Literal[1] = 1
    frame_count: int = Field(gt=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    storage_bit_depth: Literal[8, 16]
    mask_video_path: str
    mask_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transient_sequence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence_retained: bool
    window_count: int = Field(gt=0)
    windows: list[Sam2MaskWindowEvidence] = Field(min_length=1)
    model_load_seconds: float = Field(ge=0)
    propagation_seconds: float = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    propagation_fps: float = Field(gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)
    maximum_memory_growth_mb: float = Field(ge=0)
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    evidence_class: Literal["engineering_runtime_not_gold"] = (
        "engineering_runtime_not_gold"
    )
    benchmark_asset_authorized: Literal[True] = True
    gold_quality_claim_authorized: Literal[False] = False
    production_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation(self) -> Sam2MaskAssetObservation:
        if self.semantic_anchor_count != len(
            self.semantic_anchor_selected_fractions
        ):
            raise ValueError("SAM 2 semantic-anchor evidence is incomplete")
        if self.window_count != len(self.windows):
            raise ValueError("SAM 2 window count does not match evidence rows")
        if sum(window.output_frame_count for window in self.windows) != (
            self.frame_count
        ):
            raise ValueError("SAM 2 windows do not cover every output frame")
        return self


@dataclass(frozen=True, slots=True)
class Sam2MaskAssetGenerationResult:
    graph: GradeGraph
    asset: MaskAsset
    observation: Sam2MaskAssetObservation


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate(
    manifest: FormalModelSourceManifest,
    candidate_id: str,
) -> FormalModelCandidate:
    candidate = next(
        (
            item
            for item in manifest.candidates
            if item.candidate_id == candidate_id
        ),
        None,
    )
    if (
        candidate is None
        or candidate.code.revision is None
        or candidate.weights.revision is None
    ):
        raise ValueError(
            f"formal model source registry has no exact {candidate_id} source"
        )
    return candidate


def _repository_revision(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        raise OSError(
            "installed SAM 2 repository is unavailable or not a Git checkout"
        )
    return completed.stdout.strip()


def _default_runner_factory(
    backend: ComputeBackend,
    model_id: str,
    revision: str,
) -> Sam2Runner:
    return TransformersSam2VideoRunner(backend, model_id, revision)


def _default_semantic_provider_factory(
    backend: ComputeBackend,
    *,
    model_id: str,
    model_revision: str,
    local_files_only: bool,
) -> SemanticMaskProvider:
    return OneFormerSemanticMaskProvider(
        backend,
        model_id=model_id,
        model_revision=model_revision,
        local_files_only=local_files_only,
    )


def _write_observation(
    path: Path,
    observation: Sam2MaskAssetObservation,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            observation.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def generate_sam2_mask_asset(
    source_registry_path: str | Path,
    code_repository_path: str | Path,
    source_path: str | Path,
    graph: GradeGraph,
    output_root: str | Path,
    report_output_path: str | Path,
    *,
    semantic_candidate_id: SemanticRuntimeCandidateId = (
        "oneformer_ade20k_swin_large"
    ),
    target: str = "mountain",
    asset_id: str = "mask_sam21_mountain",
    maximum_edge: int = 640,
    window_frames: int = 30,
    storage_bit_depth: Literal[8, 16] = 8,
    retain_mask_sequence: bool = False,
    backend: ComputeBackend | None = None,
    semantic_provider_factory: SemanticProviderFactory = (
        _default_semantic_provider_factory
    ),
    runner_factory: Sam2RunnerFactory = _default_runner_factory,
    sequence_inspector: MaskSequenceInspector = inspect_mask_sequence,
    video_encoder: MaskVideoEncoder = _encode_mask_video,
    video_inspector: MaskVideoInspector = inspect_mask_video,
    progress: ProgressCallback | None = None,
) -> Sam2MaskAssetGenerationResult:
    if maximum_edge <= 0:
        raise ValueError("maximum_edge must be positive")
    if window_frames <= 1:
        raise ValueError("window_frames must be greater than one")
    if storage_bit_depth not in {8, 16}:
        raise ValueError("storage_bit_depth must be 8 or 16")
    if not target or not asset_id:
        raise ValueError("target and asset_id must be non-empty")

    registry_file = Path(source_registry_path).resolve()
    repository = Path(code_repository_path).resolve()
    source = Path(source_path).resolve()
    root = Path(output_root).resolve()
    report_path = Path(report_output_path).resolve()
    if not registry_file.is_file():
        raise FileNotFoundError(registry_file)
    if not source.is_file():
        raise FileNotFoundError(source)
    if report_path in {registry_file, source}:
        raise ValueError("SAM 2 asset report cannot overwrite an input")

    registry_content = registry_file.read_bytes()
    source_sha256 = _sha256(source)
    manifest = FormalModelSourceManifest.model_validate_json(registry_content)
    sam_candidate = _candidate(manifest, SAM2_CANDIDATE_ID)
    semantic_candidate = _candidate(manifest, semantic_candidate_id)
    expected_semantic_model_id = SEMANTIC_RUNTIME_MODEL_IDS[
        semantic_candidate_id
    ]
    resolved_code_revision = _repository_revision(repository)
    if resolved_code_revision != sam_candidate.code.revision:
        raise ValueError(
            "installed SAM 2 code revision does not match the registry"
        )
    license_file = repository / "LICENSE"
    if not license_file.is_file():
        raise OSError("installed SAM 2 code license file is missing")

    target_root = root / asset_id
    target_root.mkdir(parents=True, exist_ok=True)
    for stale_frame in target_root.glob("*.png"):
        _unlink_with_retry(stale_frame)

    selected_backend = backend or TorchComputeBackend(
        settings.device_preference
    )
    accelerator_enabled = (
        selected_backend.info.runtime in {"cuda", "rocm"}
        and torch.cuda.is_available()
    )
    semantic_provider = semantic_provider_factory(
        selected_backend,
        model_id=expected_semantic_model_id,
        model_revision=semantic_candidate.weights.revision,
        local_files_only=True,
    )
    runner = runner_factory(
        selected_backend,
        SAM2_MODEL_ID,
        sam_candidate.weights.revision,
    )
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        semantic_provider.release_model()
        raise OSError(f"OpenCV could not open {source}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or expected_frames <= 1:
        capture.release()
        semantic_provider.release_model()
        raise ValueError("source video has invalid frame timing")
    fps_tolerance = max(0.01, graph.media.fps * 0.001)
    if abs(fps - graph.media.fps) > fps_tolerance:
        capture.release()
        semantic_provider.release_model()
        raise ValueError("decoded source FPS does not match the Grade Graph")
    if (
        graph.media.frame_count > 0
        and expected_frames != graph.media.frame_count
    ):
        capture.release()
        semantic_provider.release_model()
        raise ValueError(
            "decoded source frame count does not match the Grade Graph"
        )

    shot_starts = {
        max(0, round(shot.time_range.start_seconds * fps)): shot.id
        for shot in graph.shots
    }
    shot_starts.setdefault(0, graph.shots[0].id if graph.shots else "shot_0")
    active_shot_id = shot_starts[0]
    pending_images: list[Image.Image] = []
    pending_indices: list[int] = []
    overlap_anchor: np.ndarray | None = None
    pending_is_overlap = False
    semantic_revision: str | None = None
    semantic_checkpoint_sha256: str | None = None
    semantic_checkpoint_hash_kind: str | None = None
    semantic_anchor_selected_fractions: list[float] = []
    checkpoint_file_sha256: str | None = None
    checkpoint_state_sha256: str | None = None
    precision: str | None = None
    windows: list[Sam2MaskWindowEvidence] = []
    decoded_frames = 0
    written_frames = 0
    model_load_seconds = 0.0
    propagation_seconds = 0.0
    peak_gpu_memory_mb = 0.0
    maximum_memory_growth_mb = 0.0
    presence_sum = 0.0
    presence_count = 0
    mask_width = 0
    mask_height = 0
    started = time.perf_counter()

    def semantic_anchor(image: Image.Image) -> np.ndarray:
        nonlocal semantic_revision
        nonlocal semantic_checkpoint_sha256
        nonlocal semantic_checkpoint_hash_kind
        nonlocal peak_gpu_memory_mb
        if accelerator_enabled:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(
                selected_backend.torch_device
            )
        prediction = semantic_provider.predict_many(image, [target])[target]
        metadata = prediction.metadata
        resolved_revision = str(metadata.get("model_revision", ""))
        resolved_checkpoint = str(
            metadata.get("checkpoint_sha256", "")
        )
        resolved_hash_kind = str(
            metadata.get("checkpoint_hash_kind", "")
        )
        if (
            resolved_revision != semantic_candidate.weights.revision
            or not resolved_checkpoint
            or resolved_hash_kind != "colorgraph.torch-state-dict/v1"
        ):
            raise ValueError(
                "semantic anchor identity does not match the registry"
            )
        if semantic_revision is None:
            semantic_revision = resolved_revision
            semantic_checkpoint_sha256 = resolved_checkpoint
            semantic_checkpoint_hash_kind = resolved_hash_kind
        elif (
            semantic_revision != resolved_revision
            or semantic_checkpoint_sha256 != resolved_checkpoint
            or semantic_checkpoint_hash_kind != resolved_hash_kind
        ):
            raise ValueError("semantic anchor model identity drifted")
        threshold = float(metadata.get("probability_threshold", 0.30))
        anchor = np.asarray(prediction.mask >= threshold, dtype=np.uint8)
        selected_fraction = float(anchor.mean())
        if not 0.001 <= selected_fraction <= 0.999:
            raise ValueError("semantic anchor is empty or nearly full-frame")
        semantic_anchor_selected_fractions.append(selected_fraction)
        if accelerator_enabled:
            selected_backend.synchronize()
            peak_gpu_memory_mb = max(
                peak_gpu_memory_mb,
                float(
                    torch.cuda.max_memory_allocated(
                        selected_backend.torch_device
                    )
                    / (1024 * 1024)
                ),
            )
            torch.cuda.empty_cache()
        return anchor

    def flush_window() -> None:
        nonlocal pending_images
        nonlocal pending_indices
        nonlocal overlap_anchor
        nonlocal pending_is_overlap
        nonlocal checkpoint_file_sha256
        nonlocal checkpoint_state_sha256
        nonlocal precision
        nonlocal written_frames
        nonlocal model_load_seconds
        nonlocal propagation_seconds
        nonlocal peak_gpu_memory_mb
        nonlocal maximum_memory_growth_mb
        nonlocal presence_sum
        nonlocal presence_count
        if not pending_images or (
            pending_is_overlap and len(pending_images) == 1
        ):
            return
        if pending_is_overlap:
            if overlap_anchor is None:
                raise RuntimeError("overlapped window has no previous mask")
            anchor = np.asarray(overlap_anchor >= 0.5, dtype=np.uint8)
            output_offset = 1
            anchor_source: Literal[
                "semantic_model", "previous_window_mask"
            ] = "previous_window_mask"
        else:
            anchor = semantic_anchor(pending_images[0])
            output_offset = 0
            anchor_source = "semantic_model"

        run: Sam2VideoRun = runner.run(pending_images, anchor)
        if (
            run.resolved_revision != sam_candidate.weights.revision
            or run.masks.shape
            != (
                len(pending_images),
                pending_images[0].height,
                pending_images[0].width,
            )
            or run.object_presence_probabilities.shape
            != (len(pending_images),)
        ):
            raise ValueError(
                "SAM 2 window output does not match the frozen source"
            )
        if checkpoint_file_sha256 is None:
            checkpoint_file_sha256 = run.checkpoint_file_sha256
            checkpoint_state_sha256 = run.checkpoint_state_sha256
            precision = run.precision
        elif (
            checkpoint_file_sha256 != run.checkpoint_file_sha256
            or checkpoint_state_sha256 != run.checkpoint_state_sha256
            or precision != run.precision
        ):
            raise ValueError("SAM 2 model identity drifted between windows")

        for local_index in range(output_offset, len(pending_images)):
            frame_index = pending_indices[local_index]
            mask = run.masks[local_index]
            _save_mask(
                target_root / f"{frame_index:06d}.png",
                mask,
                bit_depth=storage_bit_depth,
            )
            presence_sum += float(
                run.object_presence_probabilities[local_index]
            )
            presence_count += 1
            written_frames += 1
        output_indices = pending_indices[output_offset:]
        windows.append(
            Sam2MaskWindowEvidence(
                window_index=len(windows),
                shot_id=active_shot_id,
                input_start_frame=pending_indices[0],
                input_end_frame_inclusive=pending_indices[-1],
                output_start_frame=output_indices[0],
                output_end_frame_inclusive=output_indices[-1],
                input_frame_count=len(pending_indices),
                output_frame_count=len(output_indices),
                anchor_source=anchor_source,
                model_load_seconds=run.model_load_seconds,
                propagation_seconds=run.propagation_seconds,
                peak_gpu_memory_mb=run.peak_gpu_memory_mb,
                memory_growth_mb=run.memory_growth_mb,
            )
        )
        model_load_seconds += run.model_load_seconds
        propagation_seconds += run.propagation_seconds
        peak_gpu_memory_mb = max(
            peak_gpu_memory_mb,
            run.peak_gpu_memory_mb,
        )
        maximum_memory_growth_mb = max(
            maximum_memory_growth_mb,
            run.memory_growth_mb,
        )
        overlap_anchor = run.masks[-1].copy()
        pending_images = [pending_images[-1]]
        pending_indices = [pending_indices[-1]]
        pending_is_overlap = True

    try:
        while True:
            success, frame_bgr = capture.read()
            if not success:
                break
            frame_index = decoded_frames
            if frame_index in shot_starts and frame_index != 0:
                flush_window()
                pending_images = []
                pending_indices = []
                overlap_anchor = None
                pending_is_overlap = False
                active_shot_id = shot_starts[frame_index]
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            working = _resize_for_inference(frame_rgb, maximum_edge)
            mask_height, mask_width = working.shape[:2]
            if graph.media.input_color_space == ColorSpace.LOG:
                working = log_rgb_array_for_display(
                    working,
                    selected_backend,
                    graph.media.source_log_profile,
                )
            pending_images.append(Image.fromarray(working, mode="RGB"))
            pending_indices.append(frame_index)
            decoded_frames += 1
            if len(pending_images) >= window_frames:
                flush_window()
            if progress and (
                decoded_frames == 1
                or decoded_frames % max(1, round(fps)) == 0
                or decoded_frames == expected_frames
            ):
                progress(
                    decoded_frames,
                    expected_frames,
                    "Generating windowed SAM 2 masks",
                )
        flush_window()
    finally:
        capture.release()
        semantic_provider.release_model()
        release_model = getattr(runner, "release_model", None)
        if callable(release_model):
            release_model()

    if decoded_frames != expected_frames or written_frames != decoded_frames:
        raise RuntimeError(
            "windowed SAM 2 asset did not cover every decoded frame"
        )
    if (
        checkpoint_file_sha256 is None
        or checkpoint_state_sha256 is None
        or precision is None
        or semantic_revision is None
        or semantic_checkpoint_sha256 is None
        or semantic_checkpoint_hash_kind is None
        or propagation_seconds <= 0
    ):
        raise RuntimeError("windowed SAM 2 asset identity is incomplete")

    sequence = sequence_inspector(
        target_root,
        expected_frame_count=decoded_frames,
        expected_width=mask_width,
        expected_height=mask_height,
        expected_bit_depth=storage_bit_depth,
        missing_frame_policy=MissingFramePolicy.ERROR,
    )
    video_path = video_encoder(
        root,
        asset_id,
        fps,
        bit_depth=storage_bit_depth,
    )
    video = video_inspector(
        video_path,
        expected_frame_count=decoded_frames,
        expected_width=mask_width,
        expected_height=mask_height,
        expected_fps=fps,
        expected_pixel_format=(
            "gray16le" if storage_bit_depth == 16 else "gray"
        ),
    )
    if not retain_mask_sequence:
        for sequence_frame in target_root.glob("*.png"):
            _unlink_with_retry(sequence_frame)

    metadata = {
        "schema": MASK_ASSET_SCHEMA,
        "target": target,
        "target_aliases": [target, f"mask_{target}", asset_id],
        "provider": SAM2_MODEL_ID,
        "model_revision": sam_candidate.weights.revision,
        "checkpoint_sha256": checkpoint_file_sha256,
        "checkpoint_hash_kind": "sha256-file/v1",
        "prediction_evidence": {
            "model_revision": sam_candidate.weights.revision,
            "checkpoint_sha256": checkpoint_file_sha256,
            "checkpoint_state_sha256": checkpoint_state_sha256,
            "checkpoint_state_hash_kind": (
                "colorgraph.torch-state-dict/v1"
            ),
            "code_revision": resolved_code_revision,
            "semantic_model_id": expected_semantic_model_id,
            "semantic_revision": semantic_revision,
            "semantic_checkpoint_sha256": (
                semantic_checkpoint_sha256
            ),
            "semantic_checkpoint_hash_kind": (
                semantic_checkpoint_hash_kind
            ),
            "source_sha256": source_sha256,
        },
        "confidence_semantics": (
            "mean_sam2_object_presence_probability_not_accuracy"
        ),
        "confidence_is_accuracy": False,
        "file_pattern": (
            "{frame_index:06d}.png" if retain_mask_sequence else None
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
                sequence.maximum_quantization_error
            ),
            "preferred_decode": (
                "sequence"
                if retain_mask_sequence
                else "video_ffmpeg"
            ),
            "sequence_retained": retain_mask_sequence,
            "video_pixel_format": video.pixel_format,
            "video_bits_per_raw_sample": video.bits_per_raw_sample,
        },
        "video_path": str(video_path),
        "video_codec": "ffv1",
        "frame_count": decoded_frames,
        "file_count": sequence.file_count if retain_mask_sequence else 0,
        "width": mask_width,
        "height": mask_height,
        "fps": fps,
        "sequence_sha256": (
            sequence.sha256 if retain_mask_sequence else None
        ),
        "transient_sequence_sha256": sequence.sha256,
        "video_sha256": video.sha256,
        "decode_verified": True,
        "missing_frame_policy": MissingFramePolicy.ERROR.value,
        "tracking": {
            "algorithm": "sam21_windowed_video_propagation",
            "flow_direction": "not_applicable",
            "reanchor": (
                "semantic_at_shot_start_previous_window_mask_at_overlap"
            ),
            "window_frames": window_frames,
            "window_overlap_frames": 1,
            "bidirectional_consistency": False,
        },
        "source_path": str(source),
        "source_sha256": source_sha256,
    }
    asset = MaskAsset(
        id=asset_id,
        kind=SpatialKind.PROMPTED,
        target=target,
        path=str(target_root),
        confidence=(
            presence_sum / presence_count if presence_count else 0.0
        ),
        frame_count=decoded_frames,
        metadata=metadata,
    )
    updated_graph = graph.model_copy(
        update={
            "masks": [
                item for item in graph.masks if item.id != asset_id
            ]
            + [asset]
        },
        deep=True,
    )
    elapsed_seconds = max(time.perf_counter() - started, 1e-9)
    observation = Sam2MaskAssetObservation(
        created_at=datetime.now(UTC),
        status="completed",
        source_registry_path=str(registry_file),
        source_registry_sha256=hashlib.sha256(
            registry_content
        ).hexdigest(),
        project_id=graph.project_id,
        source_path=str(source),
        source_sha256=metadata["source_sha256"],
        code_repository_path=str(repository),
        code_revision=resolved_code_revision,
        code_license_id=sam_candidate.code.license_id or "unknown",
        code_license_sha256=_sha256(license_file),
        semantic_candidate_id=semantic_candidate_id,
        semantic_model_id=expected_semantic_model_id,
        semantic_revision=semantic_revision,
        semantic_checkpoint_sha256=semantic_checkpoint_sha256,
        semantic_checkpoint_hash_kind=semantic_checkpoint_hash_kind,
        semantic_anchor_count=len(
            semantic_anchor_selected_fractions
        ),
        semantic_anchor_selected_fractions=(
            semantic_anchor_selected_fractions
        ),
        sam_revision=sam_candidate.weights.revision,
        sam_checkpoint_file_sha256=checkpoint_file_sha256,
        sam_checkpoint_state_sha256=checkpoint_state_sha256,
        sam_checkpoint_hash_kind="colorgraph.torch-state-dict/v1",
        weights_license_id=(
            sam_candidate.weights.license_id or "unknown"
        ),
        weights_commercial_use_allowed=(
            sam_candidate.weights.commercial_use_allowed is True
        ),
        weights_redistribution_allowed=(
            sam_candidate.weights.redistribution_allowed is True
        ),
        target=target,
        asset_id=asset_id,
        maximum_edge=maximum_edge,
        window_frames=window_frames,
        frame_count=decoded_frames,
        width=mask_width,
        height=mask_height,
        fps=fps,
        storage_bit_depth=storage_bit_depth,
        mask_video_path=str(video_path),
        mask_video_sha256=video.sha256,
        transient_sequence_sha256=sequence.sha256,
        sequence_retained=retain_mask_sequence,
        window_count=len(windows),
        windows=windows,
        model_load_seconds=model_load_seconds,
        propagation_seconds=propagation_seconds,
        elapsed_seconds=elapsed_seconds,
        propagation_fps=decoded_frames / propagation_seconds,
        peak_cpu_memory_mb=process_peak_memory_mb(),
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        maximum_memory_growth_mb=maximum_memory_growth_mb,
        operating_system=platform.platform(),
        runtime=selected_backend.info.runtime,
        device_name=selected_backend.info.name,
        precision=precision,
    )
    _write_observation(report_path, observation)
    return Sam2MaskAssetGenerationResult(
        graph=updated_graph,
        asset=asset,
        observation=observation,
    )
