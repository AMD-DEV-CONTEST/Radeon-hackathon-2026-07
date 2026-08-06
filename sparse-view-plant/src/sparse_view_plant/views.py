"""Inference-compatible sparse-view selection (no GT or calibration needed).

The frontend estimates camera poses from the input images themselves, so a pipeline
can pick the most spread subset by farthest-point sampling on the estimated
camera centres. This mirrors the GT-based held-out sampling used in
evaluation (`select_heldout_views`) and recovers most of the quality gain of
wide-baseline input selection (near-collinear views collapse triangulation).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _rotation_angles(camera_to_world: np.ndarray) -> np.ndarray:
    """Camera-centre angles around the dominant rotation axis (PCA fit).

    Probe poses on a turntable are noisy; projecting the camera centres onto
    the plane perpendicular to the fitted rotation axis and taking the angle
    around it regularises away the noise component along the axis. This is
    what makes farthest-point selection close the blind arc that raw FPS on
    the noisy directions leaves behind.
    """
    centres = np.asarray(camera_to_world, dtype=np.float64)[:, :3, 3]
    centred = centres - centres.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    axis = vt[2]
    projected = centred - np.outer(centred @ axis, axis)
    angles = np.degrees(np.arctan2(projected @ vt[1], projected @ vt[0]))
    return angles


def select_diverse_views(
    camera_to_world: np.ndarray,
    view_ids: Sequence[str],
    count: int,
    *,
    seed: int = 0,
    regularize_axis: bool = False,
) -> list[str]:
    """Farthest-point sample `count` views on angular camera-centre spread.

    Each new view maximises its distance to the nearest already-chosen view
    (max-min FPS), which avoids picking near-duplicate viewpoints on a ring.
    With `regularize_axis=True` the spread is measured on PCA-fitted rotation
    angles (see ``_rotation_angles``) instead of the raw noisy directions.

    `camera_to_world` has shape (V, 4, 4); `view_ids` has length V. Returns
    the selected ids in the input order (not FPS order) for determinism.
    """
    ids = list(view_ids)
    if len(ids) != len(camera_to_world):
        raise ValueError("camera_to_world and view_ids must have the same length")
    if count <= 0:
        return []
    if count >= len(ids):
        return ids
    if regularize_axis:
        angles = _rotation_angles(camera_to_world)
        delta = np.abs(angles[:, None] - angles[None, :]) % 360.0
        distance = np.minimum(delta, 360.0 - delta)
    else:
        centres = np.asarray(camera_to_world, dtype=np.float64)[:, :3, 3]
        norms = np.linalg.norm(centres, axis=1, keepdims=True)
        if np.any(norms[:, 0] <= 1e-9):
            raise ValueError("camera centres must be non-zero for angular spread")
        directions = centres / norms
        distance = np.linalg.norm(
            directions[:, None, :] - directions[None, :, :], axis=-1
        )
    generator = np.random.default_rng(seed)
    chosen = [int(generator.integers(len(ids)))]
    for _ in range(count - 1):
        nearest = distance[chosen].min(axis=0)
        nearest[chosen] = -np.inf
        chosen.append(int(np.argmax(nearest)))
    selected = {ids[index] for index in chosen}
    return [view_id for view_id in ids if view_id in selected]


def sample_candidate_pool(view_ids: Sequence[str], count: int) -> list[str]:
    """Uniformly stride-sample ``count`` ids across a long sequence.

    Used to cap the ``--select-views`` probe pool: a full 214-frame plant
    rotation cannot be probed in one frontend batch on a 16GB GPU, and taking
    only the first N frames would cover a short arc of the rotation.
    Uniform sampling keeps angular coverage across the whole sequence and
    preserves the input order (temporal order) for determinism.
    """
    ids = list(view_ids)
    if count <= 0:
        return []
    if count >= len(ids):
        return ids
    indices = np.unique(np.linspace(0, len(ids) - 1, count).round().astype(int))
    return [ids[index] for index in indices]
