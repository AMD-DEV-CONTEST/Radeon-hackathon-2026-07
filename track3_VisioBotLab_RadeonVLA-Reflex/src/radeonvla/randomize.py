"""Per-episode scene randomization with zone-based layout sampling.

Table is partitioned into three regions (see ``scene_config``):

* **fruit zone** — five pickable fruits (random xy + yaw, non-overlapping);
* **left bowl zone** (y > 0) — ``white_left_bowl`` + ``blue_left_bowl`` only;
* **right bowl zone** (y < 0) — ``white_right_bowl`` + ``blue_right_bowl`` only.

Within each bowl zone the white/blue colors may swap slots, and the pair may
sit side-by-side (lateral) or front-back (depth). Bowls stay ``fixed`` (no tip)
but their XY is re-sampled every episode. Fruits never share centers with bowls.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from radeonvla.physics import set_rigid_position, set_rigid_quaternion
from radeonvla.scene_config import (
    BOWL_EULER,
    BOWL_PACK_RADIUS,
    FRANKA_QPOS,
    FRUIT_NAMES,
    FRUIT_PACK_RADIUS,
    FRUIT_ZONE_X,
    FRUIT_ZONE_Y,
    LEFT_BOWL_NAMES,
    LEFT_BOWL_ZONE_X,
    LEFT_BOWL_ZONE_Y,
    MIN_CLEARANCE,
    OBJECT_LAYOUT,
    RIGHT_BOWL_NAMES,
    RIGHT_BOWL_ZONE_X,
    RIGHT_BOWL_ZONE_Y,
    TABLE_TOP_Z,
    WORLD_CAM_LOOKAT,
    WORLD_CAM_POS,
    get_mesh_assets,
)
from radeonvla.tasks import TASKS, TaskSpec, get_task

# Back-compat aliases for scripts/tests that imported these names.
OVERLAP_MARGIN = MIN_CLEARANCE
CONTAINER_NAMES = LEFT_BOWL_NAMES + RIGHT_BOWL_NAMES


@dataclass
class RuntimeDR:
    """Runtime (per-episode) physics / camera extrinsics randomization."""

    enabled: bool = False
    friction_ratio_range: tuple[float, float] = (0.7, 1.3)
    mass_ratio_range: tuple[float, float] = (0.8, 1.2)
    cam_pos_jitter: float = 0.0
    cam_lookat_jitter: float = 0.0


@dataclass
class RandomizationConfig:
    """Episode layout + optional runtime DR knobs."""

    # Legacy small fruit jitter when ``zone_layout`` is False.
    pos_jitter: float = 0.012
    yaw_jitter: float = 12.0
    settle_steps: int = 60
    seed: int | None = None
    task_ids: tuple[str, ...] = tuple(sorted(TASKS))
    runtime_dr: RuntimeDR = field(default_factory=RuntimeDR)
    # Zone packing (default on): sample bowls + fruits in disjoint regions.
    zone_layout: bool = True
    randomize_bowls: bool = True
    randomize_fruits: bool = True
    # Full free pack of fruits is hard for the scripted expert; default is home
    # slots + small jitter (still in the fruit zone, no overlap with bowls).
    fruit_zone_pack: bool = False
    # When True, randomly pick lateral / depth / free. When False, use
    # ``bowl_arrangement`` only (default lateral — most reliable for the expert).
    vary_bowl_arrangement: bool = False
    # home_slots = canonical left/right pairs + mild jitter (most reliable).
    bowl_arrangement: str = "home_slots"  # home_slots | lateral | depth | free
    # Randomly swap white/blue assignment inside each side zone.
    swap_bowl_colors: bool = True
    pack_tries: int = 100
    min_clearance: float = MIN_CLEARANCE


def _zone_bounds(
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    radius: float,
) -> tuple[float, float, float, float]:
    """Return (x0, x1, y0, y1) inset so a disk of ``radius`` stays in the zone."""
    x0, x1 = x_range
    y0, y1 = y_range
    return (x0 + radius, x1 - radius, y0 + radius, y1 - radius)


def _sample_point(
    rng: np.random.Generator,
    bounds: tuple[float, float, float, float],
) -> np.ndarray:
    x0, x1, y0, y1 = bounds
    if x1 < x0 or y1 < y0:
        # Degenerate inset — fall back to zone center.
        return np.array([0.5 * (x0 + x1) if x1 >= x0 else x0, 0.5 * (y0 + y1) if y1 >= y0 else y0])
    return np.array([float(rng.uniform(x0, x1)), float(rng.uniform(y0, y1))])


def _overlaps(
    xy: np.ndarray,
    radius: float,
    placed: Sequence[tuple[np.ndarray, float]],
    clearance: float,
) -> bool:
    for p, r in placed:
        if float(np.linalg.norm(xy - p)) < radius + r + clearance:
            return True
    return False


def sample_non_overlapping(
    rng: np.random.Generator,
    *,
    n: int,
    radii: Sequence[float],
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    clearance: float = MIN_CLEARANCE,
    max_tries: int = 100,
    existing: Sequence[tuple[np.ndarray, float]] | None = None,
) -> list[np.ndarray] | None:
    """Sample ``n`` non-overlapping centers in a rectangle.

    Returns None if packing fails within ``max_tries`` full restarts.
    """
    if n == 0:
        return []
    assert len(radii) == n
    base_existing = list(existing or [])

    for _ in range(max_tries):
        placed: list[tuple[np.ndarray, float]] = list(base_existing)
        points: list[np.ndarray] = []
        ok = True
        for r in radii:
            bounds = _zone_bounds(x_range, y_range, r)
            found = None
            for _attempt in range(max_tries):
                cand = _sample_point(rng, bounds)
                if not _overlaps(cand, r, placed, clearance):
                    found = cand
                    break
            if found is None:
                ok = False
                break
            placed.append((found, r))
            points.append(found)
        if ok and len(points) == n:
            return points
    return None


def sample_bowl_pair(
    rng: np.random.Generator,
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    radius: float = BOWL_PACK_RADIUS,
    clearance: float = MIN_CLEARANCE,
    arrangement: str | None = None,
    max_tries: int = 80,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Sample two bowl centers in a zone.

    ``arrangement``:
      - ``"lateral"``: prefer larger |dy| (side-by-side along y);
      - ``"depth"``: prefer larger |dx| (front-back along x);
      - ``None`` / ``"free"``: free non-overlapping sample.
    """
    min_sep = 2.0 * radius + clearance
    x0, x1 = x_range
    y0, y1 = y_range
    mode = arrangement or "free"

    # If preferred arrangement cannot fit, fall through to free packing.
    x_span = (x1 - x0) - 2.0 * radius
    y_span = (y1 - y0) - 2.0 * radius
    if mode == "lateral" and y_span < min_sep:
        mode = "free"
    if mode == "depth" and x_span < min_sep:
        mode = "free"

    for _ in range(max_tries):
        if mode == "lateral":
            # Same depth band, split along y (side-by-side).
            cx = float(rng.uniform(x0 + radius, x1 - radius))
            y_lo = y0 + radius
            y_hi = y1 - radius
            ya = float(rng.uniform(y_lo, y_hi - min_sep))
            yb = float(rng.uniform(ya + min_sep, y_hi))
            jitter = min(0.02, max(0.0, 0.5 * x_span))
            p0 = np.array([cx + float(rng.uniform(-jitter, jitter)), ya])
            p1 = np.array([cx + float(rng.uniform(-jitter, jitter)), yb])
            p0[0] = float(np.clip(p0[0], x0 + radius, x1 - radius))
            p1[0] = float(np.clip(p1[0], x0 + radius, x1 - radius))
            if float(np.linalg.norm(p0 - p1)) >= min_sep - 1e-9:
                return p0, p1
        elif mode == "depth":
            # Same lateral band, split along x (front / back).
            cy = float(rng.uniform(y0 + radius, y1 - radius))
            x_lo = x0 + radius
            x_hi = x1 - radius
            xa = float(rng.uniform(x_lo, x_hi - min_sep))
            xb = float(rng.uniform(xa + min_sep, x_hi))
            jitter = min(0.02, max(0.0, 0.5 * y_span))
            p0 = np.array([xa, cy + float(rng.uniform(-jitter, jitter))])
            p1 = np.array([xb, cy + float(rng.uniform(-jitter, jitter))])
            p0[1] = float(np.clip(p0[1], y0 + radius, y1 - radius))
            p1[1] = float(np.clip(p1[1], y0 + radius, y1 - radius))
            if float(np.linalg.norm(p0 - p1)) >= min_sep - 1e-9:
                return p0, p1
        else:
            pts = sample_non_overlapping(
                rng,
                n=2,
                radii=(radius, radius),
                x_range=x_range,
                y_range=y_range,
                clearance=clearance,
                max_tries=max_tries,
            )
            if pts is not None:
                return pts[0], pts[1]
    # Last resort: free packing once more.
    pts = sample_non_overlapping(
        rng,
        n=2,
        radii=(radius, radius),
        x_range=x_range,
        y_range=y_range,
        clearance=clearance,
        max_tries=max_tries,
    )
    if pts is None:
        return None
    return pts[0], pts[1]


class EnvRandomizer:
    """Reset object poses and sample a language-conditioned sorting task."""

    def __init__(self, bundle, config: RandomizationConfig | None = None):
        self.bundle = bundle
        self.cfg = config or RandomizationConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self._assets = get_mesh_assets()
        self.names = list(OBJECT_LAYOUT)
        self.home = {n: np.asarray(OBJECT_LAYOUT[n]["pos"][:2], dtype=float) for n in self.names}
        self.home_yaw = {n: float(OBJECT_LAYOUT[n]["euler"][2]) for n in self.names}
        self.radius = {n: self._pack_radius(n) for n in self.names}
        # rest_z must match the scaled mesh placement used in build_scene.
        self.rest_z = {n: self._assets[n].rest_z_offset * float(OBJECT_LAYOUT[n].get("scale", 1.0)) for n in self.names}
        self.safe_jitter = self._compute_safe_jitter()
        self._base_cam_pos = np.asarray(WORLD_CAM_POS, dtype=float)
        self._base_cam_lookat = np.asarray(WORLD_CAM_LOOKAT, dtype=float)
        self._base_mass: dict[str, float] = {}
        self._capture_base_mass()
        # Last sampled xy per entity (for debugging / tests).
        self.last_xy: dict[str, np.ndarray] = {n: self.home[n].copy() for n in self.names}
        self.last_layout_meta: dict = {}
        self.last_runtime_meta: dict = {"enabled": False}

    def _pack_radius(self, name: str) -> float:
        layout = OBJECT_LAYOUT[name]
        scale = float(layout.get("scale", 1.0))
        if layout.get("kind") == "container":
            return BOWL_PACK_RADIUS * scale
        if name in FRUIT_PACK_RADIUS:
            return FRUIT_PACK_RADIUS[name] * scale
        return float(min(self._assets[name].radius_xy * scale, 0.05))

    def _capture_base_mass(self) -> None:
        for name, ent in self.bundle.objects.items():
            try:
                mass = ent.get_mass()
                if hasattr(mass, "detach"):
                    mass = mass.detach().cpu().numpy()
                self._base_mass[name] = float(np.asarray(mass).reshape(-1)[0])
            except Exception:
                self._base_mass[name] = 0.05

    def _compute_safe_jitter(self) -> dict[str, float]:
        """Legacy per-slot jitter caps (used when zone_layout is False)."""
        safe: dict[str, float] = {}
        for name in self.names:
            gaps = []
            for other in self.names:
                if other == name:
                    continue
                dist = float(np.linalg.norm(self.home[name] - self.home[other]))
                gap = dist - self.radius[name] - self.radius[other] - self.cfg.min_clearance
                gaps.append(max(0.0, 0.5 * gap))
            safe[name] = min(self.cfg.pos_jitter, min(gaps) if gaps else self.cfg.pos_jitter)
        return safe

    def _set_pose(self, name: str, xy: np.ndarray, euler_xyz: np.ndarray) -> None:
        from genesis.utils.geom import euler_to_quat

        ent = self.bundle.objects[name]
        z = TABLE_TOP_Z + self.rest_z[name]
        quat = euler_to_quat(np.asarray(euler_xyz, dtype=float))
        set_rigid_position(ent, np.array([float(xy[0]), float(xy[1]), z]))
        set_rigid_quaternion(ent, quat)
        self.last_xy[name] = np.asarray(xy, dtype=float).copy()

    def _jitter_home(
        self,
        name: str,
        existing: list[tuple[np.ndarray, float]],
        clearance: float,
    ) -> np.ndarray:
        """Home slot + small jitter, rejecting bowl/fruit overlaps."""
        r = self.radius[name]
        jitter = self.safe_jitter.get(name, self.cfg.pos_jitter)
        for _ in range(40):
            dx = float(self.rng.uniform(-jitter, jitter))
            dy = float(self.rng.uniform(-jitter, jitter))
            xy = self.home[name] + np.array([dx, dy])
            xy[0] = float(np.clip(xy[0], FRUIT_ZONE_X[0], FRUIT_ZONE_X[1]))
            xy[1] = float(np.clip(xy[1], FRUIT_ZONE_Y[0], FRUIT_ZONE_Y[1]))
            if not _overlaps(xy, r, existing, clearance):
                existing.append((xy, r))
                return xy
        xy = self.home[name].copy()
        xy[0] = float(np.clip(xy[0], FRUIT_ZONE_X[0], FRUIT_ZONE_X[1]))
        xy[1] = float(np.clip(xy[1], FRUIT_ZONE_Y[0], FRUIT_ZONE_Y[1]))
        existing.append((xy, r))
        return xy

    def _sample_zone_layout(self) -> dict[str, np.ndarray]:
        """Return name → xy for all objects using zone packing + color swap."""
        cfg = self.cfg
        clearance = cfg.min_clearance
        poses: dict[str, np.ndarray] = {}
        meta: dict = {"arrangement": {}, "color_swapped": {}}

        placed_for_fruit: list[tuple[np.ndarray, float]] = []

        # --- bowl pairs (left / right zones) ---
        for side, names, zx, zy in (
            ("left", LEFT_BOWL_NAMES, LEFT_BOWL_ZONE_X, LEFT_BOWL_ZONE_Y),
            ("right", RIGHT_BOWL_NAMES, RIGHT_BOWL_ZONE_X, RIGHT_BOWL_ZONE_Y),
        ):
            white_name, blue_name = names  # convention: white first in tuple
            if cfg.randomize_bowls:
                # Default reliable path: fixed home slots per side + optional color swap.
                # Full free/lateral sampling is available when bowl_arrangement != "home_slots".
                arrangement = (
                    str(self.rng.choice(["lateral", "depth", "free"]))
                    if cfg.vary_bowl_arrangement
                    else str(cfg.bowl_arrangement or "home_slots")
                )
                if arrangement == "home_slots":
                    p_white = self.home[white_name].copy()
                    p_blue = self.home[blue_name].copy()
                    # Mild slot jitter along y only (keep lateral pairing).
                    j = 0.015
                    p_white[1] += float(self.rng.uniform(-j, j))
                    p_blue[1] += float(self.rng.uniform(-j, j))
                    if cfg.swap_bowl_colors and bool(self.rng.integers(0, 2)):
                        p_white, p_blue = p_blue.copy(), p_white.copy()
                        meta["color_swapped"][side] = True
                    else:
                        meta["color_swapped"][side] = False
                    meta["arrangement"][side] = "home_slots"
                else:
                    pair = sample_bowl_pair(
                        self.rng,
                        x_range=zx,
                        y_range=zy,
                        radius=BOWL_PACK_RADIUS,
                        clearance=clearance,
                        arrangement=arrangement,
                        max_tries=cfg.pack_tries,
                    )
                    if pair is None:
                        p_white = self.home[white_name].copy()
                        p_blue = self.home[blue_name].copy()
                        arrangement = "fallback"
                        meta["color_swapped"][side] = False
                    else:
                        p_white, p_blue = pair
                        if cfg.swap_bowl_colors and bool(self.rng.integers(0, 2)):
                            p_white, p_blue = p_blue, p_white
                            meta["color_swapped"][side] = True
                        else:
                            meta["color_swapped"][side] = False
                    meta["arrangement"][side] = arrangement
            else:
                p_white = self.home[white_name].copy()
                p_blue = self.home[blue_name].copy()
                meta["arrangement"][side] = "home"
                meta["color_swapped"][side] = False

            poses[white_name] = p_white
            poses[blue_name] = p_blue
            placed_for_fruit.append((p_white, BOWL_PACK_RADIUS))
            placed_for_fruit.append((p_blue, BOWL_PACK_RADIUS))

        # --- fruits in fruit zone (avoid bowls) ---
        fruit_names = list(FRUIT_NAMES)
        if cfg.randomize_fruits and cfg.fruit_zone_pack:
            # Full free pack (harder for expert; enable for max DR).
            order = sorted(fruit_names, key=lambda n: self.radius[n], reverse=True)
            radii = [self.radius[n] for n in order]
            pts = sample_non_overlapping(
                self.rng,
                n=len(order),
                radii=radii,
                x_range=FRUIT_ZONE_X,
                y_range=FRUIT_ZONE_Y,
                clearance=clearance,
                max_tries=cfg.pack_tries,
                existing=placed_for_fruit,
            )
            if pts is None:
                for name in fruit_names:
                    poses[name] = self._jitter_home(name, placed_for_fruit, clearance)
                meta["fruit_pack"] = "fallback"
            else:
                for name, pt in zip(order, pts, strict=True):
                    poses[name] = pt
                meta["fruit_pack"] = "zone"
        elif cfg.randomize_fruits:
            # Reliable default: canonical home slots + small jitter, no bowl overlap.
            for name in fruit_names:
                poses[name] = self._jitter_home(name, placed_for_fruit, clearance)
            meta["fruit_pack"] = "home_jitter"
        else:
            for name in fruit_names:
                poses[name] = self.home[name].copy()
            meta["fruit_pack"] = "home"

        self.last_layout_meta = meta
        return poses

    def _sample_legacy_layout(self) -> dict[str, np.ndarray]:
        """Original home + small fruit jitter (bowls fixed at home)."""
        poses: dict[str, np.ndarray] = {}
        for name in self.names:
            layout = OBJECT_LAYOUT[name]
            kind = layout.get("kind", "fruit")
            if kind == "container" or layout.get("fixed"):
                poses[name] = self.home[name].copy()
                continue
            jitter = self.safe_jitter[name]
            dx = float(self.rng.uniform(-jitter, jitter))
            dy = float(self.rng.uniform(-jitter, jitter))
            xy = self.home[name] + np.array([dx, dy])
            xy[0] = float(np.clip(xy[0], FRUIT_ZONE_X[0], FRUIT_ZONE_X[1]))
            xy[1] = float(np.clip(xy[1], FRUIT_ZONE_Y[0], FRUIT_ZONE_Y[1]))
            poses[name] = xy
        self.last_layout_meta = {"arrangement": "legacy"}
        return poses

    def reset(self, *, seed: int | None = None, task_id: str | None = None) -> TaskSpec:
        if seed is not None:
            self.rng = np.random.default_rng(seed)

        # Teleport robot home first.
        self.bundle.franka.set_qpos(np.array(FRANKA_QPOS), zero_velocity=True)

        if self.cfg.zone_layout:
            poses = self._sample_zone_layout()
        else:
            poses = self._sample_legacy_layout()

        for name in self.names:
            layout = OBJECT_LAYOUT[name]
            kind = layout.get("kind", "fruit")
            xy = poses.get(name, self.home[name])
            if kind == "container" or layout.get("fixed"):
                # Bowls: keep upright BOWL_EULER (opening up); only XY randomizes.
                euler = np.asarray(layout.get("euler", BOWL_EULER), dtype=float)
                self._set_pose(name, xy, euler)
            else:
                yaw = self.home_yaw[name] + float(self.rng.uniform(-self.cfg.yaw_jitter, self.cfg.yaw_jitter))
                self._set_pose(name, xy, np.array([0.0, 0.0, yaw]))

        self.last_runtime_meta = {"enabled": bool(self.cfg.runtime_dr.enabled)}
        if self.cfg.runtime_dr.enabled:
            self._apply_runtime_dr()

        for _ in range(self.cfg.settle_steps):
            self.bundle.hold_home()
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()

        if task_id is None:
            task_id = str(self.rng.choice(self.cfg.task_ids))
        return get_task(task_id)

    def _apply_runtime_dr(self) -> None:
        dr = self.cfg.runtime_dr
        friction_ratio = float(self.rng.uniform(*dr.friction_ratio_range))
        mass_ratios: dict[str, float] = {}
        for name, ent in self.bundle.objects.items():
            try:
                if hasattr(ent, "set_friction"):
                    ent.set_friction(friction_ratio)
            except Exception:
                pass
            mass_ratio = float(self.rng.uniform(*dr.mass_ratio_range))
            mass_ratios[name] = mass_ratio
            base = self._base_mass.get(name, 0.05)
            try:
                if hasattr(ent, "set_mass_shift"):
                    ent.set_mass_shift(base * (mass_ratio - 1.0))
            except Exception:
                pass

        position_delta = np.zeros(3, dtype=float)
        lookat_delta = np.zeros(3, dtype=float)
        if self.bundle.world_cam is not None and (dr.cam_pos_jitter > 0 or dr.cam_lookat_jitter > 0):
            pos = self._base_cam_pos.copy()
            look = self._base_cam_lookat.copy()
            if dr.cam_pos_jitter > 0:
                position_delta = self.rng.uniform(-dr.cam_pos_jitter, dr.cam_pos_jitter, size=3)
                pos += position_delta
            if dr.cam_lookat_jitter > 0:
                lookat_delta = self.rng.uniform(-dr.cam_lookat_jitter, dr.cam_lookat_jitter, size=3)
                look += lookat_delta
            try:
                self.bundle.world_cam.set_pose(pos=pos, lookat=look)
            except Exception:
                pass
        self.last_runtime_meta = {
            "enabled": True,
            "friction_ratio": friction_ratio,
            "mass_ratios": mass_ratios,
            "world_camera_position_delta": position_delta.tolist(),
            "world_camera_lookat_delta": lookat_delta.tolist(),
        }
