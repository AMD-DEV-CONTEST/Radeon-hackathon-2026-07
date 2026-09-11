"""Dataset metadata checks used before expensive Radeon training runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .dataset import DEPTH_RGB_KEY


@dataclass(frozen=True)
class DatasetAudit:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    facts: dict[str, Any]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, **asdict(self)}


def audit_lerobot_metadata(
    info: dict[str, Any],
    stats: dict[str, Any] | None,
    *,
    require_depth_rgb: bool = False,
) -> DatasetAudit:
    """Validate the feature contract and catch implausible metric depth."""
    errors: list[str] = []
    warnings: list[str] = []
    features = info.get("features", {})
    required_shapes = {
        "observation.state": (20,),
        "action": (8,),
        "observation.images.overhead_rgb": (224, 224, 3),
    }
    for key, expected in required_shapes.items():
        feature = features.get(key)
        if not isinstance(feature, dict):
            errors.append(f"missing required feature: {key}")
            continue
        actual = tuple(int(value) for value in feature.get("shape", ()))
        if actual != expected:
            errors.append(f"{key} shape is {actual}, expected {expected}")

    depth_feature = features.get("observation.images.overhead_depth")
    has_depth_rgb = DEPTH_RGB_KEY in features
    depth_median_m = None
    if isinstance(depth_feature, dict):
        depth_shape = tuple(int(value) for value in depth_feature.get("shape", ()))
        if len(depth_shape) != 3 or depth_shape[-1] != 1:
            message = (
                "observation.images.overhead_depth must be an HWC single-channel "
                f"feature, received {depth_shape}"
            )
            (errors if require_depth_rgb else warnings).append(message)
        depth_unit = (depth_feature.get("info") or {}).get("depth_unit")
        if depth_unit != "m":
            message = f"metric depth feature must declare info.depth_unit='m', received {depth_unit!r}"
            (errors if require_depth_rgb else warnings).append(message)
        depth_stats = (stats or {}).get("observation.images.overhead_depth", {})
        depth_median_m = _first_number(depth_stats.get("q50"))
        if depth_median_m is None:
            message = "metric depth exists but its median is unavailable"
            (errors if require_depth_rgb else warnings).append(message)
        elif not 0.05 <= depth_median_m <= 20.0:
            message = (
                f"metric depth median {depth_median_m:.6g} m is implausible; "
                "do not use this shard for RGB-D training"
            )
            (errors if require_depth_rgb else warnings).append(message)

    if require_depth_rgb and not isinstance(depth_feature, dict):
        errors.append("RGB-D training requires observation.images.overhead_depth")
    if require_depth_rgb and not has_depth_rgb:
        errors.append(f"RGB-D training requires derived feature: {DEPTH_RGB_KEY}")
    if require_depth_rgb and isinstance(depth_feature, dict) and has_depth_rgb:
        depth_shape = tuple(int(value) for value in depth_feature.get("shape", ()))
        derived_feature = features.get(DEPTH_RGB_KEY)
        derived_shape = tuple(int(value) for value in derived_feature.get("shape", ()))
        expected_derived_shape = depth_shape[:-1] + (3,) if len(depth_shape) == 3 else ()
        if derived_shape != expected_derived_shape:
            errors.append(
                f"{DEPTH_RGB_KEY} shape is {derived_shape}, expected {expected_derived_shape}"
            )
        derived_info = derived_feature.get("info") or {}
        if derived_info.get("derived_from") != "observation.images.overhead_depth":
            errors.append(f"{DEPTH_RGB_KEY} must declare its metric-depth source")

    return DatasetAudit(
        errors=tuple(errors),
        warnings=tuple(warnings),
        facts={
            "total_episodes": int(info.get("total_episodes", 0)),
            "total_frames": int(info.get("total_frames", 0)),
            "has_metric_depth": isinstance(depth_feature, dict),
            "has_depth_rgb": has_depth_rgb,
            "depth_median_m": depth_median_m,
        },
    )


def _first_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        for item in value:
            result = _first_number(item)
            if result is not None:
                return result
    return None
