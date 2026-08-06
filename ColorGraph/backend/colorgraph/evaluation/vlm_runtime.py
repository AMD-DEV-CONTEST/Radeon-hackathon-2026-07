from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import torch
from pydantic import Field, model_validator

from colorgraph.agent.scene_understanding import LocalSceneAnalyzer
from colorgraph.agent.vlm_shadow import (
    VLMCalibrationInput,
    VLMShadowBatchReport,
    VLMShadowCalibration,
    calibrate_vlm_shadow,
)
from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.devices.base import ComputeBackend
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb

VLM_RUNTIME_OBSERVATION_VERSION = (
    "colorgraph.vlm-shadow-runtime-observation/v1"
)

RuntimeStatus = Literal["completed", "blocked", "failed"]
AnalyzerFactory = Callable[..., LocalSceneAnalyzer]


class VLMRuntimeFrame(StrictEvaluationModel):
    frame_path: str
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VLMRuntimeObservation(StrictEvaluationModel):
    schema_version: str = VLM_RUNTIME_OBSERVATION_VERSION
    created_at: datetime
    status: RuntimeStatus
    calibration_path: str
    calibration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_source_path: str
    calibration_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_status: str
    model_id: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    local_files_only: Literal[True] = True
    network_access_allowed: Literal[False] = False
    operating_system: str
    runtime: str
    device_name: str
    precision: str
    requested_frames: list[VLMRuntimeFrame] = Field(min_length=1)
    elapsed_seconds: float = Field(gt=0)
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
    shadow_report: VLMShadowBatchReport | None = None
    blocker: str | None = None
    error: str | None = None
    default_model_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> VLMRuntimeObservation:
        if self.status == "completed":
            if (
                self.shadow_report is None
                or self.processing_fps is None
                or self.blocker is not None
                or self.error is not None
            ):
                raise ValueError(
                    "completed VLM runtime observation requires metrics and "
                    "cannot carry blocker/error"
                )
        elif self.status == "blocked":
            if (
                not self.blocker
                or self.shadow_report is not None
                or self.processing_fps is not None
            ):
                raise ValueError(
                    "blocked VLM runtime observation requires a blocker and "
                    "cannot carry completed-run metrics"
                )
        elif (
            not self.error
            or self.shadow_report is not None
            or self.processing_fps is not None
        ):
            raise ValueError(
                "failed VLM runtime observation requires only an error"
            )
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_calibration(
    calibration_path: Path,
    calibration_source_path: Path,
) -> tuple[VLMShadowCalibration, VLMCalibrationInput]:
    calibration = VLMShadowCalibration.model_validate_json(
        calibration_path.read_bytes()
    )
    source = VLMCalibrationInput.model_validate_json(
        calibration_source_path.read_bytes()
    )
    recomputed = calibrate_vlm_shadow(source)
    if recomputed != calibration:
        raise ValueError(
            "VLM calibration does not match the supplied calibration source"
        )
    return calibration, source


def _validated_frames(frame_paths: Sequence[str | Path]) -> list[VLMRuntimeFrame]:
    if not frame_paths:
        raise ValueError("VLM runtime observation requires at least one frame")
    resolved = [Path(path).resolve() for path in frame_paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("VLM runtime frame paths must be unique")
    frames: list[VLMRuntimeFrame] = []
    for frame in resolved:
        if not frame.is_file():
            raise FileNotFoundError(frame)
        frames.append(
            VLMRuntimeFrame(
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


def capture_vlm_runtime_observation(
    calibration_path: str | Path,
    calibration_source_path: str | Path,
    frame_paths: Sequence[str | Path],
    output_path: str | Path,
    *,
    backend: ComputeBackend | None = None,
    analyzer_factory: AnalyzerFactory = LocalSceneAnalyzer,
) -> VLMRuntimeObservation:
    calibration_file = Path(calibration_path).resolve()
    source_file = Path(calibration_source_path).resolve()
    if not calibration_file.is_file():
        raise FileNotFoundError(calibration_file)
    if not source_file.is_file():
        raise FileNotFoundError(source_file)
    calibration, source = _validated_calibration(
        calibration_file,
        source_file,
    )
    frames = _validated_frames(frame_paths)
    destination = Path(output_path).resolve()
    protected_paths = {
        calibration_file,
        source_file,
        *(Path(frame.frame_path) for frame in frames),
    }
    if destination in protected_paths:
        raise ValueError("VLM runtime output cannot overwrite an input artifact")

    selected_backend = backend or TorchComputeBackend(
        settings.device_preference
    )
    accelerator_enabled = _accelerator_enabled(selected_backend)
    if accelerator_enabled:
        torch.cuda.reset_peak_memory_stats(selected_backend.torch_device)
        torch.cuda.synchronize(selected_backend.torch_device)

    analyzer: LocalSceneAnalyzer | None = None
    shadow_report: VLMShadowBatchReport | None = None
    status: RuntimeStatus = "completed"
    blocker: str | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        analyzer = analyzer_factory(
            selected_backend,
            model_id=calibration.model_id,
            model_revision=calibration.model_revision,
            local_files_only=True,
        )
        shadow_report = analyzer.analyze_vlm_shadow(
            [frame.frame_path for frame in frames],
            calibration,
            labels=tuple(source.labels),
        )
        if accelerator_enabled:
            torch.cuda.synchronize(selected_backend.torch_device)
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
        if analyzer is not None:
            analyzer.release_model()

    observation = VLMRuntimeObservation(
        created_at=datetime.now(UTC),
        status=status,
        calibration_path=str(calibration_file),
        calibration_sha256=_sha256(calibration_file),
        calibration_source_path=str(source_file),
        calibration_source_sha256=_sha256(source_file),
        calibration_status=calibration.status,
        model_id=calibration.model_id,
        model_revision=calibration.model_revision,
        operating_system=platform.platform(),
        runtime=selected_backend.info.runtime,
        device_name=selected_backend.info.name,
        precision=(
            "float16"
            if selected_backend.info.runtime in {"cuda", "rocm"}
            else "float32"
        ),
        requested_frames=frames,
        elapsed_seconds=elapsed_seconds,
        processing_fps=(
            len(frames) / elapsed_seconds
            if status == "completed"
            else None
        ),
        peak_cpu_memory_mb=process_peak_memory_mb(),
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        peak_gpu_memory_scope=(
            "torch_peak_allocated_since_reset"
            if accelerator_enabled
            else "not_applicable"
        ),
        shadow_report=shadow_report if status == "completed" else None,
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
