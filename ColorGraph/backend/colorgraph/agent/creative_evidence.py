from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageOps
from pydantic import Field, model_validator

from colorgraph.agent.creative_contracts import (
    ContextBudget,
    DiagnosticSeverity,
    EvidenceKind,
    EvidenceReference,
    MeasurementFact,
    MetricUnit,
    NonEmptyString,
    ProjectContextPack,
    SignedAgentAsset,
    StrictFrozenModel,
    TechnicalBaseline,
    TechnicalDiagnostic,
    TechnicalMetric,
    TimeSpan,
    canonical_sha256,
    sign_agent_asset,
)
from colorgraph.config import settings
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    NodeType,
)
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.looks import graph_digest
from colorgraph.media.frames import extract_frame

EVIDENCE_BUNDLE_VERSION = "colorgraph.agent-evidence-bundle/v1"
EVIDENCE_BUILDER_VERSION = "colorgraph.agent-evidence-builder/v1"


class AudioAvailability(StrEnum):
    AVAILABLE = "available"
    NO_TRACK = "no_track"
    DECODE_FAILED = "decode_failed"


class MotionClassification(StrEnum):
    STATIC = "static"
    CAMERA = "camera"
    OBJECT = "object"
    MIXED = "mixed"


class EvidenceArtifact(StrictFrozenModel):
    evidence_id: str
    kind: EvidenceKind
    relative_path: NonEmptyString
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    display_transform_applied: bool
    model_input_allowed: bool
    source_color_space: str
    display_color_space: str
    physical_statistics_separate: bool


class PhysicalFrameStatistics(StrictFrozenModel):
    frame_index: int = Field(ge=0)
    time_seconds: float = Field(ge=0)
    encoded_mean_luma: float = Field(ge=0, le=1)
    display_mean_luma: float = Field(ge=0, le=1)
    encoded_highlight_ratio: float = Field(ge=0, le=1)
    encoded_shadow_ratio: float = Field(ge=0, le=1)
    display_highlight_ratio: float = Field(ge=0, le=1)
    display_shadow_ratio: float = Field(ge=0, le=1)


class CompositionSummary(StrictFrozenModel):
    method: Literal["deterministic-saliency-proxy/v1"]
    subject_scale_ratio: float = Field(ge=0, le=1)
    centroid_x: float = Field(ge=0, le=1)
    centroid_y: float = Field(ge=0, le=1)
    horizon_y: float = Field(ge=0, le=1)
    source: Literal["display_preview", "decoded_signal_proxy"]


class MotionSummary(StrictFrozenModel):
    method: Literal["farneback-global-residual/v1"]
    classification: MotionClassification
    camera_dx_pixels: float
    camera_dy_pixels: float
    camera_magnitude: float = Field(ge=0)
    object_residual_p90: float = Field(ge=0)
    first_time_seconds: float = Field(ge=0)
    second_time_seconds: float = Field(ge=0)


class AudioSummary(StrictFrozenModel):
    status: AudioAvailability
    analyzed_duration_seconds: float = Field(ge=0)
    loudness_dbfs_proxy: float | None = None
    dynamic_range_db: float | None = None
    rhythm_change_rate_per_minute: float | None = None
    change_points_seconds: list[float]
    embedding_status: Literal["disabled", "not_available"]
    transcription_status: Literal["not_requested"]
    cloud_uploaded: Literal[False] = False
    failure_detail: NonEmptyString | None = None


class ShotEvidencePacket(StrictFrozenModel):
    shot_id: str
    scene_id: str
    time_range: TimeSpan
    display_frame_evidence_ids: list[str]
    measurement_evidence_ids: list[str]
    composition: CompositionSummary
    motion: MotionSummary
    audio: AudioSummary
    supporting_evidence_ids: list[str] = Field(min_length=1)
    counterevidence_ids: list[str] = Field(min_length=1)


class SceneEvidenceSynopsis(StrictFrozenModel):
    scene_id: str
    shot_ids: list[str] = Field(min_length=1)
    synopsis: NonEmptyString
    observed_model_labels: dict[str, str]
    supporting_evidence_ids: list[str] = Field(min_length=1)
    counterevidence_ids: list[str] = Field(min_length=1)


class ProjectEvidenceSynopsis(StrictFrozenModel):
    synopsis: NonEmptyString
    scene_ids: list[str] = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    counterevidence_ids: list[str] = Field(min_length=1)


class ProjectEvidenceBundle(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-evidence-bundle/v1"] = (
        "colorgraph.agent-evidence-bundle/v1"
    )
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_mode: Literal["input_display_plus_technical_balance_no_creative_look"]
    physical_statistics_separate: Literal[True] = True
    artifacts: list[EvidenceArtifact]
    frame_statistics: list[PhysicalFrameStatistics]
    shots: list[ShotEvidencePacket]
    scenes: list[SceneEvidenceSynopsis]
    project: ProjectEvidenceSynopsis
    budget: ContextBudget
    model_input_evidence_ids: list[str]
    omitted_candidate_ids: list[str]
    omission_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_budget_and_traceability(self) -> ProjectEvidenceBundle:
        if len(self.model_input_evidence_ids) > self.budget.maximum_images:
            raise ValueError("evidence bundle exceeds its image budget")
        artifact_ids = {artifact.evidence_id for artifact in self.artifacts}
        unknown_inputs = set(self.model_input_evidence_ids) - artifact_ids
        if unknown_inputs:
            raise ValueError(f"model inputs reference unknown artifacts: {sorted(unknown_inputs)}")
        if self.omitted_candidate_ids and self.omission_reason is None:
            raise ValueError("omitted candidates require an omission reason")
        return self


@dataclass(frozen=True, slots=True)
class ProjectEvidenceBuildResult:
    technical_baseline: SignedAgentAsset
    context_pack: ProjectContextPack
    evidence_bundle: ProjectEvidenceBundle
    evidence_bundle_digest: str
    artifact_root: Path


@dataclass(frozen=True, slots=True)
class _FrameCandidate:
    candidate_id: str
    shot_id: str
    scene_id: str
    frame_index: int
    time_seconds: float
    priority: int


@dataclass(frozen=True, slots=True)
class _DecodedAudio:
    status: AudioAvailability
    samples: np.ndarray
    sample_rate: int
    decoded_duration: float
    failure_detail: str | None = None


def _sha256_file(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_candidates(graph: GradeGraph) -> list[_FrameCandidate]:
    metadata = graph.metadata.get("representative_frames")
    metadata_items = metadata if isinstance(metadata, list) else []
    candidates: list[_FrameCandidate] = []
    for shot_index, shot in enumerate(graph.shots):
        duration = shot.time_range.end_seconds - shot.time_range.start_seconds
        midpoint = (shot.time_range.start_seconds + shot.time_range.end_seconds) * 0.5
        times: list[tuple[float, int]] = [(midpoint, 0)]
        if shot_index < len(metadata_items):
            shot_metadata = metadata_items[shot_index]
            if isinstance(shot_metadata, dict):
                raw_candidates = shot_metadata.get("candidates")
                if isinstance(raw_candidates, list):
                    for item in raw_candidates:
                        if (
                            isinstance(item, dict)
                            and item.get("accepted") is True
                            and isinstance(
                                item.get("time_seconds"),
                                int | float,
                            )
                        ):
                            times.append((float(item["time_seconds"]), 1))
        if len(times) == 1:
            times.extend(
                [
                    (
                        shot.time_range.start_seconds + duration * 0.25,
                        2,
                    ),
                    (
                        shot.time_range.start_seconds + duration * 0.75,
                        2,
                    ),
                ]
            )
        unique: dict[int, tuple[float, int]] = {}
        for timestamp, priority in times:
            frame_index = min(
                max(0, round(timestamp * graph.media.fps)),
                max(0, graph.media.frame_count - 1),
            )
            existing = unique.get(frame_index)
            if existing is None or priority < existing[1]:
                unique[frame_index] = (
                    frame_index / graph.media.fps,
                    priority,
                )
        for frame_index, (timestamp, priority) in unique.items():
            candidates.append(
                _FrameCandidate(
                    candidate_id=f"candidate:{shot.id}:{frame_index}",
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    frame_index=frame_index,
                    time_seconds=round(timestamp, 6),
                    priority=priority,
                )
            )
    return sorted(
        candidates,
        key=lambda item: (
            item.priority,
            item.frame_index,
            item.candidate_id,
        ),
    )


def _select_frame_candidates(
    graph: GradeGraph,
    maximum_images: int,
) -> tuple[list[_FrameCandidate], list[str]]:
    candidates = _frame_candidates(graph)
    if len(candidates) <= maximum_images:
        return sorted(candidates, key=lambda item: item.frame_index), []
    primary = [candidate for candidate in candidates if candidate.priority == 0]
    selected: list[_FrameCandidate] = []
    if maximum_images >= len(primary):
        selected.extend(primary)
        remaining = [candidate for candidate in candidates if candidate not in selected]
        slots = maximum_images - len(selected)
        if slots > 0 and remaining:
            positions = (
                {0}
                if slots == 1
                else {round(index * (len(remaining) - 1) / (slots - 1)) for index in range(slots)}
            )
            selected.extend(remaining[position] for position in sorted(positions))
    else:
        positions = (
            {0}
            if maximum_images == 1
            else {
                round(index * (len(primary) - 1) / (maximum_images - 1))
                for index in range(maximum_images)
            }
        )
        selected.extend(primary[position] for position in sorted(positions))
    selected_ids = {candidate.candidate_id for candidate in selected}
    omitted = [
        candidate.candidate_id
        for candidate in candidates
        if candidate.candidate_id not in selected_ids
    ]
    return (
        sorted(selected, key=lambda item: item.frame_index),
        sorted(omitted),
    )


def _baseline_preview_graph(graph: GradeGraph) -> GradeGraph:
    preview = graph.model_copy(deep=True)
    for node in preview.nodes:
        if node.type not in {
            NodeType.INPUT_TRANSFORM,
            NodeType.BALANCE,
            NodeType.OUTPUT_TRANSFORM,
        }:
            node.enabled = False
    return preview


def _rgb_statistics(rgb: np.ndarray) -> tuple[float, float, float]:
    normalized = np.asarray(rgb, dtype=np.float32) / (255.0 if rgb.dtype == np.uint8 else 1.0)
    luma = normalized[..., 0] * 0.2126 + normalized[..., 1] * 0.7152 + normalized[..., 2] * 0.0722
    return (
        float(np.mean(luma)),
        float(np.mean(luma >= 0.988)),
        float(np.mean(luma <= 0.02)),
    )


def _composition(
    rgb: np.ndarray,
    *,
    source: Literal["display_preview", "decoded_signal_proxy"],
) -> CompositionSummary:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.2)
    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.sqrt(gradient_x * gradient_x + gradient_y * gradient_y)
    threshold = float(np.percentile(magnitude, 82))
    salient = (magnitude >= max(threshold, 1e-6)).astype(np.uint8)
    components, labels, statistics, centroids = cv2.connectedComponentsWithStats(
        salient,
        connectivity=8,
    )
    height, width = gray.shape
    if components <= 1:
        scale = 0.0
        centroid_x = 0.5
        centroid_y = 0.5
    else:
        component = 1 + int(np.argmax(statistics[1:, cv2.CC_STAT_AREA]))
        scale = float(statistics[component, cv2.CC_STAT_AREA] / max(height * width, 1))
        centroid_x = float(centroids[component, 0] / max(width - 1, 1))
        centroid_y = float(centroids[component, 1] / max(height - 1, 1))
        del labels
    row_energy = np.mean(np.abs(gradient_y), axis=1)
    horizon_y = float(np.argmax(row_energy) / max(height - 1, 1))
    return CompositionSummary(
        method="deterministic-saliency-proxy/v1",
        subject_scale_ratio=float(np.clip(scale, 0, 1)),
        centroid_x=float(np.clip(centroid_x, 0, 1)),
        centroid_y=float(np.clip(centroid_y, 0, 1)),
        horizon_y=float(np.clip(horizon_y, 0, 1)),
        source=source,
    )


def _read_video_rgb(
    capture: cv2.VideoCapture,
    graph: GradeGraph,
    timestamp: float,
    *,
    maximum_edge: int = 320,
) -> np.ndarray:
    frame_index = min(
        max(0, round(timestamp * graph.media.fps)),
        max(0, graph.media.frame_count - 1),
    )
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    success, frame = capture.read()
    if not success:
        raise RuntimeError(f"could not decode frame {frame_index} for evidence analysis")
    height, width = frame.shape[:2]
    scale = min(1.0, maximum_edge / max(height, width))
    if scale < 1:
        frame = cv2.resize(
            frame,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _motion_summary(
    capture: cv2.VideoCapture,
    graph: GradeGraph,
    *,
    start_seconds: float,
    end_seconds: float,
) -> MotionSummary:
    duration = end_seconds - start_seconds
    first_time = start_seconds + duration * 0.25
    second_time = start_seconds + duration * 0.75
    first = _read_video_rgb(capture, graph, first_time)
    second = _read_video_rgb(capture, graph, second_time)
    first_gray = cv2.cvtColor(first, cv2.COLOR_RGB2GRAY)
    second_gray = cv2.cvtColor(second, cv2.COLOR_RGB2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        first_gray,
        second_gray,
        None,
        0.5,
        3,
        21,
        3,
        5,
        1.2,
        0,
    )
    camera_dx = float(np.median(flow[..., 0]))
    camera_dy = float(np.median(flow[..., 1]))
    camera_magnitude = math.hypot(camera_dx, camera_dy)
    residual = np.sqrt((flow[..., 0] - camera_dx) ** 2 + (flow[..., 1] - camera_dy) ** 2)
    residual_p90 = float(np.percentile(residual, 90))
    if camera_magnitude < 0.25 and residual_p90 < 0.5:
        classification = MotionClassification.STATIC
    elif camera_magnitude >= 0.5 and residual_p90 < camera_magnitude:
        classification = MotionClassification.CAMERA
    elif residual_p90 >= 0.75 and camera_magnitude < 0.5:
        classification = MotionClassification.OBJECT
    else:
        classification = MotionClassification.MIXED
    return MotionSummary(
        method="farneback-global-residual/v1",
        classification=classification,
        camera_dx_pixels=camera_dx,
        camera_dy_pixels=camera_dy,
        camera_magnitude=camera_magnitude,
        object_residual_p90=residual_p90,
        first_time_seconds=round(first_time, 6),
        second_time_seconds=round(second_time, 6),
    )


def _decode_audio(
    source: Path,
    *,
    maximum_seconds: float,
) -> _DecodedAudio:
    probe = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return _DecodedAudio(
            status=AudioAvailability.DECODE_FAILED,
            samples=np.empty(0, dtype=np.float32),
            sample_rate=16_000,
            decoded_duration=0.0,
            failure_detail=probe.stderr.strip() or "ffprobe failed",
        )
    try:
        streams = json.loads(probe.stdout).get("streams", [])
    except json.JSONDecodeError as exc:
        return _DecodedAudio(
            status=AudioAvailability.DECODE_FAILED,
            samples=np.empty(0, dtype=np.float32),
            sample_rate=16_000,
            decoded_duration=0.0,
            failure_detail=f"invalid ffprobe JSON: {exc}",
        )
    if not streams:
        return _DecodedAudio(
            status=AudioAvailability.NO_TRACK,
            samples=np.empty(0, dtype=np.float32),
            sample_rate=16_000,
            decoded_duration=0.0,
        )
    sample_rate = 16_000
    command = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
    ]
    if maximum_seconds > 0:
        command.extend(["-t", f"{maximum_seconds:.6f}"])
    command.extend(["-f", "s16le", "pipe:1"])
    decoded = subprocess.run(
        command,
        capture_output=True,
        check=False,
    )
    if decoded.returncode != 0:
        return _DecodedAudio(
            status=AudioAvailability.DECODE_FAILED,
            samples=np.empty(0, dtype=np.float32),
            sample_rate=sample_rate,
            decoded_duration=0.0,
            failure_detail=decoded.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            or "ffmpeg audio decode failed",
        )
    samples = np.frombuffer(decoded.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return _DecodedAudio(
        status=AudioAvailability.AVAILABLE,
        samples=samples,
        sample_rate=sample_rate,
        decoded_duration=len(samples) / sample_rate,
    )


def _audio_summary(
    decoded: _DecodedAudio,
    *,
    start_seconds: float,
    end_seconds: float,
) -> AudioSummary:
    if decoded.status != AudioAvailability.AVAILABLE:
        return AudioSummary(
            status=decoded.status,
            analyzed_duration_seconds=0.0,
            change_points_seconds=[],
            embedding_status=(
                "not_available" if decoded.status == AudioAvailability.NO_TRACK else "disabled"
            ),
            transcription_status="not_requested",
            cloud_uploaded=False,
            failure_detail=decoded.failure_detail,
        )
    start = min(
        len(decoded.samples),
        round(start_seconds * decoded.sample_rate),
    )
    end = min(
        len(decoded.samples),
        round(end_seconds * decoded.sample_rate),
    )
    samples = decoded.samples[start:end]
    duration = len(samples) / decoded.sample_rate
    if not len(samples):
        return AudioSummary(
            status=AudioAvailability.AVAILABLE,
            analyzed_duration_seconds=0.0,
            loudness_dbfs_proxy=-120.0,
            dynamic_range_db=0.0,
            rhythm_change_rate_per_minute=0.0,
            change_points_seconds=[],
            embedding_status="disabled",
            transcription_status="not_requested",
            cloud_uploaded=False,
        )
    rms = float(np.sqrt(np.mean(samples * samples)))
    loudness = 20 * math.log10(max(rms, 1e-6))
    block_size = max(1, round(0.5 * decoded.sample_rate))
    block_db = np.asarray(
        [
            20
            * math.log10(
                max(
                    float(np.sqrt(np.mean(samples[index : index + block_size] ** 2))),
                    1e-6,
                )
            )
            for index in range(0, len(samples), block_size)
        ],
        dtype=np.float64,
    )
    dynamic_range = float(np.percentile(block_db, 95) - np.percentile(block_db, 10))
    differences = np.abs(np.diff(block_db))
    if differences.size:
        median = float(np.median(differences))
        mad = float(np.median(np.abs(differences - median)))
        threshold = max(3.0, median + 2.5 * 1.4826 * mad)
        change_indices = np.flatnonzero(differences >= threshold) + 1
    else:
        change_indices = np.empty(0, dtype=np.int64)
    change_points = [
        round(
            start_seconds + index * block_size / decoded.sample_rate,
            6,
        )
        for index in change_indices
    ]
    change_rate = len(change_points) / max(duration, 1e-6) * 60.0
    return AudioSummary(
        status=AudioAvailability.AVAILABLE,
        analyzed_duration_seconds=duration,
        loudness_dbfs_proxy=loudness,
        dynamic_range_db=dynamic_range,
        rhythm_change_rate_per_minute=change_rate,
        change_points_seconds=change_points,
        embedding_status="disabled",
        transcription_status="not_requested",
        cloud_uploaded=False,
    )


def _contact_sheet(
    paths: list[Path],
    destination: Path,
) -> tuple[int, int]:
    thumbnails: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as source:
            thumbnail = ImageOps.contain(
                source.convert("RGB"),
                (320, 180),
            )
            canvas = Image.new("RGB", (320, 180), "black")
            canvas.paste(
                thumbnail,
                (
                    (320 - thumbnail.width) // 2,
                    (180 - thumbnail.height) // 2,
                ),
            )
            thumbnails.append(canvas)
    columns = min(3, max(1, len(thumbnails)))
    rows = math.ceil(len(thumbnails) / columns)
    sheet = Image.new(
        "RGB",
        (columns * 320, rows * 180),
        "#111111",
    )
    for index, thumbnail in enumerate(thumbnails):
        sheet.paste(
            thumbnail,
            ((index % columns) * 320, (index // columns) * 180),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=92, subsampling=0)
    return sheet.size


def _measurement_reference(
    identifier: str,
    summary: str,
    payload: dict[str, object],
    *,
    scene_id: str | None = None,
    shot_id: str | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=identifier,
        kind=EvidenceKind.MEASUREMENT,
        digest=canonical_sha256(payload),
        summary=summary,
        scene_id=scene_id,
        shot_id=shot_id,
    )


def _technical_baseline(
    graph: GradeGraph,
    *,
    graph_sha: str,
    evidence: list[EvidenceReference],
    statistics: list[PhysicalFrameStatistics],
) -> TechnicalBaseline:
    input_node = next(
        node for node in graph.ordered_nodes() if node.type == NodeType.INPUT_TRANSFORM
    )
    output_node = next(
        node for node in graph.ordered_nodes() if node.type == NodeType.OUTPUT_TRANSFORM
    )
    measurements: list[MeasurementFact] = [
        MeasurementFact(
            metric=TechnicalMetric.FRAME_RATE,
            value=graph.media.fps,
            unit=MetricUnit.FPS,
            uncertainty=0.0,
            valid_sample_ratio=1.0,
            evidence_ids=["measurement:media"],
        ),
        MeasurementFact(
            metric=TechnicalMetric.FRAME_COUNT,
            value=float(graph.media.frame_count),
            unit=MetricUnit.FRAMES,
            uncertainty=0.0,
            valid_sample_ratio=1.0,
            evidence_ids=["measurement:media"],
        ),
    ]
    diagnostics: list[TechnicalDiagnostic] = []
    for shot in graph.shots:
        balance = next(
            (
                node
                for node in graph.nodes
                if node.type == NodeType.BALANCE and node.temporal_scope.shot_id == shot.id
            ),
            None,
        )
        if balance is None:
            continue
        metadata = balance.metadata.get("color_analysis")
        analysis = metadata if isinstance(metadata, dict) else {}
        exposure_meta = analysis.get("exposure")
        exposure = exposure_meta if isinstance(exposure_meta, dict) else {}
        white_balance_meta = analysis.get("white_balance")
        white_balance = white_balance_meta if isinstance(white_balance_meta, dict) else {}
        evidence_id = f"measurement:{shot.id}:balance"
        measurements.extend(
            [
                MeasurementFact(
                    metric=TechnicalMetric.EXPOSURE_EV,
                    value=float(balance.parameters.get("exposure", 0.0)),
                    unit=MetricUnit.EV,
                    uncertainty=float(exposure.get("uncertainty_ev", 0.0)),
                    valid_sample_ratio=float(
                        np.clip(
                            exposure.get("valid_sample_ratio", 0.0),
                            0,
                            1,
                        )
                    ),
                    evidence_ids=[evidence_id],
                ),
                MeasurementFact(
                    metric=TechnicalMetric.WHITE_BALANCE_TEMPERATURE,
                    value=float(balance.parameters.get("temperature", 0.0)),
                    unit=MetricUnit.NORMALIZED,
                    uncertainty=float(white_balance.get("uncertainty", 0.0)),
                    valid_sample_ratio=float(
                        np.clip(
                            white_balance.get("valid_sample_ratio", 0.0),
                            0,
                            1,
                        )
                    ),
                    evidence_ids=[evidence_id],
                ),
                MeasurementFact(
                    metric=TechnicalMetric.WHITE_BALANCE_TINT,
                    value=float(balance.parameters.get("tint", 0.0)),
                    unit=MetricUnit.NORMALIZED,
                    uncertainty=float(white_balance.get("uncertainty", 0.0)),
                    valid_sample_ratio=float(
                        np.clip(
                            white_balance.get("valid_sample_ratio", 0.0),
                            0,
                            1,
                        )
                    ),
                    evidence_ids=[evidence_id],
                ),
            ]
        )
    for item in statistics:
        evidence_id = f"frame:{item.frame_index}"
        for identifier, metric, observed, threshold in (
            (
                "highlight-clipping",
                TechnicalMetric.HIGHLIGHT_CLIPPING_RATIO,
                item.encoded_highlight_ratio,
                0.06,
            ),
            (
                "shadow-clipping",
                TechnicalMetric.SHADOW_CLIPPING_RATIO,
                item.encoded_shadow_ratio,
                0.20,
            ),
        ):
            if observed > threshold:
                diagnostics.append(
                    TechnicalDiagnostic(
                        diagnostic_id=(f"diagnostic:{identifier}:{item.frame_index}"),
                        severity=DiagnosticSeverity.WARNING,
                        metric=metric,
                        observed=observed,
                        threshold=threshold,
                        detail=(
                            "Encoded source signal crosses the conservative "
                            f"{identifier} threshold."
                        ),
                        evidence_ids=[evidence_id],
                    )
                )
    encoded_clipped = any(
        item.encoded_highlight_ratio > 0.06 or item.encoded_shadow_ratio > 0.20
        for item in statistics
    )
    return TechnicalBaseline(
        graph_digest=graph_sha,
        color_pipeline={
            "input_color_space": graph.media.input_color_space.value,
            "working_color_space": graph.working_color_space.value,
            "output_color_space": graph.output_color_space.value,
            "renderer_version": graph.renderer_version,
            "input_transform_digest": canonical_sha256(input_node.model_dump(mode="json")),
            "output_transform_digest": canonical_sha256(output_node.model_dump(mode="json")),
            "information_already_clipped": encoded_clipped,
        },
        measurements=measurements,
        diagnostics=diagnostics,
        immutable_fact_ids=[
            "fact:input-color-space",
            "fact:working-color-space",
            "fact:output-color-space",
            "fact:renderer-version",
            "fact:frame-rate",
            "fact:frame-count",
        ],
    )


def _scene_labels(
    graph: GradeGraph,
    shot_ids: list[str],
) -> dict[str, str]:
    raw = graph.metadata.get("scene_analyses")
    analyses = raw if isinstance(raw, list) else []
    labels: dict[str, str] = {}
    for shot_id in shot_ids:
        shot = next(item for item in graph.shots if item.id == shot_id)
        if shot.index >= len(analyses):
            continue
        analysis = analyses[shot.index]
        if not isinstance(analysis, dict):
            continue
        for category in ("terrain", "lighting", "risk"):
            value = analysis.get(category)
            if isinstance(value, dict) and isinstance(value.get("label"), str):
                labels[f"{shot_id}:{category}"] = str(value["label"])
    return labels


def build_project_evidence_pack(
    *,
    source: str | Path,
    graph: GradeGraph,
    output_root: str | Path,
    backend: ComputeBackend,
    budget: ContextBudget,
    created_at: datetime | None = None,
) -> ProjectEvidenceBuildResult:
    resolved_source = Path(source).resolve()
    if not resolved_source.is_file():
        raise FileNotFoundError(resolved_source)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    graph_sha = graph_digest(graph)
    selected, omitted = _select_frame_candidates(
        graph,
        budget.maximum_images,
    )
    preview_graph = _baseline_preview_graph(graph)
    engine = GradeRenderEngine(backend)
    evidence: list[EvidenceReference] = []
    artifacts: list[EvidenceArtifact] = []
    frame_statistics: list[PhysicalFrameStatistics] = []
    paths_by_shot: dict[str, list[Path]] = {shot.id: [] for shot in graph.shots}
    ids_by_shot: dict[str, list[str]] = {shot.id: [] for shot in graph.shots}
    compositions: dict[str, list[CompositionSummary]] = {shot.id: [] for shot in graph.shots}
    scene_by_shot = {shot.id: shot.scene_id for shot in graph.shots}
    for candidate in selected:
        raw_path = root / "source-extracts" / f"{candidate.shot_id}-{candidate.frame_index:08d}.jpg"
        display_path = (
            root / "display-frames" / f"{candidate.shot_id}-{candidate.frame_index:08d}.jpg"
        )
        extract_frame(
            resolved_source,
            candidate.time_seconds,
            raw_path,
            maximum_width=budget.maximum_image_edge,
            high_quality=True,
        )
        engine.render_image(
            raw_path,
            display_path,
            preview_graph,
            time_seconds=candidate.time_seconds,
        )
        with Image.open(raw_path) as source_image:
            encoded_rgb = np.asarray(
                source_image.convert("RGB"),
                dtype=np.uint8,
            )
        with Image.open(display_path) as display_image:
            display_rgb = np.asarray(
                display_image.convert("RGB"),
                dtype=np.uint8,
            )
            width, height = display_image.size
        encoded_mean, encoded_high, encoded_shadow = _rgb_statistics(encoded_rgb)
        display_mean, display_high, display_shadow = _rgb_statistics(display_rgb)
        evidence_id = f"frame:{candidate.frame_index}"
        digest = _sha256_file(display_path)
        evidence.append(
            EvidenceReference(
                evidence_id=evidence_id,
                kind=EvidenceKind.FRAME,
                digest=digest,
                summary=(
                    f"Display-transformed baseline preview for "
                    f"{candidate.shot_id} at {candidate.time_seconds:.3f}s."
                ),
                frame_index=candidate.frame_index,
                scene_id=scene_by_shot[candidate.shot_id],
                shot_id=candidate.shot_id,
            )
        )
        artifacts.append(
            EvidenceArtifact(
                evidence_id=evidence_id,
                kind=EvidenceKind.FRAME,
                relative_path=display_path.relative_to(root).as_posix(),
                sha256=digest,
                width=width,
                height=height,
                display_transform_applied=True,
                model_input_allowed=True,
                source_color_space=graph.media.input_color_space.value,
                display_color_space=ColorSpace.SRGB.value,
                physical_statistics_separate=True,
            )
        )
        frame_statistics.append(
            PhysicalFrameStatistics(
                frame_index=candidate.frame_index,
                time_seconds=candidate.time_seconds,
                encoded_mean_luma=encoded_mean,
                display_mean_luma=display_mean,
                encoded_highlight_ratio=encoded_high,
                encoded_shadow_ratio=encoded_shadow,
                display_highlight_ratio=display_high,
                display_shadow_ratio=display_shadow,
            )
        )
        paths_by_shot[candidate.shot_id].append(display_path)
        ids_by_shot[candidate.shot_id].append(evidence_id)
        compositions[candidate.shot_id].append(_composition(display_rgb, source="display_preview"))

    capture = cv2.VideoCapture(str(resolved_source))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {resolved_source}")
    decoded_audio = _decode_audio(
        resolved_source,
        maximum_seconds=min(
            graph.media.duration_seconds,
            budget.maximum_audio_seconds,
        ),
    )
    motion_by_shot: dict[str, MotionSummary] = {}
    audio_by_shot: dict[str, AudioSummary] = {}
    try:
        for shot in graph.shots:
            motion = _motion_summary(
                capture,
                graph,
                start_seconds=shot.time_range.start_seconds,
                end_seconds=shot.time_range.end_seconds,
            )
            motion_by_shot[shot.id] = motion
            if not compositions[shot.id]:
                midpoint = (shot.time_range.start_seconds + shot.time_range.end_seconds) * 0.5
                decoded_rgb = _read_video_rgb(
                    capture,
                    graph,
                    midpoint,
                )
                compositions[shot.id].append(
                    _composition(
                        decoded_rgb,
                        source="decoded_signal_proxy",
                    )
                )
            audio_by_shot[shot.id] = _audio_summary(
                decoded_audio,
                start_seconds=shot.time_range.start_seconds,
                end_seconds=shot.time_range.end_seconds,
            )
    finally:
        capture.release()

    evidence.append(
        _measurement_reference(
            "measurement:media",
            "Container-declared frame rate and frame count.",
            {
                "fps": graph.media.fps,
                "frame_count": graph.media.frame_count,
                "duration_seconds": graph.media.duration_seconds,
            },
        )
    )
    for shot in graph.shots:
        balance = next(
            (
                node
                for node in graph.nodes
                if node.type == NodeType.BALANCE and node.temporal_scope.shot_id == shot.id
            ),
            None,
        )
        measurement_id = f"measurement:{shot.id}:balance"
        evidence.append(
            _measurement_reference(
                measurement_id,
                f"Physical exposure and white-balance baseline for {shot.id}.",
                (
                    {
                        "parameters": balance.parameters,
                        "metadata": balance.metadata.get("color_analysis"),
                    }
                    if balance is not None
                    else {"status": "missing_balance"}
                ),
                scene_id=shot.scene_id,
                shot_id=shot.id,
            )
        )
        motion = motion_by_shot[shot.id]
        motion_id = f"motion:{shot.id}"
        evidence.append(
            EvidenceReference(
                evidence_id=motion_id,
                kind=EvidenceKind.TIME_RANGE,
                digest=canonical_sha256(motion),
                summary=(f"Deterministic camera/object motion summary for {shot.id}."),
                time_range=TimeSpan(
                    start_seconds=shot.time_range.start_seconds,
                    end_seconds=shot.time_range.end_seconds,
                ),
                scene_id=shot.scene_id,
                shot_id=shot.id,
            )
        )
        audio = audio_by_shot[shot.id]
        audio_id = f"audio:{shot.id}"
        evidence.append(
            EvidenceReference(
                evidence_id=audio_id,
                kind=EvidenceKind.AUDIO,
                digest=canonical_sha256(audio),
                summary=(
                    f"Audio availability, loudness, dynamics, and rhythm "
                    f"summary for {shot.id}; status={audio.status.value}."
                ),
                time_range=TimeSpan(
                    start_seconds=shot.time_range.start_seconds,
                    end_seconds=shot.time_range.end_seconds,
                ),
                scene_id=shot.scene_id,
                shot_id=shot.id,
            )
        )

    contact_artifacts: list[EvidenceArtifact] = []
    for scene in graph.scenes:
        scene_paths = [path for shot_id in scene.shot_ids for path in paths_by_shot[shot_id]]
        if not scene_paths:
            continue
        contact_path = root / "contact-sheets" / f"{scene.id}.jpg"
        width, height = _contact_sheet(scene_paths, contact_path)
        contact_id = f"contact:{scene.id}"
        digest = _sha256_file(contact_path)
        evidence.append(
            EvidenceReference(
                evidence_id=contact_id,
                kind=EvidenceKind.CONTACT_SHEET,
                digest=digest,
                summary=(f"Chronological display-transformed contact sheet for {scene.id}."),
                scene_id=scene.id,
            )
        )
        contact_artifacts.append(
            EvidenceArtifact(
                evidence_id=contact_id,
                kind=EvidenceKind.CONTACT_SHEET,
                relative_path=contact_path.relative_to(root).as_posix(),
                sha256=digest,
                width=width,
                height=height,
                display_transform_applied=True,
                model_input_allowed=False,
                source_color_space=graph.media.input_color_space.value,
                display_color_space=ColorSpace.SRGB.value,
                physical_statistics_separate=True,
            )
        )
    artifacts.extend(contact_artifacts)

    shot_packets: list[ShotEvidencePacket] = []
    for shot in graph.shots:
        frame_ids = ids_by_shot[shot.id]
        measurement_id = f"measurement:{shot.id}:balance"
        motion_id = f"motion:{shot.id}"
        audio_id = f"audio:{shot.id}"
        trace_ids = [
            *frame_ids,
            measurement_id,
            motion_id,
            audio_id,
        ]
        shot_packets.append(
            ShotEvidencePacket(
                shot_id=shot.id,
                scene_id=shot.scene_id,
                time_range=TimeSpan(
                    start_seconds=shot.time_range.start_seconds,
                    end_seconds=shot.time_range.end_seconds,
                ),
                display_frame_evidence_ids=frame_ids,
                measurement_evidence_ids=[measurement_id],
                composition=compositions[shot.id][0],
                motion=motion_by_shot[shot.id],
                audio=audio_by_shot[shot.id],
                supporting_evidence_ids=trace_ids,
                counterevidence_ids=[motion_id, measurement_id],
            )
        )
    scene_synopses: list[SceneEvidenceSynopsis] = []
    for scene in graph.scenes:
        scene_packets = [packet for packet in shot_packets if packet.scene_id == scene.id]
        supporting = [
            evidence_id
            for packet in scene_packets
            for evidence_id in packet.supporting_evidence_ids
        ]
        counter = [
            evidence_id for packet in scene_packets for evidence_id in packet.counterevidence_ids
        ]
        motion_labels = sorted({packet.motion.classification.value for packet in scene_packets})
        audio_labels = sorted({packet.audio.status.value for packet in scene_packets})
        scene_synopses.append(
            SceneEvidenceSynopsis(
                scene_id=scene.id,
                shot_ids=scene.shot_ids,
                synopsis=(
                    f"{len(scene_packets)} shots; deterministic motion classes "
                    f"{motion_labels}; audio states {audio_labels}. "
                    "Model-observed labels are retained as observations, "
                    "not converted into a fixed style."
                ),
                observed_model_labels=_scene_labels(
                    graph,
                    scene.shot_ids,
                ),
                supporting_evidence_ids=sorted(set(supporting)),
                counterevidence_ids=sorted(set(counter)),
            )
        )
    all_supporting = sorted(
        {evidence_id for scene in scene_synopses for evidence_id in scene.supporting_evidence_ids}
    )
    all_counter = sorted(
        {evidence_id for scene in scene_synopses for evidence_id in scene.counterevidence_ids}
    )
    project_synopsis = ProjectEvidenceSynopsis(
        synopsis=(
            f"{len(graph.scenes)} scenes and {len(graph.shots)} shots. "
            "The pack keeps display previews, physical measurements, motion, "
            "composition, and audio evidence in separate auditable channels."
        ),
        scene_ids=[scene.id for scene in graph.scenes],
        supporting_evidence_ids=all_supporting,
        counterevidence_ids=all_counter,
    )
    bundle = ProjectEvidenceBundle(
        graph_digest=graph_sha,
        source_media_sha256=_sha256_file(resolved_source),
        preview_mode=("input_display_plus_technical_balance_no_creative_look"),
        physical_statistics_separate=True,
        artifacts=artifacts,
        frame_statistics=frame_statistics,
        shots=shot_packets,
        scenes=scene_synopses,
        project=project_synopsis,
        budget=budget,
        model_input_evidence_ids=[f"frame:{candidate.frame_index}" for candidate in selected],
        omitted_candidate_ids=omitted,
        omission_reason=(
            "Deterministic sampling enforced maximum_images; omitted IDs "
            "remain recorded and no silent truncation occurred."
            if omitted
            else None
        ),
    )
    bundle_digest = canonical_sha256(bundle)
    baseline_payload = _technical_baseline(
        graph,
        graph_sha=graph_sha,
        evidence=evidence,
        statistics=frame_statistics,
    )
    baseline = sign_agent_asset(
        project_id=graph.project_id,
        input_digest=graph_sha,
        payload=baseline_payload,
        prompt_version="deterministic-evidence/v1",
        model_id="deterministic",
        model_revision=EVIDENCE_BUILDER_VERSION,
        tool_versions={
            "evidence_builder": EVIDENCE_BUILDER_VERSION,
            "renderer": graph.renderer_version,
            "opencv": cv2.__version__,
        },
        created_at=created_at,
    )
    context = ProjectContextPack(
        technical_baseline_asset_id=baseline.asset_id,
        technical_baseline_sha256=baseline.sha256,
        graph_digest=graph_sha,
        evidence_bundle_schema_version=EVIDENCE_BUNDLE_VERSION,
        evidence_bundle_digest=bundle_digest,
        allowed_scene_ids=[scene.id for scene in graph.scenes],
        allowed_shot_ids=[shot.id for shot in graph.shots],
        evidence=evidence,
        budget=budget,
        omitted_evidence_ids=omitted,
        omission_reason=bundle.omission_reason,
    )
    (root / "evidence-bundle.json").write_text(
        bundle.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "technical-baseline.json").write_text(
        baseline.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "project-context-pack.json").write_text(
        context.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return ProjectEvidenceBuildResult(
        technical_baseline=baseline,
        context_pack=context,
        evidence_bundle=bundle,
        evidence_bundle_digest=bundle_digest,
        artifact_root=root,
    )
