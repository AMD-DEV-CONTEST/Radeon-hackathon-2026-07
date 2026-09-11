"""Rigid-object-aware projection for bounded dual-arm VLA residuals."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class DualArmProjection:
    left_target_m: Vector3
    right_target_m: Vector3
    common_residual_m: Vector3
    differential_residual_m: Vector3
    authority_scale: float
    separation_change_m: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "left_target_m": list(self.left_target_m),
            "right_target_m": list(self.right_target_m),
            "common_residual_m": list(self.common_residual_m),
            "differential_residual_m": list(self.differential_residual_m),
            "authority_scale": self.authority_scale,
            "separation_change_m": self.separation_change_m,
            "reasons": list(self.reasons),
        }


def transport_arm_authority(
    *,
    stage: str,
    remaining_distance_m: float | None,
    zero_authority_distance_m: float = 0.025,
    full_authority_distance_m: float = 0.120,
) -> float:
    """Fade learned arm authority to zero before precision placement begins."""

    if not 0.0 <= zero_authority_distance_m < full_authority_distance_m:
        raise ValueError("authority distances must satisfy 0 <= zero < full")
    if stage != "transport" or remaining_distance_m is None:
        return 0.0
    distance = float(remaining_distance_m)
    if not math.isfinite(distance) or distance < 0.0:
        return 0.0
    return max(
        0.0,
        min(
            1.0,
            (distance - zero_authority_distance_m)
            / (full_authority_distance_m - zero_authority_distance_m),
        ),
    )


def project_dual_arm_residuals(
    *,
    left_proposal_m: Iterable[float],
    right_proposal_m: Iterable[float],
    left_anchor_m: Iterable[float],
    right_anchor_m: Iterable[float],
    authority_scale: float,
    cooperative_carry: bool,
    max_common_residual_m: float = 0.010,
    max_differential_residual_m: float = 0.0015,
) -> DualArmProjection:
    """Project two VLA arm proposals into payload-consistent Cartesian motion.

    The common component moves both tools together. The differential component
    changes their relative pose and is therefore tightly bounded, or removed
    entirely while the suction tool and V-cradle share a rigid parcel.
    """

    left_proposal = _vector3(left_proposal_m, "left proposal")
    right_proposal = _vector3(right_proposal_m, "right proposal")
    left_anchor = _vector3(left_anchor_m, "left anchor")
    right_anchor = _vector3(right_anchor_m, "right anchor")
    authority = float(authority_scale)
    limits = (authority, max_common_residual_m, max_differential_residual_m)
    if any(not math.isfinite(value) for value in limits):
        raise ValueError("projection authority and limits must be finite")
    if not 0.0 <= authority <= 1.0:
        raise ValueError("authority_scale must be in [0, 1]")
    if max_common_residual_m <= 0.0 or max_differential_residual_m < 0.0:
        raise ValueError("projection residual limits are invalid")

    left_raw = _subtract(left_proposal, left_anchor)
    right_raw = _subtract(right_proposal, right_anchor)
    common_raw = tuple((left + right) * 0.5 for left, right in zip(left_raw, right_raw))
    differential_raw = tuple(
        (left - right) * 0.5 for left, right in zip(left_raw, right_raw)
    )
    reasons: list[str] = []
    common = _bound_norm(
        tuple(authority * value for value in common_raw),
        authority * max_common_residual_m,
    )
    if _norm(common) + 1e-12 < authority * _norm(common_raw):
        reasons.append("common_residual_bound")
    if cooperative_carry:
        differential = (0.0, 0.0, 0.0)
        if _norm(differential_raw) > 1e-12:
            reasons.append("cooperative_rigid_span_lock")
    else:
        differential = _bound_norm(
            tuple(authority * value for value in differential_raw),
            authority * max_differential_residual_m,
        )
        if _norm(differential) + 1e-12 < authority * _norm(differential_raw):
            reasons.append("differential_residual_bound")
    if authority <= 1e-12:
        reasons.append("precision_authority_handoff")

    left_target = _add(left_anchor, _add(common, differential))
    right_target = _add(right_anchor, _subtract(common, differential))
    separation_change = abs(
        math.dist(left_target, right_target) - math.dist(left_anchor, right_anchor)
    )
    return DualArmProjection(
        left_target_m=left_target,
        right_target_m=right_target,
        common_residual_m=common,
        differential_residual_m=differential,
        authority_scale=authority,
        separation_change_m=separation_change,
        reasons=tuple(reasons or ("projected",)),
    )


def _vector3(values: Iterable[float], name: str) -> Vector3:
    vector = tuple(float(value) for value in values)
    if len(vector) != 3:
        raise ValueError(f"{name} must be 3-D")
    if any(not math.isfinite(value) for value in vector):
        raise ValueError(f"{name} must be finite")
    return vector  # type: ignore[return-value]


def _norm(values: Vector3) -> float:
    return math.sqrt(sum(value * value for value in values))


def _bound_norm(values: Vector3, maximum: float) -> Vector3:
    norm = _norm(values)
    if norm <= maximum or norm <= 1e-15:
        return values
    scale = maximum / norm
    return tuple(scale * value for value in values)  # type: ignore[return-value]


def _add(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a + b for a, b in zip(left, right))  # type: ignore[return-value]


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a - b for a, b in zip(left, right))  # type: ignore[return-value]
