"""Fixed Option-D mission contract for learned four-object cleanup.

All values in this module are task configuration, not simulator observations.
Runtime controllers may combine them with measured relative odometry, but may
not read MuJoCo body/object state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from realtime_cleanup.tidybot_workspace import Pose2D, wrap_angle
from stretch_cleanup.scene import RoomSpec, option_d_tidybot_spec


OBJECT_ORDER = ("can", "bottle", "cup", "banana")
ARM_RETRACT_POSITION = np.asarray(
    [
        -5.485427667650811e-10,
        -0.3488413691520691,
        3.1415116786956787,
        -2.551842212677002,
        1.4294766515376978e-05,
        -0.8729236125946045,
        1.5707964897155762,
        0.0029122550040483475,
    ],
    dtype=np.float32,
)

# Collision-checked reference loop from scripts/record_tidybot_room_route.py.
WORLD_ROUTE = (
    (0.0, -2.70),
    (-1.00, -1.50),
    (-2.40, -1.50),
    (-2.80, -1.10),
    (-2.80, 0.80),
    (-2.50, 1.50),
    (-1.40, 2.40),
    (0.0, 2.50),
    (1.40, 2.40),
    (2.50, 1.50),
    (2.80, 0.80),
    (2.80, -1.10),
    (2.40, -1.50),
    (1.00, -1.50),
    (0.0, -2.50),
    (0.0, -2.70),
)


@dataclass(frozen=True)
class FixedManipulationReference:
    object_name: str
    episode_index: int
    scene_seed: int
    target_forward_m: float
    target_lateral_m: float
    target_relative_yaw_rad: float


# Short, physically successful demonstrations selected from
# datasets/tidybot/my_collection_v2_curated.
MANIPULATION_REFERENCES = {
    "can": FixedManipulationReference(
        "can", 36, 20260864, 0.5773450663, 0.0399680808, 0.7306573619
    ),
    "bottle": FixedManipulationReference(
        "bottle", 33, 20260861, 0.5712365820, -0.0585122890, -0.6398811925
    ),
    "cup": FixedManipulationReference(
        "cup", 34, 20260862, 0.5622012395, -0.0436667814, -0.0196526173
    ),
    "banana": FixedManipulationReference(
        "banana", 28, 20260851, 0.5165823982, 0.0002242754, -2.9915539156
    ),
}
DOCK_HEADING_OVERRIDES = {
    # A west-facing cup approach keeps the rigid trailer clear of the island
    # sofa while preserving the demonstration's target-relative geometry.
    "cup": math.pi,
}


def world_to_spawn_pose(
    pose: Pose2D,
    spawn: tuple[float, float, float],
) -> np.ndarray:
    """Express a world pose in the TidyBot spawn-frame odometry coordinates."""

    dx = pose.x_m - spawn[0]
    dy = pose.y_m - spawn[1]
    cosine = math.cos(spawn[2])
    sine = math.sin(spawn[2])
    return np.asarray(
        [
            cosine * dx + sine * dy,
            -sine * dx + cosine * dy,
            wrap_angle(pose.yaw_rad - spawn[2]),
        ],
        dtype=np.float32,
    )


def spawn_to_world_pose(
    pose: np.ndarray,
    spawn: tuple[float, float, float],
) -> Pose2D:
    """Convert measured spawn-frame odometry into a world-frame route pose."""

    if pose.shape != (3,) or not np.isfinite(pose).all():
        raise ValueError("base odometry pose must be a finite three-vector")
    cosine = math.cos(spawn[2])
    sine = math.sin(spawn[2])
    return Pose2D(
        spawn[0] + cosine * float(pose[0]) - sine * float(pose[1]),
        spawn[1] + sine * float(pose[0]) + cosine * float(pose[1]),
        wrap_angle(spawn[2] + float(pose[2])),
    )


def fixed_task_room() -> RoomSpec:
    room = option_d_tidybot_spec()
    names = tuple(item.name for item in room.litter)
    if set(names) != set(OBJECT_ORDER):
        raise RuntimeError(f"fixed room object contract changed: {names}")
    room.litter = [
        replace(
            item,
            yaw=wrap_angle(
                target_dock_pose(room, item.name).yaw_rad
                + MANIPULATION_REFERENCES[item.name].target_relative_yaw_rad
            ),
        )
        for item in room.litter
    ]
    return room


def target_dock_pose(room: RoomSpec, object_name: str) -> Pose2D:
    """Return the fixed base pose that recreates the selected demo geometry."""

    if object_name not in MANIPULATION_REFERENCES:
        raise ValueError(f"unsupported fixed-task object: {object_name}")
    target = next((item for item in room.litter if item.name == object_name), None)
    if target is None:
        raise ValueError(f"fixed room has no {object_name}")
    reference = MANIPULATION_REFERENCES[object_name]
    # Face outward from the room centre toward the perimeter target. This keeps
    # the rigid trailer on the room-interior side of the base.
    heading = DOCK_HEADING_OVERRIDES.get(
        object_name,
        math.atan2(target.pos_xy[1], target.pos_xy[0]),
    )
    cosine = math.cos(heading)
    sine = math.sin(heading)
    offset_x = (
        cosine * reference.target_forward_m - sine * reference.target_lateral_m
    )
    offset_y = (
        sine * reference.target_forward_m + cosine * reference.target_lateral_m
    )
    return Pose2D(
        float(target.pos_xy[0] - offset_x),
        float(target.pos_xy[1] - offset_y),
        heading,
    )


def route_spawn_poses(room: RoomSpec) -> tuple[np.ndarray, ...]:
    """Return the one-lap route as sensor-compatible spawn-frame goals."""

    result = []
    for index, point in enumerate(WORLD_ROUTE):
        following = WORLD_ROUTE[(index + 1) % len(WORLD_ROUTE)]
        heading = math.atan2(following[1] - point[1], following[0] - point[0])
        result.append(world_to_spawn_pose(Pose2D(point[0], point[1], heading), room.robot_start))
    return tuple(result)


def object_dock_spawn_poses(room: RoomSpec) -> dict[str, np.ndarray]:
    return {
        name: world_to_spawn_pose(target_dock_pose(room, name), room.robot_start)
        for name in OBJECT_ORDER
    }


def _pre_dock(dock: Pose2D, distance_m: float = 0.34) -> tuple[float, float]:
    return (
        dock.x_m - math.cos(dock.yaw_rad) * distance_m,
        dock.y_m - math.sin(dock.yaw_rad) * distance_m,
    )


def object_approach_world_routes(
    room: RoomSpec,
) -> dict[str, tuple[tuple[float, float], ...]]:
    """Return fixed collision-avoiding approach routes in cleanup order."""

    docks = {name: target_dock_pose(room, name) for name in OBJECT_ORDER}
    return {
        "can": (
            WORLD_ROUTE[-1],
            (1.00, -1.50),
            _pre_dock(docks["can"], 0.68),
            _pre_dock(docks["can"]),
            (docks["can"].x_m, docks["can"].y_m),
        ),
        "bottle": (
            (docks["can"].x_m, docks["can"].y_m),
            (1.00, -1.50),
            (0.00, -2.50),
            (-1.00, -1.50),
            (-2.40, -1.50),
            (-2.80, -1.10),
            _pre_dock(docks["bottle"], 0.68),
            _pre_dock(docks["bottle"]),
            (docks["bottle"].x_m, docks["bottle"].y_m),
        ),
        "cup": (
            (docks["bottle"].x_m, docks["bottle"].y_m),
            (-2.80, -1.10),
            (-2.40, -1.50),
            _pre_dock(docks["cup"], 0.68),
            _pre_dock(docks["cup"]),
            (docks["cup"].x_m, docks["cup"].y_m),
        ),
        "banana": (
            (docks["cup"].x_m, docks["cup"].y_m),
            (-2.40, -1.50),
            (-1.00, -1.50),
            (0.00, -2.50),
            (1.00, -1.50),
            (2.40, -1.50),
            (2.80, -1.10),
            _pre_dock(docks["banana"], 0.68),
            _pre_dock(docks["banana"]),
            (docks["banana"].x_m, docks["banana"].y_m),
        ),
    }


def object_approach_spawn_routes(
    room: RoomSpec,
) -> dict[str, tuple[tuple[float, float], ...]]:
    return {
        name: tuple(
            tuple(
                float(value)
                for value in world_to_spawn_pose(
                    Pose2D(x, y, 0.0),
                    room.robot_start,
                )[:2]
            )
            for x, y in points
        )
        for name, points in object_approach_world_routes(room).items()
    }
