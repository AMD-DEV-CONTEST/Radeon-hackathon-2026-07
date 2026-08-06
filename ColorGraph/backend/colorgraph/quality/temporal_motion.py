from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.domain.grade_graph import GradeGraph

TEMPORAL_METRIC_VERSION = "colorgraph.motion-compensated-temporal/v1"
_NATURAL_MOTION_TARGETS = {
    "cloud",
    "clouds",
    "lake",
    "ocean",
    "river",
    "sea",
    "sky",
    "water",
}


class TemporalClassification(StrEnum):
    STABLE = "stable"
    CAMERA_OR_OBJECT_MOTION = "camera_or_object_motion"
    CLOUD_OR_WATER_MOTION = "cloud_or_water_motion"
    SOURCE_LUMINANCE_CHANGE = "source_luminance_change"
    SOURCE_EXPOSURE_JUMP = "source_exposure_jump"
    GRADE_INDUCED_FLICKER = "grade_induced_flicker"
    HARD_CUT = "hard_cut"


class TemporalRegionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    area_ratio: float = Field(ge=0, le=1)
    mean_delta: float = Field(ge=0)
    p95_delta: float = Field(ge=0)
    overlapping_mask_targets: list[str] = Field(default_factory=list)


class MaskTemporalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    target: str
    raw_mae: float = Field(ge=0)
    motion_compensated_mae: float = Field(ge=0)
    boundary_mae: float = Field(ge=0)
    jitter_score: float = Field(ge=0)
    motion_reduction_ratio: float = Field(ge=0, le=1)


class TemporalTransitionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_frame_index: int = Field(ge=0)
    frame_index: int = Field(ge=0)
    time_seconds: float = Field(ge=0)
    analysis_width: int = Field(gt=0)
    analysis_height: int = Field(gt=0)
    classification: TemporalClassification
    confidence: float = Field(ge=0, le=1)
    excluded: bool = False
    raw_source_mean_delta: float = Field(ge=0)
    raw_output_mean_delta: float = Field(ge=0)
    source_motion_residual_p95: float = Field(ge=0)
    output_motion_residual_p95: float = Field(ge=0)
    grade_flicker_score: float = Field(ge=0)
    source_exposure_stops: float
    exposure_uniformity: float = Field(ge=0, le=1)
    camera_motion_x: float
    camera_motion_y: float
    motion_p95_pixels: float = Field(ge=0)
    nonrigid_motion_p95_pixels: float = Field(ge=0)
    valid_flow_ratio: float = Field(ge=0, le=1)
    regions: list[TemporalRegionEvidence] = Field(default_factory=list)
    masks: list[MaskTemporalEvidence] = Field(default_factory=list)


class TemporalQualityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "colorgraph.temporal-evidence/v1"
    metric_version: str = TEMPORAL_METRIC_VERSION
    sampled_frames: int = Field(ge=0)
    analyzed_transitions: int = Field(ge=0)
    excluded_cut_transitions: int = Field(ge=0)
    flicker_p95: float = Field(ge=0)
    raw_flicker_p95: float = Field(ge=0)
    mask_jitter_p95: float = Field(ge=0)
    raw_mask_jitter_p95: float = Field(ge=0)
    mask_observations: int = Field(ge=0)
    raw_flagged_transitions: int = Field(ge=0)
    compensated_flagged_transitions: int = Field(ge=0)
    suppressed_source_change_transitions: int = Field(ge=0)
    mean_valid_flow_ratio: float = Field(ge=0, le=1)
    transitions: list[TemporalTransitionEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TemporalAnalysisConfig:
    analysis_width: int = 320
    flicker_warning: float = 0.035
    exposure_jump_stops: float = 0.20
    exposure_uniformity: float = 0.55
    source_change_threshold: float = 0.04
    motion_threshold_pixels: float = 0.75
    region_threshold: float = 0.02
    maximum_regions: int = 8

    def __post_init__(self) -> None:
        if self.analysis_width < 32:
            raise ValueError("analysis_width must be at least 32 pixels")
        if self.maximum_regions <= 0:
            raise ValueError("maximum_regions must be positive")


@dataclass(slots=True)
class _Alignment:
    map_x: np.ndarray
    map_y: np.ndarray
    backward_flow: np.ndarray
    valid: np.ndarray


def _normalized_plane(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.dtype == np.uint8:
        normalized = array.astype(np.float32) / 255.0
    elif array.dtype == np.uint16:
        normalized = array.astype(np.float32) / 65535.0
    elif np.issubdtype(array.dtype, np.floating):
        normalized = array.astype(np.float32)
    else:
        raise TypeError(f"unsupported frame dtype {array.dtype}")
    if not np.isfinite(normalized).all():
        raise ValueError("temporal analysis frames must contain only finite values")
    return np.clip(normalized, 0.0, 1.0)


def _frame_luma(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    normalized = _normalized_plane(frame)
    if normalized.ndim == 2:
        luma = normalized
    elif normalized.ndim == 3 and normalized.shape[2] >= 3:
        bgr = normalized[..., :3]
        luma = bgr[..., 2] * 0.2126 + bgr[..., 1] * 0.7152 + bgr[..., 0] * 0.0722
    else:
        raise ValueError(f"expected HxW or HxWx3 frame, got {normalized.shape}")
    height, width = luma.shape
    target_width = min(width, analysis_width)
    target_height = max(1, round(height * target_width / width))
    if (target_width, target_height) != (width, height):
        luma = cv2.resize(
            luma,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
    return np.ascontiguousarray(luma, dtype=np.float32)


def _mask_plane(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    normalized = _normalized_plane(mask)
    if normalized.ndim == 3:
        normalized = normalized[..., 0]
    if normalized.ndim != 2:
        raise ValueError(f"expected a single-channel mask, got {normalized.shape}")
    if normalized.shape != shape:
        normalized = cv2.resize(
            normalized,
            (shape[1], shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
    return np.ascontiguousarray(normalized, dtype=np.float32)


def _flow(
    previous: np.ndarray,
    current: np.ndarray,
    initial_dx: float,
    initial_dy: float,
) -> np.ndarray:
    initial = np.empty((*previous.shape, 2), dtype=np.float32)
    initial[..., 0] = initial_dx
    initial[..., 1] = initial_dy
    return cv2.calcOpticalFlowFarneback(
        np.round(previous * 255).astype(np.uint8),
        np.round(current * 255).astype(np.uint8),
        initial,
        pyr_scale=0.5,
        levels=4,
        winsize=25,
        iterations=4,
        poly_n=7,
        poly_sigma=1.5,
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW | cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
    )


def _alignment(previous: np.ndarray, current: np.ndarray) -> _Alignment:
    shift, response = cv2.phaseCorrelate(previous, current)
    initial_dx, initial_dy = shift if response >= 0.03 else (0.0, 0.0)
    height, width = previous.shape
    if abs(initial_dx) > width * 0.45 or abs(initial_dy) > height * 0.45:
        initial_dx, initial_dy = 0.0, 0.0
    grid_y, grid_x = np.mgrid[:height, :width].astype(np.float32)
    if initial_dx or initial_dy:
        global_previous = cv2.remap(
            previous,
            grid_x - initial_dx,
            grid_y - initial_dy,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        global_current = cv2.remap(
            current,
            grid_x + initial_dx,
            grid_y + initial_dy,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        backward = _flow(current, global_previous, 0.0, 0.0)
        backward[..., 0] -= initial_dx
        backward[..., 1] -= initial_dy
        forward = _flow(previous, global_current, 0.0, 0.0)
        forward[..., 0] += initial_dx
        forward[..., 1] += initial_dy
    else:
        forward = _flow(previous, current, 0.0, 0.0)
        backward = _flow(current, previous, 0.0, 0.0)
    map_x = grid_x + backward[..., 0]
    map_y = grid_y + backward[..., 1]
    inside = (map_x >= 0) & (map_x <= width - 1) & (map_y >= 0) & (map_y <= height - 1)
    sampled_forward = cv2.remap(
        forward,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    consistency = np.linalg.norm(backward + sampled_forward, axis=2)
    magnitude = np.linalg.norm(backward, axis=2)
    valid = inside & (consistency <= 1.5 + magnitude * 0.05)
    if valid.mean() < 0.25:
        valid = inside
    return _Alignment(
        map_x=map_x,
        map_y=map_y,
        backward_flow=backward,
        valid=valid,
    )


def _warp(previous: np.ndarray, alignment: _Alignment) -> np.ndarray:
    return cv2.remap(
        previous,
        alignment.map_x,
        alignment.map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )


def _percentile(values: np.ndarray, valid: np.ndarray, percentile: float) -> float:
    selected = np.asarray(values)[valid]
    return float(np.percentile(selected, percentile)) if selected.size else 0.0


def _robust_temporal_slope(
    source_delta: np.ndarray,
    output_delta: np.ndarray,
    valid: np.ndarray,
) -> float:
    x = source_delta[valid]
    y = output_delta[valid]
    useful = np.abs(x) >= 0.004
    if useful.sum() < 64:
        return 1.0
    x = x[useful]
    y = y[useful]
    cutoff = float(np.percentile(np.abs(x), 95))
    central = np.abs(x) <= max(cutoff, 0.004)
    denominator = float(np.dot(x[central], x[central]))
    if denominator <= 1e-9:
        return 1.0
    return float(np.clip(np.dot(x[central], y[central]) / denominator, 0.20, 4.0))


def _expected_static_grade_delta(
    previous_source: np.ndarray,
    current_source: np.ndarray,
    previous_output: np.ndarray,
    source_delta: np.ndarray,
    output_delta: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    source_values = previous_source[valid]
    output_values = previous_output[valid]
    if source_values.size < 256:
        slope = _robust_temporal_slope(source_delta, output_delta, valid)
        return source_delta * slope
    bin_indices = np.minimum((source_values * 32).astype(np.int32), 31)
    point_source: list[float] = []
    point_output: list[float] = []
    minimum_support = max(16, source_values.size // 2048)
    for bin_index in range(32):
        selected = bin_indices == bin_index
        if selected.sum() < minimum_support:
            continue
        point_source.append(float(np.median(source_values[selected])))
        point_output.append(float(np.median(output_values[selected])))
    if len(point_source) < 4:
        slope = _robust_temporal_slope(source_delta, output_delta, valid)
        return source_delta * slope
    x = np.asarray(point_source, dtype=np.float32)
    y = np.asarray(point_output, dtype=np.float32)

    def interpolate(values: np.ndarray) -> np.ndarray:
        predicted = np.interp(values, x, y)
        below = values < x[0]
        above = values > x[-1]
        low_slope = (y[1] - y[0]) / max(float(x[1] - x[0]), 1e-6)
        high_slope = (y[-1] - y[-2]) / max(float(x[-1] - x[-2]), 1e-6)
        predicted[below] = y[0] + (values[below] - x[0]) * low_slope
        predicted[above] = y[-1] + (values[above] - x[-1]) * high_slope
        return np.clip(predicted, 0.0, 1.0)

    predicted_previous = interpolate(previous_source)
    predicted_current = interpolate(current_source)
    return np.asarray(predicted_current - predicted_previous, dtype=np.float32)


def _overlapping_targets(
    component: np.ndarray,
    masks: Mapping[str, np.ndarray],
    mask_targets: Mapping[str, str],
) -> list[str]:
    targets: set[str] = set()
    area = int(component.sum())
    if area == 0:
        return []
    for asset_id, mask in masks.items():
        overlap = float(mask[component].mean()) if component.any() else 0.0
        if overlap >= 0.20:
            targets.add(mask_targets.get(asset_id, asset_id))
    return sorted(targets)


def _regions(
    delta: np.ndarray,
    *,
    kind: str,
    valid: np.ndarray,
    current_masks: Mapping[str, np.ndarray],
    mask_targets: Mapping[str, str],
    config: TemporalAnalysisConfig,
) -> list[TemporalRegionEvidence]:
    selected = delta[valid]
    if selected.size == 0 or float(selected.max()) < config.region_threshold:
        return []
    threshold = max(
        config.region_threshold,
        float(np.percentile(selected, 85)),
    )
    binary = ((delta >= threshold) & valid).astype(np.uint8)
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    minimum_area = max(9, round(delta.size * 0.002))
    candidates: list[tuple[float, TemporalRegionEvidence]] = []
    for label_index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label_index])
        if area < minimum_area:
            continue
        component = labels == label_index
        values = delta[component]
        evidence = TemporalRegionEvidence(
            kind=kind,
            x=x,
            y=y,
            width=width,
            height=height,
            area_ratio=area / delta.size,
            mean_delta=float(values.mean()),
            p95_delta=float(np.percentile(values, 95)),
            overlapping_mask_targets=_overlapping_targets(
                component,
                current_masks,
                mask_targets,
            ),
        )
        candidates.append((evidence.p95_delta * evidence.area_ratio, evidence))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in candidates[: config.maximum_regions]]


def _mask_evidence(
    previous_masks: Mapping[str, np.ndarray],
    current_masks: Mapping[str, np.ndarray],
    mask_targets: Mapping[str, str],
    alignment: _Alignment,
) -> list[MaskTemporalEvidence]:
    evidence: list[MaskTemporalEvidence] = []
    height, width = alignment.valid.shape
    grid_y, grid_x = np.mgrid[:height, :width].astype(np.float32)
    for asset_id in sorted(previous_masks.keys() & current_masks.keys()):
        previous = previous_masks[asset_id]
        current = current_masks[asset_id]
        current_binary = (current >= 0.5).astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        boundary = cv2.morphologyEx(
            current_binary,
            cv2.MORPH_GRADIENT,
            kernel,
        ).astype(bool)
        motion_support = boundary & alignment.valid
        if motion_support.sum() < 16:
            motion_support = (current >= 0.1) & alignment.valid
        if motion_support.sum() < 16:
            motion_support = alignment.valid
        support_flow = alignment.backward_flow[motion_support]
        local_motion = np.median(support_flow, axis=0)
        local_dispersion = float(
            np.percentile(
                np.linalg.norm(support_flow - local_motion, axis=1),
                75,
            )
        )
        target = mask_targets.get(asset_id, asset_id)
        use_camera_motion = target.casefold() in _NATURAL_MOTION_TARGETS or local_dispersion > 0.50
        selected_motion = (
            np.median(alignment.backward_flow[alignment.valid], axis=0)
            if use_camera_motion
            else local_motion
        )
        mask_dx = float(selected_motion[0])
        mask_dy = float(selected_motion[1])
        map_x = grid_x + mask_dx
        map_y = grid_y + mask_dy
        valid = (map_x >= 0) & (map_x <= width - 1) & (map_y >= 0) & (map_y <= height - 1)
        rigid_alignment = _Alignment(
            map_x=map_x,
            map_y=map_y,
            backward_flow=np.broadcast_to(
                np.array([mask_dx, mask_dy], dtype=np.float32),
                (*current.shape, 2),
            ),
            valid=valid,
        )
        warped = _warp(previous, rigid_alignment)
        raw_mae = float(np.abs(current - previous).mean())
        compensated_delta = np.abs(current - warped)
        compensated_mae = float(compensated_delta[valid].mean()) if valid.any() else 0.0
        warped_binary = (warped >= 0.5).astype(np.uint8)
        boundary = (
            cv2.morphologyEx(current_binary, cv2.MORPH_GRADIENT, kernel)
            | cv2.morphologyEx(warped_binary, cv2.MORPH_GRADIENT, kernel)
        ).astype(bool)
        boundary &= valid
        boundary_mae = float(compensated_delta[boundary].mean()) if boundary.any() else 0.0
        jitter_score = max(compensated_mae, boundary_mae * 0.5)
        reduction = (
            float(np.clip(1 - compensated_mae / raw_mae, 0.0, 1.0)) if raw_mae > 1e-8 else 0.0
        )
        evidence.append(
            MaskTemporalEvidence(
                asset_id=asset_id,
                target=target,
                raw_mae=raw_mae,
                motion_compensated_mae=compensated_mae,
                boundary_mae=boundary_mae,
                jitter_score=jitter_score,
                motion_reduction_ratio=reduction,
            )
        )
    return evidence


def _hard_cut_evidence(
    previous_frame_index: int,
    frame_index: int,
    fps: float,
    shape: tuple[int, int],
) -> TemporalTransitionEvidence:
    return TemporalTransitionEvidence(
        previous_frame_index=previous_frame_index,
        frame_index=frame_index,
        time_seconds=frame_index / fps,
        analysis_width=shape[1],
        analysis_height=shape[0],
        classification=TemporalClassification.HARD_CUT,
        confidence=1.0,
        excluded=True,
        raw_source_mean_delta=0.0,
        raw_output_mean_delta=0.0,
        source_motion_residual_p95=0.0,
        output_motion_residual_p95=0.0,
        grade_flicker_score=0.0,
        source_exposure_stops=0.0,
        exposure_uniformity=0.0,
        camera_motion_x=0.0,
        camera_motion_y=0.0,
        motion_p95_pixels=0.0,
        nonrigid_motion_p95_pixels=0.0,
        valid_flow_ratio=0.0,
    )


def _transition(
    previous_source: np.ndarray,
    current_source: np.ndarray,
    previous_output: np.ndarray,
    current_output: np.ndarray,
    *,
    previous_frame_index: int,
    frame_index: int,
    fps: float,
    previous_masks: Mapping[str, np.ndarray],
    current_masks: Mapping[str, np.ndarray],
    mask_targets: Mapping[str, str],
    config: TemporalAnalysisConfig,
) -> TemporalTransitionEvidence:
    alignment = _alignment(previous_source, current_source)
    valid = alignment.valid
    warped_source = _warp(previous_source, alignment)
    warped_output = _warp(previous_output, alignment)
    source_delta = current_source - warped_source
    output_delta = current_output - warped_output
    expected_grade_delta = _expected_static_grade_delta(
        warped_source,
        current_source,
        warped_output,
        source_delta,
        output_delta,
        valid,
    )
    grade_residual = output_delta - expected_grade_delta
    grade_median = float(np.median(grade_residual[valid])) if valid.any() else 0.0
    grade_absolute = np.abs(grade_residual)
    grade_regions = _regions(
        grade_absolute,
        kind="grade_delta",
        valid=valid,
        current_masks=current_masks,
        mask_targets=mask_targets,
        config=config,
    )
    local_grade_score = max(
        (region.p95_delta for region in grade_regions),
        default=0.0,
    )
    grade_score = max(abs(grade_median), local_grade_score)

    epsilon = 1 / 1024
    exposure_pixels = (
        valid
        & (warped_source >= 0.02)
        & (warped_source <= 0.98)
        & (current_source >= 0.02)
        & (current_source <= 0.98)
    )
    log_ratio = np.log2((current_source + epsilon) / (warped_source + epsilon))
    source_exposure = float(np.median(log_ratio[exposure_pixels])) if exposure_pixels.any() else 0.0
    exposure_uniformity = (
        float((np.abs(log_ratio[exposure_pixels] - source_exposure) <= 0.12).mean())
        if exposure_pixels.any()
        else 0.0
    )
    exposure_corrected_previous = np.clip(
        warped_source * (2.0**source_exposure),
        0.0,
        1.0,
    )
    source_change_map = np.abs(current_source - exposure_corrected_previous)
    source_change_p95 = _percentile(source_change_map, valid, 95)
    output_motion_p95 = _percentile(np.abs(output_delta), valid, 95)

    flow = alignment.backward_flow
    camera_x = float(np.median(flow[..., 0][valid])) if valid.any() else 0.0
    camera_y = float(np.median(flow[..., 1][valid])) if valid.any() else 0.0
    flow_magnitude = np.linalg.norm(flow, axis=2)
    motion_p95 = _percentile(flow_magnitude, valid, 95)
    nonrigid_map = np.linalg.norm(
        flow - np.array([camera_x, camera_y], dtype=np.float32),
        axis=2,
    )
    nonrigid_p95 = _percentile(nonrigid_map, valid, 95)

    source_regions = _regions(
        source_change_map,
        kind="source_change",
        valid=valid,
        current_masks=current_masks,
        mask_targets=mask_targets,
        config=config,
    )
    semantic_targets = {
        target.casefold() for region in source_regions for target in region.overlapping_mask_targets
    }
    natural_target_overlap = bool(semantic_targets & _NATURAL_MOTION_TARGETS)
    raw_source_mean = abs(float(current_source.mean() - previous_source.mean()))
    raw_output_mean = abs(float(current_output.mean() - previous_output.mean()))

    if grade_score >= config.flicker_warning:
        classification = TemporalClassification.GRADE_INDUCED_FLICKER
        regions = grade_regions
        confidence = grade_score / max(config.flicker_warning * 2, 1e-6)
    elif (
        abs(source_exposure) >= config.exposure_jump_stops
        and exposure_uniformity >= config.exposure_uniformity
    ):
        classification = TemporalClassification.SOURCE_EXPOSURE_JUMP
        regions = source_regions
        confidence = abs(source_exposure) / max(config.exposure_jump_stops * 2, 1e-6)
    elif (
        source_change_p95 >= config.source_change_threshold
        and motion_p95 >= config.motion_threshold_pixels
    ):
        classification = (
            TemporalClassification.CLOUD_OR_WATER_MOTION
            if natural_target_overlap
            else TemporalClassification.CAMERA_OR_OBJECT_MOTION
        )
        regions = source_regions
        confidence = source_change_p95 / max(config.source_change_threshold * 2, 1e-6)
    elif (
        raw_source_mean >= config.source_change_threshold * 0.5
        and motion_p95 >= config.motion_threshold_pixels
    ):
        classification = TemporalClassification.CAMERA_OR_OBJECT_MOTION
        regions = source_regions
        confidence = motion_p95 / max(config.motion_threshold_pixels * 2, 1e-6)
    elif (
        raw_source_mean >= config.source_change_threshold * 0.5
        or source_change_p95 >= config.source_change_threshold
    ):
        classification = TemporalClassification.SOURCE_LUMINANCE_CHANGE
        regions = source_regions
        confidence = max(
            raw_source_mean / max(config.source_change_threshold, 1e-6),
            source_change_p95 / max(config.source_change_threshold * 2, 1e-6),
        )
    else:
        classification = TemporalClassification.STABLE
        regions = grade_regions or source_regions
        confidence = 1 - max(
            grade_score / max(config.flicker_warning, 1e-6),
            source_change_p95 / max(config.source_change_threshold, 1e-6),
        )

    return TemporalTransitionEvidence(
        previous_frame_index=previous_frame_index,
        frame_index=frame_index,
        time_seconds=frame_index / fps,
        analysis_width=current_source.shape[1],
        analysis_height=current_source.shape[0],
        classification=classification,
        confidence=float(np.clip(confidence, 0.05, 1.0)),
        raw_source_mean_delta=raw_source_mean,
        raw_output_mean_delta=raw_output_mean,
        source_motion_residual_p95=source_change_p95,
        output_motion_residual_p95=output_motion_p95,
        grade_flicker_score=grade_score,
        source_exposure_stops=source_exposure,
        exposure_uniformity=exposure_uniformity,
        camera_motion_x=camera_x,
        camera_motion_y=camera_y,
        motion_p95_pixels=motion_p95,
        nonrigid_motion_p95_pixels=nonrigid_p95,
        valid_flow_ratio=float(valid.mean()),
        regions=regions,
        masks=_mask_evidence(
            previous_masks,
            current_masks,
            mask_targets,
            alignment,
        ),
    )


def _crosses_cut(
    previous_frame_index: int,
    frame_index: int,
    cut_frame_indices: Collection[int],
) -> bool:
    return any(
        previous_frame_index < cut_frame_index <= frame_index
        for cut_frame_index in cut_frame_indices
    )


def _finish_evidence(
    transitions: list[TemporalTransitionEvidence],
    *,
    sampled_frames: int,
    warning_threshold: float,
    warnings: list[str] | None = None,
) -> TemporalQualityEvidence:
    analyzed = [transition for transition in transitions if not transition.excluded]
    flicker_scores = [transition.grade_flicker_score for transition in analyzed]
    raw_flicker_scores = [transition.raw_output_mean_delta for transition in analyzed]
    mask_items = [item for transition in analyzed for item in transition.masks]
    raw_flagged = sum(score >= warning_threshold for score in raw_flicker_scores)
    compensated_flagged = sum(score >= warning_threshold for score in flicker_scores)
    suppressed = sum(
        transition.raw_output_mean_delta >= warning_threshold
        and transition.grade_flicker_score < warning_threshold
        and transition.classification
        in {
            TemporalClassification.CAMERA_OR_OBJECT_MOTION,
            TemporalClassification.CLOUD_OR_WATER_MOTION,
            TemporalClassification.SOURCE_EXPOSURE_JUMP,
            TemporalClassification.SOURCE_LUMINANCE_CHANGE,
        }
        for transition in analyzed
    )
    return TemporalQualityEvidence(
        sampled_frames=sampled_frames,
        analyzed_transitions=len(analyzed),
        excluded_cut_transitions=len(transitions) - len(analyzed),
        flicker_p95=(float(np.percentile(flicker_scores, 95)) if flicker_scores else 0.0),
        raw_flicker_p95=(
            float(np.percentile(raw_flicker_scores, 95)) if raw_flicker_scores else 0.0
        ),
        mask_jitter_p95=(
            float(np.percentile([item.jitter_score for item in mask_items], 95))
            if mask_items
            else 0.0
        ),
        raw_mask_jitter_p95=(
            float(np.percentile([item.raw_mae for item in mask_items], 95)) if mask_items else 0.0
        ),
        mask_observations=len(mask_items),
        raw_flagged_transitions=raw_flagged,
        compensated_flagged_transitions=compensated_flagged,
        suppressed_source_change_transitions=suppressed,
        mean_valid_flow_ratio=(
            float(np.mean([item.valid_flow_ratio for item in analyzed])) if analyzed else 0.0
        ),
        transitions=transitions,
        warnings=list(warnings or []),
    )


def analyze_temporal_frames(
    source_frames: Sequence[np.ndarray],
    output_frames: Sequence[np.ndarray],
    *,
    frame_indices: Sequence[int] | None = None,
    fps: float = 24.0,
    masks: Mapping[str, Sequence[np.ndarray] | np.ndarray] | None = None,
    mask_targets: Mapping[str, str] | None = None,
    cut_frame_indices: Collection[int] = (),
    config: TemporalAnalysisConfig | None = None,
) -> TemporalQualityEvidence:
    """Analyze paired source/output frames without conflating scene and grade changes."""

    if fps <= 0:
        raise ValueError("fps must be positive")
    if len(source_frames) != len(output_frames):
        raise ValueError("source_frames and output_frames must have equal length")
    indices = list(range(len(source_frames))) if frame_indices is None else list(frame_indices)
    if len(indices) != len(source_frames):
        raise ValueError("frame_indices must match the number of frames")
    if any(current <= previous for previous, current in zip(indices, indices[1:], strict=False)):
        raise ValueError("frame_indices must be strictly increasing")
    configuration = config or TemporalAnalysisConfig()
    targets = dict(mask_targets or {})
    mask_sequences = {asset_id: list(sequence) for asset_id, sequence in (masks or {}).items()}
    if any(len(sequence) != len(source_frames) for sequence in mask_sequences.values()):
        raise ValueError("every mask sequence must match the number of frames")
    if not source_frames:
        return _finish_evidence(
            [],
            sampled_frames=0,
            warning_threshold=configuration.flicker_warning,
        )

    prepared_source = [_frame_luma(frame, configuration.analysis_width) for frame in source_frames]
    prepared_output = [_frame_luma(frame, configuration.analysis_width) for frame in output_frames]
    expected_shape = prepared_source[0].shape
    if any(frame.shape != expected_shape for frame in prepared_source + prepared_output):
        raise ValueError("all temporal frames must resolve to the same analysis shape")
    prepared_masks = {
        asset_id: [_mask_plane(mask, expected_shape) for mask in sequence]
        for asset_id, sequence in mask_sequences.items()
    }

    transitions: list[TemporalTransitionEvidence] = []
    for position in range(1, len(indices)):
        previous_index = indices[position - 1]
        current_index = indices[position]
        if _crosses_cut(previous_index, current_index, cut_frame_indices):
            transitions.append(
                _hard_cut_evidence(
                    previous_index,
                    current_index,
                    fps,
                    expected_shape,
                )
            )
            continue
        previous_masks = {
            asset_id: sequence[position - 1] for asset_id, sequence in prepared_masks.items()
        }
        current_masks = {
            asset_id: sequence[position] for asset_id, sequence in prepared_masks.items()
        }
        transitions.append(
            _transition(
                prepared_source[position - 1],
                prepared_source[position],
                prepared_output[position - 1],
                prepared_output[position],
                previous_frame_index=previous_index,
                frame_index=current_index,
                fps=fps,
                previous_masks=previous_masks,
                current_masks=current_masks,
                mask_targets=targets,
                config=configuration,
            )
        )
    return _finish_evidence(
        transitions,
        sampled_frames=len(source_frames),
        warning_threshold=configuration.flicker_warning,
    )


def _legacy_mask_samples(
    graph: GradeGraph,
    frame_index: int,
) -> dict[str, np.ndarray]:
    samples: dict[str, np.ndarray] = {}
    for asset in graph.masks:
        root = Path(asset.path)
        if not root.is_dir():
            continue
        path = root / f"{frame_index:06d}.png"
        frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if frame is not None:
            samples[asset.id] = frame
    return samples


def _read_forward_to(
    capture: cv2.VideoCapture,
    *,
    next_frame_index: int,
    target_frame_index: int,
) -> tuple[np.ndarray | None, int]:
    """Decode forward and return the frame at an absolute stream index."""
    if target_frame_index < next_frame_index:
        raise ValueError("target frame index must not precede the decoder")
    selected: np.ndarray | None = None
    while next_frame_index <= target_frame_index:
        success, frame = capture.read()
        if not success:
            return None, next_frame_index
        if next_frame_index == target_frame_index:
            selected = frame
        next_frame_index += 1
    return selected, next_frame_index


def analyze_video_temporal(
    source: str | Path,
    output: str | Path,
    *,
    graph: GradeGraph | None = None,
    sample_fps: float = 5.0,
    config: TemporalAnalysisConfig | None = None,
) -> TemporalQualityEvidence:
    """Stream motion-compensated temporal evidence from synchronized videos."""

    if sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    configuration = config or TemporalAnalysisConfig()
    source_capture = cv2.VideoCapture(str(Path(source)))
    output_capture = cv2.VideoCapture(str(Path(output)))
    if not source_capture.isOpened() or not output_capture.isOpened():
        source_capture.release()
        output_capture.release()
        raise RuntimeError("OpenCV could not open source/output for temporal analysis")
    source_fps = float(source_capture.get(cv2.CAP_PROP_FPS))
    output_fps = float(output_capture.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0 or output_fps <= 0:
        source_capture.release()
        output_capture.release()
        raise RuntimeError("source/output video does not report a valid frame rate")
    effective_sample_fps = min(sample_fps, source_fps, output_fps)
    cut_frames = (
        {round(shot.time_range.start_seconds * source_fps) for shot in graph.shots[1:]}
        if graph is not None
        else set()
    )
    targets = {asset.id: asset.target for asset in graph.masks} if graph is not None else {}
    warnings: list[str] = []
    resolver = None
    if graph is not None and graph.masks:
        try:
            from colorgraph.grading.masks import GraphMaskResolver

            resolver = GraphMaskResolver(
                graph,
                verify_storage=False,
                include_unreferenced_assets=True,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            warnings.append(
                "mask resolver unavailable; using retained PNG sequences only "
                f"({type(exc).__name__})"
            )

    transitions: list[TemporalTransitionEvidence] = []
    previous_source: np.ndarray | None = None
    previous_output: np.ndarray | None = None
    previous_masks: dict[str, np.ndarray] = {}
    previous_frame_index: int | None = None
    sampled_frames = 0
    sample_index = 0
    next_source_frame_index = 0
    next_output_frame_index = 0
    try:
        while True:
            sample_time_seconds = sample_index / effective_sample_fps
            source_frame_index = round(sample_time_seconds * source_fps)
            output_frame_index = round(sample_time_seconds * output_fps)
            source_frame, next_source_frame_index = _read_forward_to(
                source_capture,
                next_frame_index=next_source_frame_index,
                target_frame_index=source_frame_index,
            )
            output_frame, next_output_frame_index = _read_forward_to(
                output_capture,
                next_frame_index=next_output_frame_index,
                target_frame_index=output_frame_index,
            )
            if source_frame is None or output_frame is None:
                break
            current_source = _frame_luma(source_frame, configuration.analysis_width)
            current_output = _frame_luma(output_frame, configuration.analysis_width)
            current_masks: dict[str, np.ndarray] = {}
            if resolver is not None:
                loaded = resolver.load_batch([source_frame_index])
                current_masks = {
                    asset_id: _mask_plane(tensor[0].numpy(), current_source.shape)
                    for asset_id, tensor in loaded.items()
                    if not asset_id.startswith("__composite__:")
                }
            elif graph is not None:
                current_masks = {
                    asset_id: _mask_plane(mask, current_source.shape)
                    for asset_id, mask in _legacy_mask_samples(
                        graph,
                        source_frame_index,
                    ).items()
                }
            sampled_frames += 1
            if (
                previous_source is not None
                and previous_output is not None
                and previous_frame_index is not None
            ):
                if _crosses_cut(
                    previous_frame_index,
                    source_frame_index,
                    cut_frames,
                ):
                    transitions.append(
                        _hard_cut_evidence(
                            previous_frame_index,
                            source_frame_index,
                            source_fps,
                            current_source.shape,
                        )
                    )
                else:
                    transitions.append(
                        _transition(
                            previous_source,
                            current_source,
                            previous_output,
                            current_output,
                            previous_frame_index=previous_frame_index,
                            frame_index=source_frame_index,
                            fps=source_fps,
                            previous_masks=previous_masks,
                            current_masks=current_masks,
                            mask_targets=targets,
                            config=configuration,
                        )
                    )
            previous_source = current_source
            previous_output = current_output
            previous_masks = current_masks
            previous_frame_index = source_frame_index
            sample_index += 1
    finally:
        source_capture.release()
        output_capture.release()
        if resolver is not None:
            resolver.close()
    if sampled_frames == 0:
        raise RuntimeError("no synchronized frames were available for temporal analysis")
    return _finish_evidence(
        transitions,
        sampled_frames=sampled_frames,
        warning_threshold=configuration.flicker_warning,
        warnings=warnings,
    )
