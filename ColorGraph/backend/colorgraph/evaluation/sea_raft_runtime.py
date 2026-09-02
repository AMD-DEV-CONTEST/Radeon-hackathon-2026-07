from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np
from pydantic import Field, model_validator

from colorgraph.evaluation.formal_model_sources import (
    FormalModelCandidate,
    FormalModelSourceManifest,
)
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb

SEA_RAFT_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.sea-raft-runtime-observation/v1"
)
SEA_RAFT_CANDIDATE_ID = "sea_raft"
SEA_RAFT_MODEL_ID = "MemorySlices/Tartan-C-T-TSKH-spring540x960-M"
SEA_RAFT_RESNET34_SHA256 = (
    "b627a593bcbe140c234610266fe4f8ae95ea42fc881d091c9b6052e6b1d0590f"
)
RuntimeStatus = Literal["completed", "blocked", "failed"]
MediaOrigin = Literal[
    "camera_original",
    "camera_original_derived_clip",
    "licensed_stock",
    "published_dataset",
    "procedural",
]


class SeaRaftPairSummary(StrictEvaluationModel):
    pair_index: int = Field(ge=0)
    flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uncertainty_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    occlusion_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mean_flow_magnitude_pixels: float = Field(ge=0)
    mean_expected_laplace_scale: float = Field(ge=0)
    p95_expected_laplace_scale: float = Field(ge=0)
    occluded_fraction: float = Field(ge=0, le=1)
    elapsed_seconds: float = Field(gt=0)


class SeaRaftRuntimeObservation(StrictEvaluationModel):
    schema_version: str = SEA_RAFT_RUNTIME_OBSERVATION_VERSION
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
    source_frame_count: int = Field(gt=1)
    processed_pair_count: int = Field(gt=0)
    truncated_to_maximum_pairs: bool
    model_id: str = SEA_RAFT_MODEL_ID
    requested_model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    resolved_model_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
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
    config_path: str
    config_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    auxiliary_resnet34_path: str
    auxiliary_resnet34_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    weights_license_id: str | None
    weights_commercial_use_allowed: bool | None
    weights_redistribution_allowed: bool | None
    local_files_only: Literal[True] = True
    network_access_allowed: Literal[False] = False
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    model_load_seconds: float = Field(ge=0)
    inference_seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(gt=0)
    pair_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_cpu_memory_scope: Literal["bridge_process_lifetime_peak"] = (
        "bridge_process_lifetime_peak"
    )
    peak_gpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_scope: Literal[
        "torch_peak_allocated_since_reset",
        "not_applicable",
    ]
    memory_growth_mb: float = Field(ge=0)
    output_path: str | None = None
    output_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    flows_shape: list[int] = Field(default_factory=list)
    uncertainties_shape: list[int] = Field(default_factory=list)
    occlusions_shape: list[int] = Field(default_factory=list)
    uncertainty_semantics: Literal[
        "sea_raft_mixture_laplace_expected_scale_not_accuracy"
    ] = "sea_raft_mixture_laplace_expected_scale_not_accuracy"
    occlusion_semantics: Literal[
        "forward_backward_consistency_engineering_signal_not_accuracy"
    ] = "forward_backward_consistency_engineering_signal_not_accuracy"
    pairs: list[SeaRaftPairSummary] = Field(default_factory=list)
    blocker: str | None = None
    error: str | None = None
    evidence_class: Literal["engineering_runtime_not_gold"] = (
        "engineering_runtime_not_gold"
    )
    gold_quality_claim_authorized: Literal[False] = False
    production_default_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> SeaRaftRuntimeObservation:
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
                self.resolved_model_revision,
                self.checkpoint_file_sha256,
                self.checkpoint_state_sha256,
                self.checkpoint_hash_kind,
                self.config_sha256,
                self.auxiliary_resnet34_sha256,
                self.pair_fps,
                self.output_path,
                self.output_sha256,
            )
            expected_flow_shape = [
                self.processed_pair_count,
                2,
                self.height,
                self.width,
            ]
            expected_map_shape = [
                self.processed_pair_count,
                self.height,
                self.width,
            ]
            if (
                any(value is None for value in required)
                or self.resolved_code_revision
                != self.requested_code_revision
                or self.resolved_model_revision
                != self.requested_model_revision
                or self.auxiliary_resnet34_sha256
                != SEA_RAFT_RESNET34_SHA256
                or self.flows_shape != expected_flow_shape
                or self.uncertainties_shape != expected_map_shape
                or self.occlusions_shape != expected_map_shape
                or len(self.pairs) != self.processed_pair_count
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed SEA-RAFT evidence requires exact code, "
                    "checkpoint, auxiliary weights, tensors, and timing"
                )
        elif self.status == "blocked":
            if not self.blocker or self.pairs or self.output_sha256 is not None:
                raise ValueError(
                    "blocked SEA-RAFT evidence requires a blocker and cannot "
                    "carry completed output"
                )
        elif not self.error or self.pairs or self.output_sha256 is not None:
            raise ValueError(
                "failed SEA-RAFT evidence requires an error and cannot carry "
                "completed output"
            )
        return self


@dataclass(frozen=True)
class SeaRaftBridgeResult:
    flows: np.ndarray
    uncertainties: np.ndarray
    occlusions: np.ndarray
    pair_seconds: np.ndarray
    runtime: str
    precision: str
    model_load_seconds: float
    inference_seconds: float
    peak_cpu_memory_mb: float
    peak_gpu_memory_mb: float
    memory_growth_mb: float
    checkpoint_file_sha256: str
    checkpoint_state_sha256: str
    config_sha256: str


class SeaRaftRunner(Protocol):
    def run(
        self,
        video: Path,
        output: Path,
        maximum_pairs: int | None,
    ) -> SeaRaftBridgeResult: ...


SeaRaftRunnerFactory = Callable[
    [Path, Path, Path, Path, str],
    SeaRaftRunner,
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
    digest.update(
        f"{canonical.shape}:<f4".encode("ascii")
    )
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _candidate(
    manifest: FormalModelSourceManifest,
) -> FormalModelCandidate:
    candidate = next(
        (
            item
            for item in manifest.candidates
            if item.candidate_id == SEA_RAFT_CANDIDATE_ID
        ),
        None,
    )
    if (
        candidate is None
        or candidate.code.revision is None
        or candidate.weights.revision is None
    ):
        raise ValueError(
            "formal registry lacks immutable SEA-RAFT code/weight revisions"
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
            "installed SEA-RAFT repository is unavailable or not Git"
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
        raise ValueError("SEA-RAFT video metadata is invalid")
    return width, height, fps, frame_count


class SubprocessSeaRaftRunner:
    def __init__(
        self,
        repository: Path,
        snapshot: Path,
        config: Path,
        torch_home: Path,
        python_executable: str,
    ) -> None:
        self.repository = repository
        self.snapshot = snapshot
        self.config = config
        self.torch_home = torch_home
        self.python_executable = python_executable

    def run(
        self,
        video: Path,
        output: Path,
        maximum_pairs: int | None,
    ) -> SeaRaftBridgeResult:
        command = [
            self.python_executable,
            "-m",
            "colorgraph.vision.sea_raft_bridge",
            "--repository",
            str(self.repository),
            "--snapshot",
            str(self.snapshot),
            "--config",
            str(self.config),
            "--video",
            str(video),
            "--torch-home",
            str(self.torch_home),
            "--output",
            str(output),
        ]
        if maximum_pairs is not None:
            command.extend(["--maximum-pairs", str(maximum_pairs)])
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
                "SEA-RAFT bridge failed"
                + (f": {detail[-2000:]}" if detail else "")
            )
        if not output.is_file():
            raise RuntimeError("SEA-RAFT bridge did not write its output")
        with np.load(output, allow_pickle=False) as archive:
            return SeaRaftBridgeResult(
                flows=np.asarray(archive["flows"], dtype=np.float32),
                uncertainties=np.asarray(
                    archive["uncertainties"],
                    dtype=np.float32,
                ),
                occlusions=np.asarray(
                    archive["occlusions"],
                    dtype=np.float32,
                ),
                pair_seconds=np.asarray(
                    archive["pair_seconds"],
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
                checkpoint_file_sha256=str(
                    archive["checkpoint_file_sha256"].item()
                ),
                checkpoint_state_sha256=str(
                    archive["checkpoint_state_sha256"].item()
                ),
                config_sha256=str(archive["config_sha256"].item()),
            )


def _default_runner_factory(
    repository: Path,
    snapshot: Path,
    config: Path,
    torch_home: Path,
    python_executable: str,
) -> SeaRaftRunner:
    return SubprocessSeaRaftRunner(
        repository,
        snapshot,
        config,
        torch_home,
        python_executable,
    )


def capture_sea_raft_runtime_observation(
    source_registry_path: str | Path,
    code_repository_path: str | Path,
    model_snapshot_path: str | Path,
    torch_home_path: str | Path,
    video_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    *,
    maximum_pairs: int | None = 120,
    media_origin: MediaOrigin = "procedural",
    parent_source_path: str | Path | None = None,
    source_start_seconds: float | None = None,
    python_executable: str = sys.executable,
    runner_factory: SeaRaftRunnerFactory = _default_runner_factory,
) -> SeaRaftRuntimeObservation:
    registry_file = Path(source_registry_path).resolve()
    repository = Path(code_repository_path).resolve()
    snapshot = Path(model_snapshot_path).resolve()
    torch_home = Path(torch_home_path).resolve()
    video = Path(video_path).resolve()
    output_destination = Path(output_path).resolve()
    report_destination = Path(report_path).resolve()
    for required in (registry_file, video):
        if not required.is_file():
            raise FileNotFoundError(required)
    if maximum_pairs is not None and maximum_pairs <= 0:
        raise ValueError("maximum_pairs must be positive")
    if output_destination in {registry_file, video} or report_destination in {
        registry_file,
        video,
    }:
        raise ValueError("SEA-RAFT outputs cannot overwrite inputs")
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
    candidate = _candidate(manifest)
    config = repository / "config" / "eval" / "spring-M.json"
    auxiliary_resnet = (
        torch_home / "hub" / "checkpoints" / "resnet34-b627a593.pth"
    )
    width, height, fps, source_frame_count = _video_metadata(video)
    requested_pair_count = source_frame_count - 1
    processed_pair_count = (
        min(requested_pair_count, maximum_pairs)
        if maximum_pairs is not None
        else requested_pair_count
    )

    resolved_code_revision: str | None = None
    code_license_sha256: str | None = None
    auxiliary_resnet_sha256: str | None = None
    bridge_result: SeaRaftBridgeResult | None = None
    pairs: list[SeaRaftPairSummary] = []
    output_sha256: str | None = None
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()
    output_temporary = output_destination.with_name(
        output_destination.stem + ".tmp" + output_destination.suffix
    )

    try:
        if not repository.is_dir() or not snapshot.is_dir():
            raise OSError("SEA-RAFT repository or model snapshot is missing")
        if snapshot.name != candidate.weights.revision:
            raise ValueError(
                "SEA-RAFT snapshot directory does not match frozen revision"
            )
        resolved_code_revision = _repository_revision(repository)
        if resolved_code_revision != candidate.code.revision:
            raise ValueError(
                "installed SEA-RAFT code revision does not match registry"
            )
        license_file = repository / "LICENSE"
        checkpoint = snapshot / "model.safetensors"
        for required in (
            license_file,
            checkpoint,
            config,
            auxiliary_resnet,
        ):
            if not required.is_file():
                raise OSError(f"required SEA-RAFT artifact is missing: {required}")
        code_license_sha256 = _sha256(license_file)
        auxiliary_resnet_sha256 = _sha256(auxiliary_resnet)
        if auxiliary_resnet_sha256 != SEA_RAFT_RESNET34_SHA256:
            raise ValueError(
                "SEA-RAFT auxiliary ResNet34 checkpoint hash mismatch"
            )
        output_temporary.parent.mkdir(parents=True, exist_ok=True)
        runner = runner_factory(
            repository,
            snapshot,
            config,
            torch_home,
            python_executable,
        )
        bridge_result = runner.run(
            video,
            output_temporary,
            maximum_pairs,
        )
        expected_flow_shape = (
            processed_pair_count,
            2,
            height,
            width,
        )
        expected_map_shape = (
            processed_pair_count,
            height,
            width,
        )
        if bridge_result.flows.shape != expected_flow_shape:
            raise ValueError("SEA-RAFT flow tensor has an unexpected shape")
        if (
            bridge_result.uncertainties.shape != expected_map_shape
            or bridge_result.occlusions.shape != expected_map_shape
            or bridge_result.pair_seconds.shape
            != (processed_pair_count,)
        ):
            raise ValueError(
                "SEA-RAFT uncertainty/occlusion/timing coverage is incomplete"
            )
        if (
            bridge_result.checkpoint_file_sha256 != _sha256(checkpoint)
            or bridge_result.config_sha256 != _sha256(config)
            or not bridge_result.checkpoint_state_sha256
        ):
            raise ValueError(
                "SEA-RAFT bridge artifact identity does not match installation"
            )
        for index in range(processed_pair_count):
            flow = bridge_result.flows[index]
            uncertainty = bridge_result.uncertainties[index]
            occlusion = bridge_result.occlusions[index]
            pairs.append(
                SeaRaftPairSummary(
                    pair_index=index,
                    flow_sha256=_array_sha256(flow),
                    uncertainty_sha256=_array_sha256(uncertainty),
                    occlusion_sha256=_array_sha256(occlusion),
                    mean_flow_magnitude_pixels=float(
                        np.linalg.norm(flow, axis=0).mean()
                    ),
                    mean_expected_laplace_scale=float(
                        uncertainty.mean()
                    ),
                    p95_expected_laplace_scale=float(
                        np.quantile(uncertainty, 0.95)
                    ),
                    occluded_fraction=float(
                        np.asarray(occlusion >= 0.5).mean()
                    ),
                    elapsed_seconds=float(
                        bridge_result.pair_seconds[index]
                    ),
                )
            )
        output_temporary.replace(output_destination)
        output_sha256 = _sha256(output_destination)
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

    observation = SeaRaftRuntimeObservation(
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
        video_path=str(video),
        video_sha256=_sha256(video),
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
        source_frame_count=source_frame_count,
        processed_pair_count=processed_pair_count,
        truncated_to_maximum_pairs=(
            processed_pair_count < requested_pair_count
        ),
        requested_model_revision=candidate.weights.revision,
        resolved_model_revision=(
            candidate.weights.revision
            if bridge_result is not None
            else None
        ),
        checkpoint_file_sha256=(
            bridge_result.checkpoint_file_sha256
            if bridge_result is not None
            else None
        ),
        checkpoint_state_sha256=(
            bridge_result.checkpoint_state_sha256
            if bridge_result is not None
            else None
        ),
        checkpoint_hash_kind=(
            "colorgraph.torch-state-dict/v1"
            if bridge_result is not None
            else None
        ),
        config_path=str(config),
        config_sha256=(
            bridge_result.config_sha256
            if bridge_result is not None
            else None
        ),
        auxiliary_resnet34_path=str(auxiliary_resnet),
        auxiliary_resnet34_sha256=auxiliary_resnet_sha256,
        weights_license_id=candidate.weights.license_id,
        weights_commercial_use_allowed=(
            candidate.weights.commercial_use_allowed
        ),
        weights_redistribution_allowed=(
            candidate.weights.redistribution_allowed
        ),
        operating_system=platform.platform(),
        runtime=(
            bridge_result.runtime
            if bridge_result is not None
            else "unavailable"
        ),
        precision=(
            bridge_result.precision
            if bridge_result is not None
            else "unavailable"
        ),
        model_load_seconds=(
            bridge_result.model_load_seconds
            if bridge_result is not None
            else 0
        ),
        inference_seconds=(
            bridge_result.inference_seconds
            if bridge_result is not None
            else 0
        ),
        elapsed_seconds=elapsed_seconds,
        pair_fps=(
            processed_pair_count / bridge_result.inference_seconds
            if bridge_result is not None
            and bridge_result.inference_seconds > 0
            else None
        ),
        peak_cpu_memory_mb=(
            bridge_result.peak_cpu_memory_mb
            if bridge_result is not None
            else process_peak_memory_mb()
        ),
        peak_gpu_memory_mb=(
            bridge_result.peak_gpu_memory_mb
            if bridge_result is not None
            else 0
        ),
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if bridge_result is not None
            and bridge_result.runtime in {"cuda", "rocm"}
            else "not_applicable"
        ),
        memory_growth_mb=(
            bridge_result.memory_growth_mb
            if bridge_result is not None
            else 0
        ),
        output_path=(
            str(output_destination) if status == "completed" else None
        ),
        output_sha256=output_sha256,
        flows_shape=(
            list(bridge_result.flows.shape)
            if status == "completed" and bridge_result is not None
            else []
        ),
        uncertainties_shape=(
            list(bridge_result.uncertainties.shape)
            if status == "completed" and bridge_result is not None
            else []
        ),
        occlusions_shape=(
            list(bridge_result.occlusions.shape)
            if status == "completed" and bridge_result is not None
            else []
        ),
        pairs=pairs if status == "completed" else [],
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
