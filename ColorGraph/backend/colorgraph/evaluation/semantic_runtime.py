from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

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
from colorgraph.vision.semantic import (
    DEFAULT_LABEL_MAPPING_PATH,
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
)

SEMANTIC_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.semantic-runtime-observation/v1"
)

SemanticRuntimeCandidateId = Literal[
    "current_segformer_b0",
    "segformer_b5",
    "oneformer_ade20k_swin_large",
]
RuntimeStatus = Literal["completed", "blocked", "failed"]
ProviderFactory = Callable[..., SemanticMaskProvider]

SEMANTIC_RUNTIME_MODEL_IDS: dict[SemanticRuntimeCandidateId, str] = {
    "current_segformer_b0": (
        "nvidia/segformer-b0-finetuned-ade-512-512"
    ),
    "segformer_b5": "nvidia/segformer-b5-finetuned-ade-640-640",
    "oneformer_ade20k_swin_large": (
        "shi-labs/oneformer_ade20k_swin_large"
    ),
}


class SemanticRuntimeFrameRequest(StrictEvaluationModel):
    frame_path: str
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticRuntimeTargetPrediction(StrictEvaluationModel):
    target: str = Field(min_length=1)
    mask_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence: float = Field(ge=0, le=1)
    score_semantics: str = Field(min_length=1)
    mean_score: float = Field(ge=0, le=1)
    maximum_score: float = Field(ge=0, le=1)
    selected_fraction: float = Field(ge=0, le=1)
    class_ids: list[int]
    class_labels: list[str]
    class_mapping_status: Literal["resolved", "model_class_missing"]


class SemanticRuntimeFramePrediction(StrictEvaluationModel):
    frame_path: str
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    targets: list[SemanticRuntimeTargetPrediction] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_targets(self) -> SemanticRuntimeFramePrediction:
        target_names = [target.target for target in self.targets]
        if len(set(target_names)) != len(target_names):
            raise ValueError("semantic runtime targets must be unique")
        return self


class SemanticRuntimeObservation(StrictEvaluationModel):
    schema_version: str = SEMANTIC_RUNTIME_OBSERVATION_VERSION
    created_at: datetime
    status: RuntimeStatus
    source_registry_path: str
    source_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: SemanticRuntimeCandidateId
    model_id: str = Field(min_length=1)
    requested_model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_model_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: Literal[
        "colorgraph.torch-state-dict/v1"
    ] | None = None
    code_license_id: str | None
    weights_license_id: str | None
    code_commercial_use_allowed: bool | None
    weights_commercial_use_allowed: bool | None
    label_mapping_path: str
    label_mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_files_only: Literal[True] = True
    network_access_allowed: Literal[False] = False
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    requested_frames: list[SemanticRuntimeFrameRequest] = Field(min_length=1)
    predictions: list[SemanticRuntimeFramePrediction] = Field(
        default_factory=list
    )
    elapsed_seconds: float = Field(gt=0)
    processing_timing_scope: Literal[
        "cold_model_load_hash_and_inference"
    ] = "cold_model_load_hash_and_inference"
    processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_cpu_memory_scope: Literal["process_lifetime_peak"] = (
        "process_lifetime_peak"
    )
    peak_gpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_scope: Literal[
        "torch_peak_allocated_since_reset",
        "not_applicable",
    ]
    blocker: str | None = None
    error: str | None = None
    gold_quality_claim_authorized: Literal[False] = False
    commercial_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> SemanticRuntimeObservation:
        if self.status == "completed":
            if (
                len(self.predictions) != len(self.requested_frames)
                or self.processing_fps is None
                or self.resolved_model_revision
                != self.requested_model_revision
                or self.checkpoint_sha256 is None
                or self.checkpoint_hash_kind is None
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed semantic runtime observation requires exact "
                    "model identity, full predictions, and runtime metrics"
                )
        elif self.status == "blocked":
            if (
                not self.blocker
                or self.predictions
                or self.processing_fps is not None
                or self.resolved_model_revision is not None
                or self.checkpoint_sha256 is not None
                or self.checkpoint_hash_kind is not None
            ):
                raise ValueError(
                    "blocked semantic runtime observation requires a blocker "
                    "and cannot carry loaded-model or completed-run evidence"
                )
        elif (
            not self.error
            or self.predictions
            or self.processing_fps is not None
        ):
            raise ValueError(
                "failed semantic runtime observation requires an error and "
                "cannot carry completed-run evidence"
            )
        return self


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


def _validated_candidate(
    source_registry_path: Path,
    candidate_id: SemanticRuntimeCandidateId,
) -> tuple[FormalModelCandidate, str]:
    content = source_registry_path.read_bytes()
    manifest = FormalModelSourceManifest.model_validate_json(content)
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
            f"formal source registry is missing {candidate_id}"
        )
    expected_model_id = SEMANTIC_RUNTIME_MODEL_IDS[candidate_id]
    if candidate.weights.revision is None:
        raise ValueError(
            f"{candidate_id} weights revision is not frozen"
        )
    expected_url = (
        f"https://huggingface.co/{expected_model_id}/tree/"
        f"{candidate.weights.revision}"
    )
    if candidate.weights.url != expected_url:
        raise ValueError(
            f"{candidate_id} registry weights URL does not bind the expected "
            "model ID and revision"
        )
    return candidate, hashlib.sha256(content).hexdigest()


def _validated_frames(
    frame_paths: Sequence[str | Path],
) -> list[SemanticRuntimeFrameRequest]:
    if not frame_paths:
        raise ValueError(
            "semantic runtime observation requires at least one frame"
        )
    resolved = [Path(path).resolve() for path in frame_paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("semantic runtime frame paths must be unique")
    frames: list[SemanticRuntimeFrameRequest] = []
    for frame in resolved:
        if not frame.is_file():
            raise FileNotFoundError(frame)
        frames.append(
            SemanticRuntimeFrameRequest(
                frame_path=str(frame),
                frame_sha256=_sha256(frame),
            )
        )
    return frames


def _accelerator_enabled(backend: ComputeBackend) -> bool:
    return (
        backend.info.runtime in {"cuda", "rocm"}
        and torch.cuda.is_available()
    )


def capture_semantic_runtime_observation(
    source_registry_path: str | Path,
    candidate_id: SemanticRuntimeCandidateId,
    frame_paths: Sequence[str | Path],
    output_path: str | Path,
    *,
    backend: ComputeBackend | None = None,
    provider_factory: ProviderFactory | None = None,
    label_mapping_path: str | Path = DEFAULT_LABEL_MAPPING_PATH,
    targets: Sequence[str] = ("water", "vegetation", "mountain"),
) -> SemanticRuntimeObservation:
    registry_file = Path(source_registry_path).resolve()
    mapping_file = Path(label_mapping_path).resolve()
    if not registry_file.is_file():
        raise FileNotFoundError(registry_file)
    if not mapping_file.is_file():
        raise FileNotFoundError(mapping_file)
    if not targets or len(set(targets)) != len(targets):
        raise ValueError(
            "semantic runtime targets must be non-empty and unique"
        )
    candidate, registry_sha256 = _validated_candidate(
        registry_file,
        candidate_id,
    )
    frames = _validated_frames(frame_paths)
    destination = Path(output_path).resolve()
    protected_paths = {
        registry_file,
        mapping_file,
        *(Path(frame.frame_path) for frame in frames),
    }
    if destination in protected_paths:
        raise ValueError(
            "semantic runtime output cannot overwrite an input artifact"
        )

    selected_backend = backend or TorchComputeBackend(
        settings.device_preference
    )
    accelerator_enabled = _accelerator_enabled(selected_backend)
    if accelerator_enabled:
        torch.cuda.reset_peak_memory_stats(selected_backend.torch_device)
        torch.cuda.synchronize(selected_backend.torch_device)

    provider: SemanticMaskProvider | None = None
    predictions: list[SemanticRuntimeFramePrediction] = []
    resolved_revisions: set[str] = set()
    checkpoint_hashes: set[str] = set()
    checkpoint_kinds: set[str] = set()
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        selected_provider_factory = provider_factory or (
            OneFormerSemanticMaskProvider
            if candidate_id == "oneformer_ade20k_swin_large"
            else SemanticMaskProvider
        )
        provider = selected_provider_factory(
            selected_backend,
            model_id=SEMANTIC_RUNTIME_MODEL_IDS[candidate_id],
            model_revision=candidate.weights.revision,
            label_mapping_path=mapping_file,
            local_files_only=True,
        )
        for frame in frames:
            with Image.open(frame.frame_path) as source_image:
                image = source_image.convert("RGB")
            frame_predictions = provider.predict_many(
                image,
                list(targets),
            )
            if set(frame_predictions) != set(targets):
                raise ValueError(
                    "semantic provider did not return the requested targets"
                )
            target_predictions: list[SemanticRuntimeTargetPrediction] = []
            for target in targets:
                prediction = frame_predictions[target]
                metadata = prediction.metadata
                resolved_revision = str(
                    metadata.get("model_revision", "")
                )
                checkpoint_sha256 = str(
                    metadata.get("checkpoint_sha256", "")
                )
                checkpoint_hash_kind = str(
                    metadata.get("checkpoint_hash_kind", "")
                )
                if not resolved_revision:
                    raise ValueError(
                        "semantic prediction is missing model revision"
                    )
                if not checkpoint_sha256:
                    raise ValueError(
                        "semantic prediction is missing checkpoint SHA-256"
                    )
                if not checkpoint_hash_kind:
                    raise ValueError(
                        "semantic prediction is missing checkpoint hash kind"
                    )
                if (
                    metadata.get("label_mapping_sha256")
                    != provider.label_mapping_sha256
                ):
                    raise ValueError(
                        "semantic prediction label mapping identity changed"
                    )
                resolved_revisions.add(resolved_revision)
                checkpoint_hashes.add(checkpoint_sha256)
                checkpoint_kinds.add(checkpoint_hash_kind)
                mask = np.asarray(prediction.mask, dtype=np.float32)
                threshold = float(
                    metadata.get("probability_threshold", 0.30)
                )
                target_predictions.append(
                    SemanticRuntimeTargetPrediction(
                        target=target,
                        mask_sha256=_mask_sha256(mask),
                        confidence=prediction.confidence,
                        score_semantics=prediction.score_semantics,
                        mean_score=float(mask.mean()),
                        maximum_score=float(mask.max(initial=0.0)),
                        selected_fraction=float((mask >= threshold).mean()),
                        class_ids=[
                            int(value)
                            for value in metadata.get("class_ids", [])
                        ],
                        class_labels=[
                            str(value)
                            for value in metadata.get("class_labels", [])
                        ],
                        class_mapping_status=str(
                            metadata.get(
                                "class_mapping_status",
                                "model_class_missing",
                            )
                        ),
                    )
                )
            predictions.append(
                SemanticRuntimeFramePrediction(
                    frame_path=frame.frame_path,
                    frame_sha256=frame.frame_sha256,
                    width=image.width,
                    height=image.height,
                    targets=target_predictions,
                )
            )
        if accelerator_enabled:
            torch.cuda.synchronize(selected_backend.torch_device)
        if (
            resolved_revisions != {candidate.weights.revision}
            or len(checkpoint_hashes) != 1
            or checkpoint_kinds
            != {"colorgraph.torch-state-dict/v1"}
        ):
            raise ValueError(
                "semantic runtime identity does not match the frozen model "
                "revision/hash contract"
            )
    except ModuleNotFoundError as exception:
        status = "blocked"
        blocker = "model_or_runtime_dependency_not_available_locally"
        dependency = exception.name or "unknown"
        error = (
            "ModuleNotFoundError: required local runtime dependency is "
            f"unavailable ({dependency})"
        )
    except OSError:
        status = "blocked"
        blocker = "model_or_runtime_dependency_not_available_locally"
        error = (
            "OSError: exact model/revision is unavailable in the local cache"
        )
    except (RuntimeError, TypeError, ValueError) as exception:
        status = "failed"
        error = f"{type(exception).__name__}: {exception}"
    finally:
        elapsed_seconds = max(time.perf_counter() - started, 1e-9)
        peak_gpu_memory_mb = (
            float(
                torch.cuda.max_memory_allocated(
                    selected_backend.torch_device
                )
                / (1024 * 1024)
            )
            if accelerator_enabled
            else 0.0
        )
        if provider is not None:
            provider.release_model()

    completed = status == "completed"
    observation = SemanticRuntimeObservation(
        created_at=datetime.now(UTC),
        status=status,
        source_registry_path=str(registry_file),
        source_registry_sha256=registry_sha256,
        candidate_id=candidate_id,
        model_id=SEMANTIC_RUNTIME_MODEL_IDS[candidate_id],
        requested_model_revision=candidate.weights.revision,
        resolved_model_revision=(
            next(iter(resolved_revisions))
            if completed
            else None
        ),
        checkpoint_sha256=(
            next(iter(checkpoint_hashes))
            if completed
            else None
        ),
        checkpoint_hash_kind=(
            next(iter(checkpoint_kinds))
            if completed
            else None
        ),
        code_license_id=candidate.code.license_id,
        weights_license_id=candidate.weights.license_id,
        code_commercial_use_allowed=(
            candidate.code.commercial_use_allowed
        ),
        weights_commercial_use_allowed=(
            candidate.weights.commercial_use_allowed
        ),
        label_mapping_path=str(mapping_file),
        label_mapping_sha256=_sha256(mapping_file),
        operating_system=platform.platform(),
        runtime=selected_backend.info.runtime,
        device_name=selected_backend.info.name,
        precision=(
            "float16"
            if selected_backend.info.runtime in {"cuda", "rocm"}
            else "float32"
        ),
        requested_frames=frames,
        predictions=predictions if completed else [],
        elapsed_seconds=elapsed_seconds,
        processing_fps=(
            len(frames) / elapsed_seconds if completed else None
        ),
        peak_cpu_memory_mb=process_peak_memory_mb(),
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if accelerator_enabled
            else "not_applicable"
        ),
        blocker=blocker,
        error=error,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(
            observation.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return observation
