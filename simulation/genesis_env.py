"""SO-101 pick-and-place environment in Genesis, with a gym-style API.

Exposes ``SO101PickPlaceEnv`` with the interface the hackathon spec asks for::

    env = SO101PickPlaceEnv()
    obs = env.reset()              # -> {"image": RGB, "state": joint_position, ...}
    obs = env.step(action)         # action = 6-D joint targets
    obs = env.observe()            # current observation without stepping

The scene is a tabletop with three colored cubes (red / blue / green) placed at
randomized positions plus a basket (place container), a fixed world camera and an
eye-in-hand wrist camera. Cubes are Genesis ``Box`` primitives (color == task
semantics), which are reliably graspable and need no external meshes.

Robot model + numeric constants live in ``simulation/so101.py``. The SO-101 model
files are fetched by ``scripts/setup_so101_assets.py``.

NOTE: Requires Genesis (``genesis-world``) and a built SO-101 model; must be run
on the Radeon (ROCm) machine. Everything here targets Genesis 1.1.x APIs matching
the sibling ``franka_fruit_pick`` demo (verified there).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from genesis.utils.geom import euler_to_R, trans_R_to_T
from paths import SO101_DIR

from simulation import so101

# == Table (box primitives) ==
TABLE_TOP_Z = 0.75
TABLE_CENTER = (0.30, 0.0)
TABLE_TOP_SIZE = (0.80, 0.60, 0.05)
TABLE_LEG_SIZE = (0.05, 0.05)
TABLE_LEG_INSET = 0.08
TABLE_COLOR = (0.62, 0.47, 0.35, 1.0)
TABLE_LEG_COLOR = (0.47, 0.35, 0.24, 1.0)

# == Colored cubes (color == semantic label) ==
CUBE_SIZE = 0.03  # 3 cm edge; comfortably inside the SO-101 jaw span
CUBE_COLORS = {
    "red": (0.85, 0.12, 0.12, 1.0),
    "blue": (0.12, 0.25, 0.85, 1.0),
    "green": (0.12, 0.75, 0.20, 1.0),
}
# Home slots (x, y) on the tabletop; z filled in at build time. Spread apart so the
# per-episode jitter never overlaps them.
# SO-101 reach is only ~0.25–0.32 m from the base at SO101_POS≈(-0.05,0); keep
# cubes/basket inside that radius (older slots at x≈0.34 / basket x=0.42 were
# unreachable, so IK collapsed to a near-home pose every episode).
CUBE_HOME = {
    "red": (0.16, 0.08),
    "blue": (0.20, 0.00),
    "green": (0.16, -0.08),
}

# == Basket (place container) ==
BASKET_HOME = (0.24, 0.10)
BASKET_SIZE = (0.10, 0.10, 0.06)  # outer (x, y, z)
BASKET_WALL = 0.01
BASKET_COLOR = (0.80, 0.70, 0.45, 1.0)

# == Reachable workspace (clamp jittered cube poses) ==
REACH_X = (0.12, 0.24)
REACH_Y = (-0.12, 0.12)

# World camera placed above the +x/-y table corner looking at the table center.
WORLD_CAM_POS = (
    TABLE_CENTER[0] + TABLE_TOP_SIZE[0] / 2,
    TABLE_CENTER[1] - TABLE_TOP_SIZE[1] / 2,
    TABLE_TOP_Z + 0.7,
)
WORLD_CAM_LOOKAT = (TABLE_CENTER[0], TABLE_CENTER[1], TABLE_TOP_Z)


def task_instruction(color: str) -> str:
    """Natural-language task string for a given cube color."""
    return f"Pick the {color} cube and place it into the basket"


def _resolve_model_file() -> tuple[str, str]:
    """Return (kind, path) for the SO-101 model: ('mjcf'|'urdf', abspath).

    Prefers an MJCF (.xml) then falls back to a URDF, searching the fetched
    ``assets/robots/so101`` tree. Raises if nothing is found (run setup first).
    """
    # Ensure pick-101 fingertip pads exist (idempotent; no network).
    try:
        from simulation.so101_mjcf_patch import patch_so101_grasp_geoms

        patched = patch_so101_grasp_geoms(SO101_DIR)
        if patched:
            print(f"[env] patched fingertip pads into: {[p.name for p in patched]}")
    except Exception as exc:  # noqa: BLE001 -- patch is best-effort
        print(f"[env] WARNING: fingertip pad patch skipped ({exc})")

    for name in so101.MJCF_CANDIDATES:
        hits = list(SO101_DIR.rglob(name))
        if hits:
            return "mjcf", str(hits[0])
    any_xml = list(SO101_DIR.rglob("*.xml"))
    if any_xml:
        return "mjcf", str(any_xml[0])
    for name in so101.URDF_CANDIDATES:
        hits = list(SO101_DIR.rglob(name))
        if hits:
            return "urdf", str(hits[0])
    any_urdf = list(SO101_DIR.rglob("*.urdf"))
    if any_urdf:
        return "urdf", str(any_urdf[0])
    raise FileNotFoundError(
        f"No SO-101 model (.xml/.urdf) under {SO101_DIR}. "
        "Run: python scripts/setup_so101_assets.py"
    )


@dataclass
class SceneBundle:
    """Everything a caller needs to drive and observe the scene."""

    scene: gs.Scene
    robot: gs.RigidEntity
    cubes: dict[str, gs.RigidEntity]
    basket: gs.RigidEntity
    world_cam: gs.vis.camera.Camera | None = None
    wrist_cam: gs.vis.camera.Camera | None = None
    table: list = field(default_factory=list)
    _ee_link: object | None = None

    def update_wrist_cam(self) -> None:
        if self.wrist_cam is not None:
            self.wrist_cam.move_to_attach()


def _add_table(scene: gs.Scene) -> list:
    cx, cy = TABLE_CENTER
    top_lx, top_ly, top_lz = TABLE_TOP_SIZE
    leg_lx, leg_ly = TABLE_LEG_SIZE
    leg_lz = TABLE_TOP_Z - top_lz

    entities = []
    # Tabletop first so table[0] is the surface objects rest on.
    entities.append(
        scene.add_entity(
            morph=gs.morphs.Box(size=TABLE_TOP_SIZE, pos=(cx, cy, TABLE_TOP_Z - top_lz / 2), fixed=True),
            surface=gs.surfaces.Default(color=TABLE_COLOR),
        )
    )
    dx = top_lx / 2 - TABLE_LEG_INSET
    dy = top_ly / 2 - TABLE_LEG_INSET
    for sx in (-1, 1):
        for sy in (-1, 1):
            entities.append(
                scene.add_entity(
                    morph=gs.morphs.Box(
                        size=(leg_lx, leg_ly, leg_lz),
                        pos=(cx + sx * dx, cy + sy * dy, leg_lz / 2),
                        fixed=True,
                    ),
                    surface=gs.surfaces.Default(color=TABLE_LEG_COLOR),
                )
            )
    return entities


def _add_basket(scene: gs.Scene) -> gs.RigidEntity:
    """A simple open-top box container built from a floor + four thin walls.

    Returned as a single fixed entity is not possible with primitives, so we model
    the basket as one fixed floor plate whose AABB is used for the containment test;
    the walls are cosmetic fixed boxes. We return the floor entity as the handle.
    """
    bx, by = BASKET_HOME
    lx, ly, lz = BASKET_SIZE
    w = BASKET_WALL
    floor_z = TABLE_TOP_Z + w / 2
    floor = scene.add_entity(
        morph=gs.morphs.Box(size=(lx, ly, w), pos=(bx, by, floor_z), fixed=True),
        surface=gs.surfaces.Default(color=BASKET_COLOR),
    )
    # Four walls around the rim (cosmetic + physical containment).
    wall_z = TABLE_TOP_Z + lz / 2
    for sx, sy, sz in (
        (1, 0, (w, ly, lz)),
        (-1, 0, (w, ly, lz)),
        (0, 1, (lx, w, lz)),
        (0, -1, (lx, w, lz)),
    ):
        px = bx + sx * (lx / 2 - w / 2)
        py = by + sy * (ly / 2 - w / 2)
        scene.add_entity(
            morph=gs.morphs.Box(size=sz, pos=(px, py, wall_z), fixed=True),
            surface=gs.surfaces.Default(color=BASKET_COLOR),
        )
    return floor


def build_scene(
    *,
    show_viewer: bool = False,
    n_envs: int = 1,
    add_world_cam: bool = True,
    add_wrist_cam: bool = True,
) -> SceneBundle:
    """Build the SO-101 + table + colored cubes + basket scene and return a bundle."""
    kind, model_path = _resolve_model_file()

    cx, cy = TABLE_CENTER
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        viewer_options=gs.options.ViewerOptions(
            res=(1280, 960),
            camera_pos=(cx + 0.8, -1.0, 1.4),
            camera_lookat=(cx, cy, TABLE_TOP_Z),
            camera_fov=45,
        ),
        show_viewer=show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    scene.add_entity(gs.morphs.Plane())
    table_entities = _add_table(scene)

    # Colored cubes: color == semantic label. rho kept light for a small cube.
    cubes: dict[str, gs.RigidEntity] = {}
    for color, (x, y) in CUBE_HOME.items():
        z = TABLE_TOP_Z + CUBE_SIZE / 2 + 0.002
        cubes[color] = scene.add_entity(
            morph=gs.morphs.Box(size=(CUBE_SIZE, CUBE_SIZE, CUBE_SIZE), pos=(x, y, z)),
            material=gs.materials.Rigid(rho=300.0),
            surface=gs.surfaces.Default(color=CUBE_COLORS[color]),
        )

    basket = _add_basket(scene)

    # Robot.
    if kind == "mjcf":
        robot = scene.add_entity(
            gs.morphs.MJCF(file=model_path, pos=so101.SO101_POS, euler=so101.SO101_EULER)
        )
    else:
        robot = scene.add_entity(
            gs.morphs.URDF(file=model_path, pos=so101.SO101_POS, euler=so101.SO101_EULER, fixed=True)
        )

    world_cam = None
    if add_world_cam:
        world_cam = scene.add_camera(
            res=so101.WORLD_CAM_RES, pos=WORLD_CAM_POS, lookat=WORLD_CAM_LOOKAT,
            fov=so101.WORLD_CAM_FOV, GUI=False,
        )
    wrist_cam = None
    if add_wrist_cam:
        wrist_cam = scene.add_camera(
            res=so101.WRIST_CAM_RES, fov=so101.WRIST_CAM_FOV,
            near=so101.WRIST_CAM_NEAR, far=so101.WRIST_CAM_FAR, GUI=False,
        )

    if n_envs > 1:
        scene.build(n_envs=n_envs, env_spacing=(1.5, 1.5))
    else:
        scene.build()

    ee_link = _configure_robot(robot, n_envs=n_envs)

    if wrist_cam is not None and ee_link is not None:
        offset_T = trans_R_to_T(
            np.asarray(so101.WRIST_CAM_OFFSET_POS, dtype=np.float64),
            euler_to_R(np.asarray(so101.WRIST_CAM_OFFSET_EULER, dtype=np.float64)),
        )
        wrist_cam.attach(ee_link, offset_T)
        wrist_cam.move_to_attach()

    return SceneBundle(
        scene=scene, robot=robot, cubes=cubes, basket=basket,
        world_cam=world_cam, wrist_cam=wrist_cam, table=table_entities, _ee_link=ee_link,
    )


def _configure_robot(robot: gs.RigidEntity, *, n_envs: int):
    """Set home pose + PD gains + torque limits; return the EE link (or None)."""
    robot.set_qpos(so101.home_qpos(n_envs))
    try:
        robot.set_dofs_kp(np.asarray(so101.KP))
        robot.set_dofs_kv(np.asarray(so101.KV))
        robot.set_dofs_force_range(np.asarray(so101.FORCE_MIN), np.asarray(so101.FORCE_MAX))
    except Exception as exc:  # noqa: BLE001 -- gain arity depends on the loaded model
        print(f"[env] WARNING: could not set gains/limits ({exc}); "
              "check DOF count matches simulation/so101.py. Continuing with model defaults.")
    ee_link = None
    for name in so101.EE_LINK_CANDIDATES:
        try:
            ee_link = robot.get_link(name)
            break
        except Exception:  # noqa: BLE001,S112 -- try the next candidate link name
            continue
    if ee_link is None:
        print(f"[env] WARNING: none of EE_LINK_CANDIDATES {so101.EE_LINK_CANDIDATES} "
              "found; wrist cam + IK disabled. Update simulation/so101.py.")
    return ee_link


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def _entity_aabb(entity) -> np.ndarray:
    aabb = entity.get_AABB()
    aabb = _to_np(aabb)
    if aabb.ndim == 3:  # (n_envs, 2, 3) -> first env
        aabb = aabb[0]
    return aabb


@dataclass
class EnvConfig:
    """Per-episode randomization + control knobs for SO101PickPlaceEnv."""

    pos_jitter: float = 0.02  # +/- m box around each cube's home slot
    settle_steps: int = 60
    control_substeps: int = 5  # sim steps advanced per env.step(action)
    success_tol: float = 0.06
    seed: int | None = None


class SO101PickPlaceEnv:
    """Gym-style wrapper over the Genesis SO-101 pick-and-place scene.

    Observation (per ``observe``/``reset``/``step``)::

        {
          "image": HxWx3 uint8 (world camera RGB),
          "wrist_image": HxWx3 uint8 (wrist camera RGB, if present),
          "state": (6,) float32 joint positions,
          "instruction": str (current episode's task text),
        }

    Action: (6,) float32 joint-position targets in JOINT_NAMES order. ``step``
    position-controls the arm+gripper and advances the sim ``control_substeps``
    times, then returns the new observation.
    """

    def __init__(self, bundle: SceneBundle | None = None, config: EnvConfig | None = None):
        self.cfg = config or EnvConfig()
        self.bundle = bundle if bundle is not None else build_scene()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.target_color: str = "red"
        self._home_z = {c: TABLE_TOP_Z + CUBE_SIZE / 2 + 0.002 for c in CUBE_HOME}

    # -- public API --------------------------------------------------------

    def reset(self, *, seed: int | None = None, target_color: str | None = None) -> dict:
        """Randomize cube poses, reset the robot, choose a target, settle. Returns obs."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.target_color = target_color or str(self.rng.choice(list(CUBE_HOME)))

        self.bundle.robot.set_qpos(so101.home_qpos(1), zero_velocity=True)
        for color, (hx, hy) in CUBE_HOME.items():
            j = self.cfg.pos_jitter
            x = float(np.clip(hx + self.rng.uniform(-j, j), *REACH_X))
            y = float(np.clip(hy + self.rng.uniform(-j, j), *REACH_Y))
            z = self._home_z[color]
            ent = self.bundle.cubes[color]
            ent.set_pos(np.array([x, y, z]), zero_velocity=True, skip_forward=True)
        self._settle()
        return self.observe()

    def step(self, action: np.ndarray) -> dict:
        """Position-control to ``action`` (6-D) and advance the sim. Returns obs."""
        action = np.asarray(action, dtype=np.float64).reshape(-1)
        if action.shape[0] != so101.N_DOF:
            raise ValueError(f"action must be {so101.N_DOF}-D, got {action.shape[0]}")
        for _ in range(self.cfg.control_substeps):
            self.bundle.robot.control_dofs_position(action)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()
        return self.observe()

    def observe(self) -> dict:
        """Return the current observation dict (no sim step)."""
        state = _to_np(self.bundle.robot.get_qpos()).reshape(-1).astype(np.float32)
        obs: dict = {"state": state, "instruction": task_instruction(self.target_color)}
        if self.bundle.world_cam is not None:
            obs["image"] = np.ascontiguousarray(_to_np(self.bundle.world_cam.render(rgb=True)[0]), dtype=np.uint8)
        if self.bundle.wrist_cam is not None:
            obs["wrist_image"] = np.ascontiguousarray(_to_np(self.bundle.wrist_cam.render(rgb=True)[0]), dtype=np.uint8)
        return obs

    def check_success(self, color: str | None = None) -> bool:
        """True if the target cube's center sits inside the basket rim footprint."""
        color = color or self.target_color
        cube_pos = _to_np(self.bundle.cubes[color].get_pos()).reshape(-1)
        basket_aabb = _entity_aabb(self.bundle.basket)
        bx = 0.5 * (basket_aabb[0, 0] + basket_aabb[1, 0])
        by = 0.5 * (basket_aabb[0, 1] + basket_aabb[1, 1])
        rim_z = TABLE_TOP_Z + BASKET_SIZE[2]
        horizontal = float(np.linalg.norm(cube_pos[:2] - np.array([bx, by])))
        rim_radius = 0.5 * min(BASKET_SIZE[0], BASKET_SIZE[1])
        within = horizontal < min(self.cfg.success_tol, rim_radius)
        below_rim = cube_pos[2] < rim_z
        above_floor = cube_pos[2] > TABLE_TOP_Z
        return bool(within and below_rim and above_floor)

    # -- internals ---------------------------------------------------------

    def _settle(self) -> None:
        hold = so101.home_qpos(1)
        for _ in range(self.cfg.settle_steps):
            self.bundle.robot.control_dofs_position(hold)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()


def main() -> None:
    """Smoke-test: build the scene, reset, hold home pose, save a world-cam frame."""
    import argparse

    parser = argparse.ArgumentParser(description="Smoke-test the SO-101 Genesis env.")
    parser.add_argument("-c", "--cpu", action="store_true", help="Use the CPU backend.")
    parser.add_argument("-v", "--vis", action="store_true", help="Show the viewer.")
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--save-frame", action="store_true", help="Save world_cam.png at the end.")
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    env = SO101PickPlaceEnv(bundle=build_scene(show_viewer=args.vis))
    obs = env.reset(seed=0)
    print(f"[env] reset ok. target={env.target_color!r} instruction={obs['instruction']!r}")
    print(f"[env] state dim={obs['state'].shape} image={obs.get('image', np.empty(0)).shape}")

    hold = so101.HOME_QPOS
    for _ in range(args.steps):
        obs = env.step(np.asarray(hold))
    print(f"[env] stepped {args.steps} control cycles; success={env.check_success()}")

    if args.save_frame and "image" in obs:
        import imageio.v2 as imageio

        imageio.imwrite("world_cam.png", obs["image"])
        print("[env] saved world_cam.png")


if __name__ == "__main__":
    main()
