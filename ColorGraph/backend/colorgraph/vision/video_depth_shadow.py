from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.domain.grade_graph import TimeRange

VIDEO_DEPTH_SHADOW_SCHEMA = "colorgraph.video-depth-shadow/v1"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().with_name(
    "video_depth_anything_small_v1.json"
)


class CheckpointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class InferenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_frames: int = Field(gt=0)
    overlap_frames: int = Field(ge=0)
    input_size: int = Field(gt=0)
    depth_convention: str


class VideoDepthModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(alias="schema")
    model_id: str
    encoder: str
    parameter_count: int = Field(gt=0)
    license: str
    source_repository: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint: CheckpointRecord
    inference_contract: InferenceContract
    disallowed_default_variants: dict[str, str]


class VideoDepthInstallationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    repository_path: str
    checkpoint_path: str
    source_commit: str | None
    source_commit_matches: bool
    apache_license_present: bool
    checkpoint_sha256: str | None
    checkpoint_hash_matches: bool
    checkpoint_size_matches: bool
    encoder: str
    issues: list[str] = Field(default_factory=list)


class ShotDepthStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_index: int
    frame_count: int
    q05: float
    median: float
    q95: float
    uncertainty_mean: float
    uncertainty_p95: float
    model_load_seconds: float | None = Field(default=None, ge=0)
    inference_seconds: float | None = Field(default=None, ge=0)
    peak_cpu_memory_mb: float | None = Field(default=None, ge=0)
    peak_gpu_memory_mb: float | None = Field(default=None, ge=0)
    memory_growth_mb: float | None = Field(default=None, ge=0)


class VideoDepthShadowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = VIDEO_DEPTH_SHADOW_SCHEMA
    mode: str = "shadow"
    model_id: str
    model_license: str
    checkpoint_sha256: str
    checkpoint_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: str | None = None
    source_commit: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int
    width: int
    height: int
    fps: float
    float_depth_preserved: bool
    uncertainty_semantics: str
    performance_observed: bool = False
    operating_system: str
    runtime: str = "unavailable"
    device_name: str = "unavailable"
    precision: str = "unavailable"
    model_load_seconds: float = Field(default=0, ge=0)
    inference_seconds: float = Field(default=0, ge=0)
    elapsed_seconds: float = Field(gt=0)
    inference_fps: float | None = Field(default=None, gt=0)
    cold_processing_fps: float = Field(gt=0)
    peak_cpu_memory_mb: float = Field(default=0, ge=0)
    peak_cpu_memory_scope: str = "maximum_per_shot_bridge_process_lifetime_peak"
    peak_gpu_memory_mb: float = Field(default=0, ge=0)
    peak_gpu_memory_scope: str = "maximum_torch_peak_allocated_per_shot"
    memory_growth_mb: float = Field(default=0, ge=0)
    shot_statistics: list[ShotDepthStatistics]
    evidence_class: str = "engineering_runtime_not_gold"
    gold_quality_claim_authorized: bool = False
    production_default_authorized: bool = False


@dataclass(frozen=True)
class VideoDepthShotInference:
    depths: np.ndarray
    runtime: str
    device_name: str
    precision: str
    model_load_seconds: float
    inference_seconds: float
    peak_cpu_memory_mb: float
    peak_gpu_memory_mb: float
    memory_growth_mb: float
    checkpoint_state_sha256: str


class VideoDepthShotRunner(Protocol):
    def infer_shot(
        self,
        frames_rgb: np.ndarray,
        fps: float,
    ) -> np.ndarray | VideoDepthShotInference: ...


def load_video_depth_manifest(
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> VideoDepthModelManifest:
    manifest = VideoDepthModelManifest.model_validate_json(
        Path(path).resolve().read_text(encoding="utf-8")
    )
    if (
        manifest.schema_version != "colorgraph.video-depth-model-manifest/v1"
        or manifest.encoder != "vits"
        or manifest.license != "Apache-2.0"
    ):
        raise ValueError("only the Apache-2.0 Video Depth Anything Small manifest is allowed")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_video_depth_installation(
    repository_path: str | Path,
    checkpoint_path: str | Path,
    *,
    manifest: VideoDepthModelManifest | None = None,
) -> VideoDepthInstallationAudit:
    resolved_manifest = manifest or load_video_depth_manifest()
    repository = Path(repository_path).resolve()
    checkpoint = Path(checkpoint_path).resolve()
    issues: list[str] = []

    source_commit: str | None = None
    if repository.is_dir():
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            source_commit = completed.stdout.strip().lower()
        else:
            issues.append("repository does not expose a readable Git commit")
    else:
        issues.append("official Video Depth Anything repository is missing")
    source_commit_matches = source_commit == resolved_manifest.source_commit
    if source_commit is not None and not source_commit_matches:
        issues.append("repository commit does not match the frozen manifest")

    license_path = repository / "LICENSE"
    apache_license_present = False
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8", errors="replace")
        apache_license_present = (
            "Apache License" in license_text and "Version 2.0" in license_text
        )
    if not apache_license_present:
        issues.append("Apache-2.0 repository license evidence is missing")

    checkpoint_sha256 = _sha256(checkpoint) if checkpoint.is_file() else None
    checkpoint_hash_matches = checkpoint_sha256 == resolved_manifest.checkpoint.sha256
    checkpoint_size_matches = (
        checkpoint.is_file()
        and checkpoint.stat().st_size == resolved_manifest.checkpoint.size_bytes
    )
    if checkpoint.name != resolved_manifest.checkpoint.filename:
        issues.append("checkpoint filename is not the frozen Small/vits artifact")
    if checkpoint_sha256 is None:
        issues.append("Video Depth Anything Small checkpoint is missing")
    elif not checkpoint_hash_matches:
        issues.append("checkpoint SHA-256 does not match the frozen manifest")
    if checkpoint.is_file() and not checkpoint_size_matches:
        issues.append("checkpoint byte size does not match the frozen manifest")

    return VideoDepthInstallationAudit(
        available=not issues,
        repository_path=str(repository),
        checkpoint_path=str(checkpoint),
        source_commit=source_commit,
        source_commit_matches=source_commit_matches,
        apache_license_present=apache_license_present,
        checkpoint_sha256=checkpoint_sha256,
        checkpoint_hash_matches=checkpoint_hash_matches,
        checkpoint_size_matches=checkpoint_size_matches,
        encoder=resolved_manifest.encoder,
        issues=issues,
    )


class OfficialVideoDepthAnythingRunner:
    def __init__(
        self,
        repository_path: str | Path,
        checkpoint_path: str | Path,
        *,
        python_executable: str | Path = sys.executable,
        manifest: VideoDepthModelManifest | None = None,
    ) -> None:
        self.manifest = manifest or load_video_depth_manifest()
        self.audit = audit_video_depth_installation(
            repository_path,
            checkpoint_path,
            manifest=self.manifest,
        )
        if not self.audit.available:
            raise RuntimeError(
                "Video Depth Anything Small installation failed audit: "
                + "; ".join(self.audit.issues)
            )
        self.repository_path = Path(repository_path).resolve()
        self.checkpoint_path = Path(checkpoint_path).resolve()
        self.python_executable = str(Path(python_executable).resolve())

    def infer_shot(
        self,
        frames_rgb: np.ndarray,
        fps: float,
    ) -> VideoDepthShotInference:
        frames = np.asarray(frames_rgb, dtype=np.uint8)
        if frames.ndim != 4 or frames.shape[-1] != 3 or frames.shape[0] == 0:
            raise ValueError("video depth input must have shape [frames, height, width, 3]")
        bridge = Path(__file__).resolve().with_name("video_depth_bridge.py")
        with tempfile.TemporaryDirectory(prefix="colorgraph-vda-") as temporary:
            root = Path(temporary)
            input_path = root / "frames.npz"
            output_path = root / "depths.npz"
            np.savez_compressed(input_path, frames=frames)
            completed = subprocess.run(
                [
                    self.python_executable,
                    str(bridge),
                    "--repository",
                    str(self.repository_path),
                    "--checkpoint",
                    str(self.checkpoint_path),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--fps",
                    str(fps),
                    "--input-size",
                    str(self.manifest.inference_contract.input_size),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60 * 30,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "Video Depth Anything bridge failed: "
                    + (completed.stderr.strip() or completed.stdout.strip())
                )
            with np.load(output_path, allow_pickle=False) as payload:
                depths = np.asarray(payload["depths"], dtype=np.float32)
                inference = VideoDepthShotInference(
                    depths=depths,
                    runtime=str(payload["runtime"].item()),
                    device_name=str(payload["device_name"].item()),
                    precision=str(payload["precision"].item()),
                    model_load_seconds=float(
                        payload["model_load_seconds"].item()
                    ),
                    inference_seconds=float(
                        payload["inference_seconds"].item()
                    ),
                    peak_cpu_memory_mb=float(
                        payload["peak_cpu_memory_mb"].item()
                    ),
                    peak_gpu_memory_mb=float(
                        payload["peak_gpu_memory_mb"].item()
                    ),
                    memory_growth_mb=float(
                        payload["memory_growth_mb"].item()
                    ),
                    checkpoint_state_sha256=str(
                        payload["checkpoint_state_sha256"].item()
                    ),
                )
        if depths.shape != frames.shape[:3]:
            raise RuntimeError(
                f"Video Depth Anything returned {depths.shape}; expected {frames.shape[:3]}"
            )
        return inference


def _affine_temporal_uncertainty(previous: np.ndarray, current: np.ndarray) -> float:
    previous_flat = previous.reshape(-1).astype(np.float64)
    current_flat = current.reshape(-1).astype(np.float64)
    stride = max(1, previous_flat.size // 16384)
    previous_sample = previous_flat[::stride]
    current_sample = current_flat[::stride]
    finite = np.isfinite(previous_sample) & np.isfinite(current_sample)
    if np.count_nonzero(finite) < 32:
        return 1.0
    previous_sample = previous_sample[finite]
    current_sample = current_sample[finite]
    design = np.column_stack((current_sample, np.ones_like(current_sample)))
    coefficients, *_ = np.linalg.lstsq(design, previous_sample, rcond=None)
    aligned = current_sample * coefficients[0] + coefficients[1]
    span = max(
        float(np.percentile(previous_sample, 95) - np.percentile(previous_sample, 5)),
        1e-6,
    )
    residual = float(np.median(np.abs(aligned - previous_sample)) / span)
    return float(np.clip(0.05 + residual * 2.5, 0.02, 1.0))


def _decode_rgb_video(source: str | Path) -> tuple[np.ndarray, float]:
    capture = cv2.VideoCapture(str(Path(source).resolve()))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {source}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[np.ndarray] = []
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    if fps <= 0 or not frames:
        raise RuntimeError("video depth source does not contain decodable timed frames")
    return np.stack(frames), fps


def run_video_depth_shadow(
    source: str | Path,
    shot_ranges: list[TimeRange],
    output_path: str | Path,
    runner: VideoDepthShotRunner,
    *,
    manifest: VideoDepthModelManifest | None = None,
) -> VideoDepthShadowResult:
    started = time.perf_counter()
    resolved_manifest = manifest or load_video_depth_manifest()
    source_path = Path(source).resolve()
    frames, fps = _decode_rgb_video(source_path)
    depth_parts: list[np.ndarray] = []
    normalized_parts: list[np.ndarray] = []
    uncertainty_parts: list[np.ndarray] = []
    shot_indices: list[np.ndarray] = []
    statistics: list[ShotDepthStatistics] = []
    performance: list[VideoDepthShotInference] = []

    for shot_index, time_range in enumerate(shot_ranges):
        start = max(0, round(time_range.start_seconds * fps))
        end = min(len(frames), round(time_range.end_seconds * fps))
        if end <= start:
            continue
        raw_inference = runner.infer_shot(frames[start:end], fps)
        if isinstance(raw_inference, VideoDepthShotInference):
            performance.append(raw_inference)
            shot_depth = np.asarray(
                raw_inference.depths,
                dtype=np.float32,
            )
        else:
            shot_depth = np.asarray(raw_inference, dtype=np.float32)
        if shot_depth.shape != frames[start:end].shape[:3]:
            raise RuntimeError("video depth runner returned an invalid shot depth shape")
        if not np.isfinite(shot_depth).all():
            raise RuntimeError("video depth runner returned non-finite float depth")

        q05, median, q95 = (
            float(value) for value in np.percentile(shot_depth, (5, 50, 95))
        )
        span = max(q95 - q05, 1e-6)
        normalized = ((shot_depth - q05) / span).clip(0, 1).astype(np.float32)
        uncertainty = np.full(len(shot_depth), 0.15, dtype=np.float32)
        for frame_index in range(1, len(shot_depth)):
            uncertainty[frame_index] = _affine_temporal_uncertainty(
                shot_depth[frame_index - 1],
                shot_depth[frame_index],
            )
        if len(uncertainty) > 1:
            uncertainty[0] = uncertainty[1]

        depth_parts.append(shot_depth)
        normalized_parts.append(normalized)
        uncertainty_parts.append(uncertainty)
        shot_indices.append(np.full(len(shot_depth), shot_index, dtype=np.int32))
        statistics.append(
            ShotDepthStatistics(
                shot_index=shot_index,
                frame_count=len(shot_depth),
                q05=q05,
                median=median,
                q95=q95,
                uncertainty_mean=float(uncertainty.mean()),
                uncertainty_p95=float(np.percentile(uncertainty, 95)),
                model_load_seconds=(
                    raw_inference.model_load_seconds
                    if isinstance(raw_inference, VideoDepthShotInference)
                    else None
                ),
                inference_seconds=(
                    raw_inference.inference_seconds
                    if isinstance(raw_inference, VideoDepthShotInference)
                    else None
                ),
                peak_cpu_memory_mb=(
                    raw_inference.peak_cpu_memory_mb
                    if isinstance(raw_inference, VideoDepthShotInference)
                    else None
                ),
                peak_gpu_memory_mb=(
                    raw_inference.peak_gpu_memory_mb
                    if isinstance(raw_inference, VideoDepthShotInference)
                    else None
                ),
                memory_growth_mb=(
                    raw_inference.memory_growth_mb
                    if isinstance(raw_inference, VideoDepthShotInference)
                    else None
                ),
            )
        )

    if not depth_parts:
        raise RuntimeError("no shot frames were available for video depth shadow inference")
    inverse_depth = np.concatenate(depth_parts).astype(np.float32)
    normalized_depth = np.concatenate(normalized_parts).astype(np.float32)
    uncertainty = np.concatenate(uncertainty_parts).astype(np.float32)
    frame_shot_indices = np.concatenate(shot_indices)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        inverse_depth=inverse_depth,
        normalized_near_score=normalized_depth,
        uncertainty=uncertainty,
        shot_index=frame_shot_indices,
        fps=np.asarray(fps, dtype=np.float64),
        schema=np.asarray(VIDEO_DEPTH_SHADOW_SCHEMA),
    )
    output_sha256 = _sha256(destination)
    elapsed_seconds = max(time.perf_counter() - started, 1e-9)
    performance_observed = len(performance) == len(statistics)
    checkpoint_states = {
        item.checkpoint_state_sha256 for item in performance
    }
    if len(checkpoint_states) > 1:
        raise RuntimeError(
            "Video Depth Anything checkpoint state changed between shots"
        )
    runtimes = {item.runtime for item in performance}
    devices = {item.device_name for item in performance}
    precisions = {item.precision for item in performance}
    if (
        performance_observed
        and (len(runtimes) != 1 or len(devices) != 1 or len(precisions) != 1)
    ):
        raise RuntimeError(
            "Video Depth Anything runtime identity changed between shots"
        )
    model_load_seconds = sum(
        item.model_load_seconds for item in performance
    )
    inference_seconds = sum(
        item.inference_seconds for item in performance
    )
    audit = getattr(runner, "audit", None)
    return VideoDepthShadowResult(
        model_id=resolved_manifest.model_id,
        model_license=resolved_manifest.license,
        checkpoint_sha256=resolved_manifest.checkpoint.sha256,
        checkpoint_state_sha256=(
            next(iter(checkpoint_states)) if checkpoint_states else None
        ),
        checkpoint_hash_kind=(
            "colorgraph.torch-state-dict/v1"
            if checkpoint_states
            else None
        ),
        source_commit=(
            audit.source_commit if audit is not None else None
        ),
        source_path=str(source_path),
        source_sha256=_sha256(source_path),
        output_path=str(destination),
        output_sha256=output_sha256,
        frame_count=len(inverse_depth),
        width=inverse_depth.shape[2],
        height=inverse_depth.shape[1],
        fps=fps,
        float_depth_preserved=True,
        uncertainty_semantics="affine_aligned_temporal_residual_not_accuracy",
        performance_observed=performance_observed,
        operating_system=platform.platform(),
        runtime=next(iter(runtimes)) if len(runtimes) == 1 else "unavailable",
        device_name=next(iter(devices)) if len(devices) == 1 else "unavailable",
        precision=(
            next(iter(precisions))
            if len(precisions) == 1
            else "unavailable"
        ),
        model_load_seconds=model_load_seconds,
        inference_seconds=inference_seconds,
        elapsed_seconds=elapsed_seconds,
        inference_fps=(
            len(inverse_depth) / inference_seconds
            if performance_observed and inference_seconds > 0
            else None
        ),
        cold_processing_fps=len(inverse_depth) / elapsed_seconds,
        peak_cpu_memory_mb=max(
            (item.peak_cpu_memory_mb for item in performance),
            default=0,
        ),
        peak_gpu_memory_mb=max(
            (item.peak_gpu_memory_mb for item in performance),
            default=0,
        ),
        memory_growth_mb=max(
            (item.memory_growth_mb for item in performance),
            default=0,
        ),
        shot_statistics=statistics,
    )


def write_video_depth_shadow_report(
    result: VideoDepthShadowResult,
    output_path: str | Path,
) -> Path:
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
