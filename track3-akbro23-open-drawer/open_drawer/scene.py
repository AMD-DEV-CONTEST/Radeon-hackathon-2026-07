"""Batched scene construction and reset.

A table, a Franka Panda, and a two-drawer cabinet standing free on the table.
One code path for every N: N=1 and N=256 build and reset identically.
`env_spacing` stays (0, 0) so envs are superimposed and the camera frames the
same workspace regardless of N; per-env separation is a rendering concern,
handled by `env_separate_rigid`.

Genesis behaviours this depends on (genesis-world 1.2.3):
  * per-env rendering requires VisOptions(env_separate_rigid=True)
  * per-env DOF limits require RigidOptions(batch_dofs_info=True), and the
    setter lives on the SOLVER -- RigidEntity exposes get_dofs_limit but no
    matching set_dofs_limit, unlike every sibling dof property
  * the travel stop is a joint limit, so RigidOptions(enable_joint_limit=True)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import genesis as gs
from genesis.utils.geom import euler_to_R, trans_R_to_T

from . import assets, tactile
from .config import EnvConfig, SIDES
from .randomize import EpisodeSetup

RESET_SETTLE_STEPS = 40


def npy(x) -> np.ndarray:
    """Genesis tensor -> numpy, without assuming which it handed back."""
    return np.asarray(x.detach().cpu()) if hasattr(x, "detach") else np.asarray(x)


@dataclass
class SceneBundle:
    cfg: EnvConfig
    scene: gs.Scene
    franka: gs.RigidEntity
    cabinet: gs.RigidEntity
    hand_link: object
    drawer_links: list                  # 2, in SIDES order
    drawer_dofs_local: np.ndarray       # (2,) within the cabinet entity
    drawer_dofs_global: np.ndarray      # (2,) within the solver, for set_dofs_limit
    sensors: list = field(default_factory=list)      # 2 taxel grids, per fingertip
    camera: object = None               # free camera, for looking; not an observation
    wrist_cams: list = field(default_factory=list)   # attached to hand_link
    setup: EpisodeSetup | None = None   # the live episode's randomization

    # Control steps since the episode began, and the command last actually
    # issued. `robot.apply` uses both to command at the recorded rate rather
    # than every step. Zeroed by `reset`, so every episode starts on a tick.
    step_count: int = 0
    last_cmd: tuple | None = None

    @property
    def n_envs(self) -> int:
        return self.cfg.n_envs

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self.scene.step()
            self.step_count += 1
            # An attached camera does not follow its link on its own.
            for cam in self.wrist_cams:
                cam.move_to_attach()

    # ------------------------------------------------------------------ state
    def qpos(self) -> np.ndarray:
        return npy(self.franka.get_qpos()).reshape(self.n_envs, -1)

    def drawer_travel(self) -> np.ndarray:
        """(N, 2) how far each drawer is pulled out, in SIDES order."""
        q = self.cabinet.get_dofs_position(dofs_idx_local=self.drawer_dofs_local)
        return npy(q).reshape(self.n_envs, len(SIDES))

    def cabinet_pos(self) -> np.ndarray:
        return npy(self.cabinet.get_pos()).reshape(self.n_envs, 3)

    def cabinet_quat(self) -> np.ndarray:
        return npy(self.cabinet.get_quat()).reshape(self.n_envs, 4)

    def tactile_feature(self) -> np.ndarray:
        return tactile.feature(self.sensors, self.cfg)

    def tactile_peak(self) -> np.ndarray:
        return tactile.peak_force(self.sensors, self.cfg)

    # ----------------------------------------------------------------- render
    @staticmethod
    def _rgb(cam) -> np.ndarray:
        """(N, H, W, 3) uint8. Genesis drops the batch dim at n_envs=1, and
        every caller indexes by env."""
        out = cam.render(rgb=True)
        rgb = out[0] if isinstance(out, tuple) else out
        rgb = npy(rgb)[..., :3].astype(np.uint8)
        return np.ascontiguousarray(rgb[None] if rgb.ndim == 3 else rgb)

    def render(self) -> np.ndarray:
        return self._rgb(self.camera)

    def render_obs(self) -> dict:
        """Every observation camera, keyed by the name the dataset will use."""
        return {name: self._rgb(cam)
                for (name, _, _), cam in zip(self.cfg.wrist.mounts, self.wrist_cams)}

    # ------------------------------------------------------------------ reset
    def reset(self, setup: EpisodeSetup, *, settle: int = RESET_SETTLE_STEPS) -> None:
        """Apply an episode's randomization to every env, then let it settle."""
        n = self.n_envs
        self.setup = setup

        # Full solver restore before re-randomizing. An episode can end with the
        # gripper jammed against a stopped drawer under large constraint forces,
        # and teleporting out of that state NaN's the solver.
        self.scene.reset()

        self.cabinet.set_pos(setup.cabinet_pos, zero_velocity=True)
        self.cabinet.set_quat(setup.cabinet_quat, zero_velocity=True)
        self.cabinet.set_dofs_position(
            np.zeros((n, len(SIDES))), dofs_idx_local=self.drawer_dofs_local,
            zero_velocity=True)

        home = np.tile(self.cfg.franka.home, (n, 1))
        self.franka.set_qpos(home, zero_velocity=True)
        # scene.reset() restores build-time state, which covers neither the
        # gains nor the per-env travel stops, so both are re-applied here.
        self._apply_gains()
        self.apply_travel_limits(setup.travel)
        self.franka.control_dofs_position(home)

        self.step(settle)
        # Settling is not part of the episode. Zero afterwards so step 0 of the
        # demonstration is a command tick, in phase with the recorder.
        self.step_count, self.last_cmd = 0, None

    def apply_travel_limits(self, travel: np.ndarray) -> None:
        """Give each env its own drawer stops. (N, 2) in SIDES order.

        This is the randomization the task turns on, and it is invisible: no
        camera can see how far a closed drawer will open. RigidEntity has no
        set_dofs_limit, so this goes through the solver with GLOBAL dof indices.
        """
        travel = np.asarray(travel, dtype=np.float64).reshape(self.n_envs, len(SIDES))
        self.scene.rigid_solver.set_dofs_limit(
            np.zeros_like(travel), travel, dofs_idx=self.drawer_dofs_global)

    def _apply_gains(self) -> None:
        f = self.cfg.franka
        self.franka.set_dofs_kp(np.asarray(f.kp))
        self.franka.set_dofs_kv(np.asarray(f.kv))
        self.franka.set_dofs_force_range(np.asarray(f.force_min), np.asarray(f.force_max))


def _paint(entity, colors: list) -> None:
    """Colour an entity's visual geoms individually, before build.

    Genesis drops colour written into MJCF -- both per-geom `rgba` and named
    `<material>` -- and `surface=` at add_entity paints the whole entity one
    colour. Setting each vgeom's mesh colour is what lets one entity be
    many-toned, which is how the cabinet gets a readable drawer front and a
    dark rail instead of rendering as a single grey block.

    `colors` is in the geom order of the generated MJCF, link-major.
    """
    vgeoms = [vg for link in entity.links for vg in link.vgeoms]
    if len(vgeoms) != len(colors):
        raise ValueError(f"{len(colors)} colours for {len(vgeoms)} visual geoms")
    for vgeom, color in zip(vgeoms, colors):
        vgeom.vmesh.set_color(color)


def build_scene(cfg: EnvConfig | None = None) -> SceneBundle:
    cfg = cfg or EnvConfig()
    paths = assets.write_all(cfg.cabinet)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=cfg.dt, substeps=cfg.substeps),
        rigid_options=gs.options.RigidOptions(
            dt=cfg.dt, constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            # The per-episode travel stop IS a joint limit, and it is written
            # per env -- which the solver only stores per env when dof info is
            # batched. Without either flag every env shares one stop.
            enable_joint_limit=True,
            batch_dofs_info=True,
        ),
        # env_separate_rigid is REQUIRED for per-env rendering; without it
        # render() returns one image no matter what n_envs is.
        vis_options=gs.options.VisOptions(env_separate_rigid=True),
        show_viewer=cfg.show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    scene.add_entity(gs.morphs.Plane())
    tx, ty = cfg.table.center
    scene.add_entity(
        gs.morphs.Box(size=cfg.table.size, fixed=True,
                      pos=(tx, ty, cfg.table.top_z - cfg.table.size[2] / 2)),
        surface=gs.surfaces.Default(color=cfg.table.color),
    )

    # Free-standing, so no batch_fixed_verts: per-env set_pos works normally on
    # a body that owns a freejoint.
    cabinet = scene.add_entity(gs.morphs.MJCF(
        file=str(paths["cabinet"]),
        pos=(cfg.cabinet.center_x, 0.0, cfg.table.top_z)))
    _paint(cabinet, assets.cabinet_colors(cfg.cabinet))

    franka = scene.add_entity(gs.morphs.MJCF(file=cfg.franka.mjcf, pos=cfg.franka.pos))
    sensors = tactile.add_sensors(scene, franka, cfg)

    camera = None
    if cfg.add_camera:
        c = cfg.camera
        camera = scene.add_camera(res=c.res, fov=c.fov, pos=c.pos,
                                  lookat=c.lookat, GUI=False)
    w = cfg.wrist
    wrist_cams = [scene.add_camera(res=w.res, fov=w.fov, near=w.near, far=w.far,
                                   GUI=False)
                  for _ in w.mounts] if cfg.add_wrist_cams else []

    scene.build(n_envs=cfg.n_envs, env_spacing=(0.0, 0.0))

    hand_link = franka.get_link(cfg.franka.hand_link)
    # attach() only works after build
    for cam, (_, pos, euler) in zip(wrist_cams, w.mounts):
        cam.attach(hand_link, trans_R_to_T(
            np.asarray(pos, dtype=np.float64),
            euler_to_R(np.asarray(euler, dtype=np.float64))))
        cam.move_to_attach()

    joints = [cabinet.get_joint(f"slide_{side}") for side in SIDES]
    bundle = SceneBundle(
        cfg=cfg, scene=scene, franka=franka, cabinet=cabinet, hand_link=hand_link,
        drawer_links=[cabinet.get_link(f"drawer_{side}") for side in SIDES],
        drawer_dofs_local=np.array([j.dofs_idx_local[0] for j in joints]),
        drawer_dofs_global=np.array([j.dof_start for j in joints]),
        sensors=sensors, camera=camera, wrist_cams=wrist_cams,
    )
    bundle._apply_gains()
    franka.set_qpos(np.tile(cfg.franka.home, (cfg.n_envs, 1)), zero_velocity=True)
    return bundle
