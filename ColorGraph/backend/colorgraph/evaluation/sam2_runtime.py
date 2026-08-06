from __future__ import annotations

import gc
import hashlib
import json
import platform
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np
import torch
from PIL import Image
from pydantic import Field, model_validator

from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.devices.base import ComputeBackend
from colorgraph.evaluation.formal_model_sources import (
    FormalModelCandidate,
    FormalModelSourceManifest,
)
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.evaluation.semantic_runtime import (
    SEMANTIC_RUNTIME_MODEL_IDS,
    SemanticRuntimeCandidateId,
)
from colorgraph.vision.model_lifecycle import torch_model_state_sha256
from colorgraph.vision.semantic import (
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
)

SAM2_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.sam2-video-runtime-observation/v1"
)
SAM2_MODEL_ID = "facebook/sam2.1-hiera-small"
SAM2_CANDIDATE_ID = "sam21"
RuntimeStatus = Literal["completed", "blocked", "failed"]
MediaOrigin = Literal[
    "camera_original",
    "camera_original_derived_clip",
    "licensed_stock",
    "published_dataset",
    "procedural",
]


class Sam2RuntimeFrameSummary(StrictEvaluationModel):
    frame_index: int = Field(ge=0)
    mask_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_fraction: float = Field(ge=0, le=1)
    object_presence_probability: float = Field(ge=0, le=1)
    adjacent_binary_iou: float | None = Field(default=None, ge=0, le=1)


class Sam2RuntimeObservation(StrictEvaluationModel):
    schema_version: str = SAM2_RUNTIME_OBSERVATION_VERSION
    created_at: datetime
    status: RuntimeStatus
    source_registry_path: str
    source_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_repository_path: str
    requested_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_code_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    code_license_id: str | None
    code_license_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    video_path: str
    video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_origin: MediaOrigin
    parent_source_path: str | None = None
    parent_source_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_start_seconds: float | None = Field(default=None, ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    decoded_frame_count: int = Field(gt=1)
    source_frame_count: int = Field(gt=1)
    truncated_to_maximum_frames: bool
    semantic_candidate_id: SemanticRuntimeCandidateId
    semantic_target: str = Field(min_length=1)
    semantic_model_id: str = Field(min_length=1)
    requested_semantic_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_semantic_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    semantic_checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    semantic_checkpoint_hash_kind: str | None = None
    anchor_frame_index: Literal[0] = 0
    anchor_probability_threshold: float = Field(ge=0, le=1)
    anchor_mask_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    anchor_selected_fraction: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    anchor_elapsed_seconds: float = Field(ge=0)
    anchor_peak_gpu_memory_mb: float = Field(ge=0)
    sam_model_id: str = SAM2_MODEL_ID
    requested_sam_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_sam_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    sam_checkpoint_file_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    sam_checkpoint_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    sam_checkpoint_hash_kind: Literal[
        "colorgraph.torch-state-dict/v1"
    ] | None = None
    weights_license_id: str | None
    weights_commercial_use_allowed: bool | None
    weights_redistribution_allowed: bool | None
    local_files_only: Literal[True] = True
    network_access_allowed: Literal[False] = False
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    model_load_seconds: float = Field(ge=0)
    propagation_seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(gt=0)
    propagation_fps: float | None = Field(default=None, gt=0)
    cold_processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_cpu_memory_scope: Literal["process_lifetime_peak"] = (
        "process_lifetime_peak"
    )
    peak_gpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_scope: Literal[
        "torch_peak_allocated_since_reset",
        "not_applicable",
    ]
    memory_growth_mb: float = Field(ge=0)
    masks_path: str | None = None
    masks_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    masks_dtype: Literal["float32"] | None = None
    masks_shape: list[int] = Field(default_factory=list)
    frames: list[Sam2RuntimeFrameSummary] = Field(default_factory=list)
    mean_adjacent_binary_iou: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    blocker: str | None = None
    error: str | None = None
    evidence_class: Literal["engineering_runtime_not_gold"] = (
        "engineering_runtime_not_gold"
    )
    gold_quality_claim_authorized: Literal[False] = False
    production_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> Sam2RuntimeObservation:
        if (
            self.media_origin == "camera_original_derived_clip"
            and (
                self.parent_source_path is None
                or self.parent_source_sha256 is None
                or self.source_start_seconds is None
            )
        ):
            raise ValueError(
                "derived camera clips require parent source provenance"
            )
        if self.status == "completed":
            required_values = (
                self.resolved_code_revision,
                self.code_license_sha256,
                self.resolved_semantic_revision,
                self.semantic_checkpoint_sha256,
                self.semantic_checkpoint_hash_kind,
                self.anchor_mask_sha256,
                self.anchor_selected_fraction,
                self.resolved_sam_revision,
                self.sam_checkpoint_file_sha256,
                self.sam_checkpoint_state_sha256,
                self.sam_checkpoint_hash_kind,
                self.propagation_fps,
                self.cold_processing_fps,
                self.masks_path,
                self.masks_sha256,
                self.masks_dtype,
            )
            if (
                any(value is None for value in required_values)
                or self.resolved_code_revision
                != self.requested_code_revision
                or self.resolved_semantic_revision
                != self.requested_semantic_revision
                or self.resolved_sam_revision != self.requested_sam_revision
                or len(self.frames) != self.decoded_frame_count
                or self.masks_shape
                != [self.decoded_frame_count, self.height, self.width]
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed SAM 2 runtime evidence requires exact code, "
                    "semantic anchor, checkpoint, masks, and timing identities"
                )
        elif self.status == "blocked":
            if not self.blocker or self.frames or self.masks_sha256 is not None:
                raise ValueError(
                    "blocked SAM 2 runtime evidence requires a blocker and "
                    "cannot carry completed masks"
                )
        elif not self.error or self.frames or self.masks_sha256 is not None:
            raise ValueError(
                "failed SAM 2 runtime evidence requires an error and cannot "
                "carry completed masks"
            )
        return self


@dataclass(frozen=True)
class Sam2VideoRun:
    masks: np.ndarray
    object_presence_probabilities: np.ndarray
    resolved_revision: str
    checkpoint_file_sha256: str
    checkpoint_state_sha256: str
    model_load_seconds: float
    propagation_seconds: float
    peak_gpu_memory_mb: float
    memory_growth_mb: float
    precision: str


class Sam2Runner(Protocol):
    def run(
        self,
        frames: Sequence[Image.Image],
        anchor_mask: np.ndarray,
    ) -> Sam2VideoRun: ...


Sam2RunnerFactory = Callable[[ComputeBackend, str, str], Sam2Runner]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mask_sha256(mask: np.ndarray) -> str:
    canonical = np.ascontiguousarray(mask, dtype="<f4")
    digest = hashlib.sha256()
    digest.update(f"{canonical.shape[0]}x{canonical.shape[1]}:<f4".encode())
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _binary_iou(left: np.ndarray, right: np.ndarray) -> float:
    left_binary = np.asarray(left >= 0.5, dtype=bool)
    right_binary = np.asarray(right >= 0.5, dtype=bool)
    union = np.logical_or(left_binary, right_binary).sum()
    if not union:
        return 1.0
    return float(np.logical_and(left_binary, right_binary).sum() / union)


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
    if candidate is None:
        raise ValueError(
            f"formal model source registry is missing {candidate_id}"
        )
    if candidate.code.revision is None or candidate.weights.revision is None:
        raise ValueError(
            f"formal model source registry has no immutable {candidate_id} "
            "revision"
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


def _decode_video(
    path: Path,
    maximum_frames: int | None,
) -> tuple[list[Image.Image], float, int, int, int]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise OSError(f"OpenCV could not open {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    source_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list[Image.Image] = []
    width = 0
    height = 0
    try:
        while maximum_frames is None or len(frames) < maximum_frames:
            success, frame_bgr = capture.read()
            if not success:
                break
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            height, width = frame_rgb.shape[:2]
            frames.append(Image.fromarray(frame_rgb, mode="RGB"))
    finally:
        capture.release()
    if fps <= 0 or source_frame_count <= 1 or len(frames) <= 1:
        raise ValueError("SAM 2 runtime video has invalid timing or frame count")
    return frames, fps, width, height, source_frame_count


class TransformersSam2VideoRunner:
    def __init__(
        self,
        backend: ComputeBackend,
        model_id: str,
        revision: str,
    ) -> None:
        self.backend = backend
        self.model_id = model_id
        self.revision = revision
        self._processor: object | None = None
        self._model: torch.nn.Module | None = None
        self._resolved_revision: str | None = None
        self._checkpoint_file_sha256: str | None = None
        self._checkpoint_state_sha256: str | None = None

    def _ensure_loaded(self) -> float:
        if self._processor is not None and self._model is not None:
            return 0.0
        from huggingface_hub import try_to_load_from_cache
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        cache_dir = settings.huggingface_cache_dir
        checkpoint_path = try_to_load_from_cache(
            self.model_id,
            "model.safetensors",
            cache_dir=cache_dir,
            revision=self.revision,
        )
        if not isinstance(checkpoint_path, str):
            raise OSError(
                "exact SAM 2.1 safetensors checkpoint is not in the local cache"
            )
        checkpoint_file = Path(checkpoint_path).resolve()
        if not checkpoint_file.is_file():
            raise OSError("cached SAM 2.1 safetensors checkpoint is missing")

        accelerator_enabled = (
            self.backend.info.runtime in {"cuda", "rocm"}
            and torch.cuda.is_available()
        )
        device = self.backend.torch_device
        inference_dtype = (
            torch.bfloat16 if accelerator_enabled else torch.float32
        )
        load_started = time.perf_counter()
        processor = Sam2VideoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            cache_dir=cache_dir,
            local_files_only=True,
        )
        model = Sam2VideoModel.from_pretrained(
            self.model_id,
            revision=self.revision,
            cache_dir=cache_dir,
            local_files_only=True,
        )
        resolved_revision = str(
            getattr(model.config, "_commit_hash", None)
            or getattr(model.config, "revision", None)
            or ""
        )
        checkpoint_state_sha256 = torch_model_state_sha256(model)
        checkpoint_file_sha256 = _sha256(checkpoint_file)
        model.to(device=device, dtype=inference_dtype)
        model.eval()
        if accelerator_enabled:
            torch.cuda.synchronize(device)
        self._processor = processor
        self._model = model
        self._resolved_revision = resolved_revision
        self._checkpoint_file_sha256 = checkpoint_file_sha256
        self._checkpoint_state_sha256 = checkpoint_state_sha256
        return time.perf_counter() - load_started

    def run(
        self,
        frames: Sequence[Image.Image],
        anchor_mask: np.ndarray,
    ) -> Sam2VideoRun:
        accelerator_enabled = (
            self.backend.info.runtime in {"cuda", "rocm"}
            and torch.cuda.is_available()
        )
        device = self.backend.torch_device
        precision = "bfloat16" if accelerator_enabled else "float32"
        inference_dtype = (
            torch.bfloat16 if accelerator_enabled else torch.float32
        )
        if accelerator_enabled:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(device)
            torch.cuda.synchronize(device)
            baseline_allocated = torch.cuda.memory_allocated(device)
        else:
            baseline_allocated = 0
        model_load_seconds = self._ensure_loaded()
        processor = self._processor
        model = self._model
        if (
            processor is None
            or model is None
            or self._resolved_revision is None
            or self._checkpoint_file_sha256 is None
            or self._checkpoint_state_sha256 is None
        ):
            raise RuntimeError("SAM 2 persistent model identity is incomplete")

        propagation_started = time.perf_counter()
        masks_by_index: dict[int, np.ndarray] = {}
        presence_by_index: dict[int, float] = {}
        session = processor.init_video_session(
            video=list(frames),
            inference_device=device,
            inference_state_device="cpu",
            processing_device=device,
            video_storage_device="cpu",
            dtype=inference_dtype,
        )
        processor.add_inputs_to_inference_session(
            inference_session=session,
            frame_idx=0,
            obj_ids=1,
            input_masks=[np.asarray(anchor_mask, dtype=np.uint8)],
        )
        with torch.inference_mode():
            model(inference_session=session, frame_idx=0)
            for output in model.propagate_in_video_iterator(
                session,
                start_frame_idx=0,
                show_progress_bar=False,
            ):
                frame_index = int(output.frame_idx)
                postprocessed = processor.post_process_masks(
                    [output.pred_masks],
                    original_sizes=[
                        [session.video_height, session.video_width]
                    ],
                    binarize=False,
                )[0]
                probability = (
                    torch.sigmoid(postprocessed[0, 0].float())
                    .clamp(0, 1)
                    .cpu()
                    .numpy()
                    .astype(np.float32, copy=False)
                )
                masks_by_index[frame_index] = probability
                object_logits = output.object_score_logits
                presence_by_index[frame_index] = (
                    float(torch.sigmoid(object_logits.float()).mean().item())
                    if object_logits is not None
                    else 1.0
                )
        if accelerator_enabled:
            torch.cuda.synchronize(device)
        propagation_seconds = time.perf_counter() - propagation_started

        expected_indices = list(range(len(frames)))
        if sorted(masks_by_index) != expected_indices:
            raise RuntimeError(
                "SAM 2 propagation did not return every decoded frame"
            )
        masks = np.stack(
            [masks_by_index[index] for index in expected_indices],
            axis=0,
        ).astype(np.float32, copy=False)
        probabilities = np.asarray(
            [presence_by_index[index] for index in expected_indices],
            dtype=np.float32,
        )
        if accelerator_enabled:
            peak_gpu_memory_mb = float(
                torch.cuda.max_memory_allocated(device) / (1024 * 1024)
            )
            memory_growth_mb = float(
                max(
                    0,
                    torch.cuda.memory_allocated(device) - baseline_allocated,
                )
                / (1024 * 1024)
            )
        else:
            peak_gpu_memory_mb = 0.0
            memory_growth_mb = 0.0

        del session
        gc.collect()
        if accelerator_enabled:
            torch.cuda.empty_cache()
        return Sam2VideoRun(
            masks=masks,
            object_presence_probabilities=probabilities,
            resolved_revision=self._resolved_revision,
            checkpoint_file_sha256=self._checkpoint_file_sha256,
            checkpoint_state_sha256=self._checkpoint_state_sha256,
            model_load_seconds=model_load_seconds,
            propagation_seconds=propagation_seconds,
            peak_gpu_memory_mb=peak_gpu_memory_mb,
            memory_growth_mb=memory_growth_mb,
            precision=precision,
        )

    def release_model(self) -> None:
        self._model = None
        self._processor = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _default_runner_factory(
    backend: ComputeBackend,
    model_id: str,
    revision: str,
) -> Sam2Runner:
    return TransformersSam2VideoRunner(backend, model_id, revision)


def capture_sam2_runtime_observation(
    source_registry_path: str | Path,
    code_repository_path: str | Path,
    video_path: str | Path,
    masks_output_path: str | Path,
    report_output_path: str | Path,
    *,
    semantic_candidate_id: SemanticRuntimeCandidateId = (
        "oneformer_ade20k_swin_large"
    ),
    semantic_target: str = "mountain",
    maximum_frames: int | None = 120,
    media_origin: MediaOrigin = "procedural",
    parent_source_path: str | Path | None = None,
    source_start_seconds: float | None = None,
    backend: ComputeBackend | None = None,
    semantic_provider_factory: Callable[..., SemanticMaskProvider]
    | None = None,
    runner_factory: Sam2RunnerFactory = _default_runner_factory,
) -> Sam2RuntimeObservation:
    registry_file = Path(source_registry_path).resolve()
    repository = Path(code_repository_path).resolve()
    video_file = Path(video_path).resolve()
    masks_destination = Path(masks_output_path).resolve()
    report_destination = Path(report_output_path).resolve()
    if not registry_file.is_file():
        raise FileNotFoundError(registry_file)
    if not video_file.is_file():
        raise FileNotFoundError(video_file)
    if maximum_frames is not None and maximum_frames <= 1:
        raise ValueError("maximum_frames must be greater than one")
    protected_paths = {registry_file, video_file}
    if masks_destination in protected_paths or report_destination in protected_paths:
        raise ValueError("SAM 2 runtime outputs cannot overwrite input artifacts")
    parent_file = (
        Path(parent_source_path).resolve()
        if parent_source_path is not None
        else None
    )
    if parent_file is not None and not parent_file.is_file():
        raise FileNotFoundError(parent_file)
    if media_origin == "camera_original_derived_clip" and (
        parent_file is None or source_start_seconds is None
    ):
        raise ValueError(
            "derived camera clips require parent source and start time"
        )

    registry_content = registry_file.read_bytes()
    manifest = FormalModelSourceManifest.model_validate_json(registry_content)
    sam_candidate = _candidate(manifest, SAM2_CANDIDATE_ID)
    semantic_candidate = _candidate(manifest, semantic_candidate_id)
    expected_semantic_model_id = SEMANTIC_RUNTIME_MODEL_IDS[
        semantic_candidate_id
    ]
    frames, fps, width, height, source_frame_count = _decode_video(
        video_file,
        maximum_frames,
    )
    selected_backend = backend or TorchComputeBackend(
        settings.device_preference
    )
    accelerator_enabled = (
        selected_backend.info.runtime in {"cuda", "rocm"}
        and torch.cuda.is_available()
    )

    resolved_code_revision: str | None = None
    code_license_sha256: str | None = None
    resolved_semantic_revision: str | None = None
    semantic_checkpoint_sha256: str | None = None
    semantic_checkpoint_hash_kind: str | None = None
    anchor_mask_sha256: str | None = None
    anchor_selected_fraction: float | None = None
    anchor_probability_threshold = 0.30
    anchor_elapsed_seconds = 0.0
    anchor_peak_gpu_memory_mb = 0.0
    sam_run: Sam2VideoRun | None = None
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()

    try:
        if not repository.is_dir():
            raise OSError("installed SAM 2 code repository is missing")
        resolved_code_revision = _repository_revision(repository)
        if resolved_code_revision != sam_candidate.code.revision:
            raise ValueError(
                "installed SAM 2 code revision does not match the registry"
            )
        license_file = repository / "LICENSE"
        if not license_file.is_file():
            raise OSError("installed SAM 2 code license file is missing")
        code_license_sha256 = _sha256(license_file)

        if accelerator_enabled:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(
                selected_backend.torch_device
            )
        anchor_started = time.perf_counter()
        selected_provider_factory = semantic_provider_factory or (
            OneFormerSemanticMaskProvider
            if semantic_candidate_id == "oneformer_ade20k_swin_large"
            else SemanticMaskProvider
        )
        provider = selected_provider_factory(
            selected_backend,
            model_id=expected_semantic_model_id,
            model_revision=semantic_candidate.weights.revision,
            local_files_only=True,
        )
        try:
            prediction = provider.predict_many(
                frames[0],
                [semantic_target],
            )[semantic_target]
            metadata = prediction.metadata
            resolved_semantic_revision = str(
                metadata.get("model_revision", "")
            )
            semantic_checkpoint_sha256 = str(
                metadata.get("checkpoint_sha256", "")
            )
            semantic_checkpoint_hash_kind = str(
                metadata.get("checkpoint_hash_kind", "")
            )
            probability_mask = np.asarray(
                prediction.mask,
                dtype=np.float32,
            )
            anchor_probability_threshold = float(
                metadata.get("probability_threshold", 0.30)
            )
            anchor_mask = probability_mask >= anchor_probability_threshold
            anchor_selected_fraction = float(anchor_mask.mean())
            if not 0.001 <= anchor_selected_fraction <= 0.999:
                raise ValueError(
                    "semantic anchor is empty or nearly full-frame"
                )
            anchor_mask_sha256 = _mask_sha256(
                anchor_mask.astype(np.float32)
            )
        finally:
            provider.release_model()
        if accelerator_enabled:
            torch.cuda.synchronize(selected_backend.torch_device)
            anchor_peak_gpu_memory_mb = float(
                torch.cuda.max_memory_allocated(
                    selected_backend.torch_device
                )
                / (1024 * 1024)
            )
            torch.cuda.empty_cache()
        anchor_elapsed_seconds = time.perf_counter() - anchor_started
        if (
            resolved_semantic_revision
            != semantic_candidate.weights.revision
            or not semantic_checkpoint_sha256
            or semantic_checkpoint_hash_kind
            != "colorgraph.torch-state-dict/v1"
        ):
            raise ValueError(
                "semantic anchor identity does not match the frozen registry"
            )

        runner = runner_factory(
            selected_backend,
            SAM2_MODEL_ID,
            sam_candidate.weights.revision,
        )
        try:
            sam_run = runner.run(frames, anchor_mask.astype(np.uint8))
        finally:
            release_model = getattr(runner, "release_model", None)
            if callable(release_model):
                release_model()
        if sam_run.resolved_revision != sam_candidate.weights.revision:
            raise ValueError(
                "loaded SAM 2 model revision does not match the registry"
            )
        if sam_run.masks.shape != (len(frames), height, width):
            raise ValueError(
                "SAM 2 mask tensor does not match decoded video dimensions"
            )
        if sam_run.object_presence_probabilities.shape != (len(frames),):
            raise ValueError(
                "SAM 2 object-presence output does not cover every frame"
            )
    except ModuleNotFoundError as exception:
        status = "blocked"
        blocker = "model_or_runtime_dependency_not_available_locally"
        dependency = exception.name or "unknown"
        error = (
            "ModuleNotFoundError: required local runtime dependency is "
            f"unavailable ({dependency})"
        )
    except OSError as exception:
        status = "blocked"
        blocker = "model_or_runtime_dependency_not_available_locally"
        error = f"OSError: {exception}"
    except (RuntimeError, TypeError, ValueError) as exception:
        status = "failed"
        error = f"{type(exception).__name__}: {exception}"

    elapsed_seconds = max(time.perf_counter() - started, 1e-9)
    frame_summaries: list[Sam2RuntimeFrameSummary] = []
    masks_sha256: str | None = None
    mean_adjacent_iou: float | None = None
    if status == "completed" and sam_run is not None:
        adjacent_ious: list[float] = []
        for index, mask in enumerate(sam_run.masks):
            adjacent_iou = (
                None
                if index == 0
                else _binary_iou(sam_run.masks[index - 1], mask)
            )
            if adjacent_iou is not None:
                adjacent_ious.append(adjacent_iou)
            frame_summaries.append(
                Sam2RuntimeFrameSummary(
                    frame_index=index,
                    mask_sha256=_mask_sha256(mask),
                    selected_fraction=float((mask >= 0.5).mean()),
                    object_presence_probability=float(
                        sam_run.object_presence_probabilities[index]
                    ),
                    adjacent_binary_iou=adjacent_iou,
                )
            )
        mean_adjacent_iou = float(np.mean(adjacent_ious))
        masks_destination.parent.mkdir(parents=True, exist_ok=True)
        masks_temporary = masks_destination.with_name(
            masks_destination.stem + ".tmp" + masks_destination.suffix
        )
        np.savez_compressed(
            masks_temporary,
            masks=sam_run.masks.astype(np.float32, copy=False),
            object_presence_probabilities=(
                sam_run.object_presence_probabilities.astype(
                    np.float32,
                    copy=False,
                )
            ),
            frame_indices=np.arange(len(frames), dtype=np.int32),
        )
        masks_temporary.replace(masks_destination)
        masks_sha256 = _sha256(masks_destination)

    observation = Sam2RuntimeObservation(
        created_at=datetime.now(UTC),
        status=status,
        source_registry_path=str(registry_file),
        source_registry_sha256=hashlib.sha256(
            registry_content
        ).hexdigest(),
        code_repository_path=str(repository),
        requested_code_revision=sam_candidate.code.revision,
        resolved_code_revision=resolved_code_revision,
        code_license_id=sam_candidate.code.license_id,
        code_license_sha256=code_license_sha256,
        video_path=str(video_file),
        video_sha256=_sha256(video_file),
        media_origin=media_origin,
        parent_source_path=(
            str(parent_file) if parent_file is not None else None
        ),
        parent_source_sha256=(
            _sha256(parent_file) if parent_file is not None else None
        ),
        source_start_seconds=source_start_seconds,
        width=width,
        height=height,
        fps=fps,
        decoded_frame_count=len(frames),
        source_frame_count=source_frame_count,
        truncated_to_maximum_frames=len(frames) < source_frame_count,
        semantic_candidate_id=semantic_candidate_id,
        semantic_target=semantic_target,
        semantic_model_id=expected_semantic_model_id,
        requested_semantic_revision=semantic_candidate.weights.revision,
        resolved_semantic_revision=resolved_semantic_revision,
        semantic_checkpoint_sha256=semantic_checkpoint_sha256,
        semantic_checkpoint_hash_kind=semantic_checkpoint_hash_kind,
        anchor_probability_threshold=anchor_probability_threshold,
        anchor_mask_sha256=anchor_mask_sha256,
        anchor_selected_fraction=anchor_selected_fraction,
        anchor_elapsed_seconds=anchor_elapsed_seconds,
        anchor_peak_gpu_memory_mb=anchor_peak_gpu_memory_mb,
        requested_sam_revision=sam_candidate.weights.revision,
        resolved_sam_revision=(
            sam_run.resolved_revision if sam_run is not None else None
        ),
        sam_checkpoint_file_sha256=(
            sam_run.checkpoint_file_sha256
            if sam_run is not None
            else None
        ),
        sam_checkpoint_state_sha256=(
            sam_run.checkpoint_state_sha256
            if sam_run is not None
            else None
        ),
        sam_checkpoint_hash_kind=(
            "colorgraph.torch-state-dict/v1"
            if sam_run is not None
            else None
        ),
        weights_license_id=sam_candidate.weights.license_id,
        weights_commercial_use_allowed=(
            sam_candidate.weights.commercial_use_allowed
        ),
        weights_redistribution_allowed=(
            sam_candidate.weights.redistribution_allowed
        ),
        operating_system=platform.platform(),
        runtime=selected_backend.info.runtime,
        device_name=selected_backend.info.name,
        precision=(
            sam_run.precision
            if sam_run is not None
            else (
                "bfloat16"
                if selected_backend.info.runtime in {"cuda", "rocm"}
                else "float32"
            )
        ),
        model_load_seconds=(
            sam_run.model_load_seconds if sam_run is not None else 0.0
        ),
        propagation_seconds=(
            sam_run.propagation_seconds if sam_run is not None else 0.0
        ),
        elapsed_seconds=elapsed_seconds,
        propagation_fps=(
            len(frames) / sam_run.propagation_seconds
            if sam_run is not None and sam_run.propagation_seconds > 0
            else None
        ),
        cold_processing_fps=(
            len(frames) / elapsed_seconds
            if status == "completed"
            else None
        ),
        peak_cpu_memory_mb=process_peak_memory_mb(),
        peak_gpu_memory_mb=(
            max(anchor_peak_gpu_memory_mb, sam_run.peak_gpu_memory_mb)
            if sam_run is not None
            else anchor_peak_gpu_memory_mb
        ),
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if accelerator_enabled
            else "not_applicable"
        ),
        memory_growth_mb=(
            sam_run.memory_growth_mb if sam_run is not None else 0.0
        ),
        masks_path=(
            str(masks_destination) if status == "completed" else None
        ),
        masks_sha256=masks_sha256,
        masks_dtype="float32" if status == "completed" else None,
        masks_shape=(
            list(sam_run.masks.shape)
            if status == "completed" and sam_run is not None
            else []
        ),
        frames=frame_summaries,
        mean_adjacent_binary_iou=mean_adjacent_iou,
        blocker=blocker,
        error=error,
    )
    report_destination.parent.mkdir(parents=True, exist_ok=True)
    report_temporary = report_destination.with_name(
        report_destination.name + ".tmp"
    )
    report_temporary.write_text(
        json.dumps(
            observation.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_temporary.replace(report_destination)
    return observation
