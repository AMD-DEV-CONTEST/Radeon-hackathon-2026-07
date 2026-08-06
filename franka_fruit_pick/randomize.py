"""M2 environment randomization: per-episode reset() for the Franka scene.

This is the first (small-amplitude) stage of M2. It randomizes the *task* variety
that pick-and-place inherently needs -- object poses and task selection -- and,
opt-in, the M4 Layer-B runtime domain randomization (per-episode friction, per-object
mass and world-camera extrinsics; see ``DomainRandomizationConfig``). Build-time
appearance/intrinsics DR (M4 Layer A) lives in ``build_scene`` instead, since it must
be baked at ``scene.build()``. Layer B is disabled by default, so the base M2 behavior
is unchanged unless ``RandomizationConfig.dr.enabled`` is set.

Design choices (per user):

1. Non-overlap via a **slot method** rather than rejection sampling. Each object
   owns a fixed "home slot" (its nominal position in ``YCB_LAYOUT``). The tuned
   layout is already collision-free and reachable, so keeping every object in its
   own slot guarantees non-overlap *by construction*. To keep that guarantee even
   with jitter, each object's jitter is clamped to a per-object safe radius derived
   from the gap to its nearest neighbor, so no rejection loop is ever needed.

2. **Small perturbation to start.** Positions jitter within a few centimeters of
   the home slot and yaw is fully randomized. Amplitude can be scaled up later
   (larger jitter, slot reassignment) without changing the interface.

Usage:
    randomizer = EnvRandomizer(bundle, RandomizationConfig(seed=0))
    task = randomizer.reset()          # new episode, returns a TaskSpec
    success, _ = run_pick_place(bundle, task)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from genesis.utils.geom import euler_to_quat

from grasp_demo import PlaceTarget, TaskSpec
from scene_config import (
    FRANKA_QPOS,
    REACH_X,
    REACH_Y,
    TABLE_TOP_Z,
    WORLD_CAM_LOOKAT,
    WORLD_CAM_POS,
    YCB_LAYOUT,
    get_ycb_assets,
)

# Objects used as pick targets during M2 randomization development. Kept intentionally
# small (banana, lemon, plum) while the reset pipeline is being validated; the rest stay
# in the scene as distractors. Expand this pool once reliability is confirmed.
RELIABLE_PICK_POOL = ("011_banana", "014_lemon", "018_plum")

# Default container to place the picked object into.
DEFAULT_PLACE_CONTAINER = "024_bowl"

# Extra clearance kept between object footprints when clamping jitter (m).
OVERLAP_MARGIN = 0.02


@dataclass
class DomainRandomizationConfig:
    """M4 domain randomization -- Layer B: per-episode runtime physics / camera-extrinsics knobs.

    Unlike Layer A (baked once at ``build_scene``), these are re-sampled every ``reset()`` and
    applied to the *already-built* scene, so a single built scene yields a different physical /
    geometric domain each episode. They are driven by the same per-episode RNG as the pose
    jitter, so a given ``reset(seed)`` fully determines the episode's whole domain.

    Dynamics
    --------
    Friction is sampled as a single multiplicative ``ratio`` and applied uniformly to the YCB
    objects, the Franka links (only the fingers/hand actually contact anything) and the
    tabletop. Genesis defines a contact pair's friction as ``max()`` over the two geoms, so
    scaling only the object would be masked by the (unchanged) fingers/table; scaling every
    relevant surface by the same ratio makes the *effective* grip / support friction scale
    with it.     Object mass is scaled by a per-object ratio (applied via ``set_mass_shift`` relative to the
    captured base mass); the robot mass is left fixed so the tuned kp/kv stay valid.

    Camera extrinsics
    -----------------
    Only the static world camera is jittered (``set_pose``), since it is set once and persists.
    The wrist camera is eye-in-hand -- re-derived every step via ``move_to_attach()`` -- so
    jittering its extrinsics needs re-attach plumbing and is intentionally deferred.
    """

    enabled: bool = False

    # -- dynamics --
    friction_ratio_range: tuple[float, float] = (0.7, 1.3)  # multiplicative, shared across surfaces
    # Multiplicative per-object mass ratio (converted to set_mass_shift additively from each
    # object's captured base mass). A ratio -- rather than an absolute +/- kg shift -- keeps the
    # mass strictly positive for light YCB objects (a fixed kg shift can drive a ~30 g object
    # negative, which makes the solver diverge to NaN).
    mass_ratio_range: tuple[float, float] = (0.8, 1.2)

    # -- world-camera extrinsics (0 disables; opt-in) --
    cam_pos_jitter: float = 0.0  # +/- m, per-axis on world-cam position
    cam_lookat_jitter: float = 0.0  # +/- m, per-axis on world-cam lookat point


@dataclass
class RandomizationConfig:
    """Knobs for one episode's randomization. Defaults are the small-start regime."""

    pos_jitter: float = 0.03  # +/- m, uniform box around each object's home slot (x, y)
    # Yaw is jittered by a small amount around each object's home orientation rather than
    # fully randomized: the tuned layout packs objects only ~8 cm apart, so a large yaw
    # swings the gripper's finger sweep into neighbors and explodes the contact solver.
    yaw_jitter: float = 30.0  # +/- deg around each object's home yaw (0 disables)
    randomize_pick: bool = True  # sample the pick object from RELIABLE_PICK_POOL
    randomize_place: bool = False  # if True, sometimes place onto a random tabletop xy
    place_tabletop_prob: float = 0.0  # P(tabletop target) when randomize_place is True
    settle_steps: int = 80  # physics steps to let objects/arm settle after teleport
    success_tol: float = 0.06  # forwarded into the sampled TaskSpec
    seed: int | None = None
    dr: DomainRandomizationConfig = field(default_factory=DomainRandomizationConfig)  # M4 Layer B


class EnvRandomizer:
    """Resets a built ``SceneBundle`` to a fresh, randomized pick-and-place episode."""

    def __init__(self, bundle, config: RandomizationConfig | None = None):
        self.bundle = bundle
        self.cfg = config or RandomizationConfig()
        self.rng = np.random.default_rng(self.cfg.seed)

        self._assets = get_ycb_assets()
        self.names = list(YCB_LAYOUT.keys())
        self.home = {n: np.asarray(YCB_LAYOUT[n]["pos"][:2], dtype=float) for n in self.names}
        self.home_yaw = {n: float(YCB_LAYOUT[n]["euler"][2]) for n in self.names}
        self.radius = {n: self._assets[n].radius_xy for n in self.names}
        self.rest_z = {n: self._assets[n].rest_z_offset for n in self.names}

        # Per-object safe jitter: half the clearance to the nearest neighbor slot, so
        # that even if two neighbors jitter toward each other they cannot overlap.
        self.safe_jitter = self._compute_safe_jitter()

        # Base world-camera extrinsics that Layer-B camera jitter perturbs around. Captured
        # from config (the scene builds the world cam at exactly these values).
        self._base_cam_pos = np.asarray(WORLD_CAM_POS, dtype=float)
        self._base_cam_lookat = np.asarray(WORLD_CAM_LOOKAT, dtype=float)

        # Per-object base link masses (kg), captured once before any DR so mass-ratio scaling
        # is relative to the pristine mass and never compounds across episodes. Populated lazily
        # on first dynamics randomization (needs a built scene).
        self._base_mass: dict[str, np.ndarray] = {}

    def _compute_safe_jitter(self) -> dict[str, float]:
        safe: dict[str, float] = {}
        for a in self.names:
            gap = np.inf
            for b in self.names:
                if a == b:
                    continue
                center_dist = float(np.linalg.norm(self.home[a] - self.home[b]))
                clearance = center_dist - self.radius[a] - self.radius[b] - OVERLAP_MARGIN
                gap = min(gap, clearance)
            # Both neighbors may move by J toward each other -> require 2J <= gap.
            safe[a] = max(0.0, 0.5 * gap) if np.isfinite(gap) else self.cfg.pos_jitter
        return safe

    # -- public API ---------------------------------------------------------

    def reset(self, seed: int | None = None) -> TaskSpec:
        """Randomize object poses + task and settle physics. Returns the TaskSpec."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)

        self._reset_robot()
        self._place_objects()
        # M4 Layer B: friction/mass must be set *before* settling so the settle contacts
        # already use this episode's dynamics; camera extrinsics are physics-independent and
        # applied after settling.
        if self.cfg.dr.enabled:
            self._randomize_dynamics()
        self._settle()
        if self.cfg.dr.enabled:
            self._randomize_cameras()
        return self._sample_task()

    # -- internals ----------------------------------------------------------

    def _reset_robot(self) -> None:
        q = np.asarray(FRANKA_QPOS, dtype=float)
        self.bundle.franka.set_qpos(q, zero_velocity=True)

    def _place_objects(self) -> None:
        for name in self.names:
            jitter = min(self.cfg.pos_jitter, self.safe_jitter[name])
            dx, dy = self.rng.uniform(-jitter, jitter, size=2)
            x = float(np.clip(self.home[name][0] + dx, *REACH_X))
            y = float(np.clip(self.home[name][1] + dy, *REACH_Y))
            z = TABLE_TOP_Z + self.rest_z[name] + 0.002  # tiny clearance; settles down

            dyaw = float(self.rng.uniform(-self.cfg.yaw_jitter, self.cfg.yaw_jitter))
            yaw = self.home_yaw[name] + dyaw
            quat = euler_to_quat(np.array([0.0, 0.0, yaw]))

            entity = self.bundle.ycb[name]
            entity.set_pos(np.array([x, y, z]), relative=False, zero_velocity=True, skip_forward=True)
            entity.set_quat(quat, relative=False, zero_velocity=True, skip_forward=False)

    # -- M4 Layer B: runtime domain randomization --------------------------

    def _randomize_dynamics(self) -> None:
        """Re-sample per-episode friction and per-object mass on the built scene.

        Friction uses a single shared ratio (see ``DomainRandomizationConfig``) applied to the
        objects, the Franka links and the tabletop so the effective ``max()`` contact friction
        actually scales. ``set_friction_ratio`` / ``set_mass_shift`` overwrite (not compound)
        the solver's ratio / shift fields, so calling them every reset is safe.
        """
        dr = self.cfg.dr
        b = self.bundle

        lo, hi = dr.friction_ratio_range
        ratio = float(self.rng.uniform(lo, hi))
        self._set_friction_ratio(b.franka, ratio)
        for name in self.names:
            self._set_friction_ratio(b.ycb[name], ratio)
        for table_entity in getattr(b, "table", []) or []:
            self._set_friction_ratio(table_entity, ratio)

        mlo, mhi = dr.mass_ratio_range
        if not (mlo == 1.0 and mhi == 1.0):
            for name in self.names:
                base = self._object_base_mass(name)  # per-link base mass (kg)
                mass_ratio = float(self.rng.uniform(mlo, mhi))
                self._set_mass_shift(b.ycb[name], base * (mass_ratio - 1.0))

    def _randomize_cameras(self) -> None:
        """Jitter the static world-camera extrinsics around the config baseline."""
        dr = self.cfg.dr
        if self.bundle.world_cam is None or (dr.cam_pos_jitter <= 0.0 and dr.cam_lookat_jitter <= 0.0):
            return
        pos = self._base_cam_pos.copy()
        lookat = self._base_cam_lookat.copy()
        if dr.cam_pos_jitter > 0.0:
            pos = pos + self.rng.uniform(-dr.cam_pos_jitter, dr.cam_pos_jitter, size=3)
        if dr.cam_lookat_jitter > 0.0:
            lookat = lookat + self.rng.uniform(-dr.cam_lookat_jitter, dr.cam_lookat_jitter, size=3)
        self.bundle.world_cam.set_pose(pos=pos.tolist(), lookat=lookat.tolist())

    def _batch_shape(self, n_links: int) -> tuple[int, ...]:
        """Return the (per-env) shape expected by set_friction_ratio / set_mass_shift.

        A single-env build reports ``scene.n_envs == 0`` and the solver adds the batch dim
        itself, so we pass an unbatched ``(n_links,)`` in that case and ``(n_envs, n_links)``
        for batched builds.
        """
        n_envs = self.bundle.scene.n_envs
        return (n_links,) if n_envs == 0 else (n_envs, n_links)

    def _object_base_mass(self, name: str) -> np.ndarray:
        """Per-link base mass (kg) of a YCB object, captured once and cached."""
        if name not in self._base_mass:
            entity = self.bundle.ycb[name]
            mass = np.asarray(entity.get_links_inertial_mass().cpu().numpy(), dtype=np.float64)
            # Collapse any env batch dim to per-link masses (masses are identical across envs).
            if mass.ndim > 1:
                mass = mass.reshape(-1, entity.n_links)[0]
            self._base_mass[name] = mass.reshape(-1)[: entity.n_links]
        return self._base_mass[name]

    def _set_friction_ratio(self, entity, ratio: float) -> None:
        n = entity.n_links
        entity.set_friction_ratio(
            np.full(self._batch_shape(n), ratio, dtype=np.float32),
            links_idx_local=np.arange(n),
        )

    def _set_mass_shift(self, entity, shift_per_link: np.ndarray) -> None:
        n = entity.n_links
        shift = np.broadcast_to(np.asarray(shift_per_link, dtype=np.float32), (n,))
        n_envs = self.bundle.scene.n_envs
        payload = shift if n_envs == 0 else np.tile(shift, (n_envs, 1))
        entity.set_mass_shift(payload, links_idx_local=np.arange(n))

    def _settle(self) -> None:
        hold = np.asarray(FRANKA_QPOS, dtype=float)
        for _ in range(self.cfg.settle_steps):
            self.bundle.franka.control_dofs_position(hold)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()

    def _sample_task(self) -> TaskSpec:
        pool = [n for n in RELIABLE_PICK_POOL if n in self.bundle.ycb]
        if not pool:
            raise RuntimeError("No reliable pick objects present in the scene.")
        pick = str(self.rng.choice(pool)) if self.cfg.randomize_pick else pool[0]

        place = self._sample_place(exclude=pick)
        return TaskSpec(pick_object=pick, place_target=place, success_tol=self.cfg.success_tol)

    def _sample_place(self, *, exclude: str) -> PlaceTarget:
        want_tabletop = (
            self.cfg.randomize_place and self.rng.uniform() < self.cfg.place_tabletop_prob
        )
        container_ok = DEFAULT_PLACE_CONTAINER in self.bundle.ycb
        if not want_tabletop and container_ok:
            return DEFAULT_PLACE_CONTAINER
        return self._sample_free_xy(exclude=exclude)

    def _sample_free_xy(self, *, exclude: str, min_clear: float = 0.10, tries: int = 50) -> tuple[float, float]:
        """Sample a tabletop xy that is clear of all objects (rejection, bounded tries)."""
        others = [n for n in self.names if n != exclude]
        for _ in range(tries):
            x = float(self.rng.uniform(*REACH_X))
            y = float(self.rng.uniform(*REACH_Y))
            p = np.array([x, y])
            if all(np.linalg.norm(p - self._current_xy(n)) > self.radius[n] + min_clear for n in others):
                return x, y
        # Fallback: reachable-zone center.
        return float(np.mean(REACH_X)), float(np.mean(REACH_Y))

    def _current_xy(self, name: str) -> np.ndarray:
        return self.bundle.ycb[name].get_pos().cpu().numpy().reshape(-1)[:2]


def main() -> None:
    import argparse

    import genesis as gs

    from build_scene import build_scene
    from grasp_demo import run_pick_place

    parser = argparse.ArgumentParser(description="M2 randomized pick-and-place episodes.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-n", "--episodes", type=int, default=5, help="Number of episodes to run.")
    parser.add_argument("--seed", type=int, default=0, help="Base RNG seed.")
    parser.add_argument("--jitter", type=float, default=0.03, help="Position jitter (m).")
    # M4 Layer B (runtime domain randomization) knobs.
    parser.add_argument(
        "--dr-runtime", action="store_true", default=False, help="Enable M4 Layer-B runtime DR."
    )
    parser.add_argument(
        "--dr-friction",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=(0.7, 1.3),
        help="Friction ratio range (shared across object/finger/table).",
    )
    parser.add_argument(
        "--dr-mass",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=(0.8, 1.2),
        help="Per-object multiplicative mass-ratio range.",
    )
    parser.add_argument("--dr-cam-pos", type=float, default=0.0, help="World-cam position jitter (+/- m).")
    parser.add_argument("--dr-cam-lookat", type=float, default=0.0, help="World-cam lookat jitter (+/- m).")
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=args.vis, n_envs=1, add_world_cam=True, add_wrist_cam=True)

    dr_cfg = DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
        cam_pos_jitter=args.dr_cam_pos,
        cam_lookat_jitter=args.dr_cam_lookat,
    )
    cfg = RandomizationConfig(pos_jitter=args.jitter, seed=args.seed, dr=dr_cfg)
    randomizer = EnvRandomizer(bundle, cfg)
    if args.dr_runtime:
        print(
            f"[randomize] M4 Layer-B DR on: friction={dr_cfg.friction_ratio_range} "
            f"mass_ratio={dr_cfg.mass_ratio_range} cam_pos={dr_cfg.cam_pos_jitter} "
            f"cam_lookat={dr_cfg.cam_lookat_jitter}"
        )

    n_success = 0
    for ep in range(args.episodes):
        episode_seed = args.seed + ep
        task = randomizer.reset(seed=episode_seed)
        success, _ = run_pick_place(bundle, task)
        n_success += int(success)
        print(
            f"[randomize] ep {ep:03d} seed={episode_seed} "
            f"pick={task.pick_object} place={task.place_target} -> success={success}"
        )

    print(f"[randomize] {n_success}/{args.episodes} succeeded")


if __name__ == "__main__":
    main()
