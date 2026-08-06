from dataclasses import dataclass
from numbers import Integral

import numpy as np


@dataclass(frozen=True)
class ContactSummary:
    fixed: bool = False
    moving: bool = False
    count: int = 0
    max_force: float = 0.0

    @property
    def bilateral(self) -> bool:
        return self.fixed and self.moving


def _as_numpy(value):
    for method_name in ("detach", "cpu", "numpy"):
        method = getattr(value, method_name, None)
        if callable(method):
            value = method()
    return np.asarray(value)


def _force_maximum(force, valid_mask, contact_count):
    if force is None or not np.any(valid_mask):
        return 0.0

    try:
        force = _as_numpy(force)
        if force.size == 0 or force.ndim < 2 or force.shape[-1] != 3:
            return 0.0
        force = np.asarray(force, dtype=np.float64)
        force = force.reshape(-1, force.shape[-1])
        if force.shape != (contact_count, 3) or not np.isfinite(force).all():
            return 0.0
        norms = np.linalg.norm(force[valid_mask], axis=1)
        return float(np.max(norms)) if norms.size else 0.0
    except Exception:
        return 0.0


def _classify_contact_indices(
    contacts,
    *,
    index_a_key,
    index_b_key,
    fixed_idx,
    moving_idx,
    matched_only,
):
    if not contacts or index_a_key not in contacts or index_b_key not in contacts:
        return ContactSummary()

    index_a = _as_numpy(contacts[index_a_key]).reshape(-1)
    index_b = _as_numpy(contacts[index_b_key]).reshape(-1)
    if index_a.size != index_b.size:
        raise ValueError(
            f"{index_a_key} and {index_b_key} lengths must match "
            f"({index_a.size} != {index_b.size})"
        )

    contact_count = index_a.size
    if "valid_mask" in contacts:
        valid_mask = _as_numpy(contacts["valid_mask"]).reshape(-1)
        if valid_mask.size != contact_count:
            raise ValueError(
                "valid_mask length "
                f"({valid_mask.size}) must match contact count ({contact_count})"
            )
        valid_mask = valid_mask.astype(bool, copy=False)
    else:
        valid_mask = np.ones(contact_count, dtype=bool)

    fixed_mask = (index_a == fixed_idx) | (index_b == fixed_idx)
    moving_mask = (index_a == moving_idx) | (index_b == moving_idx)
    fixed = np.any(valid_mask & fixed_mask)
    moving = np.any(valid_mask & moving_mask)
    summary_mask = (
        valid_mask & (fixed_mask | moving_mask) if matched_only else valid_mask
    )
    max_force = max(
        _force_maximum(contacts.get("force_a"), summary_mask, contact_count),
        _force_maximum(contacts.get("force_b"), summary_mask, contact_count),
    )
    return ContactSummary(
        fixed=bool(fixed),
        moving=bool(moving),
        count=int(np.count_nonzero(summary_mask)),
        max_force=max_force,
    )


def classify_finger_contacts(contacts, *, fixed_link_idx, moving_link_idx):
    return _classify_contact_indices(
        contacts,
        index_a_key="link_a",
        index_b_key="link_b",
        fixed_idx=fixed_link_idx,
        moving_idx=moving_link_idx,
        matched_only=False,
    )


def classify_finger_pad_contacts(contacts, *, fixed_geom_idx, moving_geom_idx):
    """Classify contacts made by the two exact finger-pad collision geoms."""
    return _classify_contact_indices(
        contacts,
        index_a_key="geom_a",
        index_b_key="geom_b",
        fixed_idx=fixed_geom_idx,
        moving_idx=moving_geom_idx,
        matched_only=True,
    )


def quat_rotate_wxyz(quat, vector):
    q = np.asarray(quat, dtype=np.float64).reshape(4)
    v = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = np.linalg.norm(q)
    if not np.isfinite(q).all() or norm == 0:
        raise ValueError("quaternion must be finite and non-zero")
    q = q / norm
    w, x, y, z = q
    qv = np.array([x, y, z])
    return v + 2.0 * np.cross(qv, np.cross(qv, v) + w * v)


def local_point_world(link_pos, link_quat_wxyz, local_point):
    return np.asarray(link_pos, dtype=np.float64).reshape(3) + quat_rotate_wxyz(
        link_quat_wxyz, local_point
    )


@dataclass
class ConvergenceWindow:
    tolerance: float
    required_samples: int
    streak: int = 0

    def __post_init__(self):
        if isinstance(self.required_samples, bool) or not isinstance(
            self.required_samples, Integral
        ) or self.required_samples <= 0:
            raise ValueError("required_samples must be a positive integer")
        if not np.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("tolerance must be finite and non-negative")

    def update(self, error: float) -> bool:
        self.streak = self.streak + 1 if error <= self.tolerance else 0
        return self.streak >= self.required_samples
