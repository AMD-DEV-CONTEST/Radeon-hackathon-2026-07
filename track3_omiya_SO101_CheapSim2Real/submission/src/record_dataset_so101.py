"""Record scripted SO101 pick-and-place episodes into a LeRobotDataset.

Follows the structure of record_dataset.py (Franka): run the randomized scene
with the scripted expert, buffer (observation.state, action, camera images) per
timestep, and commit only the *successful* episodes (lerobot 0.6.x API).

  - action space : 6-D joint positions (5 arm + gripper), the commanded targets
  - state        : 6-D measured joint positions
  - cameras      : world (top-down) + wrist RGB
  - fps          : 30 (decimated from the 100 Hz sim)
  - success only : failed episodes are discarded (retries stay inside episodes
                   as recovery behavior)

Actions are captured *without modifying grasp_demo_so101*: the recorder taps
``robot.control_dofs_position`` on the entity instance to stash the latest
commanded 6-D target, and the ``on_step`` callback snapshots it per control step.

Usage:
    # dataset 1: red cube, pose randomization only (no DR)
    uv run python -m franka_fruit_pick.record_dataset_so101 --episodes 50 \
        --repo-id genesis/so101_cube_red

    # dataset 2: appearance DR (new colors/lighting every 5 successful episodes,
    # via scene rebuild) + runtime physics DR
    uv run python -m franka_fruit_pick.record_dataset_so101 --episodes 50 \
        --repo-id genesis/so101_cube_dr \
        --dr-appearance --dr-rebuild-every 5 --dr-runtime --dr-friction 0.8 1.2
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from build_scene_so101 import build_scene_so101, default_backend
from grasp_demo_so101 import TaskSpec, run_pick_place
from paths import DATASETS_DIR
from randomize_so101 import (
    DomainRandomizationConfig,
    EnvRandomizer,
    RandomizationConfig,
    sample_appearance,
)

# The sim runs at dt=0.01 (see build_scene_so101): 100 control steps per second.
CONTROL_FPS = 100

JOINT_NAMES = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]

# One fixed task string: the task (cube -> white sheet) never changes; only the
# domain does. Color is deliberately not mentioned so the same instruction holds
# for the appearance-randomized dataset.
TASK = "pick the cube and place it on the white target sheet"


class ActionTap:
    """Instance-level wrapper around ``robot.control_dofs_position`` that stashes
    the latest commanded joint target, so the scripted demo needs no changes."""

    def __init__(self, robot):
        self.last: np.ndarray | None = None
        self._orig = robot.control_dofs_position
        robot.control_dofs_position = self._tap  # instance attr shadows the method

    def _tap(self, target, *args, **kwargs):
        t = target.tolist() if hasattr(target, "tolist") else target
        self.last = np.asarray(t, dtype=np.float32).reshape(-1)
        return self._orig(target, *args, **kwargs)


class EpisodeRecorder:
    """Buffers per-timestep (state, action, images) for one episode at a target fps.

    Frames are held in memory and only committed if the episode succeeds, so
    failed attempts leave no partial data. Capture is decimated from the sim's
    control rate to ``fps`` via a fractional-step accumulator.
    """

    def __init__(self, bundle, *, fps: int, img_wh: tuple[int, int], control_fps: int = CONTROL_FPS):
        self.bundle = bundle
        self.tap = ActionTap(bundle.robot)
        self.fps = fps
        self.img_w, self.img_h = img_wh
        self.steps_per_frame = control_fps / fps
        self.reset()

    def reset(self) -> None:
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.world_imgs: list[np.ndarray] = []
        self.wrist_imgs: list[np.ndarray] = []
        self._accum = self.steps_per_frame  # preload: capture the very first step

    def __len__(self) -> int:
        return len(self.states)

    @staticmethod
    def _to_np(x) -> np.ndarray:
        if hasattr(x, "detach"):
            x = x.detach().cpu().numpy()
        elif hasattr(x, "tolist"):
            x = np.asarray(x.tolist())
        return np.asarray(x)

    def _resize(self, img) -> np.ndarray:
        img = self._to_np(img)
        if (img.shape[1], img.shape[0]) != (self.img_w, self.img_h):
            img = cv2.resize(img, (self.img_w, self.img_h), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(img, dtype=np.uint8)

    def on_step(self) -> None:
        """on_step callback for run_pick_place — called once per sim control step."""
        self._accum += 1.0
        if self._accum < self.steps_per_frame:
            return
        self._accum -= self.steps_per_frame
        if self.tap.last is None:
            return  # no command issued yet

        state = self._to_np(self.bundle.robot.get_qpos()).reshape(-1).astype(np.float32)
        world = self._resize(self.bundle.world_cam.render(rgb=True)[0])
        wrist = self._resize(self.bundle.wrist_cam.render(rgb=True)[0])

        self.states.append(state)
        self.actions.append(self.tap.last.copy())
        self.world_imgs.append(world)
        self.wrist_imgs.append(wrist)

    def flush_to(self, dataset: LeRobotDataset, task: str) -> None:
        for state, action, world, wrist in zip(self.states, self.actions, self.world_imgs, self.wrist_imgs):
            dataset.add_frame(
                {
                    "observation.state": state,
                    "action": action,
                    "observation.images.world": world,
                    "observation.images.wrist": wrist,
                    "task": task,
                }
            )
        dataset.save_episode()


def build_features(img_wh: tuple[int, int]) -> dict:
    w, h = img_wh
    vec = {"dtype": "float32", "shape": (len(JOINT_NAMES),), "names": JOINT_NAMES}
    img = {"dtype": "video", "shape": (h, w, 3), "names": ["height", "width", "channel"]}
    return {
        "observation.state": dict(vec),
        "action": dict(vec),
        "observation.images.world": dict(img),
        "observation.images.wrist": dict(img),
    }


def _appearance_scope(args: argparse.Namespace) -> dict:
    """Which Layer-A components this run randomizes ({} = appearance DR off)."""
    scope = {
        "cube": args.dr_appearance or args.dr_cube_color,
        "table": args.dr_appearance or args.dr_table_color,
        "lighting": args.dr_appearance or args.dr_lighting,
    }
    return scope if any(scope.values()) else {}


def _build(args: argparse.Namespace, domain_index: int):
    """Build the scene, optionally in appearance domain ``domain_index`` (Layer A)."""
    scope = _appearance_scope(args)
    if scope:
        base = args.dr_seed if args.dr_seed is not None else args.seed
        app = sample_appearance(base + domain_index, **scope)
        on = "+".join(k for k, v in scope.items() if v)
        desc = " ".join(f"{k}={np.round(v, 3).tolist() if isinstance(v, tuple) else round(v, 2)}"
                        for k, v in app.items())
        print(f"[record] appearance domain {domain_index} ({on}): {desc}")
        return build_scene_so101(show_viewer=args.vis, **app)
    return build_scene_so101(show_viewer=args.vis)


def _make_randomizer(bundle, args: argparse.Namespace) -> EnvRandomizer:
    dr = DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
        cam_pos_jitter=args.dr_cam_pos,
        cam_lookat_jitter=args.dr_cam_lookat,
    )
    return EnvRandomizer(bundle, RandomizationConfig(seed=args.seed, dr=dr))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record SO101 pick-and-place into a LeRobotDataset.")
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("--episodes", type=int, default=10, help="Number of SUCCESSFUL episodes to record.")
    parser.add_argument("--max-attempts", type=int, default=0, help="Cap on total attempts (0 = 5x episodes).")
    parser.add_argument("--seed", type=int, default=0, help="Base RNG seed (attempt k uses seed+k).")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=480)
    parser.add_argument("--repo-id", default="genesis/so101_cube_red")
    parser.add_argument("--root", default=None, help="Output dir (default: datasets/<repo-name>).")
    parser.add_argument("--vcodec", default="libsvtav1")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing dataset dir first.")
    parser.add_argument("--keep-failures", action="store_true",
                        help="Debug: also save failed episodes (task prefixed with 'FAILED: ').")
    # -- Layer A: build-time appearance DR (rebuild every N successful episodes).
    # Components are independent toggles so ablation datasets can randomize any
    # subset (cube color only, lighting only, table+lighting, ...). The same
    # domain seed yields the same value for a component regardless of which
    # others are enabled (sampling order is fixed in sample_appearance).
    parser.add_argument("--dr-appearance", action="store_true",
                        help="Shorthand: enable ALL appearance components "
                             "(equivalent to --dr-cube-color --dr-table-color --dr-lighting).")
    parser.add_argument("--dr-cube-color", action="store_true",
                        help="Layer A: randomize the cube color per domain.")
    parser.add_argument("--dr-table-color", action="store_true",
                        help="Layer A: randomize the table green per domain.")
    parser.add_argument("--dr-lighting", action="store_true",
                        help="Layer A: randomize ambient + directional light per domain.")
    parser.add_argument("--dr-rebuild-every", type=int, default=5,
                        help="Successful episodes per appearance domain (needs a Layer-A flag).")
    parser.add_argument("--dr-seed", type=int, default=None,
                        help="Base seed for the appearance-domain sequence (default: --seed).")
    # -- Layer B: per-episode runtime physics / camera DR --
    parser.add_argument("--dr-runtime", action="store_true",
                        help="Re-sample friction/mass/world-cam extrinsics every episode.")
    parser.add_argument("--dr-friction", type=float, nargs=2, metavar=("LO", "HI"), default=(0.8, 1.2),
                        help="Friction-ratio range (0.8-1.2 keeps the scripted expert reliable).")
    parser.add_argument("--dr-mass", type=float, nargs=2, metavar=("LO", "HI"), default=(0.8, 1.2))
    parser.add_argument("--dr-cam-pos", type=float, default=0.0)
    parser.add_argument("--dr-cam-lookat", type=float, default=0.0)
    args = parser.parse_args()

    img_wh = (args.img_width, args.img_height)
    root = Path(args.root) if args.root else DATASETS_DIR / args.repo_id.split("/")[-1]
    if root.exists():
        if args.overwrite:
            shutil.rmtree(root)
        else:
            raise SystemExit(f"[record] {root} already exists. Use --overwrite or pass a new --root.")

    max_attempts = args.max_attempts if args.max_attempts > 0 else args.episodes * 5

    backend = default_backend(force_cpu=args.cpu)
    gs.init(backend=backend)

    # Layer A appearance is baked at build time, so a new domain needs a rebuild:
    # gs.destroy()+gs.init() (the supported repeated-init pattern), then rebind the
    # randomizer + recorder to the fresh bundle. With DR off this is a single build.
    domain_index = 0
    bundle = _build(args, domain_index)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=build_features(img_wh),
        root=root,
        robot_type="so101",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    randomizer = _make_randomizer(bundle, args)
    recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)

    n_success = 0
    n_failed_saved = 0
    attempts = 0
    appearance_on = bool(_appearance_scope(args))
    while n_success < args.episodes and attempts < max_attempts:
        target_domain = n_success // args.dr_rebuild_every
        if appearance_on and target_domain != domain_index:
            domain_index = target_domain
            gs.destroy()
            gs.init(backend=backend)
            bundle = _build(args, domain_index)
            randomizer = _make_randomizer(bundle, args)
            recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)

        episode_seed = args.seed + attempts
        task_spec = TaskSpec()
        randomizer.reset(seed=episode_seed)

        recorder.reset()
        success, info = run_pick_place(bundle, task_spec, on_step=recorder.on_step)
        attempts += 1

        if success and len(recorder) > 0:
            recorder.flush_to(dataset, TASK)
            n_success += 1
            print(f"[record] episode {n_success}/{args.episodes} saved "
                  f"(attempt {attempts}, seed {episode_seed}, grasp_attempts={info.get('attempts', 1)}, "
                  f"{len(recorder)} frames)")
        elif args.keep_failures and len(recorder) > 0:
            recorder.flush_to(dataset, "FAILED: " + TASK)
            n_failed_saved += 1
            print(f"[record] attempt {attempts} (seed {episode_seed}) failed -> saved for debug")
        else:
            print(f"[record] attempt {attempts} (seed {episode_seed}) failed -> discarded")

    dataset.finalize()
    print(f"[record] done: {n_success} success"
          + (f" + {n_failed_saved} failed (debug)" if args.keep_failures else "")
          + f" in {attempts} attempts -> {root}")


if __name__ == "__main__":
    main()
