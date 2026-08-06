"""M3: record scripted pick-and-place episodes into a LeRobotDataset.

Runs the M2-randomized scene with the scripted banana pick-and-place, captures
(observation.state, action, camera images) per timestep, and writes only the
*successful* episodes into a LeRobotDataset (lerobot 0.6.x API).

Defaults (per project decision):
  - action space : 9-D joint positions (7 arm + 2 gripper), the commanded targets
  - cameras      : world + wrist RGB
  - fps          : 30 (decimated from the 100 Hz sim by capturing ~every 3.33 steps)
  - success only : failed episodes are discarded

Usage:
    uv run python franka_fruit_pick/record_dataset.py --cpu --episodes 10
    # then inspect: it writes to datasets/<name>/

    # M4 Layer-A: appearance-randomized dataset, new domain every 5 successful episodes
    uv run python franka_fruit_pick/record_dataset.py --episodes 50 \
        --dr-appearance --dr-object-color --dr-table-jitter 0.15 --dr-rebuild-every 5

    # M4 Layer-B: per-episode runtime physics DR (friction/mass), optionally with Layer A
    uv run python franka_fruit_pick/record_dataset.py --episodes 50 \
        --dr-runtime --dr-friction 0.6 1.4 --dr-mass 0.8 1.2
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

from build_scene import SceneDomainRandomizationConfig, build_scene
from grasp_demo import TaskSpec, run_pick_place
from paths import DATASETS_DIR
from randomize import DomainRandomizationConfig, EnvRandomizer, RandomizationConfig

# The sim runs at dt=0.01 (see build_scene): 100 control steps per second.
CONTROL_FPS = 100

JOINT_NAMES = [
    "panda_joint1", "panda_joint2", "panda_joint3", "panda_joint4",
    "panda_joint5", "panda_joint6", "panda_joint7",
    "panda_finger_joint1", "panda_finger_joint2",
]

# Human-readable names for the natural-language task string (per episode).
OBJECT_DISPLAY_NAMES = {
    "011_banana": "banana",
    "014_lemon": "lemon",
    "018_plum": "plum",
    "013_apple": "apple",
    "017_orange": "orange",
    "016_pear": "pear",
    "025_mug": "mug",
}


def task_description(pick_object: str) -> str:
    name = OBJECT_DISPLAY_NAMES.get(pick_object, pick_object)
    return f"pick the {name} and place it in the bowl"


class EpisodeRecorder:
    """Buffers per-timestep (state, action, images) for one episode at a target fps.

    Frames are held in memory and only committed to the dataset if the episode
    succeeds, so failed attempts leave no partial data behind. Capture is decimated
    from the sim's control rate to `fps` via a fractional-step accumulator.
    """

    def __init__(self, bundle, *, fps: int, img_wh: tuple[int, int], control_fps: int = CONTROL_FPS):
        self.bundle = bundle
        self.fps = fps
        self.img_w, self.img_h = img_wh
        self.steps_per_frame = control_fps / fps
        self.reset()

    def reset(self) -> None:
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.world_imgs: list[np.ndarray] = []
        self.wrist_imgs: list[np.ndarray] = []
        # Preload so the very first step is captured (motion onset).
        self._accum = self.steps_per_frame

    def __len__(self) -> int:
        return len(self.states)

    @staticmethod
    def _to_np(x) -> np.ndarray:
        if hasattr(x, "detach"):
            x = x.detach().cpu().numpy()
        return np.asarray(x)

    def _resize(self, img) -> np.ndarray:
        img = self._to_np(img)
        if (img.shape[1], img.shape[0]) != (self.img_w, self.img_h):
            img = cv2.resize(img, (self.img_w, self.img_h), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(img, dtype=np.uint8)

    def on_step(self, action) -> None:
        """Called once per sim control step with the 9-D commanded joint target."""
        self._accum += 1.0
        if self._accum < self.steps_per_frame:
            return
        self._accum -= self.steps_per_frame

        state = self._to_np(self.bundle.franka.get_qpos()).reshape(-1).astype(np.float32)
        action = self._to_np(action).reshape(-1).astype(np.float32)
        world = self._resize(self.bundle.world_cam.render(rgb=True)[0])
        wrist = self._resize(self.bundle.wrist_cam.render(rgb=True)[0])

        self.states.append(state)
        self.actions.append(action)
        self.world_imgs.append(world)
        self.wrist_imgs.append(wrist)

    def flush_to(self, dataset: LeRobotDataset, task: str) -> None:
        """Write the buffered frames into the dataset as one episode."""
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


def _make_scene_dr(args: argparse.Namespace, domain_index: int) -> SceneDomainRandomizationConfig:
    """M4 Layer-A config for appearance domain ``domain_index`` (seed = base + index).

    Each domain is a distinct built scene (colors/textures/FOV baked at build time); the
    per-episode object-pose jitter (M2) still varies within a domain. When DR is disabled
    this returns an inert config so ``build_scene`` behaves exactly as before.
    """
    base = args.dr_seed if args.dr_seed is not None else args.seed
    return SceneDomainRandomizationConfig(
        enabled=args.dr_appearance,
        table_color_jitter=args.dr_table_jitter,
        randomize_object_color=args.dr_object_color,
        fov_jitter_deg=args.dr_fov_jitter,
        seed=base + domain_index,
    )


def _build(args: argparse.Namespace, scene_dr: SceneDomainRandomizationConfig):
    return build_scene(
        show_viewer=args.vis, n_envs=1, add_world_cam=True, add_wrist_cam=True, scene_dr=scene_dr
    )


def _make_runtime_dr(args: argparse.Namespace) -> DomainRandomizationConfig:
    """M4 Layer-B config: per-episode runtime friction / mass / world-cam extrinsics.

    Applied inside ``EnvRandomizer.reset()`` on the built scene, so it composes with (and is
    orthogonal to) the Layer-A appearance domain. Disabled -> inert, matching prior behavior.
    """
    return DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
        cam_pos_jitter=args.dr_cam_pos,
        cam_lookat_jitter=args.dr_cam_lookat,
    )


def _make_randomizer(bundle, args: argparse.Namespace) -> EnvRandomizer:
    return EnvRandomizer(
        bundle,
        RandomizationConfig(randomize_pick=False, seed=args.seed, dr=_make_runtime_dr(args)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Record scripted pick-and-place into a LeRobotDataset.")
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("--episodes", type=int, default=10, help="Number of SUCCESSFUL episodes to record.")
    parser.add_argument("--max-attempts", type=int, default=0, help="Cap on total attempts (0 = 5x episodes).")
    parser.add_argument("--seed", type=int, default=0, help="Base RNG seed.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=360)
    parser.add_argument(
        "--pick",
        nargs="+",
        default=["011_banana"],
        help="Object(s) to pick. Give one (e.g. 014_lemon) or several "
        "(e.g. 011_banana 014_lemon 018_plum) to record a mixed dataset; "
        "one is sampled per episode.",
    )
    parser.add_argument("--repo-id", default="genesis/banana_pick")
    parser.add_argument("--root", default=None, help="Output dir (default: datasets/<repo-name>).")
    parser.add_argument("--vcodec", default="libsvtav1")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing dataset dir first.")
    parser.add_argument(
        "--keep-failures",
        action="store_true",
        help="Debug: also save failed episodes (task label prefixed with 'FAILED: ') "
        "so you can inspect failure modes in the videos.",
    )
    # -- M4 Layer-A domain randomization (build-time appearance / intrinsics) --
    parser.add_argument(
        "--dr-appearance",
        action="store_true",
        help="Enable M4 Layer-A DR: rebuild the scene with a new appearance domain every "
        "--dr-rebuild-every successful episodes.",
    )
    parser.add_argument(
        "--dr-rebuild-every",
        type=int,
        default=5,
        help="Successful episodes per appearance domain before rebuilding (needs --dr-appearance).",
    )
    parser.add_argument(
        "--dr-table-jitter", type=float, default=0.15, help="Layer-A: +/- per-RGB-channel table color jitter."
    )
    parser.add_argument(
        "--dr-object-color", action="store_true", help="Layer-A: recolor objects within DR_APPEARANCE_PRIORS."
    )
    parser.add_argument(
        "--dr-fov-jitter", type=float, default=0.0, help="Layer-A: +/- deg jitter on both cameras' vertical FOV."
    )
    parser.add_argument(
        "--dr-seed",
        type=int,
        default=None,
        help="Base seed for the appearance-domain sequence (default: --seed). Domain d uses base + d.",
    )
    # -- M4 Layer-B domain randomization (per-episode runtime physics / camera extrinsics) --
    parser.add_argument(
        "--dr-runtime",
        action="store_true",
        help="Enable M4 Layer-B DR: re-sample friction/mass/world-cam extrinsics every episode.",
    )
    parser.add_argument(
        "--dr-friction",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=(0.7, 1.3),
        help="Layer-B: friction-ratio range (shared across object/finger/table).",
    )
    parser.add_argument(
        "--dr-mass",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=(0.8, 1.2),
        help="Layer-B: per-object multiplicative mass-ratio range.",
    )
    parser.add_argument(
        "--dr-cam-pos", type=float, default=0.0, help="Layer-B: world-cam position jitter (+/- m)."
    )
    parser.add_argument(
        "--dr-cam-lookat", type=float, default=0.0, help="Layer-B: world-cam lookat jitter (+/- m)."
    )
    args = parser.parse_args()

    img_wh = (args.img_width, args.img_height)
    root = Path(args.root) if args.root else DATASETS_DIR / args.repo_id.split("/")[-1]
    if root.exists():
        if args.overwrite:
            shutil.rmtree(root)
        else:
            raise SystemExit(f"[record] {root} already exists. Use --overwrite or pass a new --root.")

    max_attempts = args.max_attempts if args.max_attempts > 0 else args.episodes * 5

    backend = gs.cpu if args.cpu else gs.gpu
    gs.init(backend=backend)

    # M4 Layer-A: the scene's appearance is baked at build time, so a new appearance domain
    # requires a rebuild. domain_index advances every --dr-rebuild-every successful episodes;
    # rebuilding uses gs.destroy()+gs.init() (the supported repeated-init pattern) and rebinds
    # the randomizer + recorder to the fresh bundle. With DR off this stays a single build.
    domain_index = 0
    bundle = _build(args, _make_scene_dr(args, domain_index))

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=build_features(img_wh),
        root=root,
        robot_type="franka",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    # Randomize object poses each episode. The pick object is sampled here (not by the
    # randomizer) so we can restrict it to the requested --pick list and set a matching
    # per-episode task string.
    randomizer = _make_randomizer(bundle, args)
    recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)
    pick_rng = np.random.default_rng(args.seed)
    pick_choices = list(args.pick)

    n_success = 0
    n_failed_saved = 0
    attempts = 0
    while n_success < args.episodes and attempts < max_attempts:
        # Rebuild into the next appearance domain once this shard's success quota is met.
        target_domain = n_success // args.dr_rebuild_every
        if args.dr_appearance and target_domain != domain_index:
            domain_index = target_domain
            scene_dr = _make_scene_dr(args, domain_index)
            gs.destroy()
            gs.init(backend=backend)
            bundle = _build(args, scene_dr)
            randomizer = _make_randomizer(bundle, args)
            recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)
            print(f"[record] rebuilt scene for appearance domain {domain_index} (seed={scene_dr.seed})")

        episode_seed = args.seed + attempts
        randomizer.reset(seed=episode_seed)
        pick_object = str(pick_rng.choice(pick_choices))
        task = TaskSpec(pick_object=pick_object, place_target="024_bowl")

        recorder.reset()
        success, _ = run_pick_place(bundle, task, recorder=recorder)
        attempts += 1

        if success and len(recorder) > 0:
            recorder.flush_to(dataset, task_description(pick_object))
            n_success += 1
            print(f"[record] episode {n_success}/{args.episodes} saved "
                  f"(attempt {attempts}, seed {episode_seed}, pick={pick_object}, {len(recorder)} frames)")
        elif args.keep_failures and len(recorder) > 0:
            recorder.flush_to(dataset, "FAILED: " + task_description(pick_object))
            n_failed_saved += 1
            print(f"[record] attempt {attempts} (seed {episode_seed}, pick={pick_object}) "
                  f"failed -> saved for debug ({len(recorder)} frames)")
        else:
            print(f"[record] attempt {attempts} (seed {episode_seed}, pick={pick_object}) failed -> discarded")

    dataset.finalize()
    print(f"[record] done: {n_success} success"
          + (f" + {n_failed_saved} failed (debug)" if args.keep_failures else "")
          + f" in {attempts} attempts -> {root}")


if __name__ == "__main__":
    main()
