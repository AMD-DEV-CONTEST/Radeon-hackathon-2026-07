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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.vision.model_lifecycle import torch_state_dict_sha256

AUTOSHOT_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.autoshot-runtime-observation/v1"
)
AUTOSHOT_SOURCE_REGISTRY_VERSION = (
    "colorgraph.shot-model-source-registry/v1"
)
AUTOSHOT_CANDIDATE_ID = "autoshot"
RuntimeStatus = Literal["completed", "blocked", "failed"]
MediaOrigin = Literal[
    "camera_original",
    "licensed_stock",
    "published_dataset",
    "procedural",
]


class _CodeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license_id: str
    commercial_use_allowed: bool
    redistribution_allowed: bool


class _ProjectAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_id: str = Field(min_length=1)
    project_use_allowed: Literal[True]
    commercial_use_allowed: Literal[True]
    redistribution_allowed: bool


class _CheckpointSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documented_filename: str = Field(min_length=1)
    share_url: str
    retrieved_on: str
    source_is_mutable: Literal[True]
    immutable_revision: None
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    loaded_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_kind: Literal["colorgraph.torch-state-dict/v1"]
    checkpoint_container_key: Literal["net"]
    state_entry_count: int = Field(gt=0)
    strict_model_load_verified: Literal[True]
    upstream_declared_license_id: str | None
    project_authorization: _ProjectAuthorization


class _AutoShotCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Literal["autoshot"]
    code: _CodeSource
    runtime_checkpoint: _CheckpointSource
    identity_note: str = Field(min_length=1)


class _SourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    checked_on: str
    candidates: list[dict[str, object]]


class AutoShotRuntimeObservation(StrictEvaluationModel):
    schema_version: str = AUTOSHOT_RUNTIME_OBSERVATION_VERSION
    created_at: datetime
    status: RuntimeStatus
    source_registry_path: str
    source_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_repository_path: str
    code_source_url: str
    requested_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_code_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    code_license_id: str
    code_commercial_use_allowed: bool
    code_redistribution_allowed: bool
    code_license_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_path: str
    checkpoint_share_url: str
    checkpoint_retrieved_on: str
    checkpoint_source_is_mutable: Literal[True] = True
    checkpoint_file_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_size_bytes: int | None = Field(default=None, gt=0)
    checkpoint_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: Literal[
        "colorgraph.torch-state-dict/v1"
    ] | None = None
    checkpoint_container_key: Literal["net"] = "net"
    checkpoint_state_entry_count: int | None = Field(default=None, gt=0)
    strict_model_load_verified: bool = False
    upstream_checkpoint_license_id: str | None = None
    project_authorization_id: str
    project_use_authorized: bool
    project_commercial_use_authorized: bool
    checkpoint_redistribution_authorized: bool
    identity_caveat: str = Field(min_length=1)
    video_path: str
    video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_origin: MediaOrigin
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    frame_count: int = Field(gt=1)
    threshold: float = Field(gt=0, lt=1)
    threshold_source: Literal[
        "upstream_reported_test_best_f1_not_project_gold"
    ] = "upstream_reported_test_best_f1_not_project_gold"
    predicted_boundaries: list[int] = Field(default_factory=list)
    output_path: str | None = None
    output_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    probability_dtype: Literal["float32"] | None = None
    probability_shape: list[int] = Field(default_factory=list)
    probability_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    model_load_seconds: float = Field(ge=0)
    inference_seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(gt=0)
    inference_fps: float | None = Field(default=None, gt=0)
    cold_processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_scope: Literal[
        "torch_peak_allocated_since_reset",
        "not_applicable",
    ]
    memory_growth_mb: float = Field(ge=0)
    blocker: str | None = None
    error: str | None = None
    evidence_class: Literal["engineering_runtime_not_gold"] = (
        "engineering_runtime_not_gold"
    )
    gold_quality_claim_authorized: Literal[False] = False
    production_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> AutoShotRuntimeObservation:
        if self.predicted_boundaries != sorted(
            set(self.predicted_boundaries)
        ):
            raise ValueError("predicted boundaries must be sorted and unique")
        if any(
            boundary < 0 or boundary >= self.frame_count
            for boundary in self.predicted_boundaries
        ):
            raise ValueError("predicted boundary lies outside video")
        if self.status == "completed":
            required = (
                self.resolved_code_revision,
                self.code_license_sha256,
                self.checkpoint_file_sha256,
                self.checkpoint_size_bytes,
                self.checkpoint_state_sha256,
                self.checkpoint_hash_kind,
                self.checkpoint_state_entry_count,
                self.output_path,
                self.output_sha256,
                self.probability_dtype,
                self.probability_sha256,
                self.inference_fps,
                self.cold_processing_fps,
            )
            if (
                any(value is None for value in required)
                or self.resolved_code_revision
                != self.requested_code_revision
                or not self.strict_model_load_verified
                or not self.project_use_authorized
                or not self.project_commercial_use_authorized
                or self.probability_shape != [self.frame_count]
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed AutoShot evidence requires exact local "
                    "checkpoint identity, strict load, authorization, "
                    "probabilities, and timing"
                )
        elif self.status == "blocked":
            if (
                not self.blocker
                or self.output_sha256 is not None
                or self.predicted_boundaries
            ):
                raise ValueError(
                    "blocked AutoShot evidence requires a blocker and "
                    "cannot carry completed predictions"
                )
        elif (
            not self.error
            or self.output_sha256 is not None
            or self.predicted_boundaries
        ):
            raise ValueError(
                "failed AutoShot evidence requires an error and cannot "
                "carry completed predictions"
            )
        return self


@dataclass(frozen=True)
class AutoShotBridgeResult:
    single_frame_probability: np.ndarray
    predicted_boundaries: np.ndarray
    batch_seconds: np.ndarray
    runtime: str
    device_name: str
    precision: str
    model_load_seconds: float
    inference_seconds: float
    peak_cpu_memory_mb: float
    peak_gpu_memory_mb: float
    memory_growth_mb: float
    checkpoint_file_sha256: str
    checkpoint_state_sha256: str
    threshold: float


class AutoShotRunner(Protocol):
    def run(
        self,
        video: Path,
        threshold: float,
    ) -> AutoShotBridgeResult: ...


AutoShotRunnerFactory = Callable[
    [Path, Path, Path, str],
    AutoShotRunner,
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(array: np.ndarray) -> str:
    canonical = np.ascontiguousarray(array, dtype="<f4")
    digest = hashlib.sha256()
    digest.update(f"{canonical.shape}:<f4".encode("ascii"))
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


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
            "installed AutoShot repository is unavailable or not Git"
        )
    return completed.stdout.strip()


def _video_metadata(video: Path) -> tuple[int, int, float, int]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise OSError(f"OpenCV could not open {video}")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 1:
        raise ValueError("AutoShot video metadata is invalid")
    return width, height, fps, frame_count


def _load_candidate(registry_content: bytes) -> _AutoShotCandidate:
    registry = _SourceRegistry.model_validate_json(registry_content)
    if registry.schema_version != AUTOSHOT_SOURCE_REGISTRY_VERSION:
        raise ValueError("unsupported shot-model source registry")
    raw = next(
        (
            candidate
            for candidate in registry.candidates
            if candidate.get("candidate_id") == AUTOSHOT_CANDIDATE_ID
        ),
        None,
    )
    if raw is None:
        raise ValueError("source registry lacks AutoShot")
    return _AutoShotCandidate.model_validate(raw)


def _checkpoint_state(path: Path) -> dict[str, torch.Tensor]:
    container = torch.load(
        path,
        map_location="cpu",
        weights_only=True,
    )
    if not isinstance(container, dict):
        raise TypeError("AutoShot checkpoint container is not a dictionary")
    state = container.get("net")
    if not isinstance(state, dict) or not state:
        raise TypeError("AutoShot checkpoint lacks the documented net state")
    return state


class SubprocessAutoShotRunner:
    def __init__(
        self,
        repository: Path,
        checkpoint: Path,
        work_directory: Path,
        python_executable: str,
    ) -> None:
        self.repository = repository
        self.checkpoint = checkpoint
        self.work_directory = work_directory
        self.python_executable = python_executable

    def run(
        self,
        video: Path,
        threshold: float,
    ) -> AutoShotBridgeResult:
        self.work_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".autoshot-bridge-",
            dir=self.work_directory,
        ) as temporary_directory:
            output = Path(temporary_directory) / "bridge.npz"
            completed = subprocess.run(
                [
                    self.python_executable,
                    "-m",
                    "colorgraph.vision.autoshot_bridge",
                    "--repository",
                    str(self.repository),
                    "--checkpoint",
                    str(self.checkpoint),
                    "--video",
                    str(video),
                    "--output",
                    str(output),
                    "--threshold",
                    str(threshold),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=60 * 30,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(
                    "AutoShot bridge failed"
                    + (f": {detail[-2000:]}" if detail else "")
                )
            if not output.is_file():
                raise RuntimeError(
                    "AutoShot bridge did not write its output"
                )
            with np.load(output, allow_pickle=False) as archive:
                return AutoShotBridgeResult(
                    single_frame_probability=np.asarray(
                        archive["single_frame_probability"],
                        dtype=np.float32,
                    ),
                    predicted_boundaries=np.asarray(
                        archive["predicted_boundaries"],
                        dtype=np.int32,
                    ),
                    batch_seconds=np.asarray(
                        archive["batch_seconds"],
                        dtype=np.float64,
                    ),
                    runtime=str(archive["runtime"].item()),
                    device_name=str(archive["device_name"].item()),
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
                    checkpoint_file_sha256=str(
                        archive["checkpoint_file_sha256"].item()
                    ),
                    checkpoint_state_sha256=str(
                        archive["checkpoint_state_sha256"].item()
                    ),
                    threshold=float(archive["threshold"].item()),
                )


def _default_runner_factory(
    repository: Path,
    checkpoint: Path,
    work_directory: Path,
    python_executable: str,
) -> AutoShotRunner:
    return SubprocessAutoShotRunner(
        repository,
        checkpoint,
        work_directory,
        python_executable,
    )


def capture_autoshot_runtime_observation(
    source_registry_path: str | Path,
    code_repository_path: str | Path,
    checkpoint_path: str | Path,
    video_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    *,
    threshold: float = 0.296,
    media_origin: MediaOrigin = "procedural",
    python_executable: str = sys.executable,
    runner_factory: AutoShotRunnerFactory = _default_runner_factory,
) -> AutoShotRuntimeObservation:
    registry_file = Path(source_registry_path).resolve()
    repository = Path(code_repository_path).resolve()
    checkpoint = Path(checkpoint_path).resolve()
    video = Path(video_path).resolve()
    output_destination = Path(output_path).resolve()
    report_destination = Path(report_path).resolve()
    for required in (registry_file, video):
        if not required.is_file():
            raise FileNotFoundError(required)
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between zero and one")
    if output_destination in {
        registry_file,
        video,
    } or report_destination in {registry_file, video}:
        raise ValueError("AutoShot outputs cannot overwrite inputs")

    registry_content = registry_file.read_bytes()
    candidate = _load_candidate(registry_content)
    width, height, fps, frame_count = _video_metadata(video)
    resolved_code_revision: str | None = None
    code_license_sha256: str | None = None
    checkpoint_file_sha256: str | None = None
    checkpoint_state_sha256: str | None = None
    checkpoint_state_entry_count: int | None = None
    strict_model_load_verified = False
    run: AutoShotBridgeResult | None = None
    output_sha256: str | None = None
    probability_sha256: str | None = None
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()

    try:
        if not repository.is_dir():
            raise OSError("installed AutoShot repository is missing")
        if not checkpoint.is_file():
            raise OSError("required AutoShot checkpoint is missing")
        resolved_code_revision = _repository_revision(repository)
        if resolved_code_revision != candidate.code.revision:
            raise ValueError(
                "installed AutoShot code revision does not match registry"
            )
        license_file = repository / "LICENSE"
        if not license_file.is_file():
            raise OSError("AutoShot code license is missing")
        code_license_sha256 = _sha256(license_file)
        checkpoint_file_sha256 = _sha256(checkpoint)
        if (
            checkpoint.name
            != candidate.runtime_checkpoint.documented_filename
            or checkpoint_file_sha256
            != candidate.runtime_checkpoint.file_sha256
            or checkpoint.stat().st_size
            != candidate.runtime_checkpoint.size_bytes
        ):
            raise ValueError(
                "AutoShot checkpoint file identity does not match registry"
            )
        state = _checkpoint_state(checkpoint)
        checkpoint_state_entry_count = len(state)
        checkpoint_state_sha256 = torch_state_dict_sha256(state)
        if (
            checkpoint_state_sha256
            != candidate.runtime_checkpoint.loaded_state_sha256
            or checkpoint_state_entry_count
            != candidate.runtime_checkpoint.state_entry_count
            or not candidate.runtime_checkpoint.strict_model_load_verified
        ):
            raise ValueError(
                "AutoShot checkpoint state identity does not match registry"
            )
        runner = runner_factory(
            repository,
            checkpoint,
            output_destination.parent,
            python_executable,
        )
        run = runner.run(video, threshold)
        if (
            run.single_frame_probability.shape != (frame_count,)
            or run.predicted_boundaries.ndim != 1
            or run.batch_seconds.shape != ((frame_count + 49) // 50,)
        ):
            raise ValueError(
                "AutoShot prediction or timing coverage is incomplete"
            )
        if (
            run.checkpoint_file_sha256 != checkpoint_file_sha256
            or run.checkpoint_state_sha256 != checkpoint_state_sha256
            or abs(run.threshold - threshold) > 1e-12
        ):
            raise ValueError(
                "AutoShot bridge identity does not match controller audit"
            )
        boundaries = [
            int(value) for value in run.predicted_boundaries.tolist()
        ]
        if boundaries != sorted(set(boundaries)) or any(
            value < 0 or value >= frame_count for value in boundaries
        ):
            raise ValueError(
                "AutoShot bridge returned invalid boundaries"
            )
        strict_model_load_verified = True
        output_destination.parent.mkdir(parents=True, exist_ok=True)
        output_temporary = output_destination.with_name(
            output_destination.stem
            + ".tmp"
            + output_destination.suffix
        )
        np.savez_compressed(
            output_temporary,
            single_frame_probability=(
                run.single_frame_probability.astype(
                    np.float32,
                    copy=False,
                )
            ),
            predicted_boundaries=run.predicted_boundaries.astype(
                np.int32,
                copy=False,
            ),
            batch_seconds=run.batch_seconds.astype(
                np.float64,
                copy=False,
            ),
            source_fps=np.asarray(fps, dtype=np.float64),
            threshold=np.asarray(threshold, dtype=np.float64),
        )
        output_temporary.replace(output_destination)
        output_sha256 = _sha256(output_destination)
        probability_sha256 = _array_sha256(
            run.single_frame_probability
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
    authorization = candidate.runtime_checkpoint.project_authorization

    observation = AutoShotRuntimeObservation(
        created_at=datetime.now(UTC),
        status=status,
        source_registry_path=str(registry_file),
        source_registry_sha256=hashlib.sha256(
            registry_content
        ).hexdigest(),
        code_repository_path=str(repository),
        code_source_url=candidate.code.url,
        requested_code_revision=candidate.code.revision,
        resolved_code_revision=resolved_code_revision,
        code_license_id=candidate.code.license_id,
        code_commercial_use_allowed=(
            candidate.code.commercial_use_allowed
        ),
        code_redistribution_allowed=(
            candidate.code.redistribution_allowed
        ),
        code_license_sha256=code_license_sha256,
        checkpoint_path=str(checkpoint),
        checkpoint_share_url=candidate.runtime_checkpoint.share_url,
        checkpoint_retrieved_on=(
            candidate.runtime_checkpoint.retrieved_on
        ),
        checkpoint_file_sha256=checkpoint_file_sha256,
        checkpoint_size_bytes=(
            checkpoint.stat().st_size
            if checkpoint.is_file()
            else None
        ),
        checkpoint_state_sha256=checkpoint_state_sha256,
        checkpoint_hash_kind=(
            "colorgraph.torch-state-dict/v1"
            if checkpoint_state_sha256 is not None
            else None
        ),
        checkpoint_state_entry_count=checkpoint_state_entry_count,
        strict_model_load_verified=strict_model_load_verified,
        upstream_checkpoint_license_id=(
            candidate.runtime_checkpoint.upstream_declared_license_id
        ),
        project_authorization_id=authorization.authorization_id,
        project_use_authorized=authorization.project_use_allowed,
        project_commercial_use_authorized=(
            authorization.commercial_use_allowed
        ),
        checkpoint_redistribution_authorized=(
            authorization.redistribution_allowed
        ),
        identity_caveat=candidate.identity_note,
        video_path=str(video),
        video_sha256=_sha256(video),
        media_origin=media_origin,
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        threshold=threshold,
        predicted_boundaries=(
            [
                int(value)
                for value in run.predicted_boundaries.tolist()
            ]
            if status == "completed" and run is not None
            else []
        ),
        output_path=(
            str(output_destination) if status == "completed" else None
        ),
        output_sha256=output_sha256,
        probability_dtype=(
            "float32" if status == "completed" else None
        ),
        probability_shape=(
            list(run.single_frame_probability.shape)
            if status == "completed" and run is not None
            else []
        ),
        probability_sha256=probability_sha256,
        operating_system=platform.platform(),
        runtime=run.runtime if run is not None else "unavailable",
        device_name=(
            run.device_name if run is not None else "unavailable"
        ),
        precision=run.precision if run is not None else "unavailable",
        model_load_seconds=(
            run.model_load_seconds if run is not None else 0
        ),
        inference_seconds=(
            run.inference_seconds if run is not None else 0
        ),
        elapsed_seconds=elapsed_seconds,
        inference_fps=(
            frame_count / run.inference_seconds
            if run is not None and run.inference_seconds > 0
            else None
        ),
        cold_processing_fps=(
            frame_count / elapsed_seconds
            if status == "completed"
            else None
        ),
        peak_cpu_memory_mb=max(
            process_peak_memory_mb(),
            run.peak_cpu_memory_mb if run is not None else 0,
        ),
        peak_gpu_memory_mb=(
            run.peak_gpu_memory_mb if run is not None else 0
        ),
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if run is not None and run.runtime == "cuda"
            else "not_applicable"
        ),
        memory_growth_mb=(
            run.memory_growth_mb if run is not None else 0
        ),
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


def bind_autoshot_runtime_to_shot_bundle(
    bundle,
    observation: AutoShotRuntimeObservation,
    *,
    item_id: str,
):
    from colorgraph.evaluation.shot_shadow import (
        ShotModelArtifacts,
        ShotModelObservation,
        ShotModelRun,
        ShotShadowBundle,
    )

    if observation.status != "completed":
        raise ValueError(
            "only a completed AutoShot runtime can be bound to a shot bundle"
        )
    item = next(
        (candidate for candidate in bundle.items if candidate.item_id == item_id),
        None,
    )
    if item is None:
        raise ValueError(f"shot bundle does not contain item {item_id}")
    fps_tolerance = max(1e-3, item.fps * 1e-4)
    if (
        item.media_sha256 != observation.video_sha256
        or item.frame_count != observation.frame_count
        or abs(item.fps - observation.fps) > fps_tolerance
    ):
        raise ValueError(
            "AutoShot runtime media identity does not match shot item"
        )
    if (
        observation.code_commercial_use_allowed is not True
        or observation.project_commercial_use_authorized is not True
        or observation.checkpoint_file_sha256 is None
        or observation.resolved_code_revision is None
    ):
        raise ValueError(
            "AutoShot runtime lacks project-authorized frozen artifacts"
        )
    run_index = next(
        (
            index
            for index, run in enumerate(bundle.runs)
            if run.model_id == "autoshot"
        ),
        None,
    )
    if run_index is None:
        raise ValueError("shot bundle does not define an AutoShot row")
    completed_run = ShotModelRun(
        model_id="autoshot",
        status="completed",
        artifacts=ShotModelArtifacts(
            code_url=observation.code_source_url,
            code_license_id=observation.code_license_id,
            code_commercial_use_allowed=(
                observation.code_commercial_use_allowed
            ),
            source_revision=observation.resolved_code_revision,
            weights_required=True,
            weights_url=observation.checkpoint_share_url,
            weights_license_id=observation.project_authorization_id,
            weights_commercial_use_allowed=(
                observation.project_commercial_use_authorized
            ),
            checkpoint_sha256=observation.checkpoint_file_sha256,
        ),
        observations=[
            ShotModelObservation(
                item_id=item_id,
                predicted_boundaries=observation.predicted_boundaries,
                elapsed_seconds=max(
                    observation.inference_seconds,
                    1e-9,
                ),
                peak_cpu_memory_mb=observation.peak_cpu_memory_mb,
                peak_gpu_memory_mb=observation.peak_gpu_memory_mb,
            )
        ],
    )
    runs = list(bundle.runs)
    runs[run_index] = completed_run
    return ShotShadowBundle.model_validate(
        bundle.model_copy(
            deep=True,
            update={"runs": runs},
        ).model_dump(mode="python")
    )


def bind_autoshot_runtime_to_shot_bundle_file(
    bundle_path: str | Path,
    runtime_report_path: str | Path,
    output_path: str | Path,
    *,
    item_id: str,
):
    from colorgraph.evaluation.shot_shadow import ShotShadowBundle

    bundle = ShotShadowBundle.model_validate_json(
        Path(bundle_path).resolve().read_bytes()
    )
    observation = AutoShotRuntimeObservation.model_validate_json(
        Path(runtime_report_path).resolve().read_bytes()
    )
    updated = bind_autoshot_runtime_to_shot_bundle(
        bundle,
        observation,
        item_id=item_id,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(
            updated.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return updated
