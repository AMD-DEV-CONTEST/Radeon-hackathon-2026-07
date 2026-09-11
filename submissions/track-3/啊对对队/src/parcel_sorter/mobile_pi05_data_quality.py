"""Action-chunk data diagnostics for residual PI0.5 training."""

from __future__ import annotations

import math
from typing import Iterable

from .mobile_pi05_contract import MOBILE_PI05_RESIDUAL_ACTION_NAMES


def summarize_pi05_action_chunk_activity(
    episodes: Iterable[Iterable[Iterable[float]]],
    *,
    chunk_size: int,
    residual_epsilon: float = 1e-5,
    minimum_active_fraction: float = 0.10,
    progress_span_epsilon: float = 0.02,
) -> dict[str, float | int]:
    """Measure largely idle chunks without treating zero residuals as bad labels.

    Mode logits are deliberately excluded because their constant one-hot target
    would make every chunk appear active. This function is an audit only: a
    zero residual can be correct and must not be removed without a matched
    data-curation ablation.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if residual_epsilon < 0.0 or progress_span_epsilon < 0.0:
        raise ValueError("activity epsilons cannot be negative")
    if not 0.0 <= minimum_active_fraction <= 1.0:
        raise ValueError("minimum_active_fraction must be in [0, 1]")
    chunk_count = 0
    informative_count = 0
    residual_active_count = 0
    transition_count = 0
    residual_fraction_sum = 0.0
    for episode in episodes:
        rows = tuple(tuple(float(value) for value in row) for row in episode)
        if any(len(row) != len(MOBILE_PI05_RESIDUAL_ACTION_NAMES) for row in rows):
            raise ValueError("PI0.5 activity audit requires 14-D residual actions")
        if any(not math.isfinite(value) for row in rows for value in row):
            raise ValueError("PI0.5 activity audit received non-finite actions")
        for start in range(len(rows)):
            window = rows[start : start + chunk_size]
            residual_active = sum(
                max(map(abs, row[:9])) > residual_epsilon for row in window
            )
            active_fraction = residual_active / len(window)
            suction_values = tuple(row[12] for row in window)
            progress_values = tuple(row[13] for row in window)
            has_transition = (
                max(suction_values) - min(suction_values) > residual_epsilon
                or max(progress_values) - min(progress_values)
                > progress_span_epsilon
            )
            residual_informative = active_fraction >= minimum_active_fraction
            informative = residual_informative or has_transition
            chunk_count += 1
            informative_count += int(informative)
            residual_active_count += int(residual_informative)
            transition_count += int(has_transition)
            residual_fraction_sum += active_fraction
    idle_count = chunk_count - informative_count
    return {
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "informative_chunk_count": informative_count,
        "largely_idle_chunk_count": idle_count,
        "informative_chunk_fraction": (
            informative_count / chunk_count if chunk_count else 0.0
        ),
        "largely_idle_chunk_fraction": idle_count / chunk_count if chunk_count else 0.0,
        "residual_active_chunk_count": residual_active_count,
        "transition_chunk_count": transition_count,
        "mean_residual_active_frame_fraction": (
            residual_fraction_sum / chunk_count if chunk_count else 0.0
        ),
        "residual_epsilon": residual_epsilon,
        "minimum_active_fraction": minimum_active_fraction,
        "progress_span_epsilon": progress_span_epsilon,
    }
