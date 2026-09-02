from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
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
from colorgraph.vision.semantic import (
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
)

CUTIE_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.cutie-runtime-observation/v1"
)
CUTIE_CANDIDATE_ID = "cutie"
CUTIE_CHECKPOINT_NAME = "cutie-base-mega.pth"
CUTIE_CHECKPOINT_MD5 = "a6071de6136982e396851903ab4c083a"
CUTIE_RESNET18_SHA256 = (
    "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8"
)
CUTIE_RESNET50_SHA256 = (
    "19c8e3572231adff6824a2da93fd67b5986919a2e65f8b6007eab4edee220097"
)
RuntimeStatus = Literal["completed", "blocked", "failed"]
MediaOrigin = Literal[
    "camera_original",
    "camera_original_derived_clip",
    "licensed_stock",
    "published_dataset",
    "procedural",
]


class CutieRuntimeFrameSummary(StrictEvaluationModel):
    frame_index: int = Field(ge=0)
    mask_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_fraction: float = Field(ge=0, le=1)
    adjacent_binary_iou: float | None = Field(default=None, ge=0, le=1)
    anchor_binary_iou: float = Field(ge=0, le=1)
    elapsed_seconds: float = Field(gt=0)


class CutieRuntimeObservation(StrictEvaluationModel):
    schema_version: str = CUTIE_RUNTIME_OBSERVATION_VERSION
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
    checkpoint_path: str
    requested_weights_source_revision: str = Field(
        pattern=r"^[0-9a-f]{40}$"
    )
    resolved_weights_source_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    checkpoint_file_md5: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )
    expected_checkpoint_file_md5: str = CUTIE_CHECKPOINT_MD5
    checkpoint_file_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: Literal[
        "colorgraph.torch-state-dict/v1"
    ] | None = None
    configuration_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    resnet18_path: str
    resnet18_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    resnet50_path: str
    resnet50_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    weights_license_id: str | None
    weights_commercial_use_allowed: bool | None
    weights_redistribution_allowed: bool | None
    weights_license_review_complete: bool
    local_files_only: Literal[True] = True
    network_access_allowed: Literal[False] = False
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    maximum_internal_size: int = Field(gt=0)
    model_load_seconds: float = Field(ge=0)
    propagation_seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(gt=0)
    propagation_fps: float | None = Field(default=None, gt=0)
    cold_processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_cpu_memory_scope: Literal[
        "maximum_controller_bridge_process_lifetime_peak"
    ] = "maximum_controller_bridge_process_lifetime_peak"
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
    frames: list[CutieRuntimeFrameSummary] = Field(default_factory=list)
    mean_adjacent_binary_iou: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    final_anchor_binary_iou: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    selected_fraction_drift: float | None = Field(default=None, ge=0, le=1)
    blocker: str | None = None
    error: str | None = None
    evidence_class: Literal["engineering_runtime_not_gold"] = (
        "engineering_runtime_not_gold"
    )
    gold_quality_claim_authorized: Literal[False] = False
    production_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> CutieRuntimeObservation:
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
            required = (
                self.resolved_code_revision,
                self.code_license_sha256,
                self.resolved_semantic_revision,
                self.semantic_checkpoint_sha256,
                self.semantic_checkpoint_hash_kind,
                self.anchor_mask_sha256,
                self.anchor_selected_fraction,
                self.resolved_weights_source_revision,
                self.checkpoint_file_md5,
                self.checkpoint_file_sha256,
                self.checkpoint_state_sha256,
                self.checkpoint_hash_kind,
                self.configuration_sha256,
                self.resnet18_sha256,
                self.resnet50_sha256,
                self.propagation_fps,
                self.cold_processing_fps,
                self.masks_path,
                self.masks_sha256,
                self.masks_dtype,
                self.mean_adjacent_binary_iou,
                self.final_anchor_binary_iou,
                self.selected_fraction_drift,
            )
            if (
                any(value is None for value in required)
                or self.resolved_code_revision
                != self.requested_code_revision
                or self.resolved_semantic_revision
                != self.requested_semantic_revision
                or self.resolved_weights_source_revision
                != self.requested_weights_source_revision
                or self.checkpoint_file_md5
                != self.expected_checkpoint_file_md5
                or self.resnet18_sha256 != CUTIE_RESNET18_SHA256
                or self.resnet50_sha256 != CUTIE_RESNET50_SHA256
                or self.masks_shape
                != [self.decoded_frame_count, self.height, self.width]
                or len(self.frames) != self.decoded_frame_count
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed Cutie evidence requires exact code, semantic "
                    "anchor, checkpoint, auxiliary weights, masks, and timing"
                )
        elif self.status == "blocked":
            if not self.blocker or self.frames or self.masks_sha256 is not None:
                raise ValueError(
                    "blocked Cutie evidence requires a blocker and cannot "
                    "carry completed masks"
                )
        elif not self.error or self.frames or self.masks_sha256 is not None:
            raise ValueError(
                "failed Cutie evidence requires an error and cannot carry "
                "completed masks"
            )
        return self


@dataclass(frozen=True)
class CutieBridgeResult:
    masks: np.ndarray
    frame_seconds: np.ndarray
    runtime: str
    precision: str
    model_load_seconds: float
    inference_seconds: float
    peak_cpu_memory_mb: float
    peak_gpu_memory_mb: float
    memory_growth_mb: float
    checkpoint_file_md5: str
    checkpoint_file_sha256: str
    checkpoint_state_sha256: str
    configuration_sha256: str
    resnet18_sha256: str
    resnet50_sha256: str
    maximum_internal_size: int


class CutieRunner(Protocol):
    def run(
        self,
        video: Path,
        anchor_mask: np.ndarray,
        maximum_frames: int | None,
        maximum_internal_size: int,
    ) -> CutieBridgeResult: ...


CutieRunnerFactory = Callable[
    [Path, Path, Path, Path, str],
    CutieRunner,
]


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


def _mask_sha256(array: np.ndarray) -> str:
    canonical = np.ascontiguousarray(array, dtype="<f4")
    if canonical.ndim != 2:
        raise ValueError("mask digest requires a two-dimensional array")
    digest = hashlib.sha256()
    digest.update(
        f"{canonical.shape[0]}x{canonical.shape[1]}:<f4".encode("ascii")
    )
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
    if (
        candidate is None
        or candidate.code.revision is None
        or candidate.weights.revision is None
    ):
        raise ValueError(
            f"formal registry lacks immutable {candidate_id} revisions"
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
            "installed Cutie repository is unavailable or not Git"
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
        raise ValueError("Cutie runtime video has invalid timing or frames")
    return frames, fps, width, height, source_frame_count


class SubprocessCutieRunner:
    def __init__(
        self,
        repository: Path,
        weights: Path,
        resnet_directory: Path,
        work_directory: Path,
        python_executable: str,
    ) -> None:
        self.repository = repository
        self.weights = weights
        self.resnet_directory = resnet_directory
        self.work_directory = work_directory
        self.python_executable = python_executable

    def run(
        self,
        video: Path,
        anchor_mask: np.ndarray,
        maximum_frames: int | None,
        maximum_internal_size: int,
    ) -> CutieBridgeResult:
        self.work_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".cutie-bridge-",
            dir=self.work_directory,
        ) as temporary_directory:
            temporary = Path(temporary_directory)
            anchor_path = temporary / "anchor.npy"
            output_path = temporary / "bridge.npz"
            np.save(
                anchor_path,
                np.asarray(anchor_mask, dtype=np.uint8),
                allow_pickle=False,
            )
            command = [
                self.python_executable,
                "-m",
                "colorgraph.vision.cutie_bridge",
                "--repository",
                str(self.repository),
                "--weights",
                str(self.weights),
                "--resnet-directory",
                str(self.resnet_directory),
                "--video",
                str(video),
                "--anchor-mask",
                str(anchor_path),
                "--output",
                str(output_path),
                "--maximum-internal-size",
                str(maximum_internal_size),
            ]
            if maximum_frames is not None:
                command.extend(["--maximum-frames", str(maximum_frames)])
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=60 * 30,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(
                    "Cutie bridge failed"
                    + (f": {detail[-2000:]}" if detail else "")
                )
            if not output_path.is_file():
                raise RuntimeError("Cutie bridge did not write its output")
            with np.load(output_path, allow_pickle=False) as archive:
                return CutieBridgeResult(
                    masks=np.asarray(archive["masks"], dtype=np.float32),
                    frame_seconds=np.asarray(
                        archive["frame_seconds"],
                        dtype=np.float64,
                    ),
                    runtime=str(archive["runtime"].item()),
                    precision=str(archive["precision"].item()),
                    model_load_seconds=float(
                        archive["model_load_seconds"].item()
                    ),
                    inference_seconds=float(
                        archive["inference_seconds"].item()
                    ),
                    peak_cpu_memory_mb=float(
                        archive["peak_cpu_memory_mb"].item()
                    ),
                    peak_gpu_memory_mb=float(
                        archive["peak_gpu_memory_mb"].item()
                    ),
                    memory_growth_mb=float(
                        archive["memory_growth_mb"].item()
                    ),
                    checkpoint_file_md5=str(
                        archive["checkpoint_file_md5"].item()
                    ),
                    checkpoint_file_sha256=str(
                        archive["checkpoint_file_sha256"].item()
                    ),
                    checkpoint_state_sha256=str(
                        archive["checkpoint_state_sha256"].item()
                    ),
                    configuration_sha256=str(
                        archive["configuration_sha256"].item()
                    ),
                    resnet18_sha256=str(
                        archive["resnet18_sha256"].item()
                    ),
                    resnet50_sha256=str(
                        archive["resnet50_sha256"].item()
                    ),
                    maximum_internal_size=int(
                        archive["maximum_internal_size"].item()
                    ),
                )


def _default_runner_factory(
    repository: Path,
    weights: Path,
    resnet_directory: Path,
    work_directory: Path,
    python_executable: str,
) -> CutieRunner:
    return SubprocessCutieRunner(
        repository,
        weights,
        resnet_directory,
        work_directory,
        python_executable,
    )


def capture_cutie_runtime_observation(
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
    maximum_internal_size: int = 480,
    media_origin: MediaOrigin = "procedural",
    parent_source_path: str | Path | None = None,
    source_start_seconds: float | None = None,
    backend: ComputeBackend | None = None,
    semantic_provider_factory: Callable[..., SemanticMaskProvider]
    | None = None,
    python_executable: str = sys.executable,
    runner_factory: CutieRunnerFactory = _default_runner_factory,
) -> CutieRuntimeObservation:
    registry_file = Path(source_registry_path).resolve()
    repository = Path(code_repository_path).resolve()
    video_file = Path(video_path).resolve()
    masks_destination = Path(masks_output_path).resolve()
    report_destination = Path(report_output_path).resolve()
    for required in (registry_file, video_file):
        if not required.is_file():
            raise FileNotFoundError(required)
    if maximum_frames is not None and maximum_frames <= 1:
        raise ValueError("maximum_frames must be greater than one")
    if maximum_internal_size <= 0:
        raise ValueError("maximum_internal_size must be positive")
    if masks_destination in {
        registry_file,
        video_file,
    } or report_destination in {registry_file, video_file}:
        raise ValueError("Cutie outputs cannot overwrite input artifacts")
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
    candidate = _candidate(manifest, CUTIE_CANDIDATE_ID)
    semantic_candidate = _candidate(manifest, semantic_candidate_id)
    semantic_model_id = SEMANTIC_RUNTIME_MODEL_IDS[semantic_candidate_id]
    weights = repository / "weights" / CUTIE_CHECKPOINT_NAME
    resnet_directory = repository / "resnet"
    resnet18 = resnet_directory / "resnet18-5c106cde.pth"
    resnet50 = resnet_directory / "resnet50-19c8e357.pth"
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
    run: CutieBridgeResult | None = None
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()

    try:
        if not repository.is_dir():
            raise OSError("installed Cutie code repository is missing")
        resolved_code_revision = _repository_revision(repository)
        if resolved_code_revision != candidate.code.revision:
            raise ValueError(
                "installed Cutie code revision does not match registry"
            )
        license_file = repository / "LICENSE"
        for required in (license_file, weights, resnet18, resnet50):
            if not required.is_file():
                raise OSError(
                    f"required Cutie artifact is missing: {required}"
                )
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
            model_id=semantic_model_id,
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
            resolved_semantic_revision != semantic_candidate.weights.revision
            or not semantic_checkpoint_sha256
            or semantic_checkpoint_hash_kind
            != "colorgraph.torch-state-dict/v1"
        ):
            raise ValueError(
                "semantic anchor identity does not match frozen registry"
            )

        runner = runner_factory(
            repository,
            weights,
            resnet_directory,
            masks_destination.parent,
            python_executable,
        )
        run = runner.run(
            video_file,
            anchor_mask.astype(np.uint8),
            maximum_frames,
            maximum_internal_size,
        )
        expected_shape = (len(frames), height, width)
        if run.masks.shape != expected_shape:
            raise ValueError(
                "Cutie mask tensor does not match decoded video dimensions"
            )
        if run.frame_seconds.shape != (len(frames),):
            raise ValueError(
                "Cutie timing does not cover every decoded frame"
            )
        if (
            run.checkpoint_file_md5 != CUTIE_CHECKPOINT_MD5
            or run.checkpoint_file_md5 != _md5(weights)
            or run.checkpoint_file_sha256 != _sha256(weights)
            or run.resnet18_sha256 != _sha256(resnet18)
            or run.resnet50_sha256 != _sha256(resnet50)
            or run.maximum_internal_size != maximum_internal_size
        ):
            raise ValueError(
                "Cutie bridge artifact identity does not match installation"
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
    except (
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exception:
        status = "failed"
        error = f"{type(exception).__name__}: {exception}"
    elapsed_seconds = max(time.perf_counter() - started, 1e-9)

    summaries: list[CutieRuntimeFrameSummary] = []
    masks_sha256: str | None = None
    mean_adjacent_iou: float | None = None
    final_anchor_iou: float | None = None
    selected_fraction_drift: float | None = None
    if status == "completed" and run is not None:
        anchor_float = anchor_mask.astype(np.float32)
        adjacent_ious: list[float] = []
        selected_fractions: list[float] = []
        for index, mask in enumerate(run.masks):
            adjacent_iou = (
                None
                if index == 0
                else _binary_iou(run.masks[index - 1], mask)
            )
            if adjacent_iou is not None:
                adjacent_ious.append(adjacent_iou)
            selected_fraction = float((mask >= 0.5).mean())
            selected_fractions.append(selected_fraction)
            summaries.append(
                CutieRuntimeFrameSummary(
                    frame_index=index,
                    mask_sha256=_mask_sha256(mask),
                    selected_fraction=selected_fraction,
                    adjacent_binary_iou=adjacent_iou,
                    anchor_binary_iou=_binary_iou(anchor_float, mask),
                    elapsed_seconds=float(run.frame_seconds[index]),
                )
            )
        mean_adjacent_iou = float(np.mean(adjacent_ious))
        final_anchor_iou = _binary_iou(anchor_float, run.masks[-1])
        selected_fraction_drift = float(
            abs(selected_fractions[-1] - selected_fractions[0])
        )
        masks_destination.parent.mkdir(parents=True, exist_ok=True)
        masks_temporary = masks_destination.with_name(
            masks_destination.stem + ".tmp" + masks_destination.suffix
        )
        np.savez_compressed(
            masks_temporary,
            masks=run.masks.astype(np.float32, copy=False),
            frame_seconds=run.frame_seconds.astype(
                np.float64,
                copy=False,
            ),
            frame_indices=np.arange(len(frames), dtype=np.int32),
        )
        masks_temporary.replace(masks_destination)
        masks_sha256 = _sha256(masks_destination)

    observation = CutieRuntimeObservation(
        created_at=datetime.now(UTC),
        status=status,
        source_registry_path=str(registry_file),
        source_registry_sha256=hashlib.sha256(
            registry_content
        ).hexdigest(),
        code_repository_path=str(repository),
        requested_code_revision=candidate.code.revision,
        resolved_code_revision=resolved_code_revision,
        code_license_id=candidate.code.license_id,
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
        semantic_model_id=semantic_model_id,
        requested_semantic_revision=semantic_candidate.weights.revision,
        resolved_semantic_revision=resolved_semantic_revision,
        semantic_checkpoint_sha256=semantic_checkpoint_sha256,
        semantic_checkpoint_hash_kind=semantic_checkpoint_hash_kind,
        anchor_probability_threshold=anchor_probability_threshold,
        anchor_mask_sha256=anchor_mask_sha256,
        anchor_selected_fraction=anchor_selected_fraction,
        anchor_elapsed_seconds=anchor_elapsed_seconds,
        anchor_peak_gpu_memory_mb=anchor_peak_gpu_memory_mb,
        checkpoint_path=str(weights),
        requested_weights_source_revision=candidate.weights.revision,
        resolved_weights_source_revision=(
            candidate.weights.revision if run is not None else None
        ),
        checkpoint_file_md5=(
            run.checkpoint_file_md5 if run is not None else None
        ),
        checkpoint_file_sha256=(
            run.checkpoint_file_sha256 if run is not None else None
        ),
        checkpoint_state_sha256=(
            run.checkpoint_state_sha256 if run is not None else None
        ),
        checkpoint_hash_kind=(
            "colorgraph.torch-state-dict/v1"
            if run is not None
            else None
        ),
        configuration_sha256=(
            run.configuration_sha256 if run is not None else None
        ),
        resnet18_path=str(resnet18),
        resnet18_sha256=(
            run.resnet18_sha256 if run is not None else None
        ),
        resnet50_path=str(resnet50),
        resnet50_sha256=(
            run.resnet50_sha256 if run is not None else None
        ),
        weights_license_id=candidate.weights.license_id,
        weights_commercial_use_allowed=(
            candidate.weights.commercial_use_allowed
        ),
        weights_redistribution_allowed=(
            candidate.weights.redistribution_allowed
        ),
        weights_license_review_complete=(
            candidate.weights.license_id is not None
            and candidate.weights.commercial_use_allowed is not None
            and candidate.weights.redistribution_allowed is not None
        ),
        operating_system=platform.platform(),
        runtime=run.runtime if run is not None else selected_backend.info.runtime,
        device_name=selected_backend.info.name,
        precision=run.precision if run is not None else "unavailable",
        maximum_internal_size=maximum_internal_size,
        model_load_seconds=(
            run.model_load_seconds if run is not None else 0
        ),
        propagation_seconds=(
            run.inference_seconds if run is not None else 0
        ),
        elapsed_seconds=elapsed_seconds,
        propagation_fps=(
            len(frames) / run.inference_seconds
            if run is not None and run.inference_seconds > 0
            else None
        ),
        cold_processing_fps=(
            len(frames) / elapsed_seconds
            if status == "completed"
            else None
        ),
        peak_cpu_memory_mb=max(
            process_peak_memory_mb(),
            run.peak_cpu_memory_mb if run is not None else 0,
        ),
        peak_gpu_memory_mb=max(
            anchor_peak_gpu_memory_mb,
            run.peak_gpu_memory_mb if run is not None else 0,
        ),
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if accelerator_enabled
            else "not_applicable"
        ),
        memory_growth_mb=(
            run.memory_growth_mb if run is not None else 0
        ),
        masks_path=(
            str(masks_destination) if status == "completed" else None
        ),
        masks_sha256=masks_sha256,
        masks_dtype="float32" if status == "completed" else None,
        masks_shape=(
            list(run.masks.shape)
            if status == "completed" and run is not None
            else []
        ),
        frames=summaries,
        mean_adjacent_binary_iou=mean_adjacent_iou,
        final_anchor_binary_iou=final_anchor_iou,
        selected_fraction_drift=selected_fraction_drift,
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
