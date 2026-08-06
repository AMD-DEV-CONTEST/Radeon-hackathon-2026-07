"""multi-robot soccer scene builder for Genesis.

Defines the 14×9 field, two goals, 6 T1 robots (3 per team), and a shared ball.
Entity handles are preserved for downstream position/velocity reads and joint control.

Genesis is imported lazily — all data classes and constants are usable without it.
Call ``Scene3v3.build()`` only when a GPU / Genesis runtime is available.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

try:
    import genesis as gs
except Exception:
    gs = None


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════

class Team(Enum):
    """Left team attacks +x goal; right team attacks -x goal."""
    LEFT = 0
    RIGHT = 1


class Role(Enum):
    ATTACKER = "attacker"
    DEFENDER = "defender"
    GOALKEEPER = "goalkeeper"


# ═══════════════════════════════════════════════════════════════════
# Field constants
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FieldConstants:
    """Immutable soccer field geometry (meters)."""
    field_length: float = 14.0      # x-axis
    field_width: float = 9.0        # y-axis
    goal_width: float = 2.6
    goal_height: float = 1.0
    circle_radius: float = 1.5
    ball_radius: float = 0.11
    robot_stand_height: float = 0.72

    @property
    def half_length(self) -> float:
        return self.field_length / 2.0

    @property
    def half_width(self) -> float:
        return self.field_width / 2.0

    @property
    def goal_half(self) -> float:
        return self.goal_width / 2.0

    @property
    def left_goal_x(self) -> float:
        """Left team defends this goal."""
        return -self.half_length

    @property
    def right_goal_x(self) -> float:
        """Right team defends this goal."""
        return self.half_length


DEFAULT_FIELD = FieldConstants()


# ═══════════════════════════════════════════════════════════════════
# Scene configuration
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SceneConfig:
    """Configuration for a multi-robot match scene."""
    field_cfg: FieldConstants = field(default_factory=FieldConstants)
    robot_urdf: str = ""          # set before build()
    dt: float = 0.02
    substeps: int = 2
    show_viewer: bool = False
    record_video: bool = True

    # Initial formations (x, y, z) per team
    # Order within team: [attacker, defender, goalkeeper]
    left_formation: list = field(default_factory=lambda: [
        (-1.0, 0.0, 0.72),   # attacker
        (-3.5, 1.5, 0.72),   # defender
        (-6.5, 0.0, 0.72),   # goalkeeper
    ])
    right_formation: list = field(default_factory=lambda: [
        (1.0, 0.0, 0.72),    # attacker
        (3.5, -1.5, 0.72),   # defender
        (6.5, 0.0, 0.72),    # goalkeeper
    ])

    ball_start: tuple = (0.0, 0.0, 0.11)

    @property
    def all_start_positions(self) -> list:
        """Flat list of 6 starting (x, y, z) positions: [L0, L1, L2, R0, R1, R2]."""
        return list(self.left_formation) + list(self.right_formation)


# ═══════════════════════════════════════════════════════════════════
# Entity handle container
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EntityHandles:
    """Stores Genesis entity handles after scene build.

    ``robots`` is ordered [L0, L1, L2, R0, R1, R2].
    Each entry can be ``None`` before build().
    """
    robots: list = field(default_factory=lambda: [None] * 6)
    ball: object = None
    camera: object = None
    scene: object = None
    built: bool = False


# ═══════════════════════════════════════════════════════════════════
# Player state (usable without Genesis)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PlayerState:
    """Per-player state tracked during a match (no Genesis required)."""
    team: Team
    robot_idx: int                # 0-5, index into EntityHandles.robots
    role: Role = Role.DEFENDER
    pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    quat: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0, 0.0]))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    fallen: bool = False
    fall_count: int = 0
    recovery_count: int = 0
    vel_cmd: np.ndarray = field(default_factory=lambda: np.zeros(3))  # vx, vy, vyaw

    @property
    def attack_goal_x(self) -> float:
        return DEFAULT_FIELD.right_goal_x if self.team == Team.LEFT else DEFAULT_FIELD.left_goal_x

    @property
    def defend_goal_x(self) -> float:
        return DEFAULT_FIELD.left_goal_x if self.team == Team.LEFT else DEFAULT_FIELD.right_goal_x

    @property
    def yaw(self) -> float:
        """Facing direction in radians (0 = +x)."""
        w, x, y, z = self.quat
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


@dataclass
class BallState:
    pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    prev_pos: np.ndarray = field(default_factory=lambda: np.zeros(3))

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.vel[:2]))


# ═══════════════════════════════════════════════════════════════════
# Scene3v3
# ═══════════════════════════════════════════════════════════════════

class Scene3v3:
    """multi-robot soccer scene with 6 T1 robots, ball, and dual goals.

    Use ``build()`` to create the Genesis scene (requires GPU).
    Use ``init_players()`` and ``init_ball()`` to set up state without Genesis.
    """

    def __init__(self, config: Optional[SceneConfig] = None):
        self.config = config or SceneConfig()
        self.field = self.config.field_cfg
        self.handles = EntityHandles()
        self.players: list[PlayerState] = []
        self.ball_state = BallState()
        self._init_players()
        self._init_ball()

    @property
    def genesis_available(self) -> bool:
        return gs is not None

    # ── State initialisation (no Genesis needed) ──────────────────

    def _init_players(self):
        """Create 6 PlayerState objects from config formations."""
        self.players = []
        positions = self.config.all_start_positions
        for i in range(6):
            team = Team.LEFT if i < 3 else Team.RIGHT
            role = [Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER][i % 3]
            p = PlayerState(
                team=team,
                robot_idx=i,
                role=role,
                pos=np.array(positions[i], dtype=np.float64),
                quat=np.array([1.0, 0.0, 0.0, 0.0]),
            )
            self.players.append(p)

    def _init_ball(self):
        self.ball_state = BallState(
            pos=np.array(self.config.ball_start, dtype=np.float64),
            vel=np.zeros(3),
            prev_pos=np.array(self.config.ball_start, dtype=np.float64),
        )

    def reset_positions(self):
        """Reset all players and ball to starting positions (no Genesis)."""
        positions = self.config.all_start_positions
        for i, p in enumerate(self.players):
            p.pos = np.array(positions[i], dtype=np.float64)
            p.quat = np.array([1.0, 0.0, 0.0, 0.0])
            p.vel = np.zeros(3)
            p.fallen = False
            p.fall_count = 0
            p.recovery_count = 0
            p.vel_cmd = np.zeros(3)
        self._init_players()  # rebuild to reset roles
        self._init_ball()

    # ── Genesis scene build (requires GPU) ────────────────────────

    def build(self, robot_urdf: Optional[str] = None):
        """Build the Genesis scene with 6 robots, ball, goals, and camera.

        Returns the EntityHandles with populated scene/robots/ball/camera.

        Raises RuntimeError if Genesis is not available.
        """
        if not self.genesis_available:
            raise RuntimeError(
                "Genesis is not available. Cannot build multi-robot scene.\n"
                "Install genesis-world or ensure GPU is accessible."
            )

        urdf = robot_urdf or self.config.robot_urdf
        if not urdf:
            raise ValueError("robot_urdf path must be provided to build().")

        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=self.config.dt, substeps=self.config.substeps),
            rigid_options=gs.options.RigidOptions(
                enable_self_collision=True, tolerance=1e-5, max_collision_pairs=2048
            ),
            viewer_options=gs.options.ViewerOptions(
                camera_pos=(0, -15, 10), camera_lookat=(0, 0, 0.5), camera_fov=50, res=(1280, 720)
            ),
            vis_options=gs.options.VisOptions(
                show_world_frame=False,
                show_link_frame=False,
                show_cameras=False,
                plane_reflection=True,
                ambient_light=(0.7, 0.7, 0.7),
                shadow=True,
            ),
            renderer=gs.renderers.Rasterizer(),
            show_viewer=self.config.show_viewer,
        )

        self._add_ground(scene)
        self._add_field_lines(scene)
        self._add_goals(scene)

        # 6 robots: [L0, L1, L2, R0, R1, R2]
        positions = self.config.all_start_positions
        robots = []
        for i, (x, y, z) in enumerate(positions):
            robot = scene.add_entity(
                gs.morphs.MJCF(file=urdf, pos=(x, y, z))
            )
            robots.append(robot)

        # Ball at center
        ball = scene.add_entity(
            morph=gs.morphs.Sphere(
                radius=self.field.ball_radius,
                pos=tuple(self.config.ball_start),
                fixed=False,
            ),
            surface=gs.surfaces.Rough(color=(0.1, 0.1, 0.1), roughness=0.4),
            material=gs.materials.Rigid(rho=400.0, friction=0.8),
        )

        # Camera
        cam = None
        if self.config.record_video:
            cam = scene.add_camera(
                res=(1280, 720), pos=(0, -15, 10), lookat=(0, 0, 0.5), fov=50, GUI=False
            )

        scene.build(n_envs=1)

        self.handles.scene = scene
        self.handles.robots = robots
        self.handles.ball = ball
        self.handles.camera = cam
        self.handles.built = True
        return self.handles

    def _add_ground(self, scene):
        scene.add_entity(
            morph=gs.morphs.Plane(),
            surface=gs.surfaces.Rough(color=(0.12, 0.45, 0.15), roughness=0.9),
        )

    def _add_field_lines(self, scene):
        f = self.field
        white = gs.surfaces.Rough(color=(1, 1, 1), roughness=0.8)
        lw, lh = 0.12, 0.005

        for x, y in [(0, -f.half_width), (0, f.half_width)]:
            scene.add_entity(
                morph=gs.morphs.Box(size=(f.field_length, lw, lh), pos=(x, y, lh / 2), fixed=True),
                surface=white)
        for x, y in [(-f.half_length, 0), (f.half_length, 0), (0, 0)]:
            scene.add_entity(
                morph=gs.morphs.Box(size=(lw, f.field_width, lh), pos=(x, y, lh / 2), fixed=True),
                surface=white)

        for i in range(32):
            a = 2 * math.pi * i / 32
            scene.add_entity(
                morph=gs.morphs.Box(
                    size=(0.3, lw, lh),
                    pos=(f.circle_radius * math.cos(a), f.circle_radius * math.sin(a), lh / 2),
                    euler=(0, 0, math.degrees(a)),
                    fixed=True,
                ),
                surface=white)

        pw = 3.0
        for px in [-f.half_length + 1.5, f.half_length - 1.5]:
            scene.add_entity(
                morph=gs.morphs.Box(size=(lw, 6.0, lh), pos=(px, -pw, lh / 2), fixed=True),
                surface=white)
            scene.add_entity(
                morph=gs.morphs.Box(size=(lw, 6.0, lh), pos=(px, pw, lh / 2), fixed=True),
                surface=white)
        for sx in [-f.half_length, f.half_length]:
            scene.add_entity(
                morph=gs.morphs.Box(size=(3.0, lw, lh), pos=(sx, pw, lh / 2), fixed=True),
                surface=white)
            scene.add_entity(
                morph=gs.morphs.Box(size=(3.0, lw, lh), pos=(sx, -pw, lh / 2), fixed=True),
                surface=white)

    def _add_goals(self, scene):
        f = self.field
        goal_s = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
        hg = f.goal_half
        pr = 0.05
        pw2 = pr * 2
        for gx in [-f.half_length, f.half_length]:
            scene.add_entity(
                morph=gs.morphs.Box(size=(pw2, pw2, f.goal_height), pos=(gx, -hg, f.goal_height / 2), fixed=True),
                surface=goal_s)
            scene.add_entity(
                morph=gs.morphs.Box(size=(pw2, pw2, f.goal_height), pos=(gx, hg, f.goal_height / 2), fixed=True),
                surface=goal_s)
            scene.add_entity(
                morph=gs.morphs.Box(size=(pw2, f.goal_width + pw2, pw2), pos=(gx, 0, f.goal_height), fixed=True),
                surface=goal_s)

    # ── Goal detection ────────────────────────────────────────────

    def check_goal(self) -> Optional[Team]:
        """Check if the ball has crossed a goal line. Returns scoring team or None."""
        ball_x = self.ball_state.pos[0]
        ball_y = self.ball_state.pos[1]
        f = self.field

        if ball_x > f.right_goal_x and abs(ball_y) < f.goal_half:
            return Team.LEFT  # left team scored in right goal
        if ball_x < f.left_goal_x and abs(ball_y) < f.goal_half:
            return Team.RIGHT  # right team scored in left goal
        return None

    def ball_out_of_bounds(self) -> bool:
        """Check if ball is out of field bounds."""
        f = self.field
        return (
            abs(self.ball_state.pos[0]) > f.half_length + 0.5
            or abs(self.ball_state.pos[1]) > f.half_width + 0.5
        )


def init_players_from_config(config: SceneConfig) -> list[PlayerState]:
    """Create 6 PlayerState objects from a SceneConfig (standalone helper)."""
    scene = Scene3v3(config)
    return scene.players
