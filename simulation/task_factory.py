"""Reusable Genesis scene factory for the Franka pick-and-place benchmark."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .genesis_env import GenesisPickPlaceEnv
from .objects import PickPlaceObjects
from .robot import FrankaRobot, load_franka_panda


@dataclass(frozen=True)
class PickPlaceTaskConfig:
    """Geometry and episode parameters shared by training and evaluation."""

    object_position: tuple[float, float, float] = (0.65, 0.0, 0.04)
    goal_position: tuple[float, float, float] = (0.45, 0.25, 0.04)
    object_size: tuple[float, float, float] = (0.06, 0.06, 0.06)
    object_color: tuple[float, float, float] = (0.9, 0.12, 0.08)
    control_decimation: int = 4
    max_episode_steps: int = 400
    success_threshold: float = 0.03
    require_release_for_success: bool = True
    require_lift_for_success: bool = True
    lift_success_height: float = 0.03
    assist_grasp: bool = True
    require_dual_finger_contact_for_assist: bool = False
    assist_contact_steps: int = 3
    grasp_distance: float = 0.15
    grasp_offset: tuple[float, float, float] = (0.0, 0.0, -0.07)
    robot_friction: float = 1.5
    gripper_kp: float = 300.0
    gripper_kv: float = 15.0
    gripper_force_limit: float = 100.0
    camera_enabled: bool = False
    camera_resolution: tuple[int, int] = (96, 96)
    camera_position: tuple[float, float, float] = (1.2, -1.2, 0.9)
    camera_lookat: tuple[float, float, float] = (0.5, 0.1, 0.1)
    camera_fov: float = 50.0
    goal_marker_enabled: bool = True
    goal_marker_size: tuple[float, float, float] = (0.12, 0.12, 0.006)
    table_color: tuple[float, float, float] = (0.20, 0.22, 0.25)
    table_emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
    presentation_camera_enabled: bool = False
    presentation_camera_resolution: tuple[int, int] = (960, 540)
    presentation_camera_position: tuple[float, float, float] = (1.55, -1.55, 1.10)
    presentation_camera_lookat: tuple[float, float, float] = (0.48, 0.10, 0.12)
    presentation_camera_fov: float = 44.0


def initialize_genesis(*, backend: str = "gpu", precision: str = "32") -> Any:
    """Initialize Genesis once in a process and return its module.

    Genesis owns global runtime initialization; call this before creating a
    vector environment. ``backend`` accepts ``gpu`` for ROCm and ``cpu`` for
    functional debugging.
    """
    # Genesis' Linux rasterizer uses EGL by default. Set it before importing
    # PyOpenGL so headless cloud workers do not attempt an X11/GLX context.
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    try:
        import genesis as gs
    except ImportError as error:
        raise ImportError("Install genesis-world[render] before creating a task.") from error
    try:
        runtime_backend = getattr(gs, backend)
    except AttributeError as error:
        raise ValueError(f"unsupported Genesis backend: {backend}") from error
    gs.init(backend=runtime_backend, precision=precision)
    return gs


def make_pick_place_env(
    *,
    config: PickPlaceTaskConfig = PickPlaceTaskConfig(),
    show_viewer: bool = False,
    domain_randomizer: Callable[[], dict[str, Any]] | None = None,
) -> GenesisPickPlaceEnv:
    """Build one independent Franka scene suitable for one RL worker.

    ``initialize_genesis`` must be called in the same process before this
    function. Worker processes must each construct their own scene.
    """
    try:
        import genesis as gs
    except ImportError as error:
        raise ImportError("Install genesis-world[render] before creating a task.") from error

    scene_kwargs: dict[str, Any] = {"show_viewer": show_viewer}
    if show_viewer:
        scene_kwargs["viewer_options"] = gs.options.ViewerOptions(
            camera_pos=(2.5, -2.5, 1.8),
            camera_lookat=(0.4, 0.0, 0.3),
            camera_fov=40,
        )
    scene = gs.Scene(**scene_kwargs)
    scene.add_entity(
        gs.morphs.Plane(),
        surface=gs.surfaces.Rough(color=config.table_color, emissive=config.table_emissive),
    )
    franka_entity = load_franka_panda(scene)
    object_position = np.asarray(config.object_position, dtype=np.float32)
    cube = scene.add_entity(
        gs.morphs.Box(pos=tuple(object_position), size=config.object_size),
        material=gs.materials.Rigid(),
        # The object must be visually separable from the table. This affects
        # rendering only; mass/friction continue to be set by PickPlaceObjects.
        surface=gs.surfaces.Rough(color=config.object_color, emissive=(0.08, 0.005, 0.0)),
    )
    target_marker = None
    if config.goal_marker_enabled:
        marker_position = np.asarray(config.goal_position, dtype=np.float32).copy()
        marker_position[2] = 0.003
        # This bright, thin tile makes the randomized placement goal observable
        # to the RGB policy while ``collision=False`` leaves task dynamics and
        # success geometry unchanged.
        target_marker = scene.add_entity(
            gs.morphs.Box(
                pos=tuple(marker_position), size=config.goal_marker_size,
                fixed=True, collision=False,
            ),
            material=gs.materials.Rigid(),
            surface=gs.surfaces.Rough(color=(0.1, 0.9, 0.2), emissive=(0.02, 0.15, 0.02)),
        )
    camera = None
    if config.camera_enabled:
        from .camera import Camera

        camera = Camera(scene.add_camera(
            res=tuple(config.camera_resolution),
            pos=tuple(config.camera_position),
            lookat=tuple(config.camera_lookat),
            fov=config.camera_fov,
            GUI=False,
        ))
    presentation_camera = None
    if config.presentation_camera_enabled:
        from .camera import Camera

        presentation_camera = Camera(scene.add_camera(
            res=tuple(config.presentation_camera_resolution),
            pos=tuple(config.presentation_camera_position),
            lookat=tuple(config.presentation_camera_lookat),
            fov=config.presentation_camera_fov,
            GUI=False,
        ))
    scene.build()
    robot = FrankaRobot(franka_entity)
    robot.configure_contact_gripper(
        friction=config.robot_friction,
        kp=config.gripper_kp,
        kv=config.gripper_kv,
        force_limit=config.gripper_force_limit,
    )
    return GenesisPickPlaceEnv(
        scene=scene,
        robot=robot,
        objects=PickPlaceObjects(
            cube, object_position, np.asarray(config.goal_position, dtype=np.float32),
            target_marker_entity=target_marker,
        ),
        camera=camera,
        presentation_camera=presentation_camera,
        control_decimation=config.control_decimation,
        max_episode_steps=config.max_episode_steps,
        success_threshold=config.success_threshold,
        require_release_for_success=config.require_release_for_success,
        require_lift_for_success=config.require_lift_for_success,
        lift_success_height=config.lift_success_height,
        domain_randomizer=domain_randomizer,
        assist_grasp=config.assist_grasp,
        require_dual_finger_contact_for_assist=config.require_dual_finger_contact_for_assist,
        assist_contact_steps=config.assist_contact_steps,
        grasp_distance=config.grasp_distance,
        grasp_offset=config.grasp_offset,
    )
