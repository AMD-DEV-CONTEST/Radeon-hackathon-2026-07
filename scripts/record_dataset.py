"""Record scripted SO-101 pick-and-place episodes into a LeRobotDataset.

Runs the randomized scene + scripted top-down pick-place, captures
(observation.state, action, world/wrist RGB) per timestep, and writes only the
*successful* episodes into a LeRobotDataset (lerobot 0.6.x API). This is the
synthetic-demonstration generator that feeds SmolVLA fine-tuning.

  - action space : 6-D joint targets (5 arm + 1 gripper), the commanded targets
  - state        : 6-D measured joint positions
  - cameras      : world + wrist RGB
  - fps          : 30 (decimated from the 100 Hz sim)
  - success only : failed episodes are discarded

Usage (on the Radeon machine, after setup_so101_assets.py):
    python scripts/record_dataset.py --episodes 100 --repo-id so101/cube_pick

NOTE: Requires Genesis + lerobot[training]. The camera-key layout (world/wrist)
matches vla/agent.py's SmolVLA rename map.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from paths import DATASETS_DIR
from simulation import so101
from simulation.genesis_env import (
    CUBE_HOME,
    SO101PickPlaceEnv,
    build_scene,
    task_instruction,
)
from simulation.scripted_pick import ScriptedPickPlace

CONTROL_FPS = 100


class EpisodeRecorder:
    """Buffers per-timestep (state, action, images) for one episode at target fps."""

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
        self._accum = self.steps_per_frame  # capture the first step

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
        """Called once per sim control step with the 6-D commanded joint target."""
        self._accum += 1.0
        if self._accum < self.steps_per_frame:
            return
        self._accum -= self.steps_per_frame
        state = self._to_np(self.bundle.robot.get_qpos()).reshape(-1).astype(np.float32)
        action = self._to_np(action).reshape(-1).astype(np.float32)
        self.states.append(state)
        self.actions.append(action)
        self.world_imgs.append(self._resize(self.bundle.world_cam.render(rgb=True)[0]))
        self.wrist_imgs.append(self._resize(self.bundle.wrist_cam.render(rgb=True)[0]))

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
    vec = {"dtype": "float32", "shape": (so101.N_DOF,), "names": so101.JOINT_NAMES}
    img = {"dtype": "video", "shape": (h, w, 3), "names": ["height", "width", "channel"]}
    return {
        "observation.state": dict(vec),
        "action": dict(vec),
        "observation.images.world": dict(img),
        "observation.images.wrist": dict(img),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record scripted SO-101 pick-place into a LeRobotDataset.")
    parser.add_argument("-c", "--cpu", action="store_true")
    parser.add_argument("-v", "--vis", action="store_true")
    parser.add_argument("--episodes", type=int, default=100, help="Number of SUCCESSFUL episodes.")
    parser.add_argument("--max-attempts", type=int, default=0, help="Cap on attempts (0 = 5x episodes).")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--img-width", type=int, default=320)
    parser.add_argument("--img-height", type=int, default=240)
    parser.add_argument(
        "--colors", nargs="+", default=list(CUBE_HOME),
        help="Cube colors to target; one sampled per episode (default: red blue green).",
    )
    parser.add_argument("--repo-id", default="so101/cube_pick")
    parser.add_argument("--root", default=None, help="Output dir (default: datasets/<repo-name>).")
    parser.add_argument("--vcodec", default="libsvtav1")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--save-debug-dir",
        default=None,
        help="Headless debug: save world_cam PNG after each attempt (no display needed).",
    )
    args = parser.parse_args()

    img_wh = (args.img_width, args.img_height)
    root = Path(args.root) if args.root else DATASETS_DIR / args.repo_id.split("/")[-1]
    if root.exists():
        if args.overwrite:
            shutil.rmtree(root)
        else:
            raise SystemExit(f"[record] {root} already exists. Use --overwrite or a new --root.")

    debug_dir = Path(args.save_debug_dir) if args.save_debug_dir else None
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

    max_attempts = args.max_attempts if args.max_attempts > 0 else args.episodes * 5
    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=args.vis)
    env = SO101PickPlaceEnv(bundle=bundle)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=build_features(img_wh),
        root=root,
        robot_type="so101",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    recorder = EpisodeRecorder(bundle, fps=args.fps, img_wh=img_wh)
    color_rng = np.random.default_rng(args.seed)

    n_success = 0
    attempts = 0
    while n_success < args.episodes and attempts < max_attempts:
        episode_seed = args.seed + attempts
        color = str(color_rng.choice(list(args.colors)))
        env.reset(seed=episode_seed, target_color=color)
        recorder.reset()
        try:
            success = ScriptedPickPlace(bundle).run(color, recorder=recorder)
        except gs.GenesisException as exc:
            print(f"[record] attempt {attempts} (seed {episode_seed}, {color}) diverged: {exc}")
            attempts += 1
            continue
        attempts += 1

        if debug_dir is not None and bundle.world_cam is not None:
            import imageio.v2 as imageio

            frame = EpisodeRecorder._to_np(bundle.world_cam.render(rgb=True)[0])
            tag = "ok" if success else "fail"
            out = debug_dir / f"attempt{attempts:03d}_{tag}_{color}_seed{episode_seed}.png"
            imageio.imwrite(out, np.ascontiguousarray(frame, dtype=np.uint8))
            print(f"[record] debug frame -> {out}")

        if success and len(recorder) > 0:
            recorder.flush_to(dataset, task_instruction(color))
            n_success += 1
            print(f"[record] episode {n_success}/{args.episodes} saved "
                  f"(attempt {attempts}, seed {episode_seed}, {color}, {len(recorder)} frames)")
        else:
            print(f"[record] attempt {attempts} (seed {episode_seed}, {color}) failed -> discarded")

    dataset.finalize()
    print(f"[record] done: {n_success} success in {attempts} attempts -> {root}")


if __name__ == "__main__":
    main()
