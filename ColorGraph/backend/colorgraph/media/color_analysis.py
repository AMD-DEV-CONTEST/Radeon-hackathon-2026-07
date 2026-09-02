from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from colorgraph.domain.grade_graph import ColorSpace, Keyframe, TimeRange
from colorgraph.grading.color import (
    ACES_AP1_TO_LINEAR_REC709,
    DJI_DGAMUT_TO_REC709,
    DJI_DLOG_DGAMUT,
    DJI_MAVIC3_DLOG_REC709,
    SONY_SGAMUT3CINE_TO_REC709,
    SONY_SLOG3_SGAMUT3CINE,
    SUPPORTED_LOG_PROFILES,
)
from colorgraph.grading.ocio_pipeline import (
    OCIO_ACES2065_1,
    OCIO_ACESCG,
    OCIO_LINEAR_REC709,
    ocio_config,
)

COLOR_ANALYSIS_VERSION = "colorgraph.content-aware-color-analysis/v1"


@dataclass(frozen=True, slots=True)
class FrameColorStatistics:
    time_seconds: float
    exposure: float
    temperature: float
    tint: float
    highlights: float
    mean_luma: float
    p99_luma: float
    exposure_valid_sample_ratio: float
    exposure_uncertainty: float
    white_balance_valid_sample_ratio: float
    white_balance_uncertainty: float
    excluded_sky_ratio: float
    excluded_snow_ratio: float
    excluded_neon_ratio: float
    excluded_dominant_color_ratio: float


@dataclass(frozen=True, slots=True)
class ShotColorAnalysis:
    time_range: TimeRange
    exposure: float
    temperature: float
    tint: float
    highlights: float
    exposure_keyframes: list[Keyframe]
    temperature_keyframes: list[Keyframe]
    lighting_change_points: list[float]
    sampled_frames: int
    exposure_valid_sample_ratio: float
    exposure_uncertainty: float
    white_balance_valid_sample_ratio: float
    white_balance_uncertainty: float
    analysis_version: str = COLOR_ANALYSIS_VERSION


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    safe = np.clip((values + 0.055) / 1.055, 0, None)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        safe**2.4,
    )


def _bt709_oetf_to_linear(values: np.ndarray) -> np.ndarray:
    safe = np.clip((values + 0.099) / 1.099, 0, None)
    return np.where(values < 0.081, values / 4.5, safe ** (1 / 0.45))


def _rec1886_to_linear(values: np.ndarray) -> np.ndarray:
    return np.sign(values) * np.abs(values) ** 2.4


def _acescct_to_linear_rec709(values: np.ndarray) -> np.ndarray:
    linear_ap1 = np.where(
        values <= 0.155251141552511,
        (values - 0.0729055341958355) / 10.5402377416545,
        np.power(2.0, values * 17.52 - 9.72),
    )
    matrix = np.asarray(ACES_AP1_TO_LINEAR_REC709, dtype=values.dtype)
    return np.einsum("ij,hwj->hwi", matrix, linear_ap1)


def _ocio_aces_to_linear_rec709(values: np.ndarray, source: str) -> np.ndarray:
    output = np.ascontiguousarray(values.astype(np.float32, copy=True))
    ocio_config().getProcessor(
        source,
        OCIO_LINEAR_REC709,
    ).getDefaultCPUProcessor().applyRGB(output.reshape(-1, 3))
    return output


def _slog3_to_linear_rec709(values: np.ndarray) -> np.ndarray:
    cut = 171.2102946929 / 1023.0
    linear_sgamut = np.where(
        values >= cut,
        np.power(10.0, (values * 1023.0 - 420.0) / 261.5) * 0.19 - 0.01,
        (values * 1023.0 - 95.0) * 0.01125 / (171.2102946929 - 95.0),
    )
    matrix = np.asarray(SONY_SGAMUT3CINE_TO_REC709, dtype=np.float32)
    return np.einsum("ij,hwj->hwi", matrix, linear_sgamut)


def _dlog_dgamut_to_linear_rec709(values: np.ndarray) -> np.ndarray:
    code = np.clip(values, 0, 1)
    linear_dgamut = np.where(
        code <= 0.14,
        (code - 0.0929) / 6.025,
        (np.power(10.0, 3.89616 * code - 2.27752) - 0.0108) / 0.9892,
    )
    matrix = np.asarray(DJI_DGAMUT_TO_REC709, dtype=np.float32)
    return np.einsum("ij,hwj->hwi", matrix, linear_dgamut)


def _log_to_linear_rec709(
    values: np.ndarray,
    source_log_profile: str | None,
) -> np.ndarray:
    if source_log_profile == SONY_SLOG3_SGAMUT3CINE:
        return _slog3_to_linear_rec709(values)
    if source_log_profile == DJI_DLOG_DGAMUT:
        return _dlog_dgamut_to_linear_rec709(values)
    if source_log_profile == DJI_MAVIC3_DLOG_REC709:
        from colorgraph.grading.lut import apply_cube_lut_numpy
        from colorgraph.grading.official_luts import (
            ensure_dji_mavic3_dlog_to_rec709_lut,
        )

        display_rec709 = apply_cube_lut_numpy(
            values,
            ensure_dji_mavic3_dlog_to_rec709_lut(),
            interpolation="trilinear",
        )
        return _rec1886_to_linear(display_rec709)
    supported = ", ".join(sorted(SUPPORTED_LOG_PROFILES))
    raise ValueError(f"unsupported source log profile; expected one of: {supported}")


def _encoded_to_linear_rec709(
    values: np.ndarray,
    input_color_space: ColorSpace,
    source_log_profile: str | None,
) -> np.ndarray:
    if input_color_space == ColorSpace.LINEAR_REC709:
        return values
    if input_color_space == ColorSpace.SRGB:
        return _srgb_to_linear(values)
    if input_color_space == ColorSpace.BT709_OETF:
        return _bt709_oetf_to_linear(values)
    if input_color_space == ColorSpace.REC1886:
        return _rec1886_to_linear(values)
    if input_color_space == ColorSpace.ACES2065_1:
        return _ocio_aces_to_linear_rec709(values, OCIO_ACES2065_1)
    if input_color_space == ColorSpace.ACESCG:
        return _ocio_aces_to_linear_rec709(values, OCIO_ACESCG)
    if input_color_space == ColorSpace.ACESCCT:
        return _acescct_to_linear_rec709(values)
    if input_color_space == ColorSpace.LOG:
        return _log_to_linear_rec709(values, source_log_profile)
    if input_color_space == ColorSpace.REC709:
        raise ValueError(
            "ambiguous legacy color space 'rec709'; use 'bt709_oetf', 'rec1886', or 'srgb'"
        )
    raise ValueError(f"unsupported input color space: {input_color_space.value}")


@dataclass(frozen=True, slots=True)
class _ContentMasks:
    usable: np.ndarray
    sky: np.ndarray
    snow: np.ndarray
    neon: np.ndarray
    dominant_color: np.ndarray
    saturation: np.ndarray


def _mask_ratio(mask: np.ndarray) -> float:
    return float(np.count_nonzero(mask) / mask.size)


def _content_masks(encoded_rgb: np.ndarray, linear_rgb: np.ndarray) -> _ContentMasks:
    """Find pixels that should not act as exposure or neutral-color references."""

    hsv = cv2.cvtColor(
        np.ascontiguousarray(np.clip(encoded_rgb, 0, 1).astype(np.float32)),
        cv2.COLOR_RGB2HSV,
    )
    hue = hsv[..., 0]
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    finite = np.isfinite(linear_rgb).all(axis=-1)
    luma = np.einsum(
        "hwi,i->hw",
        linear_rgb,
        np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32),
    )
    unclipped = (
        (encoded_rgb.min(axis=-1) > 1.0 / 255.0)
        & (encoded_rgb.max(axis=-1) < 254.0 / 255.0)
        & (luma > 2e-4)
    )

    red = encoded_rgb[..., 0]
    green = encoded_rgb[..., 1]
    blue = encoded_rgb[..., 2]
    sky = (
        (hue >= 185)
        & (hue <= 255)
        & (saturation >= 0.16)
        & (value >= 0.18)
        & (blue > green * 1.025)
        & (blue > red * 1.10)
    )
    snow = (
        (saturation <= 0.13)
        & (value >= 0.78)
        & (luma >= 0.52)
    )
    neon = (saturation >= 0.72) & (value >= 0.70)

    chromatic = finite & unclipped & (saturation >= 0.24) & ~sky & ~neon
    dominant_color = np.zeros_like(chromatic)
    if np.count_nonzero(chromatic) >= max(64, round(chromatic.size * 0.08)):
        hue_bins = np.floor(hue[chromatic] / 15.0).astype(np.int32) % 24
        histogram = np.bincount(hue_bins, minlength=24)
        dominant_bin = int(np.argmax(histogram))
        chromatic_fraction = _mask_ratio(chromatic)
        cluster_fraction = float(histogram[dominant_bin] / max(histogram.sum(), 1))
        if chromatic_fraction >= 0.32 and cluster_fraction >= 0.52:
            all_bins = np.floor(hue / 15.0).astype(np.int32) % 24
            circular_distance = np.minimum(
                (all_bins - dominant_bin) % 24,
                (dominant_bin - all_bins) % 24,
            )
            dominant_color = chromatic & (circular_distance <= 1)

    usable = finite & unclipped & ~sky & ~snow & ~neon & ~dominant_color
    return _ContentMasks(
        usable=usable,
        sky=sky,
        snow=snow,
        neon=neon,
        dominant_color=dominant_color,
        saturation=saturation,
    )


def _robust_scalar_location(values: np.ndarray) -> tuple[float, float]:
    """Return a Huber location and robust scale without assuming a Gaussian tail."""

    if values.size == 0:
        return 0.0, math.inf
    center = float(np.median(values))
    mad = float(np.median(np.abs(values - center)))
    scale = max(1.4826 * mad, 1e-4)
    for _ in range(6):
        residual = values - center
        weights = np.minimum(1.0, 1.5 * scale / np.maximum(np.abs(residual), 1e-6))
        updated = float(np.sum(weights * values) / max(float(weights.sum()), 1e-6))
        if abs(updated - center) < 1e-6:
            break
        center = updated
    return center, scale


def _robust_vector_location(values: np.ndarray) -> tuple[np.ndarray, float]:
    """Jointly estimate log chromaticity so RGB channels cannot select different objects."""

    if values.size == 0:
        return np.zeros(2, dtype=np.float64), math.inf
    center = np.median(values, axis=0).astype(np.float64)
    distances = np.linalg.norm(values - center, axis=1)
    scale = max(1.4826 * float(np.median(np.abs(distances - np.median(distances)))), 1e-4)
    for _ in range(8):
        distances = np.linalg.norm(values - center, axis=1)
        weights = np.minimum(1.0, 1.5 * scale / np.maximum(distances, 1e-6))
        updated = np.sum(values * weights[:, None], axis=0) / max(float(weights.sum()), 1e-6)
        if float(np.linalg.norm(updated - center)) < 1e-6:
            break
        center = updated
    spread = float(np.median(np.linalg.norm(values - center, axis=1)))
    return center, spread


def _estimate_exposure(
    luma: np.ndarray,
    masks: _ContentMasks,
) -> tuple[float, float, float]:
    valid_ratio = _mask_ratio(masks.usable)
    if not np.any(masks.usable):
        return 0.0, 0.0, 1.5

    samples = np.clip(luma[masks.usable].astype(np.float64), 1e-5, None)
    log_samples = np.log2(samples)
    log_anchor, robust_scale = _robust_scalar_location(log_samples)
    anchor = 2.0**log_anchor

    finite_luma = luma[np.isfinite(luma)]
    global_p50 = float(np.percentile(finite_luma, 50))
    global_p90 = float(np.percentile(finite_luma, 90))
    global_p99 = float(np.percentile(finite_luma, 99))
    snow_ratio = _mask_ratio(masks.snow)

    # Move normal scenes softly toward a photographic midtone instead of forcing
    # every frame to become 18% gray. Low-key and high-key scenes deliberately
    # retain most of their original placement.
    low_key = global_p50 < 0.035 and global_p90 < 0.16
    high_key = snow_ratio >= 0.20 or global_p50 >= 0.48
    adaptation = 0.42
    if low_key:
        adaptation = 0.08
    elif high_key:
        adaptation = 0.12
    nominal_midtone = 0.18
    raw_exposure = adaptation * math.log2(nominal_midtone / max(anchor, 1e-5))

    # Leave highlight headroom even when the midtone estimate asks for a lift.
    highlight_limit = math.log2(0.92 / max(global_p99, 1e-5))
    if raw_exposure > 0:
        raw_exposure = min(raw_exposure, highlight_limit + 0.08)

    exclusion_ratio = _mask_ratio(
        masks.sky | masks.snow | masks.neon | masks.dominant_color
    )
    uncertainty = float(
        np.clip(
            0.04
            + 0.82 * (1.0 - min(valid_ratio / 0.45, 1.0))
            + 0.18 * min(robust_scale / 2.5, 1.0)
            + 0.18 * exclusion_ratio,
            0.04,
            1.5,
        )
    )
    reliability = float(
        np.clip(valid_ratio / 0.20, 0.0, 1.0)
        * np.clip(1.15 - uncertainty / 1.5, 0.15, 1.0)
    )
    exposure = float(np.clip(raw_exposure * reliability, -1.5, 1.5))
    return exposure, valid_ratio, uncertainty


def _estimate_white_balance(
    linear: np.ndarray,
    masks: _ContentMasks,
) -> tuple[float, float, float, float]:
    positive = np.clip(linear, 1e-5, None)
    neutral = masks.usable & (masks.saturation <= 0.34)
    valid_ratio = _mask_ratio(neutral)
    fallback = False
    if not np.any(neutral):
        # A single dominant color has no defensible neutral reference. Retain
        # only a tiny directional hint and report full uncertainty.
        neutral = np.isfinite(linear).all(axis=-1) & (positive.max(axis=-1) > 1e-4)
        fallback = True
    if not np.any(neutral):
        return 0.0, 0.0, 0.0, 1.0

    selected = positive[neutral].astype(np.float64)
    log_chromaticity = np.column_stack(
        (
            np.log(selected[:, 0] / selected[:, 1]),
            np.log(selected[:, 2] / selected[:, 1]),
        )
    )
    center, spread = _robust_vector_location(log_chromaticity)
    temperature_raw = 0.40 * float(center[1] - center[0])
    tint_raw = -0.32 * float((center[0] + center[1]) * 0.5)

    uncertainty = float(
        np.clip(
            0.04
            + 0.72 * (1.0 - min(valid_ratio / 0.20, 1.0))
            + 1.15 * min(spread, 0.45),
            0.04,
            1.0,
        )
    )
    reliability = 0.05 if fallback else float(np.clip(1.08 - uncertainty, 0.08, 1.0))
    temperature = float(np.clip(temperature_raw * reliability, -0.65, 0.65))
    tint = float(np.clip(tint_raw * reliability, -0.45, 0.45))
    return temperature, tint, valid_ratio, uncertainty


def analyze_frame(
    frame_bgr: np.ndarray,
    *,
    time_seconds: float,
    input_color_space: ColorSpace = ColorSpace.BT709_OETF,
    source_log_profile: str | None = None,
) -> FrameColorStatistics:
    small = cv2.resize(frame_bgr, (320, 180), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    linear = _encoded_to_linear_rec709(rgb, input_color_space, source_log_profile)
    luma = linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722
    masks = _content_masks(rgb, linear)
    exposure, exposure_valid_ratio, exposure_uncertainty = _estimate_exposure(luma, masks)
    temperature, tint, wb_valid_ratio, wb_uncertainty = _estimate_white_balance(
        linear,
        masks,
    )
    p99_luma = float(np.percentile(luma, 99))
    highlights = float(np.clip(-(p99_luma - 0.86) * 1.2, -0.45, 0.0))
    return FrameColorStatistics(
        time_seconds=time_seconds,
        exposure=exposure,
        temperature=temperature,
        tint=tint,
        highlights=highlights,
        mean_luma=float(luma.mean()),
        p99_luma=p99_luma,
        exposure_valid_sample_ratio=exposure_valid_ratio,
        exposure_uncertainty=exposure_uncertainty,
        white_balance_valid_sample_ratio=wb_valid_ratio,
        white_balance_uncertainty=wb_uncertainty,
        excluded_sky_ratio=_mask_ratio(masks.sky),
        excluded_snow_ratio=_mask_ratio(masks.snow),
        excluded_neon_ratio=_mask_ratio(masks.neon),
        excluded_dominant_color_ratio=_mask_ratio(masks.dominant_color),
    )


def _robust_trend_filter(
    samples: list[FrameColorStatistics],
    values: list[float],
    uncertainties: list[float],
    *,
    smoothing_strength: float,
    noise_floor: float,
) -> np.ndarray:
    """Uncertainty-weighted L1 trend filter with Huber measurement loss."""

    observations = np.asarray(values, dtype=np.float64)
    count = observations.size
    if count < 3:
        return observations.astype(np.float32)

    times = np.asarray([sample.time_seconds for sample in samples], dtype=np.float64)
    measurement_scale = np.maximum(
        np.asarray(uncertainties, dtype=np.float64),
        noise_floor,
    )
    trend = observations.copy()
    isolated_precision = np.ones(count, dtype=np.float64)
    for index in range(1, count - 1):
        neighbor_gap = abs(float(observations[index - 1] - observations[index + 1]))
        predicted = float((observations[index - 1] + observations[index + 1]) * 0.5)
        innovation = abs(float(observations[index] - predicted))
        local_noise = float(np.median(measurement_scale[index - 1 : index + 2]))
        if neighbor_gap <= 2.5 * local_noise and innovation >= 3.0 * local_noise:
            isolated_precision[index] = float(
                np.clip(2.0 * local_noise / innovation, 0.03, 1.0)
            )
            trend[index] = predicted

    second_difference = np.zeros((count - 2, count), dtype=np.float64)
    for index in range(count - 2):
        left_dt = max(times[index + 1] - times[index], 1e-3)
        right_dt = max(times[index + 2] - times[index + 1], 1e-3)
        row = np.asarray(
            [1.0 / left_dt, -(1.0 / left_dt + 1.0 / right_dt), 1.0 / right_dt]
        )
        row /= max(float(np.linalg.norm(row)), 1e-6)
        second_difference[index, index : index + 3] = row

    precision = isolated_precision / np.square(measurement_scale)
    precision /= max(float(np.median(precision)), 1e-6)

    for _ in range(12):
        residual = observations - trend
        normalized_residual = np.abs(residual) / measurement_scale
        huber_weight = np.minimum(1.0, 1.5 / np.maximum(normalized_residual, 1e-6))
        data_weight = precision * huber_weight

        curvature = second_difference @ trend
        trend_weight = 1.0 / np.sqrt(np.square(curvature) + noise_floor**2)
        trend_weight = np.minimum(trend_weight, 1.0 / noise_floor)

        system = np.diag(data_weight) + smoothing_strength * (
            second_difference.T @ (trend_weight[:, None] * second_difference)
        )
        target = data_weight * observations
        updated = np.linalg.solve(system + np.eye(count) * 1e-8, target)
        if float(np.max(np.abs(updated - trend))) < 1e-5:
            trend = updated
            break
        trend = updated
    return trend.astype(np.float32)


def _change_indices(
    values: np.ndarray,
    uncertainties: np.ndarray,
    *,
    noise_floor: float,
) -> list[int]:
    candidates: list[tuple[int, float]] = []
    for index in range(1, len(values)):
        before = values[max(0, index - 2) : index]
        after = values[index : min(len(values), index + 2)]
        magnitude = abs(float(np.median(after) - np.median(before)))
        local_uncertainty = float(
            np.median(uncertainties[max(0, index - 1) : min(len(values), index + 2)])
        )
        adaptive_noise = noise_floor + 0.55 * local_uncertainty
        if magnitude >= adaptive_noise * 1.65:
            candidates.append((index, magnitude / adaptive_noise))
    if not candidates:
        return []

    groups: list[list[tuple[int, float]]] = [[candidates[0]]]
    for candidate in candidates[1:]:
        if candidate[0] <= groups[-1][-1][0] + 1:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    return [max(group, key=lambda item: item[1])[0] for group in groups]


def _select_keyframes(
    samples: list[FrameColorStatistics],
    values: np.ndarray,
    uncertainties: np.ndarray,
    *,
    noise_floor: float,
) -> list[Keyframe]:
    if not samples:
        return []
    if len(samples) == 1:
        selected = [0]
    else:
        tolerance = noise_floor + 0.45 * np.asarray(uncertainties, dtype=np.float64)
        if float(np.ptp(values)) <= float(np.median(tolerance)):
            selected = [0]
        else:
            selected_set = {0, len(samples) - 1}
            pending = [(0, len(samples) - 1)]
            while pending:
                start, end = pending.pop()
                if end - start <= 1:
                    continue
                start_time = samples[start].time_seconds
                end_time = samples[end].time_seconds
                duration = max(end_time - start_time, 1e-6)
                interior = np.arange(start + 1, end)
                fractions = np.asarray(
                    [
                        (samples[index].time_seconds - start_time) / duration
                        for index in interior
                    ],
                    dtype=np.float64,
                )
                interpolated = values[start] + fractions * (values[end] - values[start])
                normalized_error = np.abs(values[interior] - interpolated) / tolerance[interior]
                worst_offset = int(np.argmax(normalized_error))
                if float(normalized_error[worst_offset]) > 1.0:
                    split = int(interior[worst_offset])
                    selected_set.add(split)
                    pending.extend(((start, split), (split, end)))

            for change_index in _change_indices(
                values,
                np.asarray(uncertainties),
                noise_floor=noise_floor,
            ):
                selected_set.add(change_index)
                selected_set.add(max(0, change_index - 1))
            selected = sorted(selected_set)
    return [
        Keyframe(
            time_seconds=samples[index].time_seconds,
            value=round(float(values[index]), 5),
        )
        for index in selected
    ]


def analyze_video_color(
    source: str | Path,
    shot_ranges: list[TimeRange],
    *,
    sample_fps: float = 2.0,
    input_color_space: ColorSpace = ColorSpace.BT709_OETF,
    source_log_profile: str | None = None,
) -> list[ShotColorAnalysis]:
    capture = cv2.VideoCapture(str(Path(source).resolve()))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {source}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        capture.release()
        raise RuntimeError("video does not report a valid frame rate")
    interval = max(1, round(fps / sample_fps))
    per_shot: list[list[FrameColorStatistics]] = [[] for _ in shot_ranges]
    frame_index = 0
    shot_index = 0
    try:
        while shot_index < len(shot_ranges):
            success, frame = capture.read()
            if not success:
                break
            time_seconds = frame_index / fps
            while (
                shot_index < len(shot_ranges) - 1
                and time_seconds >= shot_ranges[shot_index].end_seconds
            ):
                shot_index += 1
            if (
                frame_index % interval == 0
                and shot_ranges[shot_index].start_seconds
                <= time_seconds
                < shot_ranges[shot_index].end_seconds
            ):
                per_shot[shot_index].append(
                    analyze_frame(
                        frame,
                        time_seconds=time_seconds,
                        input_color_space=input_color_space,
                        source_log_profile=source_log_profile,
                    )
                )
            frame_index += 1
    finally:
        capture.release()

    analyses: list[ShotColorAnalysis] = []
    for time_range, samples in zip(shot_ranges, per_shot, strict=True):
        if not samples:
            analyses.append(
                ShotColorAnalysis(
                    time_range=time_range,
                    exposure=0.0,
                    temperature=0.0,
                    tint=0.0,
                    highlights=0.0,
                    exposure_keyframes=[],
                    temperature_keyframes=[],
                    lighting_change_points=[],
                    sampled_frames=0,
                    exposure_valid_sample_ratio=0.0,
                    exposure_uncertainty=1.5,
                    white_balance_valid_sample_ratio=0.0,
                    white_balance_uncertainty=1.0,
                )
            )
            continue
        exposure_uncertainties = np.asarray(
            [sample.exposure_uncertainty for sample in samples],
            dtype=np.float32,
        )
        temperature_uncertainties = np.asarray(
            [sample.white_balance_uncertainty for sample in samples],
            dtype=np.float32,
        )
        exposures = _robust_trend_filter(
            samples,
            [sample.exposure for sample in samples],
            exposure_uncertainties.tolist(),
            smoothing_strength=0.04,
            noise_floor=0.04,
        )
        temperatures = _robust_trend_filter(
            samples,
            [sample.temperature for sample in samples],
            temperature_uncertainties.tolist(),
            smoothing_strength=0.08,
            noise_floor=0.025,
        )
        preserve_camera_baseline = source_log_profile == DJI_MAVIC3_DLOG_REC709
        if preserve_camera_baseline:
            # DJI's official transform already establishes the intended
            # camera-to-display baseline. Keep only within-shot drift instead
            # of imposing a generic scene placement on a high-key snow scene.
            exposures = exposures - np.median(exposures)
            temperatures = temperatures - np.median(temperatures)
        exposure_keyframes = _select_keyframes(
            samples,
            exposures,
            exposure_uncertainties,
            noise_floor=0.045,
        )
        temperature_keyframes = _select_keyframes(
            samples,
            temperatures,
            temperature_uncertainties,
            noise_floor=0.025,
        )
        exposure_changes = _change_indices(
            exposures,
            exposure_uncertainties,
            noise_floor=0.045,
        )
        temperature_changes = _change_indices(
            temperatures,
            temperature_uncertainties,
            noise_floor=0.025,
        )
        change_points = sorted(
            {
                round(samples[index].time_seconds, 4)
                for index in exposure_changes + temperature_changes
            }
        )
        exposure_residual = np.asarray(
            [sample.exposure for sample in samples],
            dtype=np.float32,
        ) - exposures
        temperature_residual = np.asarray(
            [sample.temperature for sample in samples],
            dtype=np.float32,
        ) - temperatures
        shot_exposure_uncertainty = float(
            np.clip(
                np.median(exposure_uncertainties)
                + 1.4826 * np.median(np.abs(exposure_residual)),
                0.04,
                1.5,
            )
        )
        shot_wb_uncertainty = float(
            np.clip(
                np.median(temperature_uncertainties)
                + 1.4826 * np.median(np.abs(temperature_residual)),
                0.04,
                1.0,
            )
        )
        exposure_center, _ = _robust_scalar_location(exposures.astype(np.float64))
        temperature_center, _ = _robust_scalar_location(temperatures.astype(np.float64))
        analyses.append(
            ShotColorAnalysis(
                time_range=time_range,
                exposure=round(exposure_center, 5),
                temperature=round(temperature_center, 5),
                tint=(
                    0.0
                    if preserve_camera_baseline
                    else round(float(np.median([sample.tint for sample in samples])), 5)
                ),
                highlights=(
                    0.0
                    if preserve_camera_baseline
                    else round(
                        float(np.median([sample.highlights for sample in samples])),
                        5,
                    )
                ),
                exposure_keyframes=exposure_keyframes,
                temperature_keyframes=temperature_keyframes,
                lighting_change_points=change_points,
                sampled_frames=len(samples),
                exposure_valid_sample_ratio=round(
                    float(
                        np.median(
                            [sample.exposure_valid_sample_ratio for sample in samples]
                        )
                    ),
                    5,
                ),
                exposure_uncertainty=round(shot_exposure_uncertainty, 5),
                white_balance_valid_sample_ratio=round(
                    float(
                        np.median(
                            [
                                sample.white_balance_valid_sample_ratio
                                for sample in samples
                            ]
                        )
                    ),
                    5,
                ),
                white_balance_uncertainty=round(shot_wb_uncertainty, 5),
            )
        )
    return analyses
