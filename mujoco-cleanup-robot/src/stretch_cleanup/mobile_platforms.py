"""Standalone mobile-manipulator prototypes with chassis-mounted collection bins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from stretch_cleanup.scene import PROJECT_ROOT, RoomSpec, build_xml


TASK_PHASES = ("pick", "carry", "deposit")
BASKET_INNER_SIZE_M = (0.35, 0.30, 0.25)


@dataclass(frozen=True)
class ArmOnlySchema:
    """Policy boundary that makes base/arm interference structurally impossible."""

    arm_actuators: tuple[str, ...]
    base_actuators: tuple[str, ...]
    task_phases: tuple[str, ...] = TASK_PHASES

    def __post_init__(self) -> None:
        overlap = set(self.arm_actuators) & set(self.base_actuators)
        if overlap:
            raise ValueError(f"arm and base actions overlap: {sorted(overlap)}")


@dataclass(frozen=True)
class PlatformPrototype:
    name: str
    label: str
    model_path: Path
    base_body: str
    floor_z: float
    basket_pos: tuple[float, float, float]
    basket_yaw: float
    basket_mount: str
    arm_base_reference_height: float | None
    preview_key: str
    nav_camera: str
    workspace_camera: str
    wrist_camera: str
    wrist_camera_body: str | None
    schema: ArmOnlySchema
    notes: tuple[str, ...]


@dataclass(frozen=True)
class TidyBotCameraRandomization:
    """Deterministic, calibration-sized camera perturbations for sim data."""

    seed: int
    position_std_m: float = 0.0
    fovy_std_degrees: float = 0.0

    def __post_init__(self) -> None:
        if self.position_std_m < 0.0:
            raise ValueError("position_std_m must be non-negative")
        if self.fovy_std_degrees < 0.0:
            raise ValueError("fovy_std_degrees must be non-negative")


PLATFORMS = {
    "stretch": PlatformPrototype(
        name="stretch",
        label="Stretch 3 side-bin",
        model_path=PROJECT_ROOT
        / "external"
        / "mujoco_menagerie"
        / "hello_robot_stretch_3"
        / "stretch.xml",
        base_body="base_link",
        floor_z=0.0,
        basket_pos=(0.0, -0.62, 0.22),
        basket_yaw=0.0,
        basket_mount="chassis",
        arm_base_reference_height=None,
        preview_key="stow",
        nav_camera="nav_camera_rgb",
        workspace_camera="d435i_camera_rgb",
        wrist_camera="d405_rgb",
        wrist_camera_body=None,
        schema=ArmOnlySchema(
            arm_actuators=(
                "lift",
                "arm",
                "wrist_yaw",
                "wrist_pitch",
                "wrist_roll",
                "gripper",
            ),
            base_actuators=("left_wheel_vel", "right_wheel_vel"),
        ),
        notes=(
            "Lowest software integration cost.",
            "The side bin increases width and overlaps the lateral arm workspace.",
        ),
    ),
    "tidybot": PlatformPrototype(
        name="tidybot",
        label="Stanford TidyBot rigid trailer-bin",
        model_path=PROJECT_ROOT
        / "external"
        / "mujoco_menagerie"
        / "stanford_tidybot"
        / "tidybot.xml",
        base_body="base_link",
        floor_z=0.0,
        basket_pos=(-0.62, 0.0, 0.24),
        basket_yaw=0.0,
        basket_mount="rigid_trailer",
        arm_base_reference_height=0.49,
        preview_key="retract",
        nav_camera="tidy_nav",
        workspace_camera="tidy_workspace",
        wrist_camera="wrist",
        wrist_camera_body=None,
        schema=ArmOnlySchema(
            arm_actuators=(
                "joint_1",
                "joint_2",
                "joint_3",
                "joint_4",
                "joint_5",
                "joint_6",
                "joint_7",
                "fingers_actuator",
            ),
            base_actuators=("joint_x", "joint_y", "joint_th"),
        ),
        notes=(
            "Seven-axis arm can reach the floor and a rear chassis bin.",
            "The bin rides on a rigid two-wheel trailer; its 0.49 m rim matches the arm base.",
            "The Menagerie base uses x/y/theta position actuators, not wheel dynamics.",
        ),
    ),
    "tiago": PlatformPrototype(
        name="tiago",
        label="PAL TIAGo rear-bin",
        model_path=PROJECT_ROOT
        / "external"
        / "mujoco_menagerie"
        / "pal_tiago"
        / "tiago_position.xml",
        base_body="base_link",
        floor_z=-0.99,
        basket_pos=(-0.30, 0.0, 0.36),
        basket_yaw=0.0,
        basket_mount="chassis",
        arm_base_reference_height=None,
        preview_key="home",
        nav_camera="head_camera",
        workspace_camera="head_camera",
        wrist_camera="collection_wrist",
        wrist_camera_body="arm_7_link",
        schema=ArmOnlySchema(
            arm_actuators=(
                "arm_position_1_position",
                "arm_position_2_position",
                "arm_position_3_position",
                "arm_position_4_position",
                "arm_position_5_position",
                "arm_position_6_position",
                "arm_position_7_position",
                "gripper_left_finger_position",
                "gripper_right_finger_position",
            ),
            base_actuators=("wheel_left_joint_vel", "wheel_right_joint_vel"),
        ),
        notes=(
            "Mature differential-drive platform with a lifting torso.",
            "Largest footprint and highest control dimensionality.",
        ),
    ),
}


def platform(name: str) -> PlatformPrototype:
    try:
        result = PLATFORMS[name]
    except KeyError as exc:
        raise ValueError(f"unknown platform {name!r}; choose from {sorted(PLATFORMS)}") from exc
    if not result.model_path.is_file():
        raise FileNotFoundError(result.model_path)
    return result


def _populate_open_basket(basket: mujoco.MjsBody) -> None:
    """Build the shared open bin and its downward-facing verification camera."""

    hx, hy, hz = (value / 2.0 for value in BASKET_INNER_SIZE_M)
    thickness = 0.012
    rgba = (0.04, 0.24, 0.78, 1.0)
    common = {
        "type": mujoco.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
        "friction": (0.9, 0.02, 0.001),
        "density": 180.0,
        "rgba": rgba,
    }
    basket.add_geom(
        name="cargo_basket_floor",
        pos=(0.0, 0.0, thickness),
        size=(hx + thickness, hy + thickness, thickness),
        **common,
    )
    for name, pos, size in (
        (
            "cargo_basket_wall_pos_x",
            (hx + thickness, 0.0, hz),
            (thickness, hy + 2.0 * thickness, hz),
        ),
        (
            "cargo_basket_wall_neg_x",
            (-hx - thickness, 0.0, hz),
            (thickness, hy + 2.0 * thickness, hz),
        ),
        (
            "cargo_basket_wall_pos_y",
            (0.0, hy + thickness, hz),
            (hx, thickness, hz),
        ),
        (
            "cargo_basket_wall_neg_y",
            (0.0, -hy - thickness, hz),
            (hx, thickness, hz),
        ),
    ):
        basket.add_geom(name=name, pos=pos, size=size, **common)
    basket.add_camera(
        name="basket_rgb",
        pos=(0.0, 0.0, 0.50),
        quat=(1.0, 0.0, 0.0, 0.0),
        fovy=45.0,
        resolution=(640, 480),
    )


def _add_rigid_trailer(base: mujoco.MjsBody, prototype: PlatformPrototype) -> None:
    """Add a rigid drawbar trailer whose passive wheels carry the collection bin."""

    base.add_geom(
        name="cargo_hitch_base_mount",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(-0.30, 0.0, 0.15),
        size=(0.07, 0.07, 0.06),
        contype=1,
        conaffinity=1,
        density=450.0,
        rgba=(0.18, 0.20, 0.22, 1.0),
    )
    trailer = base.add_body(
        name="cargo_trailer",
        pos=(prototype.basket_pos[0], prototype.basket_pos[1], 0.0),
        euler=(0.0, 0.0, prototype.basket_yaw),
    )
    trailer.add_geom(
        name="cargo_trailer_frame",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(0.0, 0.0, 0.19),
        size=(0.22, 0.18, 0.05),
        contype=1,
        conaffinity=1,
        density=260.0,
        rgba=(0.16, 0.18, 0.20, 1.0),
    )
    trailer.add_geom(
        name="cargo_trailer_axle",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(0.0, 0.0, 0.11),
        size=(0.035, 0.18, 0.025),
        contype=1,
        conaffinity=1,
        density=400.0,
        rgba=(0.10, 0.11, 0.12, 1.0),
    )
    trailer.add_geom(
        name="cargo_hitch_trailer_mount",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(0.18, 0.0, 0.17),
        size=(0.05, 0.07, 0.07),
        contype=1,
        conaffinity=1,
        density=450.0,
        rgba=(0.18, 0.20, 0.22, 1.0),
    )
    trailer.add_geom(
        name="cargo_trailer_drawbar",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(0.275, 0.0, 0.15),
        size=(0.075, 0.04, 0.035),
        contype=1,
        conaffinity=1,
        density=300.0,
        rgba=(0.22, 0.24, 0.26, 1.0),
    )
    for side, y in (("left", 0.205), ("right", -0.205)):
        wheel = trailer.add_body(name=f"cargo_trailer_wheel_{side}", pos=(0.0, y, 0.075))
        wheel.add_joint(
            name=f"cargo_trailer_wheel_{side}_joint",
            type=mujoco.mjtJoint.mjJNT_HINGE,
            axis=(0.0, 1.0, 0.0),
            damping=0.02,
        )
        wheel.add_geom(
            name=f"cargo_trailer_wheel_{side}_geom",
            type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=(0.075, 0.026),
            quat=(0.70710678, 0.70710678, 0.0, 0.0),
            contype=1,
            conaffinity=1,
            friction=(1.2, 0.01, 0.001),
            density=850.0,
            rgba=(0.045, 0.045, 0.045, 1.0),
        )
    basket = trailer.add_body(
        name="cargo_basket",
        pos=(0.0, 0.0, prototype.basket_pos[2]),
    )
    _populate_open_basket(basket)


def _add_basket(base: mujoco.MjsBody, prototype: PlatformPrototype) -> None:
    """Attach either a chassis bin or the selected rigid two-wheel trailer."""

    if prototype.basket_mount == "rigid_trailer":
        _add_rigid_trailer(base, prototype)
        return
    if prototype.basket_mount != "chassis":
        raise ValueError(f"unsupported basket mount {prototype.basket_mount!r}")
    basket = base.add_body(
        name="cargo_basket",
        pos=prototype.basket_pos,
        euler=(0.0, 0.0, prototype.basket_yaw),
    )
    _populate_open_basket(basket)


def build_prototype_spec(
    name: str,
    *,
    include_floor: bool = True,
    camera_randomization: TidyBotCameraRandomization | None = None,
) -> mujoco.MjSpec:
    """Load a Menagerie model and add only standalone prototype fixtures."""

    prototype = platform(name)
    spec = mujoco.MjSpec.from_file(str(prototype.model_path))
    spec.compiler.fusestatic = False
    base = spec.body(prototype.base_body)
    if base is None:
        raise ValueError(f"{name}: missing base body {prototype.base_body}")
    _add_basket(base, prototype)
    if prototype.basket_mount == "rigid_trailer":
        for key in spec.keys:
            key.qpos = [*key.qpos, 0.0, 0.0]
    if name == "tidybot":
        rng = (
            np.random.default_rng(camera_randomization.seed)
            if camera_randomization is not None
            else None
        )

        def camera_values(
            position: tuple[float, float, float],
            fovy: float,
        ) -> tuple[tuple[float, float, float], float]:
            if rng is None or camera_randomization is None:
                return position, fovy
            offset = rng.normal(0.0, camera_randomization.position_std_m, size=3)
            perturbed_fovy = fovy + float(
                rng.normal(0.0, camera_randomization.fovy_std_degrees)
            )
            return tuple((np.asarray(position) + offset).tolist()), float(
                np.clip(perturbed_fovy, 20.0, 110.0)
            )

        nav_pos, nav_fovy = camera_values((0.42, 0.0, 0.70), 72.0)
        base.add_camera(
            name="tidy_nav",
            pos=nav_pos,
            zaxis=(-0.99, 0.0, 0.14),
            fovy=nav_fovy,
            resolution=(640, 360),
        )
        workspace_pos, workspace_fovy = camera_values((0.40, 0.0, 0.84), 64.0)
        base.add_camera(
            name="tidy_workspace",
            pos=workspace_pos,
            zaxis=(-0.82, 0.0, 0.57),
            fovy=workspace_fovy,
            resolution=(640, 480),
        )
        for camera_name in ("wrist", "basket_rgb"):
            camera = spec.camera(camera_name)
            if camera is None:
                continue
            position, fovy = camera_values(tuple(camera.pos), float(camera.fovy))
            camera.pos = position
            camera.fovy = fovy

    if prototype.wrist_camera_body is not None:
        wrist = spec.body(prototype.wrist_camera_body)
        if wrist is None:
            raise ValueError(f"{name}: missing wrist body {prototype.wrist_camera_body}")
        wrist.add_camera(
            name=prototype.wrist_camera,
            pos=(0.0, 0.0, 0.11),
            quat=(1.0, 0.0, 0.0, 0.0),
            fovy=50.0,
            resolution=(640, 480),
        )

    if include_floor:
        spec.worldbody.add_geom(
            name="prototype_floor",
            type=mujoco.mjtGeom.mjGEOM_PLANE,
            pos=(0.0, 0.0, prototype.floor_z),
            size=(3.0, 3.0, 0.1),
            contype=1,
            conaffinity=1,
            friction=(1.0, 0.01, 0.001),
            rgba=(0.50, 0.43, 0.34, 1.0),
        )
        spec.worldbody.add_light(
            name="prototype_key_light",
            pos=(-2.0, -2.0, prototype.floor_z + 4.0),
            dir=(0.3, 0.3, -1.0),
            diffuse=(0.85, 0.82, 0.78),
            type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
        )
    return spec


def build_prototype_model(
    name: str,
    *,
    camera_randomization: TidyBotCameraRandomization | None = None,
) -> mujoco.MjModel:
    return build_prototype_spec(
        name,
        camera_randomization=camera_randomization,
    ).compile()


def build_tidybot_room_spec(
    room: RoomSpec,
    *,
    spawn: tuple[float, float, float] | None = None,
    camera_randomization: TidyBotCameraRandomization | None = None,
) -> mujoco.MjSpec:
    """Attach the complete TidyBot trailer prototype to a sensor-honest room."""

    spawn = room.robot_start if spawn is None else spawn
    room_spec = mujoco.MjSpec.from_string(build_xml(room, include_robot=False))
    robot_spec = build_prototype_spec(
        "tidybot",
        include_floor=False,
        camera_randomization=camera_randomization,
    )
    frame = room_spec.worldbody.add_frame(
        name="tidybot_spawn",
        pos=(spawn[0], spawn[1], 0.0),
        euler=(0.0, 0.0, spawn[2]),
    )
    room_spec.attach(robot_spec, prefix="", frame=frame)
    return room_spec


def build_tidybot_room_model(
    room: RoomSpec,
    *,
    spawn: tuple[float, float, float] | None = None,
    camera_randomization: TidyBotCameraRandomization | None = None,
) -> mujoco.MjModel:
    return build_tidybot_room_spec(
        room,
        spawn=spawn,
        camera_randomization=camera_randomization,
    ).compile()


def reset_to_home(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    key_name: str = "home",
) -> None:
    """Reset to the authored home pose before prototype rendering."""

    mujoco.mj_resetData(model, data)
    key_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, key_name)
    if key_id >= 0:
        mujoco.mj_resetDataKeyframe(model, data, key_id)
    mujoco.mj_forward(model, data)


def camera_semantics(prototype: PlatformPrototype) -> dict[str, str]:
    return {
        "navigation_rgb": prototype.nav_camera,
        "workspace_rgbd": prototype.workspace_camera,
        "wrist_rgbd": prototype.wrist_camera,
        "basket_rgb": "basket_rgb",
    }


def world_aabb(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    exclude_geoms: tuple[str, ...] = ("prototype_floor",),
) -> tuple[np.ndarray, np.ndarray]:
    """Conservative world AABB from each geom's oriented local AABB."""

    low = np.full(3, np.inf)
    high = np.full(3, -np.inf)
    excluded = set(exclude_geoms)
    for geom_id in range(model.ngeom):
        if model.geom(geom_id).name in excluded:
            continue
        rotation = data.geom_xmat[geom_id].reshape(3, 3)
        local_center = model.geom_aabb[geom_id, :3]
        local_half = model.geom_aabb[geom_id, 3:]
        center = data.geom_xpos[geom_id] + rotation @ local_center
        half = np.abs(rotation) @ local_half
        low = np.minimum(low, center - half)
        high = np.maximum(high, center + half)
    return low, high
