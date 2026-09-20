"""Optional native-3DGS visual background for BiGym observations.

MuJoCo remains the only physics engine.  The Gaussian files are never attached
to a MuJoCo body and therefore cannot add bodies, geoms, contacts, or collision
behavior.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import mujoco
import numpy as np


@dataclass(frozen=True)
class GaussianRenderBuffers:
    """Host-side buffers with one explicit, metric depth convention."""

    rgb: np.ndarray
    expected_depth_m: np.ndarray | None
    alpha: np.ndarray | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_gaussian_layer_files(
    profile_path: str | Path,
    profile: dict[str, Any],
) -> tuple[dict[str, Path], str, str]:
    """Resolve either the legacy layered shell or one combined PLY.

    Layered profiles retain precedence when both representations are present,
    which preserves the existing DL3DV behavior.  A combined-only profile is
    explicit: it must declare one of the supported combined ground modes and
    an immutable byte/hash contract for the single PLY.
    """

    path = Path(profile_path).expanduser().resolve()
    asset_dir = path.parent
    layer_files = profile.get("layer_files", {})
    if not isinstance(layer_files, dict):
        raise RuntimeError("visual-shell layer_files must be an object")
    ground_visual = profile.get("ground_visual", {})
    if not isinstance(ground_visual, dict):
        raise RuntimeError("visual-shell ground_visual must be an object")
    ground_mode = str(ground_visual.get("mode", "gaussian"))

    def resolve_relative(raw: object) -> Path:
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe visual-shell layer path: {relative}")
        return asset_dir / relative

    has_layered = all(name in layer_files for name in ("walls_decor", "ceiling"))
    if has_layered:
        resolved = {
            "background": resolve_relative(layer_files["walls_decor"]),
            "ceiling": resolve_relative(layer_files["ceiling"]),
        }
        if ground_mode in {"gaussian", "gaussian_with_metric_fallback"}:
            if "floor" not in layer_files:
                raise RuntimeError("layered Gaussian shell is missing floor")
            resolved["floor"] = resolve_relative(layer_files["floor"])
        elif ground_mode != "metric_procedural":
            raise RuntimeError(f"unsupported visual-shell ground mode: {ground_mode}")
        layer_mode = "layered"
    else:
        if "combined" not in layer_files:
            raise RuntimeError(
                "visual-shell profile requires layered files or one combined PLY"
            )
        if ground_mode not in {
            "gaussian_combined",
            "gaussian_combined_with_confidence_fallback",
        }:
            raise RuntimeError(
                "combined-only visual shell requires "
                "ground_visual.mode=gaussian_combined or "
                "gaussian_combined_with_confidence_fallback"
            )
        resolved = {"background": resolve_relative(layer_files["combined"])}
        layer_mode = "combined"

        contract = profile.get("asset")
        if not isinstance(contract, dict):
            raise RuntimeError("combined visual shell requires an asset contract")
        combined_relative = str(layer_files["combined"])
        if str(contract.get("path")) != combined_relative:
            raise RuntimeError("combined PLY path does not match asset contract")
        combined_path = resolved["background"]
        if not combined_path.is_file():
            raise FileNotFoundError(
                f"Gaussian visual-shell layers are missing: {[str(combined_path)]}"
            )
        expected_bytes = int(contract.get("bytes", -1))
        actual_bytes = combined_path.stat().st_size
        if expected_bytes != actual_bytes:
            raise RuntimeError(
                f"combined PLY size mismatch: {actual_bytes} != {expected_bytes}"
            )
        expected_sha256 = str(contract.get("sha256", "")).lower()
        if len(expected_sha256) != 64:
            raise RuntimeError("combined PLY asset contract has invalid SHA-256")
        actual_sha256 = _sha256_file(combined_path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"combined PLY SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
            )

    missing = [
        str(layer_path) for layer_path in resolved.values() if not layer_path.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"Gaussian visual-shell layers are missing: {missing}")
    return resolved, layer_mode, ground_mode


def gaussian_depth_to_meters(
    raw_depth: np.ndarray,
    gaussian_units_per_meter: float,
    *,
    semantics: str,
    alpha: np.ndarray | None = None,
    minimum_alpha: float = 1e-6,
) -> np.ndarray:
    """Convert gsplat ``D`` or ``ED`` output to expected metric z-depth.

    gsplat ``D`` is alpha-accumulated depth and therefore must be divided by
    alpha exactly once. ``ED`` is already normalised. Both are expressed in
    the Gaussian coordinate system and are converted to MuJoCo metres here.
    """

    depth = np.asarray(raw_depth, dtype=np.float64)
    units = float(gaussian_units_per_meter)
    if not np.isfinite(units) or units <= 0.0:
        raise ValueError("gaussian_units_per_meter must be positive and finite")
    if semantics == "accumulated":
        if alpha is None:
            raise ValueError("accumulated Gaussian depth requires alpha")
        opacity = np.asarray(alpha, dtype=np.float64)
        if opacity.shape != depth.shape:
            raise ValueError("Gaussian depth and alpha shapes differ")
        expected = depth / np.maximum(opacity, minimum_alpha)
        expected = np.where(opacity >= minimum_alpha, expected, np.nan)
    elif semantics == "expected":
        expected = depth
    else:
        raise ValueError(f"unsupported Gaussian depth semantics: {semantics}")
    return expected / units


@lru_cache(maxsize=16)
def _metric_ground_pixel_coordinates(
    height: int,
    width: int,
    fovy_degrees: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Cache camera-space pixel coordinates shared by every frame."""

    focal = np.float32(
        0.5 * height / np.tan(np.radians(fovy_degrees) / 2.0)
    )
    pixel_x = (
        np.arange(width, dtype=np.float32) + np.float32(0.5 - width / 2.0)
    ) / focal
    pixel_y = (
        np.arange(height, dtype=np.float32) + np.float32(0.5 - height / 2.0)
    ) / focal
    pixel_x.setflags(write=False)
    pixel_y.setflags(write=False)
    return pixel_x, pixel_y


def metric_ground_projection(
    native_rgb: np.ndarray,
    camera_position_m: np.ndarray,
    camera_rotation_mujoco: np.ndarray,
    fovy_degrees: float,
    config: dict[str, object],
) -> tuple[np.ndarray, np.ndarray]:
    """Render a metric floor and return its camera-Z intersection depth.

    The plane is visual only. Its world-space tile coordinates are derived
    from MuJoCo camera rays, so the floor remains fixed at ``z_m`` as the head
    and wrist cameras move.
    """

    result = np.asarray(native_rgb, dtype=np.uint8).copy()
    if result.ndim != 3 or result.shape[2] != 3:
        raise RuntimeError(f"invalid native RGB for metric ground: {result.shape}")
    position = np.asarray(camera_position_m, dtype=np.float32)
    rotation_mujoco = np.asarray(camera_rotation_mujoco, dtype=np.float32)
    if (
        position.shape != (3,)
        or rotation_mujoco.shape != (3, 3)
        or not np.isfinite(position).all()
        or not np.isfinite(rotation_mujoco).all()
        or not np.isfinite(fovy_degrees)
        or not (1.0 < fovy_degrees < 179.0)
    ):
        raise RuntimeError("invalid camera pose for metric ground")

    height, width = result.shape[:2]
    pixel_x, pixel_y = _metric_ground_pixel_coordinates(
        height,
        width,
        float(fovy_degrees),
    )
    conversion = np.diag(np.asarray([1.0, -1.0, -1.0], dtype=np.float32))
    rotation_cv = rotation_mujoco @ conversion
    x_grid = pixel_x[None, :]
    y_grid = pixel_y[:, None]
    direction_x = (
        x_grid * rotation_cv[0, 0]
        + y_grid * rotation_cv[0, 1]
        + rotation_cv[0, 2]
    )
    direction_y = (
        x_grid * rotation_cv[1, 0]
        + y_grid * rotation_cv[1, 1]
        + rotation_cv[1, 2]
    )
    denominator = (
        x_grid * rotation_cv[2, 0]
        + y_grid * rotation_cv[2, 1]
        + rotation_cv[2, 2]
    )
    floor_z = np.float32(config.get("z_m", 0.0))
    distance = np.full((height, width), np.nan, dtype=np.float32)
    downward = denominator < np.float32(-1e-8)
    distance[downward] = (floor_z - position[2]) / denominator[downward]
    valid = downward & np.isfinite(distance) & (distance > 0.0)
    if not valid.any():
        return result, distance

    world_x = position[0] + distance * direction_x
    world_y = position[1] + distance * direction_y
    tile_size = np.float32(config.get("tile_size_m", 0.60))
    grout_width = np.float32(config.get("grout_width_m", 0.012))
    if not (
        np.isfinite(tile_size)
        and np.isfinite(grout_width)
        and tile_size > 0.0
        and 0.0 < grout_width < tile_size / 4.0
    ):
        raise RuntimeError("invalid metric-ground tile dimensions")
    base = np.asarray(
        config.get("base_rgb", [178, 177, 171]),
        dtype=np.float32,
    )
    grout = np.asarray(
        config.get("grout_rgb", [138, 138, 134]),
        dtype=np.float32,
    )
    if base.shape != (3,) or grout.shape != (3,):
        raise RuntimeError("metric-ground colors must contain three channels")

    safe_world_x = np.where(valid, world_x, 0.0)
    safe_world_y = np.where(valid, world_y, 0.0)
    tile_x = np.floor(safe_world_x / tile_size).astype(np.int32)
    tile_y = np.floor(safe_world_y / tile_size).astype(np.int32)
    checker = ((tile_x + tile_y) & 1).astype(np.float32)
    variation = (checker * 2.0 - 1.0) * np.float32(
        config.get("tile_variation", 3.0)
    )
    color = np.broadcast_to(base, (height, width, 3)).copy()
    color += variation[..., None]
    local_x = np.mod(safe_world_x, tile_size)
    local_y = np.mod(safe_world_y, tile_size)
    on_grout = (
        (local_x < grout_width)
        | (local_x > tile_size - grout_width)
        | (local_y < grout_width)
        | (local_y > tile_size - grout_width)
    )
    color[on_grout] = grout
    result[valid] = np.clip(color[valid], 0.0, 255.0).astype(np.uint8)
    return result, distance


def metric_ground_background(
    native_rgb: np.ndarray,
    camera_position_m: np.ndarray,
    camera_rotation_mujoco: np.ndarray,
    fovy_degrees: float,
    config: dict[str, object],
) -> np.ndarray:
    """Return the visual-only metric floor background image."""

    rendered, _depth = metric_ground_projection(
        native_rgb,
        camera_position_m,
        camera_rotation_mujoco,
        fovy_degrees,
        config,
    )
    return rendered


def replace_native_floor_leakage(
    rendered_rgb: np.ndarray,
    native_rgb: np.ndarray,
    metric_ground_rgb: np.ndarray,
    native_floor_mask: np.ndarray,
    threshold_rgb: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Replace only weak Gaussian coverage over the native MuJoCo floor."""

    rendered = np.asarray(rendered_rgb, dtype=np.uint8)
    native = np.asarray(native_rgb, dtype=np.uint8)
    metric = np.asarray(metric_ground_rgb, dtype=np.uint8)
    floor_mask = np.asarray(native_floor_mask, dtype=bool)
    if (
        rendered.shape != native.shape
        or rendered.shape != metric.shape
        or rendered.ndim != 3
        or rendered.shape[2] != 3
        or floor_mask.shape != rendered.shape[:2]
    ):
        raise RuntimeError("invalid arrays for native-floor leakage replacement")
    if not np.isfinite(threshold_rgb) or threshold_rgb < 0.0:
        raise RuntimeError("native-floor leakage threshold must be non-negative")
    influence = np.mean(
        np.abs(rendered.astype(np.int16) - native.astype(np.int16)),
        axis=2,
    )
    replacement = floor_mask & (influence <= threshold_rgb)
    result = rendered.copy()
    result[replacement] = metric[replacement]
    return result, replacement


def replace_native_floor_with_metric_ground(
    rendered_rgb: np.ndarray,
    metric_ground_rgb: np.ndarray,
    native_floor_mask: np.ndarray,
    gaussian_depth_m: np.ndarray,
    metric_ground_depth_m: np.ndarray,
    depth_tolerance_m: float = 0.02,
) -> np.ndarray:
    """Insert metric ground unless a closer Gaussian surface occludes it."""

    rendered = np.asarray(rendered_rgb, dtype=np.uint8)
    metric = np.asarray(metric_ground_rgb, dtype=np.uint8)
    floor_mask = np.asarray(native_floor_mask, dtype=bool)
    gaussian_depth = np.asarray(gaussian_depth_m, dtype=np.float64)
    metric_depth = np.asarray(metric_ground_depth_m, dtype=np.float64)
    if (
        rendered.shape != metric.shape
        or rendered.ndim != 3
        or rendered.shape[2] != 3
        or floor_mask.shape != rendered.shape[:2]
        or gaussian_depth.shape != rendered.shape[:2]
        or metric_depth.shape != rendered.shape[:2]
    ):
        raise RuntimeError("invalid arrays for metric-ground floor replacement")
    if not np.isfinite(depth_tolerance_m) or depth_tolerance_m < 0.0:
        raise RuntimeError("invalid metric-ground depth tolerance")
    valid_metric = np.isfinite(metric_depth) & (metric_depth > 0.0)
    valid_gaussian = np.isfinite(gaussian_depth) & (gaussian_depth > 0.0)
    ground_visible = (
        floor_mask
        & valid_metric
        & (~valid_gaussian | (gaussian_depth >= metric_depth - depth_tolerance_m))
    )
    result = rendered.copy()
    result[ground_visible] = metric[ground_visible]
    return result


def neutralize_blue_native_floor(
    rendered_rgb: np.ndarray,
    native_floor_mask: np.ndarray,
    low_blue_dominance: float = 6.0,
    high_blue_dominance: float = 35.0,
) -> np.ndarray:
    """Turn the native blue checker floor into a neutral metric surface."""

    rendered = np.asarray(rendered_rgb, dtype=np.uint8)
    floor_mask = np.asarray(native_floor_mask, dtype=bool)
    if (
        rendered.ndim != 3
        or rendered.shape[2] != 3
        or floor_mask.shape != rendered.shape[:2]
    ):
        raise RuntimeError("invalid arrays for native-floor neutralization")
    if not (
        np.isfinite(low_blue_dominance)
        and np.isfinite(high_blue_dominance)
        and 0.0 <= low_blue_dominance < high_blue_dominance
    ):
        raise RuntimeError("invalid blue-dominance neutralization thresholds")
    source = rendered.astype(np.float64)
    blue_dominance = source[..., 2] - np.maximum(
        source[..., 0],
        source[..., 1],
    )
    weight = np.clip(
        (blue_dominance - low_blue_dominance)
        / (high_blue_dominance - low_blue_dominance),
        0.0,
        1.0,
    )
    weight = weight * weight * (3.0 - 2.0 * weight)
    weight *= floor_mask
    luma = 0.2126 * source[..., 0] + 0.7152 * source[..., 1] + 0.0722 * source[..., 2]
    neutral = np.stack([1.02 * luma, luma, 0.98 * luma], axis=2)
    result = source * (1.0 - weight[..., None]) + neutral * weight[..., None]
    return np.clip(result, 0.0, 255.0).astype(np.uint8)


def suppress_low_confidence_gaussians(
    rendered_rgb: np.ndarray,
    fallback_rgb: np.ndarray,
    alpha: np.ndarray,
    native_floor_mask: np.ndarray,
    *,
    alpha_replace: float,
    alpha_keep: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Keep opaque Gaussian structure and replace uncertain coverage.

    ``rendered_rgb`` is the Gaussian result already composited over
    ``fallback_rgb``.  A smoothstep alpha gate attenuates semi-transparent
    splats a second time, which removes fog and low-opacity edge clouds while
    preserving opaque walls and cabinets.  Pixels that MuJoCo identifies as
    its floor always use the stable metric visual floor.  This function only
    changes RGB pixels and cannot affect MuJoCo physics.

    The returned confidence map is the final Gaussian contribution in
    ``[0, 1]`` and is useful for receipts and diagnostic heatmaps.
    """

    rendered = np.asarray(rendered_rgb, dtype=np.uint8)
    fallback = np.asarray(fallback_rgb, dtype=np.uint8)
    opacity = np.asarray(alpha, dtype=np.float64)
    floor = np.asarray(native_floor_mask, dtype=bool)
    if (
        rendered.ndim != 3
        or rendered.shape[2] != 3
        or fallback.shape != rendered.shape
        or opacity.shape != rendered.shape[:2]
        or floor.shape != rendered.shape[:2]
    ):
        raise RuntimeError("invalid arrays for low-confidence Gaussian suppression")
    replace = float(alpha_replace)
    keep = float(alpha_keep)
    if not (
        np.isfinite(replace) and np.isfinite(keep) and 0.0 <= replace < keep <= 1.0
    ):
        raise RuntimeError(
            "Gaussian confidence thresholds must satisfy "
            "0 <= alpha_replace < alpha_keep <= 1"
        )
    if not np.isfinite(opacity).all():
        raise RuntimeError("Gaussian alpha contains non-finite values")

    confidence = np.clip((opacity - replace) / (keep - replace), 0.0, 1.0)
    confidence = confidence * confidence * (3.0 - 2.0 * confidence)
    confidence[floor] = 0.0
    source = rendered.astype(np.float64)
    target = fallback.astype(np.float64)
    result = source * confidence[..., None] + target * (1.0 - confidence[..., None])
    return np.clip(result, 0.0, 255.0).astype(np.uint8), confidence


def select_confident_gaussians_or_fallback(
    rendered_rgb: np.ndarray,
    fallback_rgb: np.ndarray,
    alpha: np.ndarray,
    native_floor_mask: np.ndarray,
    *,
    alpha_keep: float,
    floor_policy: str = "always_metric",
    gaussian_depth_m: np.ndarray | None = None,
    metric_ground_depth_m: np.ndarray | None = None,
    floor_depth_tolerance_m: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Select an opaque Gaussian pixel or the fallback without re-blending.

    ``rendered_rgb`` has already been composited by gsplat over
    ``fallback_rgb``.  Blending it again by alpha makes MuJoCo assets and weak
    Gaussian regions look translucent.  The hard-opaque contract therefore
    makes a binary choice: keep a sufficiently opaque renderer result, or use
    the fallback. Native floor pixels use the metric visual floor by default.
    A profile may instead retain only high-alpha Gaussian floor pixels whose
    calibrated metric depth agrees with the world-locked floor plane.

    The returned confidence map is binary and records which pixels retained
    the Gaussian renderer result.  This is an RGB-only operation and cannot
    affect MuJoCo physics.
    """

    rendered = np.asarray(rendered_rgb, dtype=np.uint8)
    fallback = np.asarray(fallback_rgb, dtype=np.uint8)
    opacity = np.asarray(alpha, dtype=np.float64)
    floor = np.asarray(native_floor_mask, dtype=bool)
    if (
        rendered.ndim != 3
        or rendered.shape[2] != 3
        or fallback.shape != rendered.shape
        or opacity.shape != rendered.shape[:2]
        or floor.shape != rendered.shape[:2]
    ):
        raise RuntimeError("invalid arrays for hard-opaque Gaussian selection")
    keep = float(alpha_keep)
    if not np.isfinite(keep) or not 0.0 <= keep <= 1.0:
        raise RuntimeError("Gaussian alpha_keep must satisfy 0 <= value <= 1")
    if not np.isfinite(opacity).all():
        raise RuntimeError("Gaussian alpha contains non-finite values")

    if floor_policy == "always_metric":
        floor_allowed = np.zeros(floor.shape, dtype=bool)
    elif floor_policy == "gaussian_if_depth_consistent":
        if gaussian_depth_m is None or metric_ground_depth_m is None:
            raise RuntimeError(
                "depth-consistent Gaussian floor requires both depth buffers"
            )
        gaussian_depth = np.asarray(gaussian_depth_m, dtype=np.float64)
        metric_depth = np.asarray(metric_ground_depth_m, dtype=np.float64)
        tolerance = float(floor_depth_tolerance_m)
        if (
            gaussian_depth.shape != floor.shape
            or metric_depth.shape != floor.shape
            or not np.isfinite(tolerance)
            or tolerance <= 0.0
        ):
            raise RuntimeError("invalid depth-consistent Gaussian floor inputs")
        floor_allowed = (
            floor
            & np.isfinite(gaussian_depth)
            & np.isfinite(metric_depth)
            & (np.abs(gaussian_depth - metric_depth) <= tolerance)
        )
    else:
        raise RuntimeError(f"unsupported floor confidence policy: {floor_policy}")
    selected = (opacity >= keep) & (~floor | floor_allowed)
    result = fallback.copy()
    result[selected] = rendered[selected]
    return result, selected.astype(np.float64)


def gaussian_exclusion_mask(
    xyz_gaussian: np.ndarray,
    gaussian_to_mujoco: np.ndarray,
    boxes_mujoco: list[dict[str, object]],
) -> np.ndarray:
    """Return Gaussians inside visual-only exclusion boxes in MuJoCo world.

    Exclusion is applied to renderer opacity only. It cannot create or modify
    MuJoCo bodies, geoms, contacts, or collision properties.
    """

    xyz = np.asarray(xyz_gaussian, dtype=np.float64)
    transform = np.asarray(gaussian_to_mujoco, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise RuntimeError("invalid Gaussian xyz for visual exclusion")
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise RuntimeError("gaussian_to_mujoco must be a finite 4x4 matrix")
    world = xyz @ transform[:3, :3].T + transform[:3, 3]
    excluded = np.zeros(xyz.shape[0], dtype=bool)
    for box in boxes_mujoco:
        lower = np.asarray(box.get("min_m"), dtype=np.float64)
        upper = np.asarray(box.get("max_m"), dtype=np.float64)
        if (
            lower.shape != (3,)
            or upper.shape != (3,)
            or not np.isfinite(lower).all()
            or not np.isfinite(upper).all()
            or np.any(lower >= upper)
        ):
            raise RuntimeError("invalid MuJoCo Gaussian exclusion box")
        excluded |= np.all((world >= lower) & (world <= upper), axis=1)
    return excluded


def camera_pose_coverage(
    source_positions_m: np.ndarray,
    source_rotations_cv: np.ndarray,
    query_position_m: np.ndarray,
    query_rotation_cv: np.ndarray,
    *,
    translation_m: float,
    rotation_degrees: float,
) -> dict[str, object]:
    """Measure one camera pose against the immutable capture trajectory.

    A pose passes only when the *same* source image satisfies both limits.
    This prevents a misleading result where one source frame is nearby in
    translation while an unrelated frame happens to have a similar rotation.
    """

    positions = np.asarray(source_positions_m, dtype=np.float64)
    rotations = np.asarray(source_rotations_cv, dtype=np.float64)
    position = np.asarray(query_position_m, dtype=np.float64)
    rotation = np.asarray(query_rotation_cv, dtype=np.float64)
    maximum_translation = float(translation_m)
    maximum_rotation = float(rotation_degrees)
    if (
        positions.ndim != 2
        or positions.shape[1] != 3
        or rotations.shape != (len(positions), 3, 3)
        or len(positions) == 0
        or position.shape != (3,)
        or rotation.shape != (3, 3)
        or not np.isfinite(positions).all()
        or not np.isfinite(rotations).all()
        or not np.isfinite(position).all()
        or not np.isfinite(rotation).all()
    ):
        raise RuntimeError("invalid camera poses for source-view coverage")
    if (
        not np.isfinite(maximum_translation)
        or maximum_translation <= 0.0
        or not np.isfinite(maximum_rotation)
        or not 0.0 < maximum_rotation <= 180.0
    ):
        raise RuntimeError("camera coverage thresholds must be positive")

    distances = np.linalg.norm(positions - position[None], axis=1)
    relative = np.einsum("nij,jk->nik", rotations.transpose(0, 2, 1), rotation)
    traces = np.trace(relative, axis1=1, axis2=2)
    angles = np.degrees(np.arccos(np.clip((traces - 1.0) * 0.5, -1.0, 1.0)))
    normalized = np.maximum(
        distances / maximum_translation,
        angles / maximum_rotation,
    )
    selected = int(np.argmin(normalized))
    passed = bool(
        distances[selected] <= maximum_translation
        and angles[selected] <= maximum_rotation
    )
    return {
        "passed": passed,
        "source_camera_index": selected,
        "translation_m": float(distances[selected]),
        "rotation_degrees": float(angles[selected]),
        "translation_threshold_m": maximum_translation,
        "rotation_threshold_degrees": maximum_rotation,
        "normalized_joint_score": float(normalized[selected]),
    }


class GaussianVisualShell:
    """Render a static Gaussian shell behind native MuJoCo geometry."""

    def __init__(
        self,
        profile_path: str | Path,
        model: mujoco.MjModel,
        *,
        strict: bool = True,
    ) -> None:
        self.profile_path = Path(profile_path).expanduser().resolve()
        self.strict = strict
        self.profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        asset_dir = self.profile_path.parent
        alignment_name = self.profile.get("alignment", {}).get("path", "alignment.json")
        alignment = json.loads((asset_dir / alignment_name).read_text(encoding="utf-8"))
        self.mujoco_to_gaussian = np.asarray(
            alignment["mujoco_to_gaussian"], dtype=np.float64
        )
        if self.mujoco_to_gaussian.shape != (4, 4):
            raise RuntimeError("mujoco_to_gaussian must be a 4x4 matrix")

        self.ground_visual = self.profile.get("ground_visual", {})
        self.confidence_compositing = str(
            self.ground_visual.get(
                "confidence_compositing",
                "legacy_smooth",
            )
        )
        if self.confidence_compositing not in {
            "legacy_smooth",
            "hard_opaque",
        }:
            raise RuntimeError(
                "unsupported confidence compositing mode: "
                f"{self.confidence_compositing}"
            )
        self.floor_confidence_policy = str(
            self.ground_visual.get("floor_confidence_policy", "always_metric")
        )
        if self.floor_confidence_policy not in {
            "always_metric",
            "gaussian_if_depth_consistent",
        }:
            raise RuntimeError(
                f"unsupported floor confidence policy: {self.floor_confidence_policy}"
            )
        resolved, self.layer_mode, self.ground_mode = resolve_gaussian_layer_files(
            self.profile_path, self.profile
        )

        import torch
        from gaussian_renderer.gs_renderer_mujoco import GSRendererMuJoCo

        if not torch.cuda.is_available() or torch.version.hip is None:
            raise RuntimeError(
                "Gaussian visual shell requires a ROCm-enabled PyTorch accelerator"
            )
        self.torch = torch
        self.renderer: Any = GSRendererMuJoCo(
            {f"__visual_shell_{name}__": str(path) for name, path in resolved.items()},
            model,
        )
        if len(self.renderer.gs_body_ids) != 0:
            raise RuntimeError("static Gaussian shell unexpectedly mapped to a body")
        integration_contract = self.profile.get("integration_contract", {})
        self.native_background_geom_names = tuple(
            str(name)
            for name in integration_contract.get(
                "native_background_geom_names",
                ["floor"],
            )
        )
        self.native_background_geom_ids = {
            int(geom_id)
            for name in self.native_background_geom_names
            if (
                geom_id := mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_GEOM,
                    name,
                )
            )
            >= 0
        }
        self.foreground_policy = str(
            integration_contract.get(
                "foreground_policy",
                "all_except_background",
            )
        )
        if self.foreground_policy not in {
            "all_except_background",
            "dynamic_only",
            "dynamic_plus_selected_static",
        }:
            raise RuntimeError(
                f"unsupported visual-shell foreground policy: {self.foreground_policy}"
            )
        self.depth_semantics = str(
            integration_contract.get("depth_semantics", "accumulated")
        )
        if self.depth_semantics != "accumulated":
            raise RuntimeError(
                "gaussian_renderer 0.2.0 uses gsplat RGB+D; "
                f"expected accumulated depth, got {self.depth_semantics}"
            )
        dynamic_bodies = np.zeros(model.nbody, dtype=bool)
        for body_id in range(1, model.nbody):
            cursor = body_id
            while cursor > 0:
                if model.body_jntnum[cursor] > 0:
                    dynamic_bodies[body_id] = True
                    break
                cursor = int(model.body_parentid[cursor])
        self.dynamic_foreground_geom_ids = {
            int(geom_id)
            for geom_id, body_id in enumerate(model.geom_bodyid)
            if dynamic_bodies[int(body_id)]
        }
        self.static_foreground_geom_name_prefixes = tuple(
            str(prefix)
            for prefix in integration_contract.get(
                "static_foreground_geom_name_prefixes",
                [],
            )
        )
        self.selected_static_foreground_geom_ids = {
            int(geom_id)
            for geom_id in range(model.ngeom)
            if geom_id not in self.dynamic_foreground_geom_ids
            and (
                name := mujoco.mj_id2name(
                    model,
                    mujoco.mjtObj.mjOBJ_GEOM,
                    geom_id,
                )
            )
            is not None
            and any(
                name.startswith(prefix)
                for prefix in self.static_foreground_geom_name_prefixes
            )
        }
        self.gaussian_exclusion_boxes_mujoco = list(
            integration_contract.get("gaussian_exclusion_boxes_mujoco", [])
        )
        self.excluded_gaussian_count = 0
        if self.gaussian_exclusion_boxes_mujoco:
            excluded = gaussian_exclusion_mask(
                self.renderer.gaussians.xyz.detach().cpu().numpy(),
                np.linalg.inv(self.mujoco_to_gaussian),
                self.gaussian_exclusion_boxes_mujoco,
            )
            excluded_tensor = self.torch.as_tensor(
                excluded,
                dtype=self.torch.bool,
                device=self.renderer.gaussians.device,
            )
            with self.torch.no_grad():
                self.renderer.gaussians.opacity[excluded_tensor] = 0.0
            self.excluded_gaussian_count = int(excluded.sum())
        self.camera_coverage_gate = integration_contract.get("camera_coverage_gate")
        self.source_camera_positions_m: np.ndarray | None = None
        self.source_camera_rotations_cv: np.ndarray | None = None
        self.camera_coverage_thresholds: dict[str, dict[str, float]] = {}
        self.camera_coverage_gate_total = 0
        self.camera_coverage_gate_passed = 0
        self.camera_coverage_gate_fallback = 0
        self.gaussian_rendered_frames = 0
        self.camera_coverage_per_camera: dict[str, dict[str, object]] = {}
        if self.camera_coverage_gate is not None:
            if not isinstance(self.camera_coverage_gate, dict):
                raise RuntimeError("camera_coverage_gate must be an object")
            if self.camera_coverage_gate.get("mode") != "whole_camera_hard_fallback":
                raise RuntimeError("unsupported camera coverage gate mode")
            if (
                self.camera_coverage_gate.get("fallback")
                != "native_rgb_with_metric_floor"
            ):
                raise RuntimeError("unsupported camera coverage fallback")
            if self.ground_mode != "gaussian_combined_with_confidence_fallback":
                raise RuntimeError(
                    "camera coverage gate requires combined confidence fallback"
                )
            capture_contract = self.profile.get("capture_path", {})
            capture_name = self.camera_coverage_gate.get(
                "camera_path",
                capture_contract.get("path"),
            )
            if not capture_name:
                raise RuntimeError("camera coverage gate requires camera_path")
            relative_capture = Path(str(capture_name))
            if relative_capture.is_absolute() or ".." in relative_capture.parts:
                raise RuntimeError("unsafe camera coverage path")
            capture_path = asset_dir / relative_capture
            if not capture_path.is_file():
                raise FileNotFoundError(capture_path)
            expected_capture_sha = str(capture_contract.get("sha256", "")).lower()
            if len(expected_capture_sha) == 64:
                actual_capture_sha = _sha256_file(capture_path)
                if actual_capture_sha != expected_capture_sha:
                    raise RuntimeError("camera path SHA-256 mismatch")
            payload = json.loads(capture_path.read_text(encoding="utf-8"))
            source_cameras = np.asarray(payload.get("camtoworlds"), dtype=np.float64)
            if (
                source_cameras.ndim != 3
                or source_cameras.shape[1:] != (4, 4)
                or len(source_cameras) == 0
                or not np.isfinite(source_cameras).all()
            ):
                raise RuntimeError("invalid source camera path")
            gaussian_to_mujoco = np.linalg.inv(self.mujoco_to_gaussian)
            linear = gaussian_to_mujoco[:3, :3]
            scale = float(np.mean(np.linalg.norm(linear, axis=0)))
            if not np.isfinite(scale) or scale <= 0.0:
                raise RuntimeError("invalid Gaussian-to-MuJoCo camera scale")
            world_rotation = linear / scale
            if not np.allclose(
                world_rotation.T @ world_rotation,
                np.eye(3),
                atol=1e-5,
            ):
                raise RuntimeError("Gaussian-to-MuJoCo camera rotation is not rigid")
            self.source_camera_positions_m = (
                source_cameras[:, :3, 3] @ linear.T + gaussian_to_mujoco[:3, 3]
            )
            self.source_camera_rotations_cv = np.einsum(
                "ij,njk->nik",
                world_rotation,
                source_cameras[:, :3, :3],
            )
            thresholds = self.camera_coverage_gate.get("thresholds", {})
            if not isinstance(thresholds, dict) or not thresholds:
                raise RuntimeError("camera coverage gate requires thresholds")
            for camera_name, limits in thresholds.items():
                if not isinstance(limits, dict):
                    raise TypeError("camera coverage threshold must be an object")
                translation = float(limits.get("translation_m", 0.0))
                rotation = float(limits.get("rotation_degrees", 0.0))
                if (
                    not np.isfinite(translation)
                    or translation <= 0.0
                    or not np.isfinite(rotation)
                    or not 0.0 < rotation <= 180.0
                ):
                    raise RuntimeError("invalid camera coverage threshold")
                self.camera_coverage_thresholds[str(camera_name)] = {
                    "translation_m": translation,
                    "rotation_degrees": rotation,
                }
        self.rendered_frames = 0
        self.last_error: str | None = None

    def _camera_coverage_decision(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        camera_id: int,
    ) -> dict[str, object] | None:
        if self.camera_coverage_gate is None:
            return None
        camera_name = mujoco.mj_id2name(
            model,
            mujoco.mjtObj.mjOBJ_CAMERA,
            camera_id,
        )
        logical_names = [
            name
            for name in self.camera_coverage_thresholds
            if camera_name == name
            or (camera_name is not None and camera_name.endswith(f"/{name}"))
        ]
        if camera_name is None or len(logical_names) != 1:
            raise RuntimeError(
                f"camera coverage gate has no threshold for {camera_name!r}"
            )
        logical_name = logical_names[0]
        assert self.source_camera_positions_m is not None
        assert self.source_camera_rotations_cv is not None
        conversion = np.diag([1.0, -1.0, -1.0])
        query_rotation_cv = (
            np.asarray(
                data.cam_xmat[camera_id],
                dtype=np.float64,
            ).reshape(3, 3)
            @ conversion
        )
        limits = self.camera_coverage_thresholds[logical_name]
        decision = camera_pose_coverage(
            self.source_camera_positions_m,
            self.source_camera_rotations_cv,
            np.asarray(data.cam_xpos[camera_id], dtype=np.float64),
            query_rotation_cv,
            translation_m=limits["translation_m"],
            rotation_degrees=limits["rotation_degrees"],
        )
        decision["camera"] = logical_name
        decision["mujoco_camera"] = camera_name
        return decision

    def native_foreground_mask(
        self,
        segmentation: np.ndarray,
    ) -> np.ndarray:
        """Return pixels belonging to MuJoCo foreground geoms.

        MuJoCo segmentation stores ``(object id, object type)``.  Native floor
        geoms are intentionally treated as background so that the Gaussian
        room floor remains visible, while the robot, table, props, and other
        task geometry are composited in front of the Gaussian renderer.
        """

        segmentation = np.asarray(segmentation)
        if segmentation.ndim != 3 or segmentation.shape[-1] != 2:
            raise RuntimeError(
                f"invalid MuJoCo segmentation image: {segmentation.shape}"
            )
        object_id = segmentation[..., 0]
        object_type = segmentation[..., 1]
        foreground = (object_id >= 0) & (object_type == int(mujoco.mjtObj.mjOBJ_GEOM))
        if (
            getattr(self, "foreground_policy", "all_except_background")
            == "dynamic_only"
        ):
            dynamic_ids = getattr(
                self,
                "dynamic_foreground_geom_ids",
                set(),
            )
            foreground &= np.isin(
                object_id,
                np.fromiter(dynamic_ids, dtype=np.int64),
            )
        elif (
            getattr(self, "foreground_policy", "all_except_background")
            == "dynamic_plus_selected_static"
        ):
            selected_ids = set(
                getattr(self, "dynamic_foreground_geom_ids", set())
            ) | set(
                getattr(
                    self,
                    "selected_static_foreground_geom_ids",
                    set(),
                )
            )
            foreground &= np.isin(
                object_id,
                np.fromiter(selected_ids, dtype=np.int64),
            )
        for geom_id in self.native_background_geom_ids:
            foreground &= object_id != geom_id
        return foreground

    def native_floor_mask(self, segmentation: np.ndarray) -> np.ndarray:
        """Return pixels whose nearest native MuJoCo geom is a floor."""

        segmentation = np.asarray(segmentation)
        if segmentation.ndim != 3 or segmentation.shape[-1] != 2:
            raise RuntimeError(
                f"invalid MuJoCo segmentation image: {segmentation.shape}"
            )
        object_id = segmentation[..., 0]
        object_type = segmentation[..., 1]
        floor = np.zeros(object_id.shape, dtype=bool)
        for geom_id in self.native_background_geom_ids:
            floor |= (object_id == geom_id) & (
                object_type == int(mujoco.mjtObj.mjOBJ_GEOM)
            )
        return floor

    def _camera_in_gaussian_frame(
        self,
        data: mujoco.MjData,
        camera_id: int,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        position_metric = np.asarray(data.cam_xpos[camera_id], dtype=np.float64)
        rotation_mujoco_metric = np.asarray(
            data.cam_xmat[camera_id], dtype=np.float64
        ).reshape(3, 3)
        conversion = np.diag([1.0, -1.0, -1.0])
        rotation_cv_metric = rotation_mujoco_metric @ conversion
        rigid_inverse = self.mujoco_to_gaussian[:3, :3]
        inverse_scale = float(np.mean(np.linalg.norm(rigid_inverse, axis=1)))
        if not np.isfinite(inverse_scale) or inverse_scale <= 0.0:
            raise RuntimeError("invalid Sim(3) inverse scale")
        inverse_rotation = rigid_inverse / inverse_scale
        position_gaussian = (
            rigid_inverse @ position_metric + self.mujoco_to_gaussian[:3, 3]
        )
        rotation_cv_gaussian = inverse_rotation @ rotation_cv_metric
        rotation_mujoco_gaussian = rotation_cv_gaussian @ conversion
        return (
            position_gaussian,
            rotation_mujoco_gaussian.reshape(9),
            inverse_scale,
        )

    def render_rgb(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        camera_id: int,
        native_rgb: np.ndarray,
        native_foreground_mask: np.ndarray | None = None,
        native_floor_mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """Composite MuJoCo task geometry over the Gaussian room shell."""

        try:
            height, width = native_rgb.shape[:2]
            if native_foreground_mask is not None:
                native_foreground_mask = np.asarray(
                    native_foreground_mask,
                    dtype=bool,
                )
                if native_foreground_mask.shape != (height, width):
                    raise RuntimeError(
                        "native foreground mask has invalid shape: "
                        f"{native_foreground_mask.shape}"
                    )
            if native_floor_mask is not None:
                native_floor_mask = np.asarray(native_floor_mask, dtype=bool)
                if native_floor_mask.shape != (height, width):
                    raise RuntimeError(
                        "native floor mask has invalid shape: "
                        f"{native_floor_mask.shape}"
                    )
            background_rgb = native_rgb
            metric_ground_rgb: np.ndarray | None = None
            metric_ground_depth_m: np.ndarray | None = None
            confidence_fallback_rgb: np.ndarray | None = None
            if self.ground_mode in {
                "metric_procedural",
                "gaussian_with_metric_fallback",
                "gaussian_combined_with_confidence_fallback",
            }:
                metric_ground_rgb, metric_ground_depth_m = metric_ground_projection(
                    native_rgb,
                    np.asarray(
                        data.cam_xpos[camera_id],
                        dtype=np.float64,
                    ),
                    np.asarray(
                        data.cam_xmat[camera_id],
                        dtype=np.float64,
                    ).reshape(3, 3),
                    float(model.cam_fovy[camera_id]),
                    self.ground_visual,
                )
            if self.ground_mode == "metric_procedural":
                assert metric_ground_rgb is not None
                background_rgb = metric_ground_rgb
            elif self.ground_mode == "gaussian_with_metric_fallback":
                hybrid_compositing = self.ground_visual.get(
                    "hybrid_compositing",
                    "native_floor_blue_neutralization",
                )
                if hybrid_compositing in {
                    "native_floor_leakage_replacement",
                    "native_floor_blue_neutralization",
                }:
                    background_rgb = native_rgb
                else:
                    assert metric_ground_rgb is not None
                    background_rgb = metric_ground_rgb
            elif self.ground_mode == "gaussian_combined_with_confidence_fallback":
                if native_floor_mask is None or metric_ground_rgb is None:
                    raise RuntimeError(
                        "combined confidence fallback requires a native floor mask"
                    )
                confidence_fallback_rgb = native_rgb.copy()
                confidence_fallback_rgb[native_floor_mask] = metric_ground_rgb[
                    native_floor_mask
                ]
                background_rgb = confidence_fallback_rgb
            coverage_decision = self._camera_coverage_decision(
                model,
                data,
                camera_id,
            )
            if coverage_decision is not None:
                camera_name = str(coverage_decision["camera"])
                self.camera_coverage_gate_total += 1
                camera_status = self.camera_coverage_per_camera.setdefault(
                    camera_name,
                    {"total": 0, "passed": 0, "fallback": 0},
                )
                camera_status["total"] = int(camera_status["total"]) + 1
                camera_status["last"] = coverage_decision
                if bool(coverage_decision["passed"]):
                    self.camera_coverage_gate_passed += 1
                    camera_status["passed"] = int(camera_status["passed"]) + 1
                else:
                    if confidence_fallback_rgb is None:
                        raise RuntimeError(
                            "camera coverage fallback image is unavailable"
                        )
                    self.camera_coverage_gate_fallback += 1
                    camera_status["fallback"] = int(camera_status["fallback"]) + 1
                    self.rendered_frames += 1
                    self.last_error = None
                    return confidence_fallback_rgb
            needs_metric_depth = self.ground_mode == "metric_procedural" or (
                self.ground_mode == "gaussian_combined_with_confidence_fallback"
                and self.floor_confidence_policy == "gaussian_if_depth_consistent"
            )
            needs_confidence_alpha = (
                self.ground_mode == "gaussian_combined_with_confidence_fallback"
            )
            buffers = self.render_buffers(
                model,
                data,
                camera_id,
                height,
                width,
                background_rgb=background_rgb,
                include_expected_depth=needs_metric_depth,
                include_alpha=needs_confidence_alpha,
            )
            self.gaussian_rendered_frames += 1
            result = buffers.rgb
            if result.shape != native_rgb.shape or result.dtype != np.uint8:
                raise RuntimeError(
                    f"invalid composed RGB: {result.shape} {result.dtype}"
                )
            if self.ground_mode == "gaussian_with_metric_fallback":
                hybrid_compositing = self.ground_visual.get(
                    "hybrid_compositing",
                    "native_floor_blue_neutralization",
                )
                if hybrid_compositing == "native_floor_leakage_replacement":
                    if native_floor_mask is None or metric_ground_rgb is None:
                        raise RuntimeError(
                            "hybrid leakage replacement requires a native floor mask"
                        )
                    result, _replacement = replace_native_floor_leakage(
                        result,
                        native_rgb,
                        metric_ground_rgb,
                        native_floor_mask,
                        float(
                            self.ground_visual.get(
                                "native_floor_leakage_threshold_rgb",
                                30.0,
                            )
                        ),
                    )
                elif hybrid_compositing == "native_floor_blue_neutralization":
                    if native_floor_mask is None:
                        raise RuntimeError(
                            "hybrid floor neutralization requires a native floor mask"
                        )
                    result = neutralize_blue_native_floor(
                        result,
                        native_floor_mask,
                        float(
                            self.ground_visual.get(
                                "low_blue_dominance",
                                6.0,
                            )
                        ),
                        float(
                            self.ground_visual.get(
                                "high_blue_dominance",
                                35.0,
                            )
                        ),
                    )
            elif self.ground_mode == "metric_procedural":
                if (
                    native_floor_mask is None
                    or metric_ground_rgb is None
                    or metric_ground_depth_m is None
                ):
                    raise RuntimeError(
                        "metric procedural ground requires a native floor mask"
                    )
                if buffers.expected_depth_m is None:
                    raise RuntimeError("metric ground requires Gaussian depth")
                gaussian_depth_m = buffers.expected_depth_m
                result = replace_native_floor_with_metric_ground(
                    result,
                    metric_ground_rgb,
                    native_floor_mask,
                    gaussian_depth_m,
                    metric_ground_depth_m,
                    float(
                        self.ground_visual.get(
                            "depth_tolerance_m",
                            0.02,
                        )
                    ),
                )
            elif self.ground_mode == "gaussian_combined_with_confidence_fallback":
                if native_floor_mask is None or confidence_fallback_rgb is None:
                    raise RuntimeError(
                        "combined confidence fallback requires a native floor mask"
                    )
                if buffers.alpha is None:
                    raise RuntimeError(
                        "combined confidence fallback requires Gaussian alpha"
                    )
                if self.confidence_compositing == "hard_opaque":
                    result, _confidence = select_confident_gaussians_or_fallback(
                        result,
                        confidence_fallback_rgb,
                        buffers.alpha,
                        native_floor_mask,
                        alpha_keep=float(self.ground_visual.get("alpha_keep", 0.90)),
                        floor_policy=self.floor_confidence_policy,
                        gaussian_depth_m=buffers.expected_depth_m,
                        metric_ground_depth_m=metric_ground_depth_m,
                        floor_depth_tolerance_m=float(
                            self.ground_visual.get(
                                "floor_depth_tolerance_m",
                                0.05,
                            )
                        ),
                    )
                else:
                    result, _confidence = suppress_low_confidence_gaussians(
                        result,
                        confidence_fallback_rgb,
                        buffers.alpha,
                        native_floor_mask,
                        alpha_replace=float(
                            self.ground_visual.get("alpha_replace", 0.70)
                        ),
                        alpha_keep=float(self.ground_visual.get("alpha_keep", 0.95)),
                    )
            if native_foreground_mask is not None:
                result[native_foreground_mask] = native_rgb[native_foreground_mask]
            self.rendered_frames += 1
            self.last_error = None
            return result
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.strict:
                raise RuntimeError(
                    f"Gaussian visual-shell render failed: {self.last_error}"
                ) from exc
            return native_rgb

    def render_buffers(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        camera_id: int,
        height: int,
        width: int,
        *,
        background_rgb: np.ndarray | None = None,
        include_expected_depth: bool = False,
        include_alpha: bool = False,
    ) -> GaussianRenderBuffers:
        """Render RGB and optionally calibrated expected metric depth.

        This is the sole depth conversion path used by compositing and
        validation. The gsplat rasterizer returns alpha together with RGB-D,
        avoiding two additional matched black/white renders per camera.
        """

        position, xmat, gaussian_units_per_meter = self._camera_in_gaussian_frame(
            data, camera_id
        )
        if background_rgb is None:
            background_rgb = np.zeros((height, width, 3), dtype=np.uint8)
        background_np = np.asarray(background_rgb, dtype=np.uint8)
        if background_np.shape != (height, width, 3):
            raise RuntimeError("Gaussian render background has invalid shape")
        background = self.torch.as_tensor(
            background_np,
            dtype=self.torch.float32,
            device=self.renderer.gaussians.device,
        ).div(255.0)[None]
        fovy = np.asarray([model.cam_fovy[camera_id]], dtype=np.float64)
        needs_alpha = (
            include_expected_depth or include_alpha
        ) and self.depth_semantics == "accumulated"
        with self.torch.no_grad():
            if needs_alpha:
                rgb_tensor, depth_tensor, alpha_batch = self.renderer.render_batch(
                    position[None],
                    xmat[None],
                    height,
                    width,
                    fovy,
                    bg_imgs=background,
                    return_alpha=True,
                )
                alpha_tensor = alpha_batch[0, ..., 0].clamp(0.0, 1.0)
            else:
                rgb_tensor, depth_tensor = self.renderer.render_batch(
                    position[None],
                    xmat[None],
                    height,
                    width,
                    fovy,
                    bg_imgs=background,
                )
                alpha_tensor = None
        rgb = rgb_tensor[0].clamp(0.0, 1.0).mul(255.0).byte().cpu().numpy()
        expected_depth_m = None
        alpha = None
        if alpha_tensor is not None:
            alpha = alpha_tensor.cpu().numpy()
        if include_expected_depth:
            raw_depth = depth_tensor[0, ..., 0].cpu().numpy()
            expected_depth_m = gaussian_depth_to_meters(
                raw_depth,
                gaussian_units_per_meter,
                semantics=self.depth_semantics,
                alpha=alpha,
            )
        return GaussianRenderBuffers(
            rgb=rgb,
            expected_depth_m=expected_depth_m,
            alpha=alpha,
        )

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "profile": str(self.profile_path),
            "strict": self.strict,
            "rendered_frames": self.rendered_frames,
            "gaussian_rendered_frames": self.gaussian_rendered_frames,
            "last_error": self.last_error,
            "camera_coverage_gate": {
                "enabled": self.camera_coverage_gate is not None,
                "mode": (
                    self.camera_coverage_gate.get("mode")
                    if self.camera_coverage_gate is not None
                    else None
                ),
                "fallback": (
                    self.camera_coverage_gate.get("fallback")
                    if self.camera_coverage_gate is not None
                    else None
                ),
                "thresholds": self.camera_coverage_thresholds,
                "total": self.camera_coverage_gate_total,
                "passed": self.camera_coverage_gate_passed,
                "fallback_count": self.camera_coverage_gate_fallback,
                "per_camera": self.camera_coverage_per_camera,
            },
            "background_physics": {
                "body_count": 0,
                "geom_count": 0,
                "collision_count": 0,
            },
            "foreground_occlusion": {
                "method": "MuJoCo segmentation foreground overwrite",
                "policy": self.foreground_policy,
                "native_background_geom_names": list(self.native_background_geom_names),
                "dynamic_foreground_geom_count": len(self.dynamic_foreground_geom_ids),
                "selected_static_foreground_geom_count": len(
                    self.selected_static_foreground_geom_ids
                ),
                "static_foreground_geom_name_prefixes": list(
                    self.static_foreground_geom_name_prefixes
                ),
            },
            "gaussian_exclusion": {
                "boxes_mujoco": self.gaussian_exclusion_boxes_mujoco,
                "excluded_gaussian_count": self.excluded_gaussian_count,
                "physics_changed": False,
            },
            "depth": {
                "renderer_mode": "RGB+D",
                "semantics": self.depth_semantics,
                "normalization": (
                    "divide_alpha_once_then_gaussian_units_per_meter"
                    if self.depth_semantics == "accumulated"
                    else "divide_gaussian_units_per_meter"
                ),
            },
            "ground_visual": {
                "mode": self.ground_mode,
                "layer_mode": self.layer_mode,
                "z_m": float(self.ground_visual.get("z_m", 0.0)),
                "gaussian_floor_loaded": self.ground_mode
                in {
                    "gaussian",
                    "gaussian_with_metric_fallback",
                    "gaussian_combined",
                    "gaussian_combined_with_confidence_fallback",
                },
                "alpha_replace": self.ground_visual.get("alpha_replace"),
                "alpha_keep": self.ground_visual.get("alpha_keep"),
                "confidence_compositing": self.confidence_compositing,
                "floor_confidence_policy": self.floor_confidence_policy,
                "floor_depth_tolerance_m": self.ground_visual.get(
                    "floor_depth_tolerance_m"
                ),
                "low_confidence_fallback": (
                    self.ground_mode == "gaussian_combined_with_confidence_fallback"
                ),
                "collision_geometry_added": False,
            },
        }
