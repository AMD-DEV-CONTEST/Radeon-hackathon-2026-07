"""Per-episode randomization for the SO101 scene: cube pose + task reset.

Follows the structure of randomize.py (Franka): a RandomizationConfig holds the
knobs, EnvRandomizer.reset() teleports the scene into a fresh episode and returns
the TaskSpec to execute.

Design choices:

1. The cube position is sampled in **polar coordinates around the arm base**
   (annulus + bearing sector) instead of a box, because the grasp protocol's
   reliability is governed by the base->cube distance: the scripted rake grasp
   was validated 9/9 only inside 17-26 cm from the base. Sampling directly in
   that annulus makes every episode start from a reachable, grasp-friendly pose
   by construction (no reachability rejection loop).

2. Rejection is only needed for one constraint -- the cube must not spawn on or
   near the white target sheet (it is the *place* destination) -- so a bounded
   rejection loop with a deterministic fallback handles it.

3. Cube color is a **build-time** knob (Genesis bakes surface color at
   scene.build()), so per-episode color DR is not possible on a built scene.
   The CLI samples one color per process from CUBE_COLOR_PALETTE instead;
   dataset variety comes from running multiple processes/seeds.

Usage:
    randomizer = EnvRandomizer(bundle, RandomizationConfig(seed=0))
    task = randomizer.reset()          # new episode, returns a TaskSpec
    success, _ = run_pick_place(bundle, task)

CLI:
    uv run python -m franka_fruit_pick.randomize_so101 -n 5 --seed 0
    uv run python -m franka_fruit_pick.randomize_so101 -v --cube-color random
"""

from __future__ import annotations

import colorsys
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from genesis.utils.geom import euler_to_quat

from build_scene_so101 import (
    CUBE_POS,
    CUBE_SIZE,
    SO101_HOME_QPOS,
    SO101_POS,
    TARGET_BORDER,
    TARGET_POS,
    TARGET_SIZE,
    WORKSPACE_COLOR,
    WORLD_CAM_LOOKAT,
    WORLD_CAM_POS,
    SceneBundleSO101,
)
from grasp_demo_so101 import GRIPPER_IDLE, TaskSpec

# Arm base position on the table (xy). All grasp geometry is relative to this.
BASE_XY = np.array(SO101_POS[:2], dtype=float)

# Validated grasp envelope (scripted rake grasp, 9/9 success map): the fixed
# finger reaches and the tool stays near vertical only when the *fingertip* is
# 17-26 cm from the base. The grasp standoff puts the fingertip 2.8 cm on the
# base side of the cube, so the cube itself must stay >= 0.17 + standoff: with
# the cube at r=0.183 the fingertip lands at 0.155 and the grasp reproducibly
# fails (never lifts). Farther out, IK tool tilt exceeds 5 deg.
GRASP_R_MIN = 0.20
GRASP_R_MAX = 0.26

# Bearing sector around straight-ahead (+y from the base), degrees. Keeps the
# cube in front of the arm, inside the green table and the world-cam frame.
GRASP_AZ_MAX_DEG = 55.0

# Keep-out radius around the white sheet center: sheet half-width + black border
# + cube half-width + margin, so the cube never spawns on its own destination.
TARGET_CLEAR = TARGET_SIZE[0] / 2 + TARGET_BORDER + CUBE_SIZE[0] / 2 + 0.025


# --- Layer A: build-time appearance sampling ----------------------------------
# Baked at scene.build(), so sampled once per process (per recording run), not per
# episode. Ranges are chosen for ACT training with held-out color evaluation:
# the cube's hue is fully free and saturation/value reach low enough that the
# eval cubes (yellow, blue, black, natural wood) all lie inside the training
# distribution. The table stays recognizably green; lighting covers real-rig
# illumination drift. Walls / target sheet are intentionally fixed (the white
# sheet is the task landmark).

CUBE_SAT_RANGE  = (0.10, 1.00)   # low end reaches gray/black/wood tones
CUBE_VAL_RANGE  = (0.15, 0.95)   # dark end covers the black eval cube
TABLE_HUE_JITTER = 10.0 / 360.0  # +/- around the real table's green hue
TABLE_SV_RATIO  = (0.80, 1.20)   # multiplicative on saturation and value
AMBIENT_RANGE   = (0.55, 0.85)   # build default 0.70
LIGHT_RANGE     = (1.2, 2.0)     # build default 1.6


def sample_appearance(seed: int | None = None, *, cube: bool = True,
                      table: bool = True, lighting: bool = True) -> dict:
    """Sample Layer-A appearance kwargs for ``build_scene_so101``.

    Returns a subset of {cube_color, bg_color, ambient, light_intensity} per the
    scope flags; deterministic for a given seed. All values are drawn in a fixed
    order regardless of scope, so the SAME seed yields the SAME cube color in a
    cube-color-only dataset and a full-appearance dataset (clean ablations).
    """
    rng = np.random.default_rng(seed)
    cube_rgb = colorsys.hsv_to_rgb(
        rng.uniform(0.0, 1.0),
        rng.uniform(*CUBE_SAT_RANGE),
        rng.uniform(*CUBE_VAL_RANGE),
    )
    h, s, v = colorsys.rgb_to_hsv(*WORKSPACE_COLOR[:3])
    table_rgb = colorsys.hsv_to_rgb(
        (h + rng.uniform(-TABLE_HUE_JITTER, TABLE_HUE_JITTER)) % 1.0,
        float(np.clip(s * rng.uniform(*TABLE_SV_RATIO), 0.0, 1.0)),
        float(np.clip(v * rng.uniform(*TABLE_SV_RATIO), 0.0, 1.0)),
    )
    ambient = float(rng.uniform(*AMBIENT_RANGE))
    light = float(rng.uniform(*LIGHT_RANGE))

    out: dict = {}
    if cube:
        out["cube_color"] = (*cube_rgb, 1.0)
    if table:
        out["bg_color"] = (*table_rgb, 1.0)
    if lighting:
        out["ambient"] = ambient
        out["light_intensity"] = light
    return out


@dataclass
class DomainRandomizationConfig:
    """Runtime domain randomization (Layer B): per-episode physics / camera knobs.

    Unlike Layer A (cube/table color, baked once at ``build_scene_so101``), these
    are re-sampled every ``reset()`` and applied to the already-built scene, so a
    single build yields a different physical domain each episode. Driven by the
    same per-episode RNG as the pose sampling, so ``reset(seed)`` fully determines
    the episode.

    Friction is one shared multiplicative ratio applied to the cube, the robot
    links and the tabletop: Genesis resolves a contact pair's friction as max()
    over the two geoms, so scaling only the cube would be masked by the unchanged
    fingers/table. Mass scales the cube only (the robot stays fixed so the tuned
    kp/kv/force-clamp calibration stays valid — the jaw torque 4.0 is load-bearing).
    Camera jitter moves the static world camera only; the wrist camera is re-derived
    from the gripper link every step, so its extrinsics are not independently jittered.
    """

    enabled: bool = False

    # -- dynamics --
    friction_ratio_range: tuple[float, float] = (0.7, 1.3)   # shared across surfaces
    mass_ratio_range: tuple[float, float] = (0.8, 1.2)       # cube only, multiplicative

    # -- world-camera extrinsics (0 disables; opt-in) --
    cam_pos_jitter: float = 0.0     # +/- m, per-axis on world-cam position
    cam_lookat_jitter: float = 0.0  # +/- m, per-axis on world-cam lookat point


@dataclass
class RandomizationConfig:
    """Knobs for one episode's randomization."""

    r_range: tuple[float, float] = (GRASP_R_MIN, GRASP_R_MAX)
    az_range_deg: tuple[float, float] = (-GRASP_AZ_MAX_DEG, GRASP_AZ_MAX_DEG)
    randomize_yaw: bool = True     # uniform cube yaw (grasp is yaw-agnostic: the
                                   # jaw rakes the cube in regardless of its spin)
    place_jitter: float = 0.0      # +/- m around the sheet center; keep below
                                   # TARGET_SIZE/2 - CUBE_SIZE/2 (~0.035) so the
                                   # cube still lands fully on the sheet
    settle_steps: int = 60         # physics steps after teleport (cube slides a
                                   # few mm before resting; grasp targets are read
                                   # from the settled pose in run_pick_place)
    seed: int | None = None
    dr: DomainRandomizationConfig = field(default_factory=DomainRandomizationConfig)


class EnvRandomizer:
    """Resets a built SceneBundleSO101 to a fresh, randomized pick-and-place episode."""

    def __init__(self, bundle: SceneBundleSO101, config: RandomizationConfig | None = None):
        self.bundle = bundle
        self.cfg = config or RandomizationConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self._home6 = np.append(SO101_HOME_QPOS[:5], GRIPPER_IDLE)
        self.last_yaw = 0.0   # deg; sampled cube yaw of the latest reset (for logging)

        # Layer-B baselines: world-cam extrinsics jitter is applied around the
        # build-time values; the cube's pristine mass is captured once so the
        # per-episode mass ratio never compounds across episodes.
        self._base_cam_pos = np.asarray(WORLD_CAM_POS, dtype=float)
        self._base_cam_lookat = np.asarray(WORLD_CAM_LOOKAT, dtype=float)
        self._cube_base_mass: np.ndarray | None = None

    # -- public API ---------------------------------------------------------

    def reset(self, seed: int | None = None) -> TaskSpec:
        """Randomize the cube pose, reset the arm, settle physics. Returns the TaskSpec."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)

        self._reset_robot()
        self._place_cube()
        # Layer B: friction/mass must be set *before* settling so the settle
        # contacts already use this episode's dynamics; camera extrinsics are
        # physics-independent and applied after.
        if self.cfg.dr.enabled:
            self._randomize_dynamics()
        self._settle()
        if self.cfg.dr.enabled:
            self._randomize_cameras()
        return self._sample_task()

    # -- internals ----------------------------------------------------------

    def _reset_robot(self) -> None:
        self.bundle.robot.set_qpos(self._home6.copy())

    def _sample_cube_xy(self, tries: int = 50) -> np.ndarray:
        """Polar sample in the validated annulus, rejecting the sheet keep-out zone."""
        target_xy = np.array(TARGET_POS[:2], dtype=float)
        for _ in range(tries):
            # Uniform over the annulus *area* (sqrt on r), not over radius.
            r = float(np.sqrt(self.rng.uniform(self.cfg.r_range[0] ** 2,
                                               self.cfg.r_range[1] ** 2)))
            az = np.radians(self.rng.uniform(*self.cfg.az_range_deg))
            xy = BASE_XY + r * np.array([np.sin(az), np.cos(az)])
            if np.linalg.norm(xy - target_xy) > TARGET_CLEAR:
                return xy
        return np.array(CUBE_POS[:2], dtype=float)   # fallback: tuned default spot

    def _place_cube(self) -> None:
        xy = self._sample_cube_xy()
        pos = np.array([xy[0], xy[1], CUBE_POS[2] + 0.002])   # tiny clearance; settles down
        yaw = float(self.rng.uniform(0.0, 360.0)) if self.cfg.randomize_yaw else 0.0
        self.last_yaw = yaw
        cube = self.bundle.cube
        cube.set_pos(pos)
        cube.set_quat(euler_to_quat(np.array([0.0, 0.0, yaw])))
        cube.set_dofs_velocity(np.zeros(6))

    # -- Layer B: runtime domain randomization -------------------------------

    def _randomize_dynamics(self) -> None:
        """Re-sample per-episode friction (shared ratio) and cube mass.

        ``set_friction_ratio`` / ``set_mass_shift`` overwrite (not compound) the
        solver's ratio/shift fields, so calling them every reset is safe.
        """
        dr = self.cfg.dr
        b = self.bundle

        lo, hi = dr.friction_ratio_range
        ratio = float(self.rng.uniform(lo, hi))
        for entity in (b.cube, b.robot, b.table):
            if entity is not None:
                self._set_friction_ratio(entity, ratio)

        mlo, mhi = dr.mass_ratio_range
        if not (mlo == 1.0 and mhi == 1.0):
            if self._cube_base_mass is None:
                mass = np.asarray(b.cube.get_links_inertial_mass().cpu().numpy(),
                                  dtype=np.float64)
                self._cube_base_mass = mass.reshape(-1)[: b.cube.n_links]
            mass_ratio = float(self.rng.uniform(mlo, mhi))
            shift = (self._cube_base_mass * (mass_ratio - 1.0)).astype(np.float32)
            b.cube.set_mass_shift(shift, links_idx_local=np.arange(b.cube.n_links))

    def _randomize_cameras(self) -> None:
        """Jitter the static world-camera extrinsics around the build baseline."""
        dr = self.cfg.dr
        if self.bundle.world_cam is None or (dr.cam_pos_jitter <= 0.0
                                             and dr.cam_lookat_jitter <= 0.0):
            return
        pos = self._base_cam_pos.copy()
        lookat = self._base_cam_lookat.copy()
        if dr.cam_pos_jitter > 0.0:
            pos = pos + self.rng.uniform(-dr.cam_pos_jitter, dr.cam_pos_jitter, size=3)
        if dr.cam_lookat_jitter > 0.0:
            lookat = lookat + self.rng.uniform(-dr.cam_lookat_jitter,
                                               dr.cam_lookat_jitter, size=3)
        self.bundle.world_cam.set_pose(pos=pos.tolist(), lookat=lookat.tolist())

    def _set_friction_ratio(self, entity, ratio: float) -> None:
        n = entity.n_links
        entity.set_friction_ratio(
            np.full((n,), ratio, dtype=np.float32),   # single-env build: unbatched shape
            links_idx_local=np.arange(n),
        )

    def _settle(self) -> None:
        for _ in range(self.cfg.settle_steps):
            self.bundle.robot.control_dofs_position(self._home6)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()

    def _sample_task(self) -> TaskSpec:
        px, py = float(TARGET_POS[0]), float(TARGET_POS[1])
        if self.cfg.place_jitter > 0.0:
            j = self.cfg.place_jitter
            dx, dy = self.rng.uniform(-j, j, size=2)
            px, py = px + float(dx), py + float(dy)
        return TaskSpec(place_xy=(px, py))


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    import argparse

    import genesis as gs

    from build_scene_so101 import CUBE_COLOR_PALETTE, build_scene_so101
    from grasp_demo_so101 import run_pick_place

    palette = {"red": 0, "blue": 1, "green": 2, "yellow": 3}

    parser = argparse.ArgumentParser(description="SO101 randomized pick-and-place episodes.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-n", "--episodes", type=int, default=5, help="Number of episodes to run.")
    parser.add_argument("--seed", type=int, default=0, help="Base RNG seed (episode ep uses seed+ep).")
    parser.add_argument("--cube-color", choices=[*palette, "random"], default="red",
                        help="Cube color, baked at scene build ('random' samples from the palette).")
    parser.add_argument("--place-jitter", type=float, default=0.0,
                        help="Place-target jitter around the sheet center (+/- m).")
    parser.add_argument("--seeds", type=str, default=None,
                        help="Comma-separated explicit episode seeds (overrides -n/--seed).")
    parser.add_argument("--save-video", type=str, default=None, metavar="DIR",
                        help="Save a per-episode world-cam video (25 fps) into DIR.")
    # Layer A (build-time appearance DR) knob.
    parser.add_argument("--dr-appearance", action="store_true", default=False,
                        help="Sample cube/table color + lighting from --seed at build "
                             "time (overrides --cube-color).")
    # Layer B (runtime domain randomization) knobs.
    parser.add_argument("--dr-runtime", action="store_true", default=False,
                        help="Enable per-episode runtime DR (friction/mass/camera).")
    parser.add_argument("--dr-friction", type=float, nargs=2, metavar=("LO", "HI"),
                        default=(0.7, 1.3),
                        help="Friction ratio range (shared across cube/robot/table).")
    parser.add_argument("--dr-mass", type=float, nargs=2, metavar=("LO", "HI"),
                        default=(0.8, 1.2),
                        help="Cube multiplicative mass-ratio range.")
    parser.add_argument("--dr-cam-pos", type=float, default=0.0,
                        help="World-cam position jitter (+/- m).")
    parser.add_argument("--dr-cam-lookat", type=float, default=0.0,
                        help="World-cam lookat jitter (+/- m).")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    idx = int(rng.integers(len(CUBE_COLOR_PALETTE))) if args.cube_color == "random" \
        else palette[args.cube_color]

    gs.init(backend=gs.metal)
    if args.dr_appearance:
        app = sample_appearance(args.seed)
        print(f"[randomize] appearance DR: cube={np.round(app['cube_color'], 3).tolist()} "
              f"table={np.round(app['bg_color'], 3).tolist()} ambient={app['ambient']:.2f} "
              f"light={app['light_intensity']:.2f}")
        bundle = build_scene_so101(show_viewer=args.vis, **app)
    else:
        bundle = build_scene_so101(show_viewer=args.vis, cube_color=CUBE_COLOR_PALETTE[idx])

    dr_cfg = DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
        cam_pos_jitter=args.dr_cam_pos,
        cam_lookat_jitter=args.dr_cam_lookat,
    )
    cfg = RandomizationConfig(place_jitter=args.place_jitter, seed=args.seed, dr=dr_cfg)
    randomizer = EnvRandomizer(bundle, cfg)
    if args.dr_runtime:
        print(f"[randomize] runtime DR on: friction={dr_cfg.friction_ratio_range} "
              f"mass_ratio={dr_cfg.mass_ratio_range} cam_pos={dr_cfg.cam_pos_jitter} "
              f"cam_lookat={dr_cfg.cam_lookat_jitter}")

    seeds = ([int(s) for s in args.seeds.split(",")] if args.seeds
             else [args.seed + ep for ep in range(args.episodes)])

    n_success = 0
    for ep, episode_seed in enumerate(seeds):
        task = randomizer.reset(seed=episode_seed)
        cube_xy = np.asarray(bundle.cube.get_pos().tolist())[:2]
        r = float(np.linalg.norm(cube_xy - BASE_XY))

        # Track the cube's peak height so failures separate into "never grasped"
        # (zmax stays at cube height) vs "dropped in transit / placed off-target".
        zmax = {"z": 0.0}
        frames: list = []
        step_i = {"i": 0}

        def on_step() -> None:
            zmax["z"] = max(zmax["z"], float(np.asarray(bundle.cube.get_pos().tolist())[2]))
            if args.save_video:
                step_i["i"] += 1
                if step_i["i"] % 4 == 0:          # 25 fps at dt=0.01
                    out = bundle.world_cam.render(rgb=True)
                    frames.append(out[0] if isinstance(out, tuple) else out)

        success, info = run_pick_place(bundle, task, on_step=on_step)
        n_success += int(success)
        final = info["cube_final"]
        print(
            f"[randomize] ep {ep:03d} seed={episode_seed} "
            f"cube=({cube_xy[0]:+.3f},{cube_xy[1]:+.3f}) r={r:.3f} yaw={randomizer.last_yaw % 90:4.1f} "
            f"place=({task.place_xy[0]:+.3f},{task.place_xy[1]:+.3f}) -> success={success} "
            f"att={info.get('attempts', 1)} zmax={zmax['z']:.3f} "
            f"final=({final[0]:+.3f},{final[1]:+.3f}) "
            f"err=({info['err_xy'][0]:.3f},{info['err_xy'][1]:.3f})"
        )

        if args.save_video and frames:
            import imageio.v2 as imageio
            out_dir = Path(args.save_video)
            out_dir.mkdir(parents=True, exist_ok=True)
            tag = "ok" if success else "fail"
            path = out_dir / f"ep{ep:02d}_seed{episode_seed}_{tag}.mp4"
            imageio.mimwrite(str(path), frames, fps=25, codec="libx264", quality=8)
            print(f"[randomize] saved {path} ({len(frames)} frames)")

    print(f"[randomize] {n_success}/{len(seeds)} succeeded")


if __name__ == "__main__":
    main()
