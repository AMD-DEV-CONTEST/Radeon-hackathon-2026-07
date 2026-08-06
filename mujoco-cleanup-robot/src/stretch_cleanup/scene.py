"""Procedural living-room scene generation for the V2 cleanup stack.

Three rules distinguish these scenes from the V1 hand-written XML, and each one
maps to a defect that made V1 results untransferable:

1. Every visual surface is also a collision surface.  V1 drew furniture with
   ``contype="0" conaffinity="0"`` decor geoms over a single collision box, so
   the cameras and the contact solver saw different worlds.
2. Litter rests directly on the floor.  V1 raised it onto 0.24 m pedestals
   because the arm could not reach the ground.
3. No ``<equality>`` section exists.  Grasps must be produced by contact.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRETCH_XML = (
    PROJECT_ROOT / "external" / "mujoco_menagerie" / "hello_robot_stretch_3" / "stretch.xml"
)
BIN_WALL_THICKNESS = 0.015


@dataclass(frozen=True)
class Litter:
    """A graspable object resting on the floor."""

    name: str
    shape: str  # "box" | "cylinder" | "banana"
    half_size: tuple[float, ...]
    mass: float
    rgba: tuple[float, float, float, float]
    pos_xy: tuple[float, float]
    yaw: float = 0.0

    @property
    def half_height(self) -> float:
        if self.shape == "box":
            return self.half_size[2]
        if self.shape == "cylinder":
            return self.half_size[1]
        if self.shape == "banana":
            radius, _, curve_drop = self.half_size
            return radius + curve_drop
        raise ValueError(f"unsupported litter shape: {self.shape!r}")

    @property
    def xy_radius(self) -> float:
        if self.shape == "cylinder":
            return self.half_size[0]
        if self.shape == "banana":
            radius, half_length, _ = self.half_size
            return radius + half_length
        if self.shape == "box":
            return max(self.half_size[0], self.half_size[1])
        raise ValueError(f"unsupported litter shape: {self.shape!r}")

    def to_xml(self) -> str:
        z = self.half_height
        rgba = " ".join(f"{v:.3f}" for v in self.rgba)
        qw, qz = _yaw_quat(self.yaw)
        if self.shape == "banana":
            radius, half_length, curve_drop = self.half_size
            joints = (-half_length, -half_length / 3.0, half_length / 3.0, half_length)
            heights = (-curve_drop, 0.0, 0.0, -curve_drop)
            body = [
                f'    <body name="{self.name}" pos="{self.pos_xy[0]:.4f} '
                f'{self.pos_xy[1]:.4f} {z:.4f}" quat="{qw:.6f} 0 0 {qz:.6f}">',
                f'      <freejoint name="{self.name}_free"/>',
            ]
            for index in range(3):
                body.append(
                    f'      <geom name="{self.name}_geom_{index}" type="capsule"'
                    f' fromto="{joints[index]:.4f} 0 {heights[index]:.4f} '
                    f'{joints[index + 1]:.4f} 0 {heights[index + 1]:.4f}"'
                    f' size="{radius:.4f}" mass="{self.mass / 3.0:.4f}"'
                    f' rgba="{rgba}" friction="1.2 0.02 0.001" condim="4"'
                    f' solref="0.005 1"/>'
                )
            body.append("    </body>")
            return "\n".join(body)
        size = " ".join(f"{v:.4f}" for v in self.half_size)
        return f"""    <body name="{self.name}" pos="{self.pos_xy[0]:.4f} {self.pos_xy[1]:.4f} {z:.4f}" quat="{qw:.6f} 0 0 {qz:.6f}">
      <freejoint name="{self.name}_free"/>
      <geom name="{self.name}_geom" type="{self.shape}" size="{size}" mass="{self.mass:.4f}"
            rgba="{rgba}" friction="1.2 0.02 0.001" condim="4" solref="0.005 1"/>
    </body>"""


@dataclass(frozen=True)
class Furniture:
    """A box-composed furniture item whose visual and collision geometry match."""

    name: str
    parts: tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]
    material: str
    pos_xy: tuple[float, float]
    yaw: float = 0.0
    navigation_obstacle: bool = True

    def to_xml(self) -> str:
        qw, qz = _yaw_quat(self.yaw)
        body = [
            f'    <body name="{self.name}" pos="{self.pos_xy[0]:.4f} {self.pos_xy[1]:.4f} 0"'
            f' quat="{qw:.6f} 0 0 {qz:.6f}">'
        ]
        for index, (offset, half) in enumerate(self.parts):
            body.append(
                f'      <geom name="{self.name}_{index}" type="box"'
                f' pos="{offset[0]:.4f} {offset[1]:.4f} {offset[2]:.4f}"'
                f' size="{half[0]:.4f} {half[1]:.4f} {half[2]:.4f}"'
                f' material="{self.material}"/>'
            )
        body.append("    </body>")
        return "\n".join(body)


@dataclass
class RoomSpec:
    """A living room sized so the base still has a navigable corridor.

    The V1 layout put a sofa, table, console, armchair and shelf into 6 x 4 m.
    Inflating that by the measured 0.276 m footprint leaves under 5 m^2 free,
    split into disconnected pockets, so no route exists between objects.  V2
    uses a larger room with furniture pushed against the walls.
    """

    width: float = 7.0
    depth: float = 5.0
    wall_height: float = 1.3
    furniture: list[Furniture] = field(default_factory=list)
    litter: list[Litter] = field(default_factory=list)
    bin_pos: tuple[float, float] = (-2.95, -1.95)
    bin_half: tuple[float, float, float] = (0.18, 0.18, 0.13)
    robot_start: tuple[float, float, float] = (0.30, -0.70, 0.0)
    light_pos: tuple[float, float, float] = (0.0, 0.0, 2.8)
    light_diffuse: tuple[float, float, float] = (0.65, 0.64, 0.62)
    floor_rgb1: tuple[float, float, float] = (0.62, 0.50, 0.36)
    floor_rgb2: tuple[float, float, float] = (0.68, 0.56, 0.41)
    south_opening_width: float = 0.0
    seed_robot_start: bool = False
    randomization_manifest: dict[str, object] = field(default_factory=dict)


def _yaw_quat(yaw: float) -> tuple[float, float]:
    import math

    return math.cos(yaw / 2.0), math.sin(yaw / 2.0)


def default_furniture() -> list[Furniture]:
    """Furniture against the walls, leaving an open corridor through the middle."""
    return [
        Furniture(
            name="sofa",
            parts=(
                ((0.0, 0.0, 0.20), (0.95, 0.38, 0.20)),
                ((0.0, 0.30, 0.50), (0.95, 0.08, 0.30)),
                ((-0.87, 0.0, 0.42), (0.08, 0.38, 0.22)),
                ((0.87, 0.0, 0.42), (0.08, 0.38, 0.22)),
            ),
            material="fabric_teal",
            pos_xy=(-0.40, 2.05),
        ),
        Furniture(
            name="coffee_table",
            parts=(
                ((0.0, 0.0, 0.36), (0.45, 0.24, 0.03)),
                ((-0.38, -0.17, 0.18), (0.04, 0.04, 0.18)),
                ((0.38, -0.17, 0.18), (0.04, 0.04, 0.18)),
                ((-0.38, 0.17, 0.18), (0.04, 0.04, 0.18)),
                ((0.38, 0.17, 0.18), (0.04, 0.04, 0.18)),
            ),
            material="wood_light",
            pos_xy=(-0.40, 1.15),
        ),
        Furniture(
            name="tv_console",
            parts=(
                ((0.0, 0.0, 0.22), (0.85, 0.18, 0.22)),
                ((0.0, 0.0, 0.78), (0.55, 0.03, 0.34)),
            ),
            material="wood_dark",
            pos_xy=(-0.40, -2.28),
        ),
        Furniture(
            name="armchair",
            parts=(
                ((0.0, 0.0, 0.22), (0.34, 0.34, 0.22)),
                ((0.0, 0.30, 0.50), (0.34, 0.06, 0.28)),
            ),
            material="fabric_rust",
            pos_xy=(-3.05, 1.30),
            yaw=-0.9,
        ),
        Furniture(
            name="bookshelf",
            parts=(
                ((0.0, 0.0, 0.90), (0.16, 0.45, 0.06)),
                ((0.0, 0.0, 0.03), (0.16, 0.45, 0.03)),
                ((0.0, -0.42, 0.47), (0.16, 0.03, 0.47)),
                ((0.0, 0.42, 0.47), (0.16, 0.03, 0.47)),
                ((0.0, 0.0, 0.45), (0.16, 0.42, 0.02)),
            ),
            material="wood_dark",
            pos_xy=(3.30, 1.40),
        ),
    ]


def default_litter() -> list[Litter]:
    """Floor litter in the open corridor, sized for a parallel-jaw top-down grasp."""
    return [
        Litter("can", "cylinder", (0.033, 0.062), 0.08, (0.14, 0.48, 0.86, 1.0), (0.85, -0.60)),
        Litter("bottle", "cylinder", (0.036, 0.075), 0.10, (0.16, 0.66, 0.36, 1.0), (2.30, 0.45)),
        Litter("cup", "cylinder", (0.038, 0.050), 0.06, (0.94, 0.80, 0.24, 1.0), (1.55, -1.35)),
        Litter("banana", "banana", (0.030, 0.065, 0.012), 0.11, (0.98, 0.80, 0.08, 1.0), (0.35, 1.00)),
    ]


def option_d_furniture() -> list[Furniture]:
    """Island-sofa layout based on the selected photorealistic option D.

    All pieces are assembled from MuJoCo primitives so their rendered and
    collision geometry agree.  The rug remains a real, 4 mm-high contact
    surface, but is not treated as a navigation obstacle.
    """

    return [
        Furniture(
            name="island_sofa",
            parts=(
                ((0.0, 0.0, 0.20), (1.20, 0.42, 0.20)),
                ((0.0, -0.34, 0.55), (1.20, 0.08, 0.35)),
                ((-1.11, 0.0, 0.43), (0.09, 0.42, 0.23)),
                ((1.11, 0.0, 0.43), (0.09, 0.42, 0.23)),
            ),
            material="fabric_ivory",
            pos_xy=(0.0, -0.25),
        ),
        Furniture(
            name="sofa_cushion_left",
            parts=(((0.0, 0.0, 0.48), (0.27, 0.08, 0.18)),),
            material="fabric_blue",
            pos_xy=(-0.58, -0.10),
            yaw=-0.12,
        ),
        Furniture(
            name="sofa_cushion_right",
            parts=(((0.0, 0.0, 0.48), (0.27, 0.08, 0.18)),),
            material="fabric_blue",
            pos_xy=(0.58, -0.10),
            yaw=0.12,
        ),
        Furniture(
            name="area_rug",
            parts=(((0.0, 0.0, 0.004), (1.45, 0.95, 0.004)),),
            material="rug_grey",
            pos_xy=(0.0, 1.05),
            navigation_obstacle=False,
        ),
        Furniture(
            name="coffee_table",
            parts=(
                ((0.0, 0.0, 0.37), (0.58, 0.34, 0.035)),
                ((-0.49, -0.25, 0.18), (0.04, 0.04, 0.18)),
                ((0.49, -0.25, 0.18), (0.04, 0.04, 0.18)),
                ((-0.49, 0.25, 0.18), (0.04, 0.04, 0.18)),
                ((0.49, 0.25, 0.18), (0.04, 0.04, 0.18)),
            ),
            material="wood_light",
            pos_xy=(0.0, 1.05),
        ),
        Furniture(
            name="tv_console",
            parts=(
                ((0.0, 0.0, 0.24), (1.20, 0.20, 0.24)),
                ((0.0, -0.02, 0.86), (0.88, 0.035, 0.42)),
            ),
            material="wood_dark",
            pos_xy=(0.0, 2.42),
        ),
        Furniture(
            name="tv_screen",
            parts=(((0.0, 0.0, 1.02), (0.82, 0.025, 0.34)),),
            material="screen_black",
            pos_xy=(0.0, 2.37),
        ),
        Furniture(
            name="armchair_left",
            parts=(
                ((0.0, 0.0, 0.22), (0.40, 0.40, 0.22)),
                ((0.0, 0.33, 0.56), (0.40, 0.07, 0.34)),
                ((-0.34, 0.0, 0.43), (0.07, 0.40, 0.23)),
                ((0.34, 0.0, 0.43), (0.07, 0.40, 0.23)),
            ),
            material="fabric_ivory",
            pos_xy=(-2.35, 1.73),
            yaw=-0.20,
        ),
        Furniture(
            name="armchair_right",
            parts=(
                ((0.0, 0.0, 0.22), (0.40, 0.40, 0.22)),
                ((0.0, 0.33, 0.56), (0.40, 0.07, 0.34)),
                ((-0.34, 0.0, 0.43), (0.07, 0.40, 0.23)),
                ((0.34, 0.0, 0.43), (0.07, 0.40, 0.23)),
            ),
            material="fabric_ivory",
            pos_xy=(2.35, 1.73),
            yaw=0.20,
        ),
        Furniture(
            name="plant_left",
            parts=(
                ((0.0, 0.0, 0.20), (0.18, 0.18, 0.20)),
                ((0.0, 0.0, 0.58), (0.05, 0.05, 0.38)),
                ((0.0, 0.0, 0.82), (0.28, 0.10, 0.06)),
                ((0.0, 0.0, 0.82), (0.10, 0.28, 0.06)),
            ),
            material="plant_green",
            pos_xy=(-2.96, -2.08),
        ),
        Furniture(
            name="plant_right",
            parts=(
                ((0.0, 0.0, 0.20), (0.18, 0.18, 0.20)),
                ((0.0, 0.0, 0.58), (0.05, 0.05, 0.38)),
                ((0.0, 0.0, 0.82), (0.28, 0.10, 0.06)),
                ((0.0, 0.0, 0.82), (0.10, 0.28, 0.06)),
            ),
            material="plant_green",
            pos_xy=(3.02, 2.04),
        ),
    ]


def option_d_litter() -> list[Litter]:
    """Four cleanup targets distributed across the front and rear room zones."""

    return [
        Litter("can", "cylinder", (0.033, 0.062), 0.08, (0.82, 0.12, 0.10, 1.0), (1.62, -1.82), 0.2),
        Litter("bottle", "cylinder", (0.036, 0.075), 0.10, (0.20, 0.62, 0.86, 1.0), (-2.58, -0.36), -0.7),
        Litter("cup", "cylinder", (0.038, 0.050), 0.06, (0.92, 0.88, 0.76, 1.0), (-1.62, -1.73), -0.2),
        Litter("banana", "banana", (0.030, 0.065, 0.012), 0.11, (0.98, 0.80, 0.08, 1.0), (2.60, 0.20), 0.45),
    ]


def option_d_spec() -> RoomSpec:
    """Fixed review scene: option-D room with the option-C Stretch 3 placement."""

    return RoomSpec(
        width=6.8,
        depth=5.4,
        wall_height=2.4,
        furniture=option_d_furniture(),
        litter=option_d_litter(),
        bin_pos=(2.95, 1.62),
        bin_half=(0.18, 0.18, 0.13),
        robot_start=(0.0, -2.18, math.pi / 2.0),
        light_pos=(-0.8, -0.6, 3.4),
        light_diffuse=(0.82, 0.80, 0.76),
        floor_rgb1=(0.46, 0.31, 0.20),
        floor_rgb2=(0.52, 0.36, 0.23),
        south_opening_width=1.60,
        seed_robot_start=True,
    )


def option_d_tidybot_spec() -> RoomSpec:
    """Expanded option-D layout with trailer-safe aisles and turning space."""

    positions = {
        "island_sofa": (0.0, -0.45),
        "sofa_cushion_left": (-0.58, -0.30),
        "sofa_cushion_right": (0.58, -0.30),
        "area_rug": (0.0, 1.65),
        "coffee_table": (0.0, 1.65),
        "tv_console": (0.0, 3.50),
        "tv_screen": (0.0, 3.45),
        "armchair_left": (-3.25, 2.50),
        "armchair_right": (3.25, 2.50),
        "plant_left": (-3.85, -3.15),
        "plant_right": (3.85, 3.10),
    }
    furniture = [
        replace(item, pos_xy=positions[item.name])
        for item in option_d_furniture()
    ]
    litter = [
        Litter("can", "cylinder", (0.033, 0.062), 0.08, (0.82, 0.12, 0.10, 1.0), (2.05, -2.35), 0.2),
        Litter("bottle", "cylinder", (0.036, 0.075), 0.10, (0.20, 0.62, 0.86, 1.0), (-3.65, -0.30), -0.7),
        Litter("cup", "cylinder", (0.038, 0.050), 0.06, (0.92, 0.88, 0.76, 1.0), (-2.10, -2.25), -0.2),
        Litter("banana", "banana", (0.030, 0.065, 0.012), 0.11, (0.98, 0.80, 0.08, 1.0), (3.65, 0.20), 0.45),
    ]
    return RoomSpec(
        width=8.8,
        depth=7.6,
        wall_height=2.6,
        furniture=furniture,
        litter=litter,
        bin_pos=(3.65, 2.55),
        bin_half=(0.18, 0.18, 0.13),
        robot_start=(0.0, -2.70, math.pi / 2.0),
        light_pos=(-1.0, -0.8, 4.2),
        light_diffuse=(0.84, 0.82, 0.78),
        floor_rgb1=(0.46, 0.31, 0.20),
        floor_rgb2=(0.52, 0.36, 0.23),
        south_opening_width=2.20,
        seed_robot_start=False,
    )


TIDYBOT_TARGET_NAMES = ("can", "bottle", "cup", "banana")
TIDYBOT_TARGET_SAFE_ZONES = (
    ("south_west", (-2.45, -1.45, -2.65, -1.90)),
    ("south_east", (1.45, 2.45, -2.65, -1.90)),
    ("west_aisle", (-3.45, -2.70, -1.00, 0.65)),
    ("east_aisle", (2.70, 3.45, -1.00, 0.65)),
    ("north_center", (-2.20, 2.20, 2.35, 2.85)),
)
TIDYBOT_WALL_MARGIN_M = 0.70
TIDYBOT_OBJECT_SPACING_M = 0.80
TIDYBOT_FURNITURE_CLEARANCE_M = 0.18
TIDYBOT_ROBOT_TARGET_CLEARANCE_M = 1.05
# Keep initial browser demonstrations in the dense, collision-free part of the
# calibrated floor workspace. Harder edge placements belong in a later curriculum.
TIDYBOT_MANIPULATION_FORWARD_RANGE_M = (0.50, 0.58)
TIDYBOT_MANIPULATION_LATERAL_RANGE_M = (-0.06, 0.06)


def _tidybot_rng(seed: int, stream: str) -> random.Random:
    """Independent deterministic streams keep one random choice from shifting all others."""

    return random.Random(f"option-d-tidybot-v1:{seed}:{stream}")


def _clamp_channel(value: float) -> float:
    return min(1.0, max(0.0, value))


def _litter_xy_radius(item: Litter) -> float:
    return item.xy_radius


def _point_clear_of_furniture(
    point: tuple[float, float],
    furniture: list[Furniture],
    clearance: float,
) -> bool:
    """Conservative point-vs-oriented-box test using each visible collision part."""

    x, y = point
    for item in furniture:
        cosine, sine = math.cos(item.yaw), math.sin(item.yaw)
        relative_x = x - item.pos_xy[0]
        relative_y = y - item.pos_xy[1]
        local_x = cosine * relative_x + sine * relative_y
        local_y = -sine * relative_x + cosine * relative_y
        for offset, half in item.parts:
            if (
                abs(local_x - offset[0]) <= half[0] + clearance
                and abs(local_y - offset[1]) <= half[1] + clearance
            ):
                return False
    return True


def _tidybot_target_position_is_safe(
    point: tuple[float, float],
    *,
    room: RoomSpec,
    furniture: list[Furniture],
    radius: float,
    robot_start: tuple[float, float, float],
    placed: list[tuple[float, float]],
    minimum_robot_distance: float,
) -> bool:
    half_width, half_depth = room.width / 2.0, room.depth / 2.0
    if abs(point[0]) > half_width - TIDYBOT_WALL_MARGIN_M - radius:
        return False
    if abs(point[1]) > half_depth - TIDYBOT_WALL_MARGIN_M - radius:
        return False
    if not _point_clear_of_furniture(
        point,
        furniture,
        TIDYBOT_FURNITURE_CLEARANCE_M + radius,
    ):
        return False
    bin_clearance = 0.25 + radius
    if (
        abs(point[0] - room.bin_pos[0]) <= room.bin_half[0] + bin_clearance
        and abs(point[1] - room.bin_pos[1]) <= room.bin_half[1] + bin_clearance
    ):
        return False
    if math.dist(point, robot_start[:2]) < minimum_robot_distance:
        return False
    return all(math.dist(point, other) >= TIDYBOT_OBJECT_SPACING_M for other in placed)


def _randomized_option_d_tidybot_furniture(seed: int) -> list[Furniture]:
    """Apply small rigid transforms to semantic furniture groups."""

    fixed = option_d_tidybot_spec().furniture
    by_name = {item.name: item for item in fixed}
    groups = (
        (
            "sofa_group",
            ("island_sofa", "sofa_cushion_left", "sofa_cushion_right"),
            (0.055, 0.045, 0.018),
        ),
        ("table_group", ("area_rug", "coffee_table"), (0.060, 0.060, 0.022)),
        ("television_group", ("tv_console", "tv_screen"), (0.040, 0.025, 0.012)),
        ("armchair_left", ("armchair_left",), (0.055, 0.055, 0.030)),
        ("armchair_right", ("armchair_right",), (0.055, 0.055, 0.030)),
        ("plant_left", ("plant_left",), (0.035, 0.035, 0.020)),
        ("plant_right", ("plant_right",), (0.035, 0.035, 0.020)),
    )
    randomized: dict[str, Furniture] = {}
    for group_name, names, limits in groups:
        rng = _tidybot_rng(seed, f"furniture:{group_name}")
        translate_x = rng.uniform(-limits[0], limits[0])
        translate_y = rng.uniform(-limits[1], limits[1])
        yaw_delta = rng.uniform(-limits[2], limits[2])
        anchor = by_name[names[0]].pos_xy
        cosine, sine = math.cos(yaw_delta), math.sin(yaw_delta)
        for name in names:
            item = by_name[name]
            offset_x = item.pos_xy[0] - anchor[0]
            offset_y = item.pos_xy[1] - anchor[1]
            randomized[name] = replace(
                item,
                pos_xy=(
                    anchor[0] + translate_x + cosine * offset_x - sine * offset_y,
                    anchor[1] + translate_y + sine * offset_x + cosine * offset_y,
                ),
                yaw=item.yaw + yaw_delta,
            )
    return [randomized[item.name] for item in fixed]


def _randomized_litter(
    template: Litter,
    *,
    seed: int,
    pos_xy: tuple[float, float],
) -> Litter:
    rng = _tidybot_rng(seed, f"litter:{template.name}:appearance")
    rgb = tuple(_clamp_channel(channel + rng.uniform(-0.035, 0.035)) for channel in template.rgba[:3])
    return replace(
        template,
        mass=template.mass * rng.uniform(0.85, 1.15),
        rgba=(*rgb, template.rgba[3]),
        pos_xy=pos_xy,
        yaw=rng.uniform(-math.pi, math.pi),
    )


def _litter_manifest(item: Litter, *, safe_zone: str, selected: bool) -> dict[str, object]:
    return {
        "name": item.name,
        "selected_target": selected,
        "shape": item.shape,
        "half_size_m": [float(value) for value in item.half_size],
        "position_xy_m": [float(value) for value in item.pos_xy],
        "yaw_rad": float(item.yaw),
        "mass_kg": float(item.mass),
        "rgba": [float(value) for value in item.rgba],
        "safe_zone": safe_zone,
    }


def _furniture_manifest(
    furniture: list[Furniture],
    fixed: list[Furniture],
) -> list[dict[str, object]]:
    fixed_by_name = {item.name: item for item in fixed}
    records = []
    for item in furniture:
        base = fixed_by_name[item.name]
        records.append(
            {
                "name": item.name,
                "position_xy_m": [float(value) for value in item.pos_xy],
                "position_delta_m": [
                    float(item.pos_xy[0] - base.pos_xy[0]),
                    float(item.pos_xy[1] - base.pos_xy[1]),
                ],
                "yaw_rad": float(item.yaw),
                "yaw_delta_rad": float(item.yaw - base.yaw),
            }
        )
    return records


def _tidybot_randomization_manifest(
    *,
    seed: int,
    target_name: str,
    single_target: bool,
    spec: RoomSpec,
    object_records: list[dict[str, object]],
) -> dict[str, object]:
    fixed = option_d_tidybot_spec()
    return {
        "schema": "stretch_cleanup.tidybot_scene_randomization",
        "schema_version": 1,
        "generator": "randomized_option_d_tidybot_spec",
        "seed": seed,
        "target_name": target_name,
        "single_target": single_target,
        "room": {
            "width_m": float(spec.width),
            "depth_m": float(spec.depth),
            "bin_position_xy_m": [float(value) for value in spec.bin_pos],
        },
        "constraints": {
            "wall_margin_m": TIDYBOT_WALL_MARGIN_M,
            "minimum_object_spacing_m": TIDYBOT_OBJECT_SPACING_M,
            "furniture_clearance_m": TIDYBOT_FURNITURE_CLEARANCE_M,
            "minimum_robot_target_distance_m": TIDYBOT_ROBOT_TARGET_CLEARANCE_M,
            "target_safe_zones": [
                {
                    "name": name,
                    "x_range_m": [bounds[0], bounds[1]],
                    "y_range_m": [bounds[2], bounds[3]],
                }
                for name, bounds in TIDYBOT_TARGET_SAFE_ZONES
            ],
        },
        "robot_start": [float(value) for value in spec.robot_start],
        "lighting": {
            "position_m": [float(value) for value in spec.light_pos],
            "diffuse_rgb": [float(value) for value in spec.light_diffuse],
        },
        "floor": {
            "rgb1": [float(value) for value in spec.floor_rgb1],
            "rgb2": [float(value) for value in spec.floor_rgb2],
        },
        "furniture": _furniture_manifest(spec.furniture, fixed.furniture),
        "objects": object_records,
    }


def randomized_option_d_tidybot_spec(
    seed: int,
    target_name: str | None = None,
    single_target: bool = True,
) -> RoomSpec:
    """Return a deterministic, auditable option-D episode for TidyBot.

    Target zones sit in the broad south and side aisles.  Their dimensions,
    wall margin, spacing, and furniture-clearance tests are explicit here so
    scene generation does not need to import the planner and create a cycle.
    """

    seed = int(seed)
    fixed = option_d_tidybot_spec()
    templates = {item.name: item for item in fixed.litter}
    if target_name is not None and target_name not in templates:
        raise ValueError(
            f"unknown TidyBot target {target_name!r}; choose from {TIDYBOT_TARGET_NAMES}"
        )
    selected = target_name or _tidybot_rng(seed, "target_selection").choice(TIDYBOT_TARGET_NAMES)
    names = [selected] if single_target else list(TIDYBOT_TARGET_NAMES)

    furniture = _randomized_option_d_tidybot_furniture(seed)
    robot_rng = _tidybot_rng(seed, "robot_start")
    robot_start = (
        robot_rng.uniform(-0.22, 0.22),
        robot_rng.uniform(-2.76, -2.60),
        math.pi / 2.0 + robot_rng.uniform(-0.10, 0.10),
    )

    environment_rng = _tidybot_rng(seed, "environment")
    light_scale = environment_rng.uniform(0.92, 1.08)
    light_diffuse = tuple(
        _clamp_channel(channel * light_scale + environment_rng.uniform(-0.012, 0.012))
        for channel in fixed.light_diffuse
    )
    floor_scale = environment_rng.uniform(0.92, 1.08)
    floor_shift = [environment_rng.uniform(-0.018, 0.018) for _ in range(3)]
    floor_rgb1 = tuple(
        _clamp_channel(channel * floor_scale + floor_shift[index])
        for index, channel in enumerate(fixed.floor_rgb1)
    )
    floor_rgb2 = tuple(
        _clamp_channel(channel * floor_scale + floor_shift[index])
        for index, channel in enumerate(fixed.floor_rgb2)
    )
    spec = replace(
        fixed,
        furniture=furniture,
        litter=[],
        robot_start=robot_start,
        light_pos=(
            fixed.light_pos[0] + environment_rng.uniform(-0.35, 0.35),
            fixed.light_pos[1] + environment_rng.uniform(-0.30, 0.30),
            fixed.light_pos[2] + environment_rng.uniform(-0.25, 0.25),
        ),
        light_diffuse=light_diffuse,
        floor_rgb1=floor_rgb1,
        floor_rgb2=floor_rgb2,
        randomization_manifest={},
    )

    zone_rng = _tidybot_rng(seed, "target_zones")
    zones = zone_rng.sample(list(TIDYBOT_TARGET_SAFE_ZONES), k=len(names))
    placed: list[tuple[float, float]] = []
    litter: list[Litter] = []
    object_records: list[dict[str, object]] = []
    for name, (zone_name, bounds) in zip(names, zones, strict=True):
        template = templates[name]
        radius = _litter_xy_radius(template)
        position_rng = _tidybot_rng(seed, f"litter:{name}:position")
        for _ in range(200):
            position = (
                position_rng.uniform(bounds[0], bounds[1]),
                position_rng.uniform(bounds[2], bounds[3]),
            )
            if _tidybot_target_position_is_safe(
                position,
                room=spec,
                furniture=furniture,
                radius=radius,
                robot_start=robot_start,
                placed=placed,
                minimum_robot_distance=TIDYBOT_ROBOT_TARGET_CLEARANCE_M,
            ):
                break
        else:
            raise RuntimeError(f"could not place {name!r} safely in {zone_name!r}")
        item = _randomized_litter(template, seed=seed, pos_xy=position)
        litter.append(item)
        placed.append(position)
        object_records.append(
            _litter_manifest(item, safe_zone=zone_name, selected=name == selected)
        )

    spec.litter = litter
    spec.randomization_manifest = _tidybot_randomization_manifest(
        seed=seed,
        target_name=selected,
        single_target=single_target,
        spec=spec,
        object_records=object_records,
    )
    return spec


def tidybot_manipulation_spec(seed: int, target_name: str) -> RoomSpec:
    """Single reachable target in front of a TidyBot whose base remains locked."""

    seed = int(seed)
    spec = randomized_option_d_tidybot_spec(seed, target_name=target_name, single_target=True)
    target = spec.litter[0]
    rng = _tidybot_rng(seed, f"manipulation:{target_name}:pose")
    for _ in range(100):
        forward = rng.uniform(*TIDYBOT_MANIPULATION_FORWARD_RANGE_M)
        lateral = rng.uniform(*TIDYBOT_MANIPULATION_LATERAL_RANGE_M)
        heading = spec.robot_start[2]
        position = (
            spec.robot_start[0] + math.cos(heading) * forward - math.sin(heading) * lateral,
            spec.robot_start[1] + math.sin(heading) * forward + math.cos(heading) * lateral,
        )
        if _tidybot_target_position_is_safe(
            position,
            room=spec,
            furniture=spec.furniture,
            radius=_litter_xy_radius(target),
            robot_start=spec.robot_start,
            placed=[],
            minimum_robot_distance=TIDYBOT_MANIPULATION_FORWARD_RANGE_M[0] - 0.01,
        ):
            break
    else:
        raise RuntimeError(f"could not place {target_name!r} in the locked-base reach zone")

    target = replace(target, pos_xy=position)
    spec.litter = [target]
    manifest = dict(spec.randomization_manifest)
    constraints = dict(manifest["constraints"])
    constraints["minimum_robot_target_distance_m"] = (
        TIDYBOT_MANIPULATION_FORWARD_RANGE_M[0] - 0.01
    )
    constraints["locked_base_reach_zone_m"] = {
        "forward_range": list(TIDYBOT_MANIPULATION_FORWARD_RANGE_M),
        "lateral_range": list(TIDYBOT_MANIPULATION_LATERAL_RANGE_M),
    }
    manifest.update(
        {
            "generator": "tidybot_manipulation_spec",
            "mode": "locked_base_manipulation",
            "constraints": constraints,
            "objects": [
                _litter_manifest(target, safe_zone="locked_base_reach", selected=True)
            ],
            "manipulation": {
                "base_locked": True,
                "target_relative_position_m": {
                    "forward": float(forward),
                    "lateral": float(lateral),
                },
            },
        }
    )
    spec.randomization_manifest = manifest
    return spec


def randomized_furniture(rng: random.Random, spec: RoomSpec) -> list[Furniture]:
    """Re-arrange the room: which items are present, and where along the walls.

    Randomising only object placement and lighting would leave every scene with
    the same floor plan, so a held-out split would not actually be unseen.  Here
    the layout itself varies: items are dropped, mirrored, slid along their wall
    and rotated.
    """
    half_w, half_d = spec.width / 2.0, spec.depth / 2.0
    catalogue = {item.name: item for item in default_furniture()}
    chosen: list[Furniture] = []

    # Wall-hugging slots: (wall_axis, fixed coordinate, slide range, base yaw)
    slots = {
        "sofa": ("y", half_d - 0.45, (-1.6, 1.6), 0.0),
        "coffee_table": ("free", 0.0, (0.0, 0.0), 0.0),
        "tv_console": ("y", -half_d + 0.22, (-1.6, 1.6), 0.0),
        "armchair": ("corner", 0.0, (0.0, 0.0), 0.0),
        "bookshelf": ("x", half_w - 0.20, (-1.4, 1.4), 0.0),
    }

    sofa_x = rng.uniform(-1.2, 1.2)
    for name, (kind, fixed, slide, base_yaw) in slots.items():
        if name != "sofa" and rng.random() < 0.18:
            continue  # sometimes the room simply lacks this piece
        template = catalogue[name]
        if kind == "y":
            pos = (rng.uniform(*slide), fixed)
            yaw = base_yaw + rng.uniform(-0.06, 0.06)
        elif kind == "x":
            pos = (fixed * rng.choice([1.0, -1.0]), rng.uniform(*slide))
            yaw = base_yaw + rng.uniform(-0.06, 0.06)
        elif kind == "corner":
            pos = (
                rng.choice([-1.0, 1.0]) * rng.uniform(half_w - 1.1, half_w - 0.55),
                rng.choice([-1.0, 1.0]) * rng.uniform(half_d - 1.2, half_d - 0.6),
            )
            yaw = rng.uniform(-math.pi, math.pi)
        else:  # coffee table sits in front of the sofa
            pos = (sofa_x + rng.uniform(-0.35, 0.35), half_d - rng.uniform(1.25, 1.75))
            yaw = rng.uniform(-0.10, 0.10)
        if name == "sofa":
            pos = (sofa_x, fixed)
        chosen.append(
            Furniture(
                name=template.name,
                parts=template.parts,
                material=template.material,
                pos_xy=pos,
                yaw=yaw,
                navigation_obstacle=template.navigation_obstacle,
            )
        )
    return chosen


def randomized_spec(seed: int) -> RoomSpec:
    """A domain-randomized room: layout, litter placement, lighting, and floor tone."""
    rng = random.Random(seed)
    spec = RoomSpec(furniture=[], litter=[])
    spec.width = rng.uniform(6.2, 7.8)
    spec.depth = rng.uniform(4.4, 5.6)
    spec.furniture = randomized_furniture(rng, spec)
    spec.bin_pos = (
        rng.choice([-1.0, 1.0]) * rng.uniform(spec.width / 2 - 0.75, spec.width / 2 - 0.45),
        rng.choice([-1.0, 1.0]) * rng.uniform(spec.depth / 2 - 0.85, spec.depth / 2 - 0.5),
    )

    free_zones = [(-2.4, 2.8, -1.60, -0.35), (0.4, 2.8, 0.20, 0.80)]
    templates = default_litter()
    placed: list[tuple[float, float]] = []
    for template in templates:
        for _ in range(60):
            zx0, zx1, zy0, zy1 = rng.choice(free_zones)
            x, y = rng.uniform(zx0, zx1), rng.uniform(zy0, zy1)
            if all((x - px) ** 2 + (y - py) ** 2 > 0.35**2 for px, py in placed):
                placed.append((x, y))
                spec.litter.append(
                    Litter(
                        name=template.name,
                        shape=template.shape,
                        half_size=template.half_size,
                        mass=template.mass * rng.uniform(0.8, 1.25),
                        rgba=template.rgba,
                        pos_xy=(x, y),
                        yaw=rng.uniform(-3.14, 3.14),
                    )
                )
                break

    spec.light_pos = (rng.uniform(-1.5, 1.5), rng.uniform(-1.0, 1.0), rng.uniform(2.4, 3.2))
    level = rng.uniform(0.45, 0.85)
    spec.light_diffuse = (level, level * rng.uniform(0.95, 1.02), level * rng.uniform(0.92, 1.0))
    tone = rng.uniform(0.45, 0.72)
    spec.floor_rgb1 = (tone, tone * 0.82, tone * 0.60)
    spec.floor_rgb2 = (tone * 1.08, tone * 0.90, tone * 0.68)
    spec.robot_start = (rng.uniform(-0.4, 0.8), rng.uniform(-0.85, -0.55), rng.uniform(-0.3, 0.3))
    return spec


def _bin_xml(spec: RoomSpec) -> str:
    bx, by = spec.bin_pos
    hx, hy, hz = spec.bin_half
    t = BIN_WALL_THICKNESS
    rim_half_height = min(0.010, hz / 4.0)
    wall_half_height = hz - rim_half_height
    wall_center_z = wall_half_height
    rim_center_z = 2.0 * hz - rim_half_height
    walls = [
        ((hx - t, 0.0), (t, hy)),
        ((-hx + t, 0.0), (t, hy)),
        ((0.0, hy - t), (hx, t)),
        ((0.0, -hy + t), (hx, t)),
    ]
    parts = [
        f'      <geom name="bin_floor" type="box" pos="0 0 {t:.4f}"'
        f' size="{hx:.4f} {hy:.4f} {t:.4f}" material="bin_inner_mat"/>'
    ]
    for index, (offset, half) in enumerate(walls):
        parts.append(
            f'      <geom name="bin_wall_{index}" type="box"'
            f' pos="{offset[0]:.4f} {offset[1]:.4f} {wall_center_z:.4f}"'
            f' size="{half[0]:.4f} {half[1]:.4f} {wall_half_height:.4f}"'
            f' material="bin_mat"/>'
        )
        parts.append(
            f'      <geom name="bin_rim_{index}" type="box"'
            f' pos="{offset[0]:.4f} {offset[1]:.4f} {rim_center_z:.4f}"'
            f' size="{half[0]:.4f} {half[1]:.4f} {rim_half_height:.4f}"'
            f' material="bin_rim_mat"/>'
        )
    rendered = "\n".join(parts)
    return (
        f'    <body name="collection_bin" pos="{bx:.4f} {by:.4f} 0">\n'
        f"{rendered}\n"
        "    </body>"
    )


def build_xml(
    spec: RoomSpec,
    stretch_path: Path | None = None,
    *,
    include_robot: bool = True,
) -> str:
    """Emit a complete MJCF document for the given room specification."""
    stretch = (stretch_path or STRETCH_XML).resolve()
    if include_robot and not stretch.exists():
        raise FileNotFoundError(
            f"Stretch 3 model not found at {stretch}. Clone mujoco_menagerie into external/."
        )
    robot_asset = f'    <model name="stretch" file="{stretch}"/>' if include_robot else ""
    robot_attach = (
        '    <attach model="stretch" body="base_link" prefix="stretch_"/>'
        if include_robot
        else ""
    )

    hw, hd, wh = spec.width / 2.0, spec.depth / 2.0, spec.wall_height
    furniture = "\n".join(f.to_xml() for f in spec.furniture)
    litter = "\n".join(item.to_xml() for item in spec.litter)
    lx, ly, lz = spec.light_pos
    dr, dg, db = spec.light_diffuse
    f1 = " ".join(f"{v:.3f}" for v in spec.floor_rgb1)
    f2 = " ".join(f"{v:.3f}" for v in spec.floor_rgb2)
    overview_height = max(8.0, max(spec.width, spec.depth) * 1.22)
    if spec.south_opening_width > 0.0:
        opening = min(spec.south_opening_width, spec.width - 0.2)
        segment_half = (spec.width - opening) / 4.0
        segment_offset = opening / 2.0 + segment_half
        south_wall = (
            f'    <geom name="wall_south_left" type="box" pos="{-segment_offset:.3f} {-hd:.3f} {wh / 2:.3f}"\n'
            f'          size="{segment_half:.3f} 0.03 {wh / 2:.3f}" material="wall_mat"/>\n'
            f'    <geom name="wall_south_right" type="box" pos="{segment_offset:.3f} {-hd:.3f} {wh / 2:.3f}"\n'
            f'          size="{segment_half:.3f} 0.03 {wh / 2:.3f}" material="wall_mat"/>'
        )
    else:
        south_wall = (
            f'    <geom name="wall_south" type="box" pos="0 {-hd:.3f} {wh / 2:.3f}"\n'
            f'          size="{hw:.3f} 0.03 {wh / 2:.3f}" material="wall_mat"/>'
        )

    return f"""<mujoco model="stretch_living_room_v2">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="10"
          noslip_iterations="3">
    <flag multiccd="enable"/>
  </option>

  <asset>
{robot_asset}
    <texture name="sky" type="skybox" builtin="gradient"
             rgb1="0.70 0.78 0.86" rgb2="0.22 0.26 0.32" width="512" height="3072"/>
    <texture name="floor_tex" type="2d" builtin="checker" rgb1="{f1}" rgb2="{f2}"
             width="512" height="512"/>
    <material name="floor_mat" texture="floor_tex" texrepeat="8 6" reflectance="0.05"/>
    <material name="wall_mat" rgba="0.87 0.85 0.80 1"/>
    <material name="fabric_teal" rgba="0.19 0.42 0.47 1"/>
    <material name="fabric_rust" rgba="0.66 0.31 0.21 1"/>
    <material name="fabric_ivory" rgba="0.78 0.75 0.69 1"/>
    <material name="fabric_blue" rgba="0.20 0.34 0.48 1"/>
    <material name="rug_grey" rgba="0.56 0.54 0.50 1"/>
    <material name="screen_black" rgba="0.015 0.018 0.020 1" specular="0.2"/>
    <material name="plant_green" rgba="0.12 0.34 0.15 1"/>
    <material name="wood_light" rgba="0.62 0.44 0.26 1"/>
    <material name="wood_dark" rgba="0.24 0.17 0.12 1"/>
    <material name="bin_mat" rgba="0.04 0.28 0.85 1"/>
    <material name="bin_inner_mat" rgba="0.02 0.08 0.24 1"/>
    <material name="bin_rim_mat" rgba="0.72 0.90 1.00 1"/>
  </asset>

  <visual>
    <headlight ambient="0.32 0.32 0.32" diffuse="0.45 0.45 0.45" specular="0.05 0.05 0.05"/>
    <global azimuth="130" elevation="-25" offwidth="1280" offheight="720"/>
    <map znear="0.01" zfar="30"/>
  </visual>

  <worldbody>
    <light name="room_light" pos="{lx:.3f} {ly:.3f} {lz:.3f}" dir="0 0 -1"
           diffuse="{dr:.3f} {dg:.3f} {db:.3f}" directional="true"/>
    <geom name="floor" type="plane" size="{hw:.3f} {hd:.3f} 0.1" material="floor_mat"
          friction="1.0 0.01 0.001" condim="4"/>
    <camera name="overview" pos="0 0 {overview_height:.2f}" xyaxes="1 0 0 0 1 0" fovy="45"/>
    <camera name="route_overview" pos="0 0 {overview_height:.2f}" xyaxes="1 0 0 0 1 0" fovy="48"/>
    <camera name="route_oblique" pos="0 {-hd - 2.8:.2f} {wh + 5.0:.2f}"
            xyaxes="1 0 0 0 0.68 0.73" fovy="52"/>
    <camera name="corner" pos="{-hw - 1.0:.2f} {-hd - 1.0:.2f} {wh + 4.5:.2f}"
            xyaxes="0.707 -0.707 0 0.5 0.5 0.707" fovy="65"/>

{south_wall}
    <geom name="wall_north" type="box" pos="0 {hd:.3f} {wh / 2:.3f}"
          size="{hw:.3f} 0.03 {wh / 2:.3f}" material="wall_mat"/>
    <geom name="wall_west" type="box" pos="{-hw:.3f} 0 {wh / 2:.3f}"
          size="0.03 {hd:.3f} {wh / 2:.3f}" material="wall_mat"/>
    <geom name="wall_east" type="box" pos="{hw:.3f} 0 {wh / 2:.3f}"
          size="0.03 {hd:.3f} {wh / 2:.3f}" material="wall_mat"/>

{furniture}

{_bin_xml(spec)}

{litter}

{robot_attach}
  </worldbody>
</mujoco>
"""
