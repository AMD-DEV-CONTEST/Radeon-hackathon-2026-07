from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from pydantic import Field, model_validator

from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import GradeGraph, MaskAsset, SpatialKind
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.masks import mask_expression_operands
from colorgraph.grading.video import VideoRenderer
from colorgraph.media.probe import (
    VideoFrameTiming,
    probe_frame_timings,
    probe_media,
)
from colorgraph.quality import QualityReport, analyze_video_quality
from colorgraph.storage import ProjectStore

PRODUCTION_BENCHMARK_VERSION = "colorgraph.production-video-benchmark/v1"
LONG_VIDEO_MINIMUM_SECONDS = 120.0
BenchmarkVariant = Literal[
    "no_mask",
    "farneback",
    "vda",
    "current_combined",
    "sam21",
]
BenchmarkProfileId = Literal["proxy_1080p", "master_4k"]
BenchmarkThermalState = Literal["cold", "warm"]
BenchmarkCaseStatus = Literal["completed", "blocked", "failed"]

REQUIRED_VARIANTS: tuple[BenchmarkVariant, ...] = (
    "no_mask",
    "farneback",
    "vda",
    "current_combined",
    "sam21",
)
REQUIRED_PROFILES: tuple[BenchmarkProfileId, ...] = (
    "proxy_1080p",
    "master_4k",
)
REQUIRED_THERMAL_STATES: tuple[BenchmarkThermalState, ...] = ("cold", "warm")
_DEVELOPMENT_PROJECT = (
    "synthetic_landscape",
    "api-e2e",
    "api-scene-test",
    "reference-e2e",
    "agent-ui-e2e",
    "agent-cancel-resume-qa",
    "creative-shadow-browser-qa",
)


class ProductionBenchmarkProfile(StrictEvaluationModel):
    profile_id: BenchmarkProfileId
    maximum_width: int = Field(gt=0)
    maximum_height: int = Field(gt=0)
    target_fps: float | None = Field(default=None, gt=0)
    bit_depth: Literal[8, 10]
    delivery_kind: Literal["proxy", "master"]
    quality_mode: Literal["fp32_preview", "fp32_master"]


PROFILE_PRESETS: dict[BenchmarkProfileId, ProductionBenchmarkProfile] = {
    "proxy_1080p": ProductionBenchmarkProfile(
        profile_id="proxy_1080p",
        maximum_width=1920,
        maximum_height=1080,
        target_fps=30.0,
        bit_depth=8,
        delivery_kind="proxy",
        quality_mode="fp32_preview",
    ),
    "master_4k": ProductionBenchmarkProfile(
        profile_id="master_4k",
        maximum_width=3840,
        maximum_height=2160,
        target_fps=None,
        bit_depth=10,
        delivery_kind="master",
        quality_mode="fp32_master",
    ),
}


class BenchmarkMaskModel(StrictEvaluationModel):
    asset_id: str
    kind: str
    target: str
    provider: str
    model_revision: str | None = None
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    tracking_algorithm: str
    asset_schema: str
    asset_content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_complete: bool = False
    provenance_blockers: list[str] = Field(default_factory=list)


class BenchmarkSource(StrictEvaluationModel):
    project_id: str
    path: str
    size_bytes: int = Field(ge=0)
    modified_time_ns: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    codec: str
    pixel_format: str | None
    real_long_media_qualified: bool
    qualification_reasons: list[str] = Field(default_factory=list)


class BenchmarkRenderAcceleratorEvidence(StrictEvaluationModel):
    schema_version: str
    runtime: str
    vendor: str
    device_name: str
    torch_device: str
    hip_version: str | None
    batch_count: int = Field(gt=0)
    all_batches_accelerator_verified: bool
    peak_allocated_memory_mb: float | None = Field(default=None, ge=0)
    peak_reserved_memory_mb: float | None = Field(default=None, ge=0)
    batch_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductionBenchmarkCase(StrictEvaluationModel):
    case_key: str
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: BenchmarkCaseStatus
    variant: BenchmarkVariant
    profile: BenchmarkProfileId
    thermal_state: BenchmarkThermalState
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_mask_asset_ids: list[str] = Field(default_factory=list)
    mask_models: list[BenchmarkMaskModel] = Field(default_factory=list)
    verify_mask_storage: bool
    batch_size: int = Field(default=4, gt=0)
    blocker: str | None = None
    error: str | None = None
    output_path: str | None = None
    output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_bytes: int | None = Field(default=None, ge=0)
    output_width: int | None = Field(default=None, gt=0)
    output_height: int | None = Field(default=None, gt=0)
    output_fps: float | None = Field(default=None, gt=0)
    output_duration_seconds: float | None = Field(default=None, gt=0)
    output_codec: str | None = None
    output_pixel_format: str | None = None
    frame_count: int | None = Field(default=None, gt=0)
    elapsed_seconds: float | None = Field(default=None, gt=0)
    processing_fps: float | None = Field(default=None, gt=0)
    p95_frame_latency_ms: float | None = Field(default=None, ge=0)
    batch_latency_sample_count: int = Field(default=0, ge=0)
    peak_vram_allocated_mb: float | None = Field(default=None, ge=0)
    peak_vram_reserved_mb: float | None = Field(default=None, ge=0)
    encoder: str | None = None
    encoder_hardware_accelerated: bool | None = None
    encoder_available_verified: bool | None = None
    render_accelerator_evidence: BenchmarkRenderAcceleratorEvidence | None = None
    bit_depth: int | None = Field(default=None, ge=8, le=10)
    compute_precision: str | None = None
    precision_budget: str | None = None
    meets_master_precision: bool | None = None
    maximum_timestamp_error_seconds: float | None = Field(default=None, ge=0)
    quality_checked: bool = False
    quality_score: int | None = Field(default=None, ge=0, le=100)
    hard_quality_checks_passed: bool | None = None
    quality_report_path: str | None = None
    quality_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    measurement_origin: Literal[
        "fresh_render",
        "compatible_checkpoint",
    ] = "fresh_render"
    resumed_from_checkpoint: bool = False
    resumed_from_input_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_reuse_reason: Literal[
        "exact_input_digest",
        "source_graph_changed_variant_graph_unchanged",
    ] | None = None
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_status_payload(self) -> ProductionBenchmarkCase:
        if self.status == "completed":
            required = {
                "output_path": self.output_path,
                "output_sha256": self.output_sha256,
                "frame_count": self.frame_count,
                "elapsed_seconds": self.elapsed_seconds,
                "processing_fps": self.processing_fps,
                "encoder": self.encoder,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    f"completed benchmark case lacks required fields: {sorted(missing)}"
                )
            if self.blocker is not None or self.error is not None:
                raise ValueError("completed benchmark case cannot carry blocker/error")
        elif self.status == "blocked":
            if not self.blocker:
                raise ValueError("blocked benchmark case requires a blocker")
        elif not self.error:
            raise ValueError("failed benchmark case requires an error")
        return self


class ProductionBenchmarkReport(StrictEvaluationModel):
    schema_version: str = PRODUCTION_BENCHMARK_VERSION
    benchmark_version: str = PRODUCTION_BENCHMARK_VERSION
    created_at: datetime
    updated_at: datetime
    run_id: str
    status: Literal["complete", "partial", "failed"]
    source: BenchmarkSource
    source_graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_start_seconds: float = Field(ge=0)
    render_end_seconds: float = Field(gt=0)
    render_duration_seconds: float = Field(gt=0)
    long_video_minimum_seconds: float = Field(gt=0)
    long_video_run_qualified: bool
    batch_size: int = Field(default=4, gt=0)
    hardware: dict[str, object]
    software: dict[str, str | None]
    requested_variants: list[BenchmarkVariant]
    requested_profiles: list[BenchmarkProfileId]
    requested_thermal_states: list[BenchmarkThermalState]
    required_coverage: list[str]
    completed_coverage: list[str]
    blocked_coverage: list[str]
    failed_coverage: list[str]
    missing_coverage: list[str]
    quality_coverage_required: list[str]
    quality_coverage_completed: list[str]
    model_provenance_complete: bool = False
    model_provenance_blockers: dict[str, list[str]] = Field(
        default_factory=dict,
    )
    cases: list[ProductionBenchmarkCase]
    production_claim_allowed: bool
    notes: list[str] = Field(default_factory=list)


class ProgressLatencyTracker:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._previous_time: float | None = None
        self._previous_completed = 0
        self.frame_latency_ms: list[float] = []

    def __call__(self, completed: int, _: int) -> None:
        now = self._clock()
        if self._previous_time is not None and completed > self._previous_completed:
            frame_delta = completed - self._previous_completed
            self.frame_latency_ms.append((now - self._previous_time) * 1000.0 / frame_delta)
        self._previous_time = now
        self._previous_completed = completed

    @property
    def p95_ms(self) -> float:
        if not self.frame_latency_ms:
            return 0.0
        return float(np.percentile(np.asarray(self.frame_latency_ms), 95))


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _model_descriptor(asset: MaskAsset) -> BenchmarkMaskModel:
    metadata = asset.metadata
    prediction_evidence = metadata.get("prediction_evidence")
    evidence = prediction_evidence if isinstance(prediction_evidence, dict) else {}
    tracking = asset.metadata.get("tracking")
    tracking_algorithm = (
        str(tracking.get("algorithm", "unknown")) if isinstance(tracking, dict) else "unknown"
    )
    provider = str(metadata.get("provider", "unknown"))
    model_revision = next(
        (
            str(metadata[key])
            for key in ("model_revision", "provider_revision", "revision")
            if metadata.get(key)
        ),
        next(
            (
                str(evidence[key])
                for key in ("model_revision", "provider_revision", "revision")
                if evidence.get(key)
            ),
            None,
        ),
    )
    checkpoint_sha256 = next(
        (
            str(metadata[key]).lower()
            for key in ("checkpoint_sha256", "model_sha256", "weights_sha256")
            if metadata.get(key)
        ),
        next(
            (
                str(evidence[key]).lower()
                for key in (
                    "checkpoint_sha256",
                    "model_sha256",
                    "weights_sha256",
                )
                if evidence.get(key)
            ),
            None,
        ),
    )
    asset_content_sha256 = next(
        (
            str(metadata[key]).lower()
            for key in ("video_sha256", "sequence_sha256", "content_sha256")
            if metadata.get(key)
        ),
        None,
    )
    blockers: list[str] = []
    if provider == "unknown":
        blockers.append("provider_missing")
    if model_revision is None:
        blockers.append("model_revision_missing")
    if checkpoint_sha256 is None:
        blockers.append("checkpoint_sha256_missing")
    if asset_content_sha256 is None:
        blockers.append("asset_content_sha256_missing")
    return BenchmarkMaskModel(
        asset_id=asset.id,
        kind=asset.kind.value,
        target=asset.target,
        provider=provider,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        tracking_algorithm=tracking_algorithm,
        asset_schema=str(metadata.get("schema", "unknown")),
        asset_content_sha256=asset_content_sha256,
        metadata_sha256=_canonical_sha256(metadata),
        provenance_complete=not blockers,
        provenance_blockers=blockers,
    )


def _asset_is_farneback(asset: MaskAsset) -> bool:
    tracking = asset.metadata.get("tracking")
    algorithm = str(tracking.get("algorithm", "")).lower() if isinstance(tracking, dict) else ""
    return asset.kind == SpatialKind.SEMANTIC and "farneback" in algorithm


def _asset_is_vda(asset: MaskAsset) -> bool:
    provider = str(asset.metadata.get("provider", "")).lower()
    return asset.kind == SpatialKind.DEPTH and (
        "depth-anything" in provider or "video-depth-anything" in provider
    )


def _asset_is_sam21(asset: MaskAsset) -> bool:
    provider = str(asset.metadata.get("provider", "")).lower()
    tracking = asset.metadata.get("tracking")
    algorithm = str(tracking.get("algorithm", "")).lower() if isinstance(tracking, dict) else ""
    combined = f"{provider} {algorithm}".replace("_", "").replace("-", "")
    combined = combined.replace(".", "")
    return "sam21" in combined or "segmentanything21" in combined


def _active_mask_asset_ids(graph: GradeGraph) -> set[str]:
    assets = {asset.id: asset for asset in graph.masks}
    selected_ids = {
        node.spatial_scope.mask_asset_id
        for node in graph.nodes
        if node.enabled
        and node.spatial_scope.mask_asset_id in assets
    }
    expression_operands = {
        operand
        for node in graph.nodes
        if node.enabled and node.spatial_scope.expression
        for operand in mask_expression_operands(
            node.spatial_scope.expression or ""
        )
    }
    for operand in expression_operands:
        if operand in assets:
            selected_ids.add(operand)
            continue
        for asset in assets.values():
            declared = asset.metadata.get("target_aliases", [])
            aliases = {
                asset.id,
                asset.target,
                *(
                    str(item)
                    for item in declared
                    if isinstance(declared, list)
                ),
            }
            if operand in aliases:
                selected_ids.add(asset.id)
    return selected_ids


def prepare_benchmark_graph(
    graph: GradeGraph,
    variant: BenchmarkVariant,
) -> tuple[GradeGraph | None, list[BenchmarkMaskModel], str | None]:
    candidate = graph.model_copy(deep=True)
    if variant == "no_mask":
        selected_ids: set[str] = set()
    elif variant == "farneback":
        selected_ids = {asset.id for asset in candidate.masks if _asset_is_farneback(asset)}
    elif variant == "vda":
        selected_ids = {asset.id for asset in candidate.masks if _asset_is_vda(asset)}
    elif variant == "sam21":
        selected_ids = {asset.id for asset in candidate.masks if _asset_is_sam21(asset)}
    else:
        selected_ids = _active_mask_asset_ids(candidate)

    if variant != "no_mask" and not selected_ids:
        label = {
            "farneback": "no semantic Farneback mask asset is installed",
            "vda": "no Depth Anything depth mask asset is installed",
            "sam21": "no audited SAM 2.1 video mask asset is installed",
            "current_combined": "the current graph has no active mask assets",
        }[variant]
        return None, [], label

    aliases: dict[str, str] = {}
    selected_assets = {
        asset.id: asset for asset in candidate.masks if asset.id in selected_ids
    }
    for asset in selected_assets.values():
        declared = asset.metadata.get("target_aliases", [])
        values = declared if isinstance(declared, list) else []
        for alias in {asset.id, asset.target, *(str(item) for item in values)}:
            aliases[alias] = asset.id

    for node in candidate.nodes:
        mask_id = node.spatial_scope.mask_asset_id
        if mask_id and mask_id not in selected_ids:
            replacement_id = aliases.get(mask_id)
            replacement = (
                selected_assets.get(replacement_id)
                if replacement_id is not None
                else None
            )
            if replacement is None:
                node.enabled = False
            else:
                node.spatial_scope.mask_asset_id = replacement.id
                node.spatial_scope.kind = replacement.kind
                node.spatial_scope.target = replacement.target
        expression = node.spatial_scope.expression
        if expression:
            operands = {
                aliases.get(operand, operand) for operand in mask_expression_operands(expression)
            }
            if not operands.issubset(selected_ids):
                node.enabled = False
    candidate.masks = [asset for asset in candidate.masks if asset.id in selected_ids]
    validated = GradeGraph.model_validate(candidate.model_dump(mode="python"))
    descriptors = [_model_descriptor(asset) for asset in validated.masks]
    return validated, descriptors, None


def required_case_keys() -> list[str]:
    return [
        f"{variant}:{profile}:{thermal}"
        for variant in REQUIRED_VARIANTS
        for profile in REQUIRED_PROFILES
        for thermal in REQUIRED_THERMAL_STATES
    ]


def _quality_case_keys() -> list[str]:
    return [f"current_combined:{profile}:warm" for profile in REQUIRED_PROFILES]


def summarize_benchmark_report(
    *,
    created_at: datetime,
    run_id: str,
    source: BenchmarkSource,
    source_graph_digest: str,
    render_start_seconds: float,
    render_end_seconds: float,
    hardware: dict[str, object],
    software: dict[str, str | None],
    requested_variants: Sequence[BenchmarkVariant],
    requested_profiles: Sequence[BenchmarkProfileId],
    requested_thermal_states: Sequence[BenchmarkThermalState],
    cases: Sequence[ProductionBenchmarkCase],
    quality_checks_required: bool,
    batch_size: int = 4,
) -> ProductionBenchmarkReport:
    required = required_case_keys()
    by_key = {case.case_key: case for case in cases}
    completed = sorted(
        key for key, case in by_key.items() if key in required and case.status == "completed"
    )
    blocked = sorted(
        key for key, case in by_key.items() if key in required and case.status == "blocked"
    )
    failed = sorted(
        key for key, case in by_key.items() if key in required and case.status == "failed"
    )
    missing = sorted(set(required) - set(completed) - set(blocked) - set(failed))
    quality_required = _quality_case_keys() if quality_checks_required else []
    quality_completed = sorted(
        key
        for key in quality_required
        if (
            key in by_key
            and by_key[key].status == "completed"
            and by_key[key].quality_checked
            and by_key[key].hard_quality_checks_passed is True
            and by_key[key].quality_report_path is not None
            and by_key[key].quality_report_sha256 is not None
        )
    )
    provenance_blockers = {
        key: sorted(
            {
                f"{model.asset_id}:{blocker}"
                for model in by_key[key].mask_models
                for blocker in (
                    model.provenance_blockers
                    or ([] if model.provenance_complete else ["provenance_incomplete_unspecified"])
                )
            }
        )
        for key in completed
        if any(
            model.provenance_blockers or not model.provenance_complete
            for model in by_key[key].mask_models
        )
    }
    duration = render_end_seconds - render_start_seconds
    long_video_run = duration + 1e-6 >= LONG_VIDEO_MINIMUM_SECONDS
    production_allowed = (
        source.real_long_media_qualified
        and source.sha256 is not None
        and long_video_run
        and len(completed) == len(required)
        and not blocked
        and not failed
        and not missing
        and len(quality_completed) == len(quality_required)
        and not provenance_blockers
    )
    if production_allowed:
        status: Literal["complete", "partial", "failed"] = "complete"
    elif failed and not completed:
        status = "failed"
    else:
        status = "partial"
    notes = [
        "Every required matrix row must be measured; blocked rows are not inferred.",
        "Fixture or short-segment runs never authorize a production performance claim.",
        "SAM 2.1 rows are measured only when an audited real mask asset is present.",
        "Mask-model provider revisions, checkpoint hashes, and asset hashes must "
        "be frozen before a production claim is allowed.",
    ]
    return ProductionBenchmarkReport(
        created_at=created_at,
        updated_at=datetime.now(UTC),
        run_id=run_id,
        status=status,
        source=source,
        source_graph_digest=source_graph_digest,
        render_start_seconds=render_start_seconds,
        render_end_seconds=render_end_seconds,
        render_duration_seconds=duration,
        long_video_minimum_seconds=LONG_VIDEO_MINIMUM_SECONDS,
        long_video_run_qualified=long_video_run,
        batch_size=batch_size,
        hardware=hardware,
        software=software,
        requested_variants=list(requested_variants),
        requested_profiles=list(requested_profiles),
        requested_thermal_states=list(requested_thermal_states),
        required_coverage=required,
        completed_coverage=completed,
        blocked_coverage=blocked,
        failed_coverage=failed,
        missing_coverage=missing,
        quality_coverage_required=quality_required,
        quality_coverage_completed=quality_completed,
        model_provenance_complete=not provenance_blockers,
        model_provenance_blockers=provenance_blockers,
        cases=sorted(cases, key=lambda item: item.case_key),
        production_claim_allowed=production_allowed,
        notes=notes,
    )


def _source_record(
    *,
    project_id: str,
    source_path: Path,
    hash_source: bool,
) -> BenchmarkSource:
    media = probe_media(source_path)
    stat = source_path.stat()
    reasons: list[str] = []
    if project_id.lower().startswith(_DEVELOPMENT_PROJECT):
        reasons.append("project id identifies a development/browser fixture")
    if media.duration_seconds + 1e-6 < LONG_VIDEO_MINIMUM_SECONDS:
        reasons.append(f"duration is below {LONG_VIDEO_MINIMUM_SECONDS:.0f} seconds")
    if media.width < 1920 or media.height < 1080:
        reasons.append("source is below 1920x1080")
    return BenchmarkSource(
        project_id=project_id,
        path=str(source_path),
        size_bytes=stat.st_size,
        modified_time_ns=stat.st_mtime_ns,
        sha256=_file_sha256(source_path) if hash_source else None,
        width=media.width,
        height=media.height,
        fps=media.fps,
        duration_seconds=media.duration_seconds,
        frame_count=media.frame_count,
        codec=media.codec,
        pixel_format=media.pixel_format,
        real_long_media_qualified=not reasons,
        qualification_reasons=reasons,
    )


def _command_version(
    executable: str,
    *arguments: str,
    timeout_seconds: float = 10,
) -> str | None:
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return next(
        (line.strip() for line in completed.stdout.splitlines() if line.strip()),
        None,
    )


def _nvidia_driver_version() -> str | None:
    line = _command_version(
        "nvidia-smi",
        "--query-gpu=driver_version",
        "--format=csv,noheader",
    )
    if line is None:
        return None
    versions = sorted({value.strip() for value in line.splitlines() if value.strip()})
    return ",".join(versions) or None


def _software_snapshot() -> dict[str, str | None]:
    return {
        "operating_system": platform.platform(),
        "python_version": sys.version,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "hip_version": torch.version.hip,
        "ffmpeg_binary": settings.ffmpeg_binary,
        "ffmpeg_version": _command_version(
            settings.ffmpeg_binary,
            "-version",
        ),
        "ffprobe_binary": settings.ffprobe_binary,
        "ffprobe_version": _command_version(
            settings.ffprobe_binary,
            "-version",
        ),
        "nvidia_driver_version": _nvidia_driver_version(),
    }


def _expected_dimensions(
    source: BenchmarkSource,
    profile: ProductionBenchmarkProfile,
) -> tuple[int, int]:
    scale = min(
        1.0,
        profile.maximum_width / source.width,
        profile.maximum_height / source.height,
    )
    return (
        max(2, int(source.width * scale) // 2 * 2),
        max(2, int(source.height * scale) // 2 * 2),
    )


def _requires_full_source_timings(
    source: BenchmarkSource,
    *,
    start_seconds: float,
    end_seconds: float,
) -> bool:
    return (
        start_seconds <= 1e-9
        and end_seconds >= source.duration_seconds - 1e-6
    )


def _case_digest(
    *,
    source: BenchmarkSource,
    source_graph_digest: str,
    variant_graph_digest: str,
    variant: BenchmarkVariant,
    profile: ProductionBenchmarkProfile,
    thermal_state: BenchmarkThermalState,
    start_seconds: float,
    end_seconds: float,
) -> str:
    return _canonical_sha256(
        {
            "benchmark_version": PRODUCTION_BENCHMARK_VERSION,
            "source": source.model_dump(mode="json"),
            "source_graph_digest": source_graph_digest,
            "variant_graph_digest": variant_graph_digest,
            "variant": variant,
            "profile": profile.model_dump(mode="json"),
            "thermal_state": thermal_state,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
        }
    )


def _case_key(
    variant: BenchmarkVariant,
    profile: BenchmarkProfileId,
    thermal_state: BenchmarkThermalState,
) -> str:
    return f"{variant}:{profile}:{thermal_state}"


def _load_checkpoint(
    path: Path,
    *,
    input_digest: str,
    compatible_input_digests: Sequence[str] = (),
    expected_case_key: str | None = None,
    expected_graph_digest: str | None = None,
    expected_batch_size: int | None = None,
) -> ProductionBenchmarkCase | None:
    if not path.is_file():
        return None
    try:
        case = ProductionBenchmarkCase.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    accepted_input_digests = {
        input_digest,
        *compatible_input_digests,
    }
    if case.input_digest not in accepted_input_digests or case.status != "completed":
        return None
    if expected_case_key is not None and case.case_key != expected_case_key:
        return None
    if (
        expected_graph_digest is not None
        and case.graph_digest != expected_graph_digest
    ):
        return None
    if expected_batch_size is not None and case.batch_size != expected_batch_size:
        return None
    if case.output_path is None or case.output_sha256 is None:
        return None
    output = Path(case.output_path)
    if not output.is_file() or _file_sha256(output) != case.output_sha256:
        return None
    quality_report_sha256 = case.quality_report_sha256
    if case.quality_checked:
        if case.quality_report_path is None:
            return None
        quality_path = Path(case.quality_report_path)
        if not quality_path.is_file():
            return None
        try:
            quality_payload = quality_path.read_bytes()
            quality = QualityReport.model_validate_json(quality_payload)
        except (OSError, ValueError):
            return None
        quality_report_sha256 = hashlib.sha256(quality_payload).hexdigest()
        if (
            case.quality_report_sha256 is not None
            and case.quality_report_sha256 != quality_report_sha256
        ):
            return None
        if (
            quality.score != case.quality_score
            or quality.hard_checks_passed != case.hard_quality_checks_passed
            or Path(quality.output_path).resolve() != output.resolve()
        ):
            return None
    reused_from_input_digest = (
        case.input_digest
        if case.input_digest != input_digest
        else case.resumed_from_input_digest
    )
    measurement_origin = (
        "compatible_checkpoint"
        if reused_from_input_digest is not None
        else case.measurement_origin
    )
    checkpoint_reuse_reason = (
        "source_graph_changed_variant_graph_unchanged"
        if reused_from_input_digest is not None
        else case.checkpoint_reuse_reason or "exact_input_digest"
    )
    return case.model_copy(
        update={
            "input_digest": input_digest,
            "measurement_origin": measurement_origin,
            "resumed_from_checkpoint": True,
            "resumed_from_input_digest": reused_from_input_digest,
            "checkpoint_reuse_reason": checkpoint_reuse_reason,
            "quality_report_sha256": quality_report_sha256,
        }
    )


def _load_prior_report(path: Path) -> ProductionBenchmarkReport | None:
    if not path.is_file():
        return None
    try:
        return ProductionBenchmarkReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None


def _compatible_prior_input_digest(
    report: ProductionBenchmarkReport | None,
    *,
    source: BenchmarkSource,
    case_key: str,
    variant_graph_digest: str,
    variant: BenchmarkVariant,
    profile: ProductionBenchmarkProfile,
    thermal_state: BenchmarkThermalState,
    batch_size: int,
    start_seconds: float,
    end_seconds: float,
) -> str | None:
    if (
        report is None
        or report.benchmark_version != PRODUCTION_BENCHMARK_VERSION
        or report.source != source
        or report.render_start_seconds != start_seconds
        or report.render_end_seconds != end_seconds
        or report.batch_size != batch_size
    ):
        return None
    prior_case = next(
        (case for case in report.cases if case.case_key == case_key),
        None,
    )
    if (
        prior_case is None
        or prior_case.status != "completed"
        or prior_case.graph_digest != variant_graph_digest
        or prior_case.batch_size != batch_size
    ):
        return None
    prior_input_digest = _case_digest(
        source=source,
        source_graph_digest=report.source_graph_digest,
        variant_graph_digest=variant_graph_digest,
        variant=variant,
        profile=profile,
        thermal_state=thermal_state,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    if prior_case.input_digest != prior_input_digest:
        return None
    return prior_input_digest


def _peak_memory_reset(
    backend: TorchComputeBackend,
    *,
    empty_cache: bool,
) -> None:
    if backend.info.runtime not in {"cuda", "rocm"} or not torch.cuda.is_available():
        return
    backend.synchronize()
    if empty_cache:
        backend.empty_cache()
    torch.cuda.reset_peak_memory_stats(backend.torch_device)


def _peak_memory(
    backend: TorchComputeBackend,
) -> tuple[float | None, float | None]:
    if backend.info.runtime not in {"cuda", "rocm"} or not torch.cuda.is_available():
        return None, None
    backend.synchronize()
    divisor = 1024.0**2
    return (
        float(torch.cuda.max_memory_allocated(backend.torch_device) / divisor),
        float(torch.cuda.max_memory_reserved(backend.torch_device) / divisor),
    )


def _blocked_case(
    *,
    case_key: str,
    input_digest: str,
    variant: BenchmarkVariant,
    profile: BenchmarkProfileId,
    thermal_state: BenchmarkThermalState,
    batch_size: int,
    graph_digest_value: str,
    blocker: str,
) -> ProductionBenchmarkCase:
    now = datetime.now(UTC)
    return ProductionBenchmarkCase(
        case_key=case_key,
        input_digest=input_digest,
        status="blocked",
        variant=variant,
        profile=profile,
        thermal_state=thermal_state,
        graph_digest=graph_digest_value,
        verify_mask_storage=thermal_state == "cold",
        batch_size=batch_size,
        blocker=blocker,
        started_at=now,
        completed_at=now,
    )


def _failed_case(
    *,
    case_key: str,
    input_digest: str,
    variant: BenchmarkVariant,
    profile: BenchmarkProfileId,
    thermal_state: BenchmarkThermalState,
    batch_size: int,
    graph_digest_value: str,
    active_mask_asset_ids: list[str],
    mask_models: list[BenchmarkMaskModel],
    error: Exception,
    started_at: datetime,
) -> ProductionBenchmarkCase:
    return ProductionBenchmarkCase(
        case_key=case_key,
        input_digest=input_digest,
        status="failed",
        variant=variant,
        profile=profile,
        thermal_state=thermal_state,
        graph_digest=graph_digest_value,
        active_mask_asset_ids=active_mask_asset_ids,
        mask_models=mask_models,
        verify_mask_storage=thermal_state == "cold",
        batch_size=batch_size,
        error=f"{type(error).__name__}: {error}",
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def run_production_benchmark(
    *,
    project_id: str,
    output: str | Path,
    variants: Sequence[BenchmarkVariant] = REQUIRED_VARIANTS,
    profiles: Sequence[BenchmarkProfileId] = REQUIRED_PROFILES,
    thermal_states: Sequence[BenchmarkThermalState] = REQUIRED_THERMAL_STATES,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    batch_size: int = 4,
    hash_source: bool = False,
    quality_checks: bool = True,
    resume: bool = True,
    require_hardware_encoder: bool = False,
    progress: Callable[[str, int, int], None] | None = None,
) -> ProductionBenchmarkReport:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not variants or not profiles or not thermal_states:
        raise ValueError("variants, profiles and thermal_states cannot be empty")
    if len(set(variants)) != len(variants):
        raise ValueError("benchmark variants must be unique")
    if len(set(profiles)) != len(profiles):
        raise ValueError("benchmark profiles must be unique")
    if len(set(thermal_states)) != len(thermal_states):
        raise ValueError("benchmark thermal states must be unique")

    report_path = Path(output).resolve()
    artifacts_root = report_path.with_name(f"{report_path.stem}-artifacts")
    prior_report = _load_prior_report(report_path) if resume else None
    store = ProjectStore()
    project = store.get(project_id)
    source_path = store.resolve_source(project)
    source = _source_record(
        project_id=project_id,
        source_path=source_path,
        hash_source=hash_source,
    )
    graph = store.load_graph(project_id)
    source_digest = graph_digest(graph)
    render_end = (
        source.duration_seconds
        if end_seconds is None
        else min(float(end_seconds), source.duration_seconds)
    )
    if start_seconds < 0 or start_seconds >= source.duration_seconds:
        raise ValueError("benchmark start must be inside the source duration")
    if render_end <= start_seconds:
        raise ValueError("benchmark end must be greater than start")
    run_id = _canonical_sha256(
        {
            "benchmark_version": PRODUCTION_BENCHMARK_VERSION,
            "source": source.model_dump(mode="json"),
            "graph_digest": source_digest,
            "batch_size": batch_size,
            "start_seconds": start_seconds,
            "end_seconds": render_end,
        }
    )[:24]
    created_at = datetime.now(UTC)
    cases: list[ProductionBenchmarkCase] = []
    validated_source_timings: list[VideoFrameTiming] | None = None
    requires_source_timings = _requires_full_source_timings(
        source,
        start_seconds=start_seconds,
        end_seconds=render_end,
    )

    initial_backend = TorchComputeBackend(settings.device_preference)
    hardware = initial_backend.info.model_dump(mode="json")
    for variant in variants:
        variant_graph, models, blocker = prepare_benchmark_graph(graph, variant)
        variant_digest = graph_digest(variant_graph) if variant_graph is not None else source_digest
        for profile_id in profiles:
            profile = PROFILE_PRESETS[profile_id]
            backend = TorchComputeBackend(settings.device_preference)
            renderer = VideoRenderer(backend)
            for thermal_state in thermal_states:
                key = _case_key(variant, profile_id, thermal_state)
                input_digest = _case_digest(
                    source=source,
                    source_graph_digest=source_digest,
                    variant_graph_digest=variant_digest,
                    variant=variant,
                    profile=profile,
                    thermal_state=thermal_state,
                    start_seconds=start_seconds,
                    end_seconds=render_end,
                )
                sidecar = artifacts_root / f"{key.replace(':', '-')}.json"
                if blocker is not None or variant_graph is None:
                    cases.append(
                        _blocked_case(
                            case_key=key,
                            input_digest=input_digest,
                            variant=variant,
                            profile=profile_id,
                            thermal_state=thermal_state,
                            batch_size=batch_size,
                            graph_digest_value=variant_digest,
                            blocker=blocker or "benchmark graph is unavailable",
                        )
                    )
                    continue
                checkpoint = (
                    _load_checkpoint(
                        sidecar,
                        input_digest=input_digest,
                        compatible_input_digests=tuple(
                            digest
                            for digest in [
                                _compatible_prior_input_digest(
                                    prior_report,
                                    source=source,
                                    case_key=key,
                                    variant_graph_digest=variant_digest,
                                    variant=variant,
                                    profile=profile,
                                    thermal_state=thermal_state,
                                    batch_size=batch_size,
                                    start_seconds=start_seconds,
                                    end_seconds=render_end,
                                )
                            ]
                            if digest is not None
                        ),
                        expected_case_key=key,
                        expected_graph_digest=variant_digest,
                        expected_batch_size=batch_size,
                    )
                    if resume
                    else None
                )
                if checkpoint is not None:
                    checkpoint = checkpoint.model_copy(
                        update={
                            "mask_models": models,
                        }
                    )
                    _atomic_write(
                        sidecar,
                        checkpoint.model_dump_json(indent=2),
                    )
                    cases.append(checkpoint)
                    continue

                started_at = datetime.now(UTC)
                destination = artifacts_root / f"{key.replace(':', '-')}.mp4"
                tracker = ProgressLatencyTracker()
                if requires_source_timings and validated_source_timings is None:
                    validated_source_timings = probe_frame_timings(source_path)

                def report_progress(
                    completed: int,
                    total: int,
                    *,
                    _tracker: ProgressLatencyTracker = tracker,
                    _key: str = key,
                ) -> None:
                    _tracker(completed, total)
                    if progress is not None:
                        progress(_key, completed, total)

                try:
                    _peak_memory_reset(
                        backend,
                        empty_cache=thermal_state == "cold",
                    )
                    result = renderer.render(
                        source_path,
                        destination,
                        variant_graph,
                        batch_size=batch_size,
                        bit_depth=profile.bit_depth,
                        progress=report_progress,
                        maximum_width=profile.maximum_width,
                        maximum_height=profile.maximum_height,
                        target_fps=profile.target_fps,
                        start_time_seconds=(start_seconds if start_seconds > 0 else None),
                        end_time_seconds=(
                            render_end if render_end < source.duration_seconds - 1e-6 else None
                        ),
                        include_audio=True,
                        verify_mask_storage=thermal_state == "cold",
                        validated_source_timings=validated_source_timings,
                        require_hardware_encoder=require_hardware_encoder,
                    )
                    allocated, reserved = _peak_memory(backend)
                    rendered = probe_media(destination)
                    expected_width, expected_height = _expected_dimensions(
                        source,
                        profile,
                    )
                    if (rendered.width, rendered.height) != (
                        expected_width,
                        expected_height,
                    ):
                        raise RuntimeError(
                            "benchmark output dimensions do not match profile: "
                            f"{rendered.width}x{rendered.height} != "
                            f"{expected_width}x{expected_height}"
                        )
                    expected_duration = render_end - start_seconds
                    duration_tolerance = max(0.1, 2.0 / rendered.fps)
                    if abs(rendered.duration_seconds - expected_duration) > duration_tolerance:
                        raise RuntimeError(
                            "benchmark output duration does not match requested range: "
                            f"{rendered.duration_seconds:.6f}s != "
                            f"{expected_duration:.6f}s"
                        )
                    quality_checked = (
                        quality_checks and variant == "current_combined" and thermal_state == "warm"
                    )
                    quality_score = None
                    hard_quality_passed = None
                    quality_report_path = None
                    quality_report_sha256 = None
                    if quality_checked:
                        quality = analyze_video_quality(
                            source_path,
                            destination,
                            graph=variant_graph,
                            expected_frame_count=result.frame_count,
                        )
                        quality_path = destination.with_suffix(".quality.json")
                        _atomic_write(
                            quality_path,
                            quality.model_dump_json(indent=2),
                        )
                        quality_report_sha256 = _file_sha256(quality_path)
                        quality_score = quality.score
                        hard_quality_passed = quality.hard_checks_passed
                        quality_report_path = str(quality_path)
                    case = ProductionBenchmarkCase(
                        case_key=key,
                        input_digest=input_digest,
                        status="completed",
                        variant=variant,
                        profile=profile_id,
                        thermal_state=thermal_state,
                        graph_digest=variant_digest,
                        active_mask_asset_ids=[asset.id for asset in variant_graph.masks],
                        mask_models=models,
                        verify_mask_storage=thermal_state == "cold",
                        batch_size=batch_size,
                        output_path=str(destination),
                        output_sha256=_file_sha256(destination),
                        output_bytes=destination.stat().st_size,
                        output_width=rendered.width,
                        output_height=rendered.height,
                        output_fps=rendered.fps,
                        output_duration_seconds=rendered.duration_seconds,
                        output_codec=rendered.codec,
                        output_pixel_format=rendered.pixel_format,
                        frame_count=result.frame_count,
                        elapsed_seconds=result.elapsed_seconds,
                        processing_fps=result.processing_fps,
                        p95_frame_latency_ms=tracker.p95_ms,
                        batch_latency_sample_count=len(tracker.frame_latency_ms),
                        peak_vram_allocated_mb=allocated,
                        peak_vram_reserved_mb=reserved,
                        encoder=result.encoder,
                        encoder_hardware_accelerated=(
                            result.encoder_hardware_accelerated
                        ),
                        encoder_available_verified=(
                            result.encoder_available_verified
                        ),
                        render_accelerator_evidence=(
                            BenchmarkRenderAcceleratorEvidence.model_validate(
                                asdict(result.accelerator_evidence)
                            )
                        ),
                        bit_depth=result.bit_depth,
                        compute_precision=result.compute_precision,
                        precision_budget=result.precision_budget,
                        meets_master_precision=result.meets_master_precision,
                        maximum_timestamp_error_seconds=(result.max_timestamp_error_seconds),
                        quality_checked=quality_checked,
                        quality_score=quality_score,
                        hard_quality_checks_passed=hard_quality_passed,
                        quality_report_path=quality_report_path,
                        quality_report_sha256=quality_report_sha256,
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                    )
                    _atomic_write(sidecar, case.model_dump_json(indent=2))
                    cases.append(case)
                except Exception as exc:
                    case = _failed_case(
                        case_key=key,
                        input_digest=input_digest,
                        variant=variant,
                        profile=profile_id,
                        thermal_state=thermal_state,
                        batch_size=batch_size,
                        graph_digest_value=variant_digest,
                        active_mask_asset_ids=[asset.id for asset in variant_graph.masks],
                        mask_models=models,
                        error=exc,
                        started_at=started_at,
                    )
                    _atomic_write(sidecar, case.model_dump_json(indent=2))
                    cases.append(case)

                partial = summarize_benchmark_report(
                    created_at=created_at,
                    run_id=run_id,
                    source=source,
                    source_graph_digest=source_digest,
                    render_start_seconds=start_seconds,
                    render_end_seconds=render_end,
                    hardware=hardware,
                    software=_software_snapshot(),
                    requested_variants=variants,
                    requested_profiles=profiles,
                    requested_thermal_states=thermal_states,
                    cases=cases,
                    quality_checks_required=quality_checks,
                    batch_size=batch_size,
                )
                _atomic_write(report_path, partial.model_dump_json(indent=2))

    report = summarize_benchmark_report(
        created_at=created_at,
        run_id=run_id,
        source=source,
        source_graph_digest=source_digest,
        render_start_seconds=start_seconds,
        render_end_seconds=render_end,
        hardware=hardware,
        software=_software_snapshot(),
        requested_variants=variants,
        requested_profiles=profiles,
        requested_thermal_states=thermal_states,
        cases=cases,
        quality_checks_required=quality_checks,
        batch_size=batch_size,
    )
    _atomic_write(report_path, report.model_dump_json(indent=2))
    return report


def validate_requested_values(
    values: Iterable[str],
    *,
    allowed: set[str],
    label: str,
) -> list[str]:
    result = list(values)
    invalid = sorted(set(result) - allowed)
    if invalid:
        raise ValueError(f"unsupported {label}: {invalid}")
    if not result:
        raise ValueError(f"{label} cannot be empty")
    return result
