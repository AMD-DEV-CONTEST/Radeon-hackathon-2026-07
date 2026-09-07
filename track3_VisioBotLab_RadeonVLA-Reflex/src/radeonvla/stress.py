"""Deterministic scene perturbations for robustness evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np

from radeonvla.physics import set_rigid_position

PERTURBATIONS = ("none", "target_shift", "container_shift")


def _to_np(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float64).reshape(-1)


def shifted_position(position, *, distance: float, seed: int) -> np.ndarray:
    """Return a deterministic XY shift while preserving object height."""
    original = _to_np(position).copy()
    if original.size < 3:
        raise ValueError("Rigid position must have at least three coordinates")
    angle = float(np.random.default_rng(seed).uniform(0.0, 2.0 * np.pi))
    original[0] += float(distance) * np.cos(angle)
    original[1] += float(distance) * np.sin(angle)
    return original


def inject_perturbation(
    bundle: Any,
    resolved: Any,
    *,
    kind: str,
    distance: float,
    seed: int,
    step: int,
) -> dict[str, Any] | None:
    """Shift the current target or destination and return a serializable event."""
    if kind == "none":
        return None
    if kind not in PERTURBATIONS:
        raise ValueError(f"Unknown perturbation {kind!r}; expected one of {PERTURBATIONS}")
    if not resolved.goals:
        raise ValueError("Resolved task has no goals")

    goal = resolved.goals[0]
    entity_name = goal.object_name if kind == "target_shift" else goal.container
    entity = bundle.objects.get(entity_name)
    if entity is None:
        raise KeyError(f"Scene entity not found for perturbation: {entity_name}")

    before = _to_np(entity.get_pos())
    after = shifted_position(before, distance=distance, seed=seed)
    set_rigid_position(entity, after)
    return {
        "type": "perturbation",
        "kind": kind,
        "step": step,
        "entity": entity_name,
        "distance_m": float(distance),
        "before": before[:3].tolist(),
        "after": after[:3].tolist(),
    }
