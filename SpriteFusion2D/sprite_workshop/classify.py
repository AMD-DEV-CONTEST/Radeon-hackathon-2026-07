"""Deterministic source classifier used to route imports.

The classifier intentionally answers one narrow question: does the image look
like nearest-neighbour enlarged pixel art?  It does not attempt semantic image
classification and therefore remains cheap enough to run during import.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import RgbaImage


@dataclass(frozen=True, slots=True)
class SourceClassification:
    kind: str
    confidence: float
    detected_step: int

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "detected_step": self.detected_step,
        }


def _run_score(values: np.ndarray, step: int) -> float:
    """Score how often equal-colour runs are divisible by ``step``."""

    if values.shape[0] < step * 2:
        return 0.0
    changes = np.any(values[1:] != values[:-1], axis=1)
    cuts = np.flatnonzero(changes) + 1
    runs = np.diff(np.concatenate(([0], cuts, [values.shape[0]])))
    if runs.size == 0:
        return 0.0
    return float(np.mean(np.minimum(runs % step, step - (runs % step)) == 0))


def classify_source(image: RgbaImage) -> SourceClassification:
    rgb = image.array[:, :, :3]
    alpha = image.array[:, :, 3]
    visible = alpha > 0
    if not visible.any():
        return SourceClassification("illustration", 1.0, 1)

    # Use several scan lines so a flat background cannot dominate the answer.
    rows = np.linspace(0, image.height - 1, min(12, image.height), dtype=int)
    cols = np.linspace(0, image.width - 1, min(12, image.width), dtype=int)
    scores: dict[int, list[float]] = {step: [] for step in range(2, 17)}
    for row in rows:
        line = np.column_stack((rgb[row], alpha[row]))
        for step in scores:
            scores[step].append(_run_score(line, step))
    for col in cols:
        line = np.column_stack((rgb[:, col], alpha[:, col]))
        for step in scores:
            scores[step].append(_run_score(line, step))

    ranked = {step: float(np.mean(parts)) for step, parts in scores.items()}
    best = max(ranked.values())
    # Divisors of the true block size score equally (a 6px grid is also
    # divisible by 2 and 3).  Prefer the largest near-tied period, which is the
    # useful value for recovery's pixel-size override.
    best_step = max(step for step, score in ranked.items() if score >= best - 0.02)

    # Nearest-neighbour art also has relatively few adjacent transitions.  A
    # smooth gradient can accidentally have periodic runs after quantisation,
    # so require a strong grid signal rather than merely picking the maximum.
    horizontal_equal = (
        np.mean(np.all(rgb[:, 1:] == rgb[:, :-1], axis=2)) if image.width > 1 else 1.0
    )
    vertical_equal = (
        np.mean(np.all(rgb[1:] == rgb[:-1], axis=2)) if image.height > 1 else 1.0
    )
    flatness = float((horizontal_equal + vertical_equal) / 2.0)
    confidence = max(0.0, min(1.0, 0.65 * best + 0.35 * flatness))
    is_pixel = best >= 0.72 and flatness >= 0.45
    return SourceClassification(
        "pixel-art" if is_pixel else "illustration",
        confidence if is_pixel else 1.0 - confidence,
        best_step if is_pixel else 1,
    )
