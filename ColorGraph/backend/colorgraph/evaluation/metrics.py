from __future__ import annotations

from collections.abc import Iterable, Sequence

import cv2
import numpy as np


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def boundary_f1(
    predicted_frames: Sequence[int],
    reference_frames: Sequence[int],
    *,
    tolerance_frames: int = 1,
) -> dict[str, float]:
    if tolerance_frames < 0:
        raise ValueError("tolerance_frames must be non-negative")
    predictions = sorted(set(int(value) for value in predicted_frames))
    references = sorted(set(int(value) for value in reference_frames))
    unmatched = set(range(len(references)))
    matches = 0
    for prediction in predictions:
        candidates = [
            index
            for index in unmatched
            if abs(references[index] - prediction) <= tolerance_frames
        ]
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda index: (abs(references[index] - prediction), index),
        )
        unmatched.remove(best)
        matches += 1
    precision = _safe_ratio(matches, len(predictions))
    recall = _safe_ratio(matches, len(references))
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": float(matches),
        "false_positives": float(len(predictions) - matches),
        "false_negatives": float(len(references) - matches),
    }


def interval_iou(
    predicted: Sequence[tuple[int, int]],
    reference: Sequence[tuple[int, int]],
) -> dict[str, float]:
    def pair_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
        intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]) + 1)
        union = max(left[1], right[1]) - min(left[0], right[0]) + 1
        return _safe_ratio(intersection, union)

    candidates = sorted(
        (
            pair_iou(prediction, truth),
            prediction_index,
            truth_index,
        )
        for prediction_index, prediction in enumerate(predicted)
        for truth_index, truth in enumerate(reference)
    )
    used_predictions: set[int] = set()
    used_references: set[int] = set()
    matches: list[float] = []
    for value, prediction_index, truth_index in reversed(candidates):
        if prediction_index in used_predictions or truth_index in used_references:
            continue
        used_predictions.add(prediction_index)
        used_references.add(truth_index)
        matches.append(value)
    denominator = max(len(predicted), len(reference))
    padded = matches + [0.0] * (denominator - len(matches))
    return {
        "mean_iou": float(np.mean(padded)) if padded else 1.0,
        "matched_mean_iou": float(np.mean(matches)) if matches else 0.0,
        "matched_intervals": float(len(matches)),
    }


def classification_metrics(
    predicted: Sequence[str],
    reference: Sequence[str],
    *,
    unknown_label: str = "unknown",
) -> dict[str, float]:
    if len(predicted) != len(reference):
        raise ValueError("predicted and reference labels must have equal length")
    labels = sorted(set(reference) - {unknown_label})
    per_label_f1: list[float] = []
    for label in labels:
        true_positive = sum(
            prediction == label and truth == label
            for prediction, truth in zip(predicted, reference, strict=True)
        )
        false_positive = sum(
            prediction == label and truth != label
            for prediction, truth in zip(predicted, reference, strict=True)
        )
        false_negative = sum(
            prediction != label and truth == label
            for prediction, truth in zip(predicted, reference, strict=True)
        )
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        per_label_f1.append(_safe_ratio(2 * precision * recall, precision + recall))
    return {
        "macro_f1": float(np.mean(per_label_f1)) if per_label_f1 else 0.0,
        "accuracy": _safe_ratio(
            sum(
                prediction == truth
                for prediction, truth in zip(predicted, reference, strict=True)
            ),
            len(reference),
        ),
        "unknown_rate": _safe_ratio(
            sum(prediction == unknown_label for prediction in predicted),
            len(predicted),
        ),
    }


def _binary_masks(
    predicted: np.ndarray,
    reference: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    prediction = np.asarray(predicted) >= threshold
    truth = np.asarray(reference) >= threshold
    if prediction.shape != truth.shape:
        raise ValueError(
            f"mask shapes differ: {prediction.shape} and {truth.shape}"
        )
    return prediction, truth


def mask_overlap_metrics(
    predicted: np.ndarray,
    reference: np.ndarray,
    *,
    threshold: float = 0.5,
) -> dict[str, float]:
    prediction, truth = _binary_masks(predicted, reference, threshold)
    intersection = int(np.logical_and(prediction, truth).sum())
    union = int(np.logical_or(prediction, truth).sum())
    total = int(prediction.sum() + truth.sum())
    return {
        "iou": _safe_ratio(intersection, union) if union else 1.0,
        "dice": _safe_ratio(2 * intersection, total) if total else 1.0,
    }


def boundary_f_score(
    predicted: np.ndarray,
    reference: np.ndarray,
    *,
    tolerance_pixels: int = 2,
    threshold: float = 0.5,
) -> float:
    if tolerance_pixels < 0:
        raise ValueError("tolerance_pixels must be non-negative")
    prediction, truth = _binary_masks(predicted, reference, threshold)
    kernel = np.ones((3, 3), dtype=np.uint8)
    prediction_boundary = cv2.morphologyEx(
        prediction.astype(np.uint8),
        cv2.MORPH_GRADIENT,
        kernel,
    )
    truth_boundary = cv2.morphologyEx(
        truth.astype(np.uint8),
        cv2.MORPH_GRADIENT,
        kernel,
    )
    if not prediction_boundary.any() and not truth_boundary.any():
        return 1.0
    radius = tolerance_pixels * 2 + 1
    tolerance_kernel = np.ones((radius, radius), dtype=np.uint8)
    dilated_prediction = cv2.dilate(prediction_boundary, tolerance_kernel)
    dilated_truth = cv2.dilate(truth_boundary, tolerance_kernel)
    precision = _safe_ratio(
        int(np.logical_and(prediction_boundary, dilated_truth).sum()),
        int(prediction_boundary.sum()),
    )
    recall = _safe_ratio(
        int(np.logical_and(truth_boundary, dilated_prediction).sum()),
        int(truth_boundary.sum()),
    )
    return _safe_ratio(2 * precision * recall, precision + recall)


def motion_compensated_temporal_stability(
    masks: np.ndarray,
    backward_flows: np.ndarray,
    *,
    cut_after_frames: Iterable[int] = (),
) -> dict[str, float]:
    values = np.asarray(masks, dtype=np.float32)
    flows = np.asarray(backward_flows, dtype=np.float32)
    if values.ndim != 3:
        raise ValueError("masks must have shape [frames, height, width]")
    if flows.shape != (values.shape[0] - 1, *values.shape[1:], 2):
        raise ValueError(
            "backward_flows must have shape [frames-1, height, width, 2]"
        )
    height, width = values.shape[1:]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    cuts = set(cut_after_frames)
    errors: list[float] = []
    for index in range(1, values.shape[0]):
        if index - 1 in cuts:
            continue
        flow = flows[index - 1]
        warped_previous = cv2.remap(
            values[index - 1],
            grid_x + flow[..., 0],
            grid_y + flow[..., 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        errors.append(float(np.abs(values[index] - warped_previous).mean()))
    return {
        "mean_absolute_error": float(np.mean(errors)) if errors else 0.0,
        "p95_absolute_error": float(np.percentile(errors, 95)) if errors else 0.0,
        "stability": max(0.0, 1.0 - (float(np.mean(errors)) if errors else 0.0)),
    }


def depth_temporal_scale_consistency(depth_frames: np.ndarray) -> dict[str, float]:
    values = np.asarray(depth_frames, dtype=np.float64)
    if values.ndim != 3 or values.shape[0] < 2:
        raise ValueError("depth_frames must have shape [frames>=2, height, width]")
    normalized: list[np.ndarray] = []
    scales: list[float] = []
    medians: list[float] = []
    for frame in values:
        finite = frame[np.isfinite(frame)]
        if finite.size == 0:
            raise ValueError("depth frame contains no finite samples")
        median = float(np.median(finite))
        low, high = np.percentile(finite, (5, 95))
        scale = max(float(high - low), 1e-9)
        medians.append(median)
        scales.append(scale)
        normalized.append((frame - median) / scale)
    temporal_errors = [
        float(np.nanmedian(np.abs(current - previous)))
        for previous, current in zip(normalized, normalized[1:], strict=False)
    ]
    return {
        "temporal_median_absolute_error": float(np.mean(temporal_errors)),
        "scale_coefficient_of_variation": _safe_ratio(
            float(np.std(scales)),
            float(np.mean(scales)),
        ),
        "median_drift_normalized": _safe_ratio(
            float(np.std(medians)),
            float(np.mean(np.abs(scales))),
        ),
    }


def delta_e_2000(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    first = np.asarray(lab_a, dtype=np.float64)
    second = np.asarray(lab_b, dtype=np.float64)
    if first.shape != second.shape or first.shape[-1] != 3:
        raise ValueError("Lab arrays must have equal shape ending in 3")
    l1, a1, b1 = np.moveaxis(first, -1, 0)
    l2, a2, b2 = np.moveaxis(second, -1, 0)
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1_prime = (1 + g) * a1
    a2_prime = (1 + g) * a2
    c1_prime = np.hypot(a1_prime, b1)
    c2_prime = np.hypot(a2_prime, b2)
    h1_prime = np.mod(np.degrees(np.arctan2(b1, a1_prime)), 360)
    h2_prime = np.mod(np.degrees(np.arctan2(b2, a2_prime)), 360)
    delta_l = l2 - l1
    delta_c = c2_prime - c1_prime
    raw_hue_delta = h2_prime - h1_prime
    delta_hue = np.where(
        c1_prime * c2_prime == 0,
        0,
        np.where(
            np.abs(raw_hue_delta) <= 180,
            raw_hue_delta,
            np.where(raw_hue_delta > 180, raw_hue_delta - 360, raw_hue_delta + 360),
        ),
    )
    delta_h = 2 * np.sqrt(c1_prime * c2_prime) * np.sin(
        np.radians(delta_hue / 2)
    )
    l_bar = (l1 + l2) / 2
    c_prime_bar = (c1_prime + c2_prime) / 2
    hue_sum = h1_prime + h2_prime
    h_bar = np.where(
        c1_prime * c2_prime == 0,
        hue_sum,
        np.where(
            np.abs(h1_prime - h2_prime) <= 180,
            hue_sum / 2,
            np.where(hue_sum < 360, (hue_sum + 360) / 2, (hue_sum - 360) / 2),
        ),
    )
    t = (
        1
        - 0.17 * np.cos(np.radians(h_bar - 30))
        + 0.24 * np.cos(np.radians(2 * h_bar))
        + 0.32 * np.cos(np.radians(3 * h_bar + 6))
        - 0.20 * np.cos(np.radians(4 * h_bar - 63))
    )
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * c_prime_bar
    s_h = 1 + 0.015 * c_prime_bar * t
    delta_theta = 30 * np.exp(-((h_bar - 275) / 25) ** 2)
    r_c = 2 * np.sqrt(c_prime_bar**7 / (c_prime_bar**7 + 25**7))
    r_t = -r_c * np.sin(np.radians(2 * delta_theta))
    l_term = delta_l / s_l
    c_term = delta_c / s_c
    h_term = delta_h / s_h
    return np.sqrt(
        l_term**2
        + c_term**2
        + h_term**2
        + r_t * c_term * h_term
    )


def delta_e_itp(ictcp_a: np.ndarray, ictcp_b: np.ndarray) -> np.ndarray:
    first = np.asarray(ictcp_a, dtype=np.float64)
    second = np.asarray(ictcp_b, dtype=np.float64)
    if first.shape != second.shape or first.shape[-1] != 3:
        raise ValueError("ICtCp arrays must have equal shape ending in 3")
    difference = first - second
    return 720 * np.sqrt(
        difference[..., 0] ** 2
        + 0.25 * difference[..., 1] ** 2
        + difference[..., 2] ** 2
    )


def color_sweep_metrics(
    predicted_lab: np.ndarray,
    reference_lab: np.ndarray,
) -> dict[str, float]:
    prediction = np.asarray(predicted_lab, dtype=np.float64)
    reference = np.asarray(reference_lab, dtype=np.float64)
    delta_e = delta_e_2000(prediction, reference)
    prediction_hue = np.degrees(np.arctan2(prediction[..., 2], prediction[..., 1]))
    reference_hue = np.degrees(np.arctan2(reference[..., 2], reference[..., 1]))
    hue_error = np.abs((prediction_hue - reference_hue + 180) % 360 - 180)
    return {
        "delta_e_2000_mean": float(np.mean(delta_e)),
        "delta_e_2000_p95": float(np.percentile(delta_e, 95)),
        "hue_error_degrees_mean": float(np.mean(hue_error)),
    }


def gray_axis_metrics(neutral_lab: np.ndarray) -> dict[str, float]:
    values = np.asarray(neutral_lab, dtype=np.float64)
    if values.ndim < 2 or values.shape[-1] != 3:
        raise ValueError("neutral Lab array must end in 3")
    chroma = np.hypot(values[..., 1], values[..., 2])
    return {
        "gray_axis_chroma_mean": float(np.mean(chroma)),
        "gray_axis_chroma_max": float(np.max(chroma)),
    }


def signal_range_metrics(rgb: np.ndarray) -> dict[str, float]:
    values = np.asarray(rgb, dtype=np.float64)
    if values.size == 0:
        raise ValueError("rgb array cannot be empty")
    outside = np.logical_or(values < 0, values > 1)
    clipped = np.logical_or(values <= 0, values >= 1)
    return {
        "gamut_outside_ratio": float(outside.mean()),
        "clipping_ratio": float(clipped.mean()),
    }


def banding_metrics(values: np.ndarray, *, code_values: int = 1024) -> dict[str, float]:
    samples = np.asarray(values, dtype=np.float64).reshape(-1)
    if samples.size < 3:
        raise ValueError("banding metrics require at least three samples")
    quantized = np.round(np.clip(samples, 0, 1) * (code_values - 1)).astype(np.int64)
    unique_ratio = len(np.unique(quantized)) / min(samples.size, code_values)
    steps = np.diff(quantized)
    zero_run_ratio = float((steps == 0).mean())
    return {
        "occupied_code_ratio": float(unique_ratio),
        "zero_step_ratio": zero_run_ratio,
        "banding_risk": float(max(0.0, 1.0 - unique_ratio)),
    }


def pairwise_ranking_metrics(
    score_a: Sequence[float],
    score_b: Sequence[float],
    preference: Sequence[int],
) -> dict[str, float]:
    if not (len(score_a) == len(score_b) == len(preference)):
        raise ValueError("pairwise ranking arrays must have equal length")
    if not preference:
        raise ValueError("pairwise ranking arrays cannot be empty")
    margins = np.asarray(score_a, dtype=np.float64) - np.asarray(
        score_b,
        dtype=np.float64,
    )
    labels = np.asarray(preference, dtype=np.int64)
    if not np.isin(labels, (-1, 1)).all():
        raise ValueError("preference values must be -1 (B) or 1 (A)")
    probabilities = 1 / (1 + np.exp(-np.clip(margins, -60, 60)))
    binary_labels = (labels == 1).astype(np.float64)
    epsilon = 1e-12
    log_loss = -np.mean(
        binary_labels * np.log(probabilities + epsilon)
        + (1 - binary_labels) * np.log(1 - probabilities + epsilon)
    )
    predicted = np.where(margins >= 0, 1, -1)
    return {
        "pairwise_accuracy": float((predicted == labels).mean()),
        "bradley_terry_log_loss": float(log_loss),
    }


def fleiss_kappa(category_counts: np.ndarray) -> float:
    counts = np.asarray(category_counts, dtype=np.float64)
    if counts.ndim != 2 or counts.shape[0] < 1 or counts.shape[1] < 2:
        raise ValueError("category_counts must have shape [items, categories>=2]")
    ratings_per_item = counts.sum(axis=1)
    if not np.all(ratings_per_item == ratings_per_item[0]):
        raise ValueError("every item must have the same number of ratings")
    ratings = ratings_per_item[0]
    if ratings < 2:
        raise ValueError("Fleiss kappa requires at least two ratings per item")
    observed = np.mean((np.sum(counts**2, axis=1) - ratings) / (ratings * (ratings - 1)))
    category_proportions = counts.sum(axis=0) / counts.sum()
    expected = float(np.sum(category_proportions**2))
    return _safe_ratio(float(observed - expected), float(1 - expected))


def percentile_latency(values_ms: Sequence[float]) -> dict[str, float]:
    values = np.asarray(values_ms, dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("latencies must be a non-empty finite non-negative sequence")
    return {
        "latency_mean_ms": float(np.mean(values)),
        "latency_p95_ms": float(np.percentile(values, 95)),
        "latency_max_ms": float(np.max(values)),
    }


def _finite_vector(
    values: Sequence[float],
    *,
    name: str,
) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def _equal_length_vectors(
    values: dict[str, Sequence[float]],
) -> dict[str, np.ndarray]:
    arrays = {
        name: _finite_vector(sequence, name=name)
        for name, sequence in values.items()
    }
    lengths = {array.size for array in arrays.values()}
    if len(lengths) != 1:
        raise ValueError(
            "paired evaluation vectors must have equal length: "
            + ", ".join(
                f"{name}={array.size}" for name, array in arrays.items()
            )
        )
    return arrays


def _residual_flicker_p95(
    prediction: np.ndarray,
    reference: np.ndarray,
    *,
    cut_after_samples: Iterable[int],
) -> float:
    if prediction.size < 2:
        return 0.0
    cuts = {int(value) for value in cut_after_samples}
    if any(value < 0 or value >= prediction.size - 1 for value in cuts):
        raise ValueError("cut_after_samples contains an out-of-range index")
    residual_steps = np.diff(prediction - reference)
    retained = np.asarray(
        [
            value
            for index, value in enumerate(residual_steps)
            if index not in cuts
        ],
        dtype=np.float64,
    )
    return (
        float(np.percentile(np.abs(retained), 95))
        if retained.size
        else 0.0
    )


def color_balance_acceptance_metrics(
    *,
    candidate_exposure_ev: Sequence[float],
    baseline_exposure_ev: Sequence[float],
    reference_exposure_ev: Sequence[float],
    candidate_temperature_kelvin: Sequence[float],
    baseline_temperature_kelvin: Sequence[float],
    reference_temperature_kelvin: Sequence[float],
    candidate_clipping_ratio: Sequence[float],
    baseline_clipping_ratio: Sequence[float],
    candidate_tint: Sequence[float] | None = None,
    baseline_tint: Sequence[float] | None = None,
    reference_tint: Sequence[float] | None = None,
    cut_after_samples: Iterable[int] = (),
) -> dict[str, float]:
    """Compare content-aware balance against a frozen baseline and expert truth."""
    arrays = _equal_length_vectors(
        {
            "candidate_exposure_ev": candidate_exposure_ev,
            "baseline_exposure_ev": baseline_exposure_ev,
            "reference_exposure_ev": reference_exposure_ev,
            "candidate_temperature_kelvin": candidate_temperature_kelvin,
            "baseline_temperature_kelvin": baseline_temperature_kelvin,
            "reference_temperature_kelvin": reference_temperature_kelvin,
            "candidate_clipping_ratio": candidate_clipping_ratio,
            "baseline_clipping_ratio": baseline_clipping_ratio,
        }
    )
    for name in (
        "candidate_temperature_kelvin",
        "baseline_temperature_kelvin",
        "reference_temperature_kelvin",
    ):
        if (arrays[name] <= 0).any():
            raise ValueError(f"{name} values must be positive")
    for name in ("candidate_clipping_ratio", "baseline_clipping_ratio"):
        if ((arrays[name] < 0) | (arrays[name] > 1)).any():
            raise ValueError(f"{name} values must lie in [0, 1]")

    candidate_exposure_error = (
        arrays["candidate_exposure_ev"] - arrays["reference_exposure_ev"]
    )
    baseline_exposure_error = (
        arrays["baseline_exposure_ev"] - arrays["reference_exposure_ev"]
    )
    candidate_exposure_mae = float(np.mean(np.abs(candidate_exposure_error)))
    baseline_exposure_mae = float(np.mean(np.abs(baseline_exposure_error)))

    candidate_mired = 1_000_000 / arrays["candidate_temperature_kelvin"]
    baseline_mired = 1_000_000 / arrays["baseline_temperature_kelvin"]
    reference_mired = 1_000_000 / arrays["reference_temperature_kelvin"]
    candidate_mired_error = candidate_mired - reference_mired
    baseline_mired_error = baseline_mired - reference_mired
    candidate_mired_mae = float(np.mean(np.abs(candidate_mired_error)))
    baseline_mired_mae = float(np.mean(np.abs(baseline_mired_error)))

    candidate_flicker = _residual_flicker_p95(
        arrays["candidate_exposure_ev"],
        arrays["reference_exposure_ev"],
        cut_after_samples=cut_after_samples,
    )
    baseline_flicker = _residual_flicker_p95(
        arrays["baseline_exposure_ev"],
        arrays["reference_exposure_ev"],
        cut_after_samples=cut_after_samples,
    )
    candidate_clipping = float(np.mean(arrays["candidate_clipping_ratio"]))
    baseline_clipping = float(np.mean(arrays["baseline_clipping_ratio"]))
    metrics = {
        "samples": float(arrays["candidate_exposure_ev"].size),
        "candidate_exposure_mae_ev": candidate_exposure_mae,
        "baseline_exposure_mae_ev": baseline_exposure_mae,
        "exposure_mae_improvement_ev": (
            baseline_exposure_mae - candidate_exposure_mae
        ),
        "candidate_exposure_bias_ev": float(
            np.mean(candidate_exposure_error)
        ),
        "baseline_exposure_bias_ev": float(np.mean(baseline_exposure_error)),
        "candidate_exposure_flicker_p95_ev": candidate_flicker,
        "baseline_exposure_flicker_p95_ev": baseline_flicker,
        "exposure_flicker_improvement_ev": (
            baseline_flicker - candidate_flicker
        ),
        "candidate_white_balance_mae_mired": candidate_mired_mae,
        "baseline_white_balance_mae_mired": baseline_mired_mae,
        "white_balance_mae_improvement_mired": (
            baseline_mired_mae - candidate_mired_mae
        ),
        "candidate_white_balance_bias_mired": float(
            np.mean(candidate_mired_error)
        ),
        "baseline_white_balance_bias_mired": float(
            np.mean(baseline_mired_error)
        ),
        "candidate_clipping_risk_mean": candidate_clipping,
        "baseline_clipping_risk_mean": baseline_clipping,
        "clipping_risk_improvement": baseline_clipping - candidate_clipping,
        "candidate_clipping_risk_p95": float(
            np.percentile(arrays["candidate_clipping_ratio"], 95)
        ),
        "baseline_clipping_risk_p95": float(
            np.percentile(arrays["baseline_clipping_ratio"], 95)
        ),
    }
    tint_vectors = (candidate_tint, baseline_tint, reference_tint)
    if any(value is not None for value in tint_vectors):
        if not all(value is not None for value in tint_vectors):
            raise ValueError(
                "candidate, baseline and reference tint must be provided together"
            )
        tint_arrays = _equal_length_vectors(
            {
                "candidate_tint": (
                    candidate_tint if candidate_tint is not None else ()
                ),
                "baseline_tint": (
                    baseline_tint if baseline_tint is not None else ()
                ),
                "reference_tint": (
                    reference_tint if reference_tint is not None else ()
                ),
            }
        )
        if (
            tint_arrays["candidate_tint"].size
            != arrays["candidate_exposure_ev"].size
        ):
            raise ValueError("tint vectors must match the balance sample count")
        candidate_tint_mae = float(
            np.mean(
                np.abs(
                    tint_arrays["candidate_tint"]
                    - tint_arrays["reference_tint"]
                )
            )
        )
        baseline_tint_mae = float(
            np.mean(
                np.abs(
                    tint_arrays["baseline_tint"]
                    - tint_arrays["reference_tint"]
                )
            )
        )
        metrics.update(
            {
                "candidate_tint_mae": candidate_tint_mae,
                "baseline_tint_mae": baseline_tint_mae,
                "tint_mae_improvement": (
                    baseline_tint_mae - candidate_tint_mae
                ),
            }
        )
    return metrics


def paired_cluster_bootstrap_difference(
    candidate: Sequence[float],
    baseline: Sequence[float],
    source_group_ids: Sequence[str],
    *,
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 20260730,
) -> dict[str, float]:
    """Return a source-cluster bootstrap CI for a paired mean difference."""
    arrays = _equal_length_vectors(
        {
            "candidate": candidate,
            "baseline": baseline,
        }
    )
    if len(source_group_ids) != arrays["candidate"].size:
        raise ValueError("source_group_ids must match paired values")
    if bootstrap_samples < 20:
        raise ValueError("bootstrap_samples must be at least 20")
    normalized_groups = [str(value).strip() for value in source_group_ids]
    if any(not value for value in normalized_groups):
        raise ValueError("source_group_ids cannot contain empty values")
    group_names = sorted(set(normalized_groups))
    group_indexes = {
        name: np.asarray(
            [
                index
                for index, value in enumerate(normalized_groups)
                if value == name
            ],
            dtype=np.int64,
        )
        for name in group_names
    }
    differences = arrays["candidate"] - arrays["baseline"]
    rng = np.random.default_rng(bootstrap_seed)
    sampled_differences: list[float] = []
    for _ in range(bootstrap_samples):
        sampled_groups = rng.choice(
            group_names,
            size=len(group_names),
            replace=True,
        )
        sampled_indexes = np.concatenate(
            [group_indexes[str(name)] for name in sampled_groups]
        )
        sampled_differences.append(
            float(np.mean(differences[sampled_indexes]))
        )
    return {
        "mean_difference": float(np.mean(differences)),
        "difference_ci95_low": float(
            np.percentile(sampled_differences, 2.5)
        ),
        "difference_ci95_high": float(
            np.percentile(sampled_differences, 97.5)
        ),
        "source_groups": float(len(group_names)),
        "bootstrap_samples": float(bootstrap_samples),
    }


def repair_acceptance_metrics(
    *,
    should_accept: Sequence[bool],
    accepted: Sequence[bool],
    objectives_passed: Sequence[bool],
    hard_safe: Sequence[bool],
    side_effect_safe: Sequence[bool],
    intent_drift_within_limit: Sequence[bool],
    objective_improvement: Sequence[float],
    intent_drift: Sequence[float],
    source_group_ids: Sequence[str],
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 20260730,
) -> dict[str, float]:
    """Quantify repair success, safe rollback and unintended side effects."""
    boolean_values = {
        "should_accept": np.asarray(should_accept, dtype=np.bool_),
        "accepted": np.asarray(accepted, dtype=np.bool_),
        "objectives_passed": np.asarray(objectives_passed, dtype=np.bool_),
        "hard_safe": np.asarray(hard_safe, dtype=np.bool_),
        "side_effect_safe": np.asarray(side_effect_safe, dtype=np.bool_),
        "intent_drift_within_limit": np.asarray(
            intent_drift_within_limit,
            dtype=np.bool_,
        ),
    }
    if any(value.ndim != 1 or value.size == 0 for value in boolean_values.values()):
        raise ValueError("repair acceptance vectors must be non-empty and one-dimensional")
    lengths = {value.size for value in boolean_values.values()}
    numeric = _equal_length_vectors(
        {
            "objective_improvement": objective_improvement,
            "intent_drift": intent_drift,
        }
    )
    lengths.add(numeric["objective_improvement"].size)
    if len(lengths) != 1:
        raise ValueError("repair acceptance vectors must have equal length")
    total = next(iter(lengths))
    if len(source_group_ids) != total:
        raise ValueError("source_group_ids must match repair cases")
    repairable = boolean_values["should_accept"]
    rollback = ~repairable
    if not repairable.any() or not rollback.any():
        raise ValueError(
            "repair acceptance evaluation requires repairable and rollback cases"
        )
    accepted_values = boolean_values["accepted"]
    safe = (
        boolean_values["hard_safe"]
        & boolean_values["side_effect_safe"]
        & boolean_values["intent_drift_within_limit"]
    )
    successful_repairs = (
        repairable
        & accepted_values
        & boolean_values["objectives_passed"]
        & safe
    )
    successful_rollbacks = rollback & ~accepted_values
    repair_groups = [
        source_group_ids[index]
        for index in np.flatnonzero(repairable)
    ]
    rollback_groups = [
        source_group_ids[index]
        for index in np.flatnonzero(rollback)
    ]
    success_ci = paired_cluster_bootstrap_difference(
        successful_repairs[repairable].astype(np.float64),
        np.zeros(int(repairable.sum()), dtype=np.float64),
        repair_groups,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    rollback_ci = paired_cluster_bootstrap_difference(
        successful_rollbacks[rollback].astype(np.float64),
        np.zeros(int(rollback.sum()), dtype=np.float64),
        rollback_groups,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed + 1,
    )
    accepted_count = int(accepted_values.sum())
    accepted_improvements = numeric["objective_improvement"][accepted_values]
    accepted_drifts = numeric["intent_drift"][accepted_values]
    return {
        "total_cases": float(total),
        "repairable_cases": float(repairable.sum()),
        "expected_rollback_cases": float(rollback.sum()),
        "repair_acceptance_rate": float(
            accepted_values[repairable].mean()
        ),
        "repair_success_rate": float(
            successful_repairs[repairable].mean()
        ),
        "repair_success_ci95_low": success_ci["difference_ci95_low"],
        "repair_success_ci95_high": success_ci["difference_ci95_high"],
        "rollback_accuracy": float(
            successful_rollbacks[rollback].mean()
        ),
        "rollback_accuracy_ci95_low": rollback_ci["difference_ci95_low"],
        "rollback_accuracy_ci95_high": rollback_ci["difference_ci95_high"],
        "unexpected_acceptance_rate": float(
            accepted_values[rollback].mean()
        ),
        "unsafe_acceptance_rate": (
            float((accepted_values & ~safe).sum() / accepted_count)
            if accepted_count
            else 0.0
        ),
        "hard_regression_acceptance_rate": (
            float(
                (
                    accepted_values
                    & ~boolean_values["hard_safe"]
                ).sum()
                / accepted_count
            )
            if accepted_count
            else 0.0
        ),
        "side_effect_acceptance_rate": (
            float(
                (
                    accepted_values
                    & ~boolean_values["side_effect_safe"]
                ).sum()
                / accepted_count
            )
            if accepted_count
            else 0.0
        ),
        "intent_drift_violation_acceptance_rate": (
            float(
                (
                    accepted_values
                    & ~boolean_values["intent_drift_within_limit"]
                ).sum()
                / accepted_count
            )
            if accepted_count
            else 0.0
        ),
        "accepted_objective_improvement_mean": (
            float(np.mean(accepted_improvements))
            if accepted_improvements.size
            else 0.0
        ),
        "accepted_intent_drift_p95": (
            float(np.percentile(accepted_drifts, 95))
            if accepted_drifts.size
            else 0.0
        ),
        "source_groups": float(len(set(source_group_ids))),
        "bootstrap_samples": float(bootstrap_samples),
    }
