"""Record scripted color-sorting episodes into a LeRobotDataset.

Based on franka_fruit_pick_demo's record_dataset.py. Key changes:
- Task text = "pick the <color> <geometry> into the <color> bin"
- Pick pool = PICKABLE_GEOMETRIES (cube + cylinder, no sphere)
- Train/eval color hold-out: train on red/blue/green, eval on yellow/purple
- Action space: 9-D joint positions (7 arm + 2 gripper)
- Cameras: world + wrist RGB, 30fps decimated from 100Hz sim

Usage:
    # Record 50 training episodes (red/blue/green only)
    python record_dataset.py --episodes 50 --split train --repo-id color_sort/train

    # Record 20 eval episodes (yellow/purple only, hold-out colors)
    python record_dataset.py --episodes 20 --split eval --repo-id color_sort/eval
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

from build_scene import build_scene
from sk_grasp_demo import TaskSpec, run_pick_place
from paths import DATASETS_DIR
from randomize import EnvRandomizer, RandomizationConfig
from scene_config import COLORS, PICKABLE_GEOMETRIES

CONTROL_FPS = 100

JOINT_NAMES = [
    "panda_joint1", "panda_joint2", "panda_joint3", "panda_joint4",
    "panda_joint5", "panda_joint6", "panda_joint7",
    "panda_finger_joint1", "panda_finger_joint2",
]

# Color hold-out split: train colors vs eval colors
TRAIN_COLORS = ("red", "blue", "green")
EVAL_COLORS = ("yellow", "purple")


def task_description(pick_object: str, place_color: str) -> str:
    """Natural-language task string for the dataset."""
    color, geometry = pick_object.rsplit("_", 1)
    geom_name = "cube" if geometry == "cube" else "cylinder"
    return f"pick the {color} {geom_name} into the {place_color} bin"


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


def _colors_for_split(split: str) -> tuple[str, ...]:
    if split == "train":
        return TRAIN_COLORS
    elif split == "eval":
        return EVAL_COLORS
    else:
        return COLORS


def main() -> None:
    parser = argparse.ArgumentParser(description="Record scripted color-sorting into a LeRobotDataset.")
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("--episodes", type=int, default=10, help="Number of SUCCESSFUL episodes to record.")
    parser.add_argument("--max-attempts", type=int, default=0, help="Cap on total attempts (0 = 5x episodes).")
    parser.add_argument("--seed", type=int, default=0, help="Base RNG seed.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=360)
    parser.add_argument(
        "--split",
        choices=["train", "eval", "all"],
        default="train",
        help="Color hold-out split: train (red/blue/green), eval (yellow/purple), all (5 colors).",
    )
    parser.add_argument("--repo-id", default="color_sort/train")
    parser.add_argument("--root", default=None, help="Output dir (default: datasets/<repo-name>).")
    parser.add_argument("--vcodec", default="libsvtav1")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing dataset dir first.")
    args = parser.parse_args()

    img_wh = (args.img_width, args.img_height)
    root = Path(args.root) if args.root else DATASETS_DIR / args.repo_id.split("/")[-1]
    if root.exists():
        if args.overwrite:
            shutil.rmtree(root)
        else:
            raise SystemExit(f"[record] {root} already exists. Use --overwrite or pass a new --root.")

    max_attempts = args.max_attempts if args.max_attempts > 0 else args.episodes * 5

    # Determine which colors to build into the scene
    split_colors = _colors_for_split(args.split)

    backend = gs.cpu if args.cpu else gs.gpu
    gs.init(backend=backend)

    # Build scene with split colors (train or eval)
    bundle = build_scene(show_viewer=args.vis, colors=split_colors)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=build_features(img_wh),
        root=root,
        robot_type="franka",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    # Randomizer: pick from pickable geometries of the split colors only
    pick_pool = [f"{color}_{geom}" for color in split_colors for geom in PICKABLE_GEOMETRIES]
    cfg = RandomizationConfig(pos_jitter=0.04, randomize_pick=True, seed=args.seed)
    randomizer = EnvRandomizer(bundle, cfg)
    recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)
    pick_rng = np.random.default_rng(args.seed)

    n_success = 0
    attempts = 0
    while n_success < args.episodes and attempts < max_attempts:
        episode_seed = args.seed + attempts
        randomizer.reset(seed=episode_seed)
        pick_object = str(pick_rng.choice(pick_pool))
        # Place target = the pick object's color
        pick_color = pick_object.rsplit("_", 1)[0]
        task = TaskSpec(pick_object=pick_object, place_target=pick_color)
        task_text = task_description(pick_object, pick_color)

        recorder.reset()
        success, _ = run_pick_place(bundle, task, recorder=recorder)
        attempts += 1

        if success and len(recorder) > 0:
            recorder.flush_to(dataset, task_text)
            n_success += 1
            print(f"[record] episode {n_success}/{args.episodes} saved "
                  f"(attempt {attempts}, seed {episode_seed}, pick={pick_object}, {len(recorder)} frames)")
        else:
            print(f"[record] attempt {attempts} (seed {episode_seed}, pick={pick_object}) failed -> discarded")

    dataset.finalize()
    print(f"[record] done: {n_success} success in {attempts} attempts -> {root}")


if __name__ == "__main__":
    main()