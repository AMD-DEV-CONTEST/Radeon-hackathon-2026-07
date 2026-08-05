"""Source-derived Quadrupedal-Agility single-task geometry and observations."""

from __future__ import annotations

import math
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from unilab.terrains import (
    HfFlatTerrainCfg,
    SubTerrainCfg,
    TerrainHeightField,
    TerrainOutput,
)

ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = Path(__file__).resolve().parent / "assets"
HORIZONTAL_SCALE = 0.05
VERTICAL_SCALE = 0.005
SCAN_X = tuple(0.1 * index for index in range(12))
SCAN_Y = tuple(0.1 * index for index in range(-5, 6))
GOAL_THRESHOLD_M = 0.4
GOAL_DELAY_STEPS = 1
SOURCE_FRICTION = 1.0


@dataclass(frozen=True)
class SourceTaskSpec:
    name: str
    obstacle_index: int
    run_id: str
    goals: tuple[tuple[float, float, float], ...]
    fragment_file: Path
    joint_mode: str

    @property
    def start_xy(self) -> tuple[float, float]:
        return self.goals[0][:2]


@dataclass(frozen=True)
class SourceProxySampler:
    noise: np.ndarray
    size: tuple[float, float]
    horizontal_scale: float
    vertical_scale: float

    def sample_height(self, xy: np.ndarray) -> np.ndarray:
        points = np.asarray(xy, dtype=np.float64)
        flat = points.reshape(-1, 2)
        px = np.trunc(
            (flat[:, 0] + self.size[0] / 2) / self.horizontal_scale
        ).astype(np.intp)
        py = np.trunc(
            (flat[:, 1] + self.size[1] / 2) / self.horizontal_scale
        ).astype(np.intp)
        px = np.clip(px, 0, self.noise.shape[0] - 2)
        py = np.clip(py, 0, self.noise.shape[1] - 2)
        raw = np.minimum(
            np.minimum(self.noise[px, py], self.noise[px + 1, py]),
            self.noise[px, py + 1],
        )
        return (raw * self.vertical_scale).reshape(points.shape[:-1])


TASKS = {
    "frame": SourceTaskSpec(
        "frame",
        1,
        "NAG-210F",
        ((-2.15, 0.0, 0.3), (-1.45, 0.0, 0.3), (0.0, 0.0, 0.63), (1.45, 0.0, 0.3)),
        ASSET_DIR / "frame.xml",
        "fixed",
    ),
    "tunnel": SourceTaskSpec(
        "tunnel",
        5,
        "NAG-210T",
        ((-1.0, 0.0, 0.3), (-0.5, 0.0, 0.3), (1.0, 0.0, 0.3), (2.5, 0.0, 0.3)),
        ASSET_DIR / "tunnel.xml",
        "fixed",
    ),
    "poles": SourceTaskSpec(
        "poles",
        2,
        "NAG-210P",
        ((0.0, -0.5, 0.3), (1.0, 0.5, 0.3), (2.0, -0.5, 0.3), (3.0, 0.5, 0.3)),
        ASSET_DIR / "poles.xml",
        "fixed",
    ),
    "bar_jump": SourceTaskSpec(
        "bar_jump",
        0,
        "NAG-210B",
        ((-1.8, 0.0, 0.3), (-0.9, 0.0, 0.3), (0.0, 0.0, 0.50), (0.9, 0.0, 0.3)),
        ASSET_DIR / "bar_jump.xml",
        "stiff_slide@0.20m,k=20000,d=1000",
    ),
    "tire_jump": SourceTaskSpec(
        "tire_jump",
        4,
        "NAG-210R",
        ((-1.8, 0.0, 0.3), (-0.9, 0.0, 0.3), (0.0, 0.0, 0.475), (0.9, 0.0, 0.3)),
        ASSET_DIR / "tire_jump.xml",
        "stiff_slide@0.475m,k=20000,d=1000",
    ),
    "tire_jump_east": SourceTaskSpec(
        "tire_jump_east",
        4,
        "NAG-TE0",
        ((1.8, 0.0, 0.3), (0.9, 0.0, 0.3), (0.0, 0.0, 0.475), (-0.9, 0.0, 0.3)),
        ASSET_DIR / "tire_jump_east.xml",
        "stiff_slide@0.475m,k=20000,d=1000",
    ),
    "combo_tunnel": SourceTaskSpec(
        "combo_tunnel",
        5,
        "NAG-CT0",
        ((-5.5, 0.0, 0.3), (0.0, 0.0, 0.55), (4.5, 0.0, 0.3)),
        ASSET_DIR / "combo_tunnel.xml",
        "fixed",
    ),
    "seesaw": SourceTaskSpec(
        "seesaw",
        3,
        "NAG-210S",
        ((-2.2, 0.0, 0.3), (-1.5, 0.0, 0.3), (0.0, 0.0, 0.56), (1.5, 0.0, 0.3)),
        ASSET_DIR / "seesaw.xml",
        "passive_hinge@-asin(0.25/1.5),damping=5.5,ground_stop=+-0.16745",
    ),
}
TASK_ORDER = tuple(TASKS)


@dataclass(kw_only=True)
class SourceProxyTerrainCfg(SubTerrainCfg):
    task: str = "frame"
    horizontal_scale: float = HORIZONTAL_SCALE
    vertical_scale: float = VERTICAL_SCALE
    bar_height: float = 0.20

    def function(self, difficulty: float, rng: np.random.Generator) -> TerrainOutput:
        del difficulty, rng
        if self.task not in TASKS:
            raise ValueError(f"unknown source task: {self.task}")
        size_x = int(round(self.size[0] / self.horizontal_scale))
        size_y = int(round(self.size[1] / self.horizontal_scale))
        height = np.zeros((size_x, size_y), dtype=np.int16)
        cx, cy = size_x // 2, size_y // 2
        getattr(self, f"_add_{self.task}")(height, cx, cy)
        peak = int(height.max(initial=0))
        return TerrainOutput(
            origin=np.asarray([self.size[0] / 2, self.size[1] / 2, 0.0]),
            heightfield=TerrainHeightField(
                noise=height,
                size=self.size,
                horizontal_scale=self.horizontal_scale,
                vertical_scale=self.vertical_scale,
                elevation_min=0,
                elevation_max=peak,
                max_physical_height=peak * self.vertical_scale,
                base_thickness=max(peak * self.vertical_scale, 0.01),
                z_offset=0.0,
            ),
        )

    def _add_frame(self, height: np.ndarray, cx: int, cy: int) -> None:
        self._add_ramp(height, cx, cy, half_length=int(1.4625 / self.horizontal_scale))

    def _add_seesaw(self, height: np.ndarray, cx: int, cy: int) -> None:
        self._add_ramp(
            height,
            cx,
            cy,
            half_length=int(1.5 / self.horizontal_scale),
            physical_height=0.26,
        )

    def _add_ramp(
        self,
        height: np.ndarray,
        cx: int,
        cy: int,
        *,
        half_length: int,
        physical_height: float = 0.333,
    ) -> None:
        width = int(0.6 / self.horizontal_scale)
        peak = int(physical_height / self.vertical_scale)
        slope = peak / half_length
        y0, y1 = int(cy - width / 2), int(cy + width / 2) + 1
        left = np.arange(cx - half_length, cx + 1)
        right = np.arange(cx, cx + half_length + 1)
        height[left[0] : left[-1] + 1, y0:y1] = np.floor(
            (left - left[0]) * slope
        ).astype(np.int16)[:, None]
        height[right[0] : right[-1] + 1, y0:y1] = np.floor(
            np.flip(right - right[0]) * slope
        ).astype(np.int16)[:, None]

    def _add_poles(self, height: np.ndarray, cx: int, cy: int) -> None:
        radius = int(0.1 / self.horizontal_scale)
        spacing = int(1.0 / self.horizontal_scale)
        value = int(1.0 / self.vertical_scale)
        for index in range(4):
            x0 = cx - radius + index * spacing
            height[x0 : x0 + 2 * radius, cy - radius : cy + radius] = value

    def _add_bar_jump(self, height: np.ndarray, cx: int, cy: int) -> None:
        bar_height = int(self.bar_height / self.vertical_scale)
        bar_width = int(1.2 / self.horizontal_scale)
        bar_length = int(0.2 / self.horizontal_scale)
        base_width = int(2.04 / self.horizontal_scale)
        base_length = int(0.5 / self.horizontal_scale)
        base_height = int(0.42 / self.vertical_scale)
        height[
            int(cx - bar_length / 2) : int(cx - bar_length / 2) + bar_length,
            int(cy - bar_width / 2) : int(cy - bar_width / 2) + bar_width,
        ] = bar_height
        side = int((base_width - bar_width) / 2)
        x0 = int(cx - base_length / 2)
        height[x0 : x0 + base_length, int(cy - base_width / 2) : int(cy - base_width / 2) + side] = base_height
        height[x0 : x0 + base_length, int(cy + bar_width / 2) : int(cy + bar_width / 2) + side] = base_height

    def _add_tire_jump(self, height: np.ndarray, cx: int, cy: int) -> None:
        radius = int(0.4 / self.horizontal_scale)
        width = int(1.5 / self.horizontal_scale)
        tire_length = int(0.2 / self.horizontal_scale)
        base_length = int(0.6 / self.horizontal_scale)
        x = np.arange(2 * radius + 1)
        arc = -np.sqrt(radius**2 - (x - radius) ** 2)
        profile = np.floor(
            arc * self.horizontal_scale / self.vertical_scale
            + 0.475 / self.vertical_scale
        ).astype(np.int16)
        x0 = int(cx - tire_length / 2)
        height[x0 : int(cx + tire_length / 2) + 1, cy - radius : cy + radius + 1] = profile
        base_height = int(1.5 / self.vertical_scale)
        height[
            int(cx - base_length / 2) : int(cx + base_length / 2) + 1,
            int(cy - width / 2) : cy - radius + 1,
        ] = base_height
        height[
            int(cx - base_length / 2) : int(cx + base_length / 2) + 1,
            cy + radius : int(cy + width / 2) + 1,
        ] = base_height

    def _add_tunnel(self, height: np.ndarray, cx: int, cy: int) -> None:
        radius = int(0.4 / self.horizontal_scale)
        length = int(2.0 / self.horizontal_scale)
        y = np.arange(2 * radius + 1)
        profile = np.floor(
            (-np.sqrt(radius**2 - (y - radius) ** 2) + radius)
            * self.horizontal_scale
            / self.vertical_scale
        ).astype(np.int16)
        height[cx : cx + length + 1, cy - radius : cy + radius + 1] = profile


def flat_physics_terrain(seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "curriculum": False,
        "size": [8.0, 8.0],
        "horizontal_scale": HORIZONTAL_SCALE,
        "vertical_scale": VERTICAL_SCALE,
        "border_width": 10.0,
        "num_rows": 1,
        "num_cols": 1,
        "sub_terrains": {
            "flat": HfFlatTerrainCfg(
                proportion=1.0,
                horizontal_scale=HORIZONTAL_SCALE,
                vertical_scale=VERTICAL_SCALE,
            )
        },
    }


@contextmanager
def configured_fragment(
    spec: SourceTaskSpec, *, bar_height: float
) -> Iterator[Path]:
    if spec.name != "bar_jump":
        yield spec.fragment_file
        return

    tree = ET.parse(spec.fragment_file)
    joint = tree.find(".//joint[@name='source_bar_joint']")
    if joint is None:
        raise ValueError("bar fragment is missing source_bar_joint")
    joint.set("springref", f"{bar_height:.6f}")
    for mesh in tree.findall(".//mesh[@file]"):
        mesh_file = Path(mesh.attrib["file"])
        if not mesh_file.is_absolute():
            mesh.set("file", str((spec.fragment_file.parent / mesh_file).resolve()))

    with tempfile.TemporaryDirectory(prefix="unilab-agility-bar-") as tmp:
        fragment = Path(tmp) / "bar_jump.xml"
        tree.write(fragment, encoding="utf-8")
        yield fragment


def proxy_sampler(task: str, *, bar_height: float = 0.20):
    output = SourceProxyTerrainCfg(
        proportion=1.0,
        task=task,
        size=(8.0, 8.0),
        horizontal_scale=HORIZONTAL_SCALE,
        vertical_scale=VERTICAL_SCALE,
        bar_height=bar_height,
    ).function(0.0, np.random.default_rng(0))
    return SourceProxySampler(
        noise=output.heightfield.noise,
        size=output.heightfield.size,
        horizontal_scale=output.heightfield.horizontal_scale,
        vertical_scale=output.heightfield.vertical_scale,
    )


def proxy_height_scan(
    base_pos: np.ndarray,
    base_quat_wxyz: np.ndarray,
    sampler: Any,
) -> np.ndarray:
    position = np.asarray(base_pos, dtype=np.float32).reshape(1, 3)
    quat = np.asarray(base_quat_wxyz, dtype=np.float32).reshape(1, 4)
    w, x, y, z = quat[0]
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    x_grid, y_grid = np.meshgrid(SCAN_X, SCAN_Y, indexing="ij")
    offsets = np.stack((x_grid.reshape(-1), y_grid.reshape(-1)), axis=1)
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.asarray(((c, -s), (s, c)), dtype=np.float32)
    world_xy = offsets @ rotation.T + position[0, :2]
    ground = sampler.sample_height(world_xy).reshape(1, -1)
    return np.clip(position[:, 2:3] - 0.3 - ground, -1.0, 1.0).astype(np.float32)


def goal_delta_yaw(
    spec: SourceTaskSpec,
    base_pos: np.ndarray,
    base_quat_wxyz: np.ndarray,
    goal_index: int,
    reach_goal_timer: int,
) -> tuple[np.ndarray, int, int]:
    position = np.asarray(base_pos, dtype=np.float32).reshape(1, 3)
    quat = np.asarray(base_quat_wxyz, dtype=np.float32).reshape(1, 4)
    if goal_index < len(spec.goals) - 1 and reach_goal_timer > GOAL_DELAY_STEPS:
        goal_index += 1
        reach_goal_timer = 0
    goal_xy = np.asarray(spec.goals[goal_index][:2], dtype=np.float32)
    if np.linalg.norm(position[0, :2] - goal_xy) < GOAL_THRESHOLD_M:
        reach_goal_timer += 1
    next_index = min(goal_index + 1, len(spec.goals) - 1)
    targets = np.asarray(
        (spec.goals[goal_index][:2], spec.goals[next_index][:2]),
        dtype=np.float32,
    )
    target_yaw = np.arctan2(
        targets[:, 1] - position[0, 1],
        targets[:, 0] - position[0, 0],
    )
    w, x, y, z = quat[0]
    base_yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    delta = (target_yaw - base_yaw + np.pi) % (2.0 * np.pi) - np.pi
    return delta.reshape(1, 2).astype(np.float32), goal_index, reach_goal_timer


def source_episode_complete(
    spec: SourceTaskSpec, goal_index: int, reach_goal_timer: int
) -> bool:
    """Match the source reset after the final goal delay expires."""
    return goal_index == len(spec.goals) - 1 and reach_goal_timer > GOAL_DELAY_STEPS


__all__ = [
    "GOAL_DELAY_STEPS",
    "GOAL_THRESHOLD_M",
    "HORIZONTAL_SCALE",
    "SCAN_X",
    "SCAN_Y",
    "SOURCE_FRICTION",
    "TASKS",
    "TASK_ORDER",
    "SourceProxyTerrainCfg",
    "SourceProxySampler",
    "SourceTaskSpec",
    "configured_fragment",
    "flat_physics_terrain",
    "goal_delta_yaw",
    "proxy_height_scan",
    "proxy_sampler",
    "source_episode_complete",
]
