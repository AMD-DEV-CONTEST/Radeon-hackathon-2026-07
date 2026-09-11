"""Deterministic metric-depth risk sidecar for an RGB semantic policy."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class DepthSidecarConfig:
    valid_min_m: float = 0.05
    valid_max_m: float = 20.0
    minimum_valid_fraction: float = 0.70
    full_quality_valid_fraction: float = 0.95
    hard_near_plane_m: float = 0.10
    caution_near_plane_m: float = 0.25
    nearest_quantile: float = 0.01
    roi_fraction: float = 0.60

    def __post_init__(self) -> None:
        if not 0.0 < self.valid_min_m < self.valid_max_m:
            raise ValueError("depth validity range is invalid")
        if not 0.0 <= self.minimum_valid_fraction < self.full_quality_valid_fraction <= 1.0:
            raise ValueError("depth validity fractions are invalid")
        if not 0.0 < self.hard_near_plane_m < self.caution_near_plane_m:
            raise ValueError("depth near-plane thresholds are invalid")
        if not 0.0 < self.nearest_quantile < 0.5:
            raise ValueError("nearest_quantile must be in (0, 0.5)")
        if not 0.0 < self.roi_fraction <= 1.0:
            raise ValueError("roi_fraction must be in (0, 1]")


@dataclass(frozen=True)
class DepthRiskDecision:
    scale_cap: float
    valid_fraction: float
    nearest_quantile_m: float | None
    quality_scale_cap: float
    near_plane_scale_cap: float
    fail_closed: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scale_cap": self.scale_cap,
            "valid_fraction": self.valid_fraction,
            "nearest_quantile_m": self.nearest_quantile_m,
            "quality_scale_cap": self.quality_scale_cap,
            "near_plane_scale_cap": self.near_plane_scale_cap,
            "fail_closed": self.fail_closed,
            "reasons": list(self.reasons),
        }


def depth_risk_scale_cap(
    depth_m: Any | None,
    *,
    config: DepthSidecarConfig = DepthSidecarConfig(),
) -> DepthRiskDecision:
    """Convert a central metric-depth region into a conservative VLA scale cap."""

    if depth_m is None:
        return _failed("missing_metric_depth")
    import numpy as np

    depth = np.asarray(depth_m, dtype=np.float32)
    if depth.ndim == 3 and depth.shape[-1] == 1:
        depth = depth[..., 0]
    if depth.ndim != 2 or min(depth.shape) < 2:
        return _failed("invalid_depth_shape")
    height, width = depth.shape
    roi_height = max(2, int(round(height * config.roi_fraction)))
    roi_width = max(2, int(round(width * config.roi_fraction)))
    y0 = (height - roi_height) // 2
    x0 = (width - roi_width) // 2
    roi = depth[y0 : y0 + roi_height, x0 : x0 + roi_width]
    valid = np.isfinite(roi) & (roi >= config.valid_min_m) & (roi <= config.valid_max_m)
    valid_fraction = float(valid.mean())
    if valid_fraction < config.minimum_valid_fraction or not bool(valid.any()):
        return DepthRiskDecision(
            scale_cap=0.0,
            valid_fraction=valid_fraction,
            nearest_quantile_m=None,
            quality_scale_cap=0.0,
            near_plane_scale_cap=0.0,
            fail_closed=True,
            reasons=("insufficient_valid_depth",),
        )

    nearest = float(np.quantile(roi[valid], config.nearest_quantile))
    quality_cap = min(
        1.0,
        max(
            0.0,
            (valid_fraction - config.minimum_valid_fraction)
            / (config.full_quality_valid_fraction - config.minimum_valid_fraction),
        ),
    )
    near_plane_cap = min(
        1.0,
        max(
            0.0,
            (nearest - config.hard_near_plane_m)
            / (config.caution_near_plane_m - config.hard_near_plane_m),
        ),
    )
    scale_cap = min(quality_cap, near_plane_cap)
    reasons: list[str] = []
    if quality_cap < 1.0 - 1e-12:
        reasons.append("depth_quality_cap")
    if near_plane_cap < 1.0 - 1e-12:
        reasons.append("depth_near_plane_cap")
    return DepthRiskDecision(
        scale_cap=scale_cap,
        valid_fraction=valid_fraction,
        nearest_quantile_m=nearest,
        quality_scale_cap=quality_cap,
        near_plane_scale_cap=near_plane_cap,
        fail_closed=scale_cap <= 1e-12,
        reasons=tuple(reasons or ("clear_depth_geometry",)),
    )


def _failed(reason: str) -> DepthRiskDecision:
    return DepthRiskDecision(
        scale_cap=0.0,
        valid_fraction=0.0,
        nearest_quantile_m=None,
        quality_scale_cap=0.0,
        near_plane_scale_cap=0.0,
        fail_closed=True,
        reasons=(reason,),
    )
