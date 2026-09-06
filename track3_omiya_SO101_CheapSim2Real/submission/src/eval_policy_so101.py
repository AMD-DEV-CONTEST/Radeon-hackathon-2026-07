"""Policy-agnostic closed-loop evaluation of a trained lerobot policy on SO101.

Follows the structure of eval_policy.py (Franka): load any lerobot checkpoint
(ACT, SmolVLA, ...), run it closed-loop in the same Genesis scene used for
recording, and report the success rate.

Layers (unchanged from the Franka version):
  1. Policy layer   -- PreTrainedConfig + make_policy + make_pre_post_processors
  2. Observation    -- build_observation reads sim state into the dataset's raw
                       feature keys (observation.state + world/wrist images)
  3. Action layer   -- the policy emits 6-D joint targets; position control
  4. Rollout layer  -- run_episode decimates 100 Hz control to the policy fps,
                       with a dwell on check_success so fly-bys don't count

Usage:
    uv run python -m franka_fruit_pick.eval_policy_so101 \
        --policy-path outputs/act_so101_red/checkpoints/last/pretrained_model \
        --repo-id omiya239532/so101_cube_red --dataset-root datasets/so101_cube_red \
        --episodes 20

    # held-out cube colors (the eval scenes are rebuilt per color):
    uv run python -m franka_fruit_pick.eval_policy_so101 ... --cube-color 0.9,0.7,0.05
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from lerobot.common.control_utils import predict_action
from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.utils.device_utils import get_safe_torch_device

from build_scene_so101 import (CUBE_COLOR_RED, build_scene_so101, default_backend,
                               default_policy_device)
from grasp_demo_so101 import (
    SO101_FORCE,
    SO101_KP,
    SO101_KV,
    TaskSpec,
    check_success,
)
from paths import EVAL_RESULTS_DIR, EVAL_VIDEOS_DIR
from randomize_so101 import (
    DomainRandomizationConfig,
    EnvRandomizer,
    RandomizationConfig,
    sample_appearance,
)
from record_dataset_so101 import CONTROL_FPS, TASK

STATE_KEY = "observation.state"

# After the success condition first holds, keep RUNNING THE POLICY this much longer
# before the final verdict. The condition can trigger while the cube is still
# gripped just above the sheet, and releasing can flick it off — so the tail lets
# the policy finish its release/retreat and the episode is judged on where the
# cube actually ends up. Also makes the saved video show the full protocol
# (8 s covers release + the slower policy-paced return toward home).
POST_SUCCESS_SECONDS = 8.0


@dataclass
class PolicyBundle:
    """A loaded policy plus everything needed to run inference on it."""

    policy: object
    preprocessor: object
    postprocessor: object
    device: torch.device
    fps: int
    image_keys: list[str]
    image_hw: tuple[int, int]
    use_amp: bool = False
    policy_type: str = "unknown"

    def reset(self) -> None:
        self.policy.reset()

    def select_action(self, observation: dict[str, np.ndarray], task: str | None) -> np.ndarray:
        action = predict_action(
            observation,
            self.policy,
            self.device,
            self.preprocessor,
            self.postprocessor,
            use_amp=self.use_amp,
            task=task,
            robot_type="so101",
        )
        return action.detach().cpu().numpy().reshape(-1).astype(np.float32)


def _load_rename_map(policy_path: str) -> dict:
    """Recover the training-time camera rename_map from the checkpoint (if any)."""
    p = Path(policy_path) / "train_config.json"
    if p.is_file():
        try:
            return json.loads(p.read_text()).get("rename_map") or {}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_policy(
    policy_path: str,
    repo_id: str,
    dataset_root: str | None,
    device_str: str,
    *,
    use_amp: bool = False,
    rename_map: dict | None = None,
) -> PolicyBundle:
    """Generically load any lerobot policy checkpoint for closed-loop inference."""
    device = get_safe_torch_device(device_str, log=True)

    ds_meta = LeRobotDatasetMetadata(repo_id, root=dataset_root)

    cfg = PreTrainedConfig.from_pretrained(policy_path)
    cfg.pretrained_path = policy_path
    cfg.device = str(device)

    if rename_map is None:
        rename_map = _load_rename_map(policy_path)
    if rename_map:
        print(f"[eval] camera rename_map: {rename_map}")

    policy = make_policy(cfg=cfg, ds_meta=ds_meta, rename_map=rename_map)
    policy.eval()

    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg,
        pretrained_path=policy_path,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    image_keys = [k for k in ds_meta.features if k.startswith("observation.images")]
    if not image_keys:
        raise RuntimeError(f"No image features found in dataset {repo_id!r}.")
    h, w, _ = ds_meta.features[image_keys[0]]["shape"]

    print(
        f"[eval] loaded {cfg.type} policy from {policy_path}\n"
        f"       device={device} fps={ds_meta.fps} images={image_keys} @ {w}x{h}"
    )
    return PolicyBundle(
        policy=policy,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        device=device,
        fps=ds_meta.fps,
        image_keys=image_keys,
        image_hw=(h, w),
        use_amp=use_amp,
        policy_type=cfg.type,
    )


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    elif hasattr(x, "tolist"):
        x = np.asarray(x.tolist())
    return np.asarray(x)


def _render_camera(cam, size_wh: tuple[int, int]) -> np.ndarray:
    img = _to_np(cam.render(rgb=True)[0])
    w, h = size_wh
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def build_observation(bundle, pb: PolicyBundle) -> dict[str, np.ndarray]:
    """Read the current sim state into the dataset's raw feature layout (numpy)."""
    h, w = pb.image_hw
    obs: dict[str, np.ndarray] = {
        STATE_KEY: _to_np(bundle.robot.get_qpos()).reshape(-1).astype(np.float32),
    }
    cam_for_key = {
        "observation.images.world": bundle.world_cam,
        "observation.images.wrist": bundle.wrist_cam,
    }
    for key in pb.image_keys:
        cam = cam_for_key.get(key)
        if cam is None:
            raise RuntimeError(f"Dataset expects camera {key!r} but the scene has no such camera.")
        obs[key] = _render_camera(cam, (w, h))
    return obs


def _record_frame(bundle, pb: PolicyBundle, obs: dict[str, np.ndarray]) -> np.ndarray:
    """One saved-video frame: world + wrist side by side."""
    primary = obs[pb.image_keys[0]]
    h, w = primary.shape[:2]
    panels = [primary]
    if bundle.wrist_cam is not None:
        panels.append(_render_camera(bundle.wrist_cam, (w, h)))
    if len(panels) == 1:
        return primary.copy()
    return np.ascontiguousarray(np.hstack(panels))


def apply_action(bundle, action: np.ndarray, n_sim_steps: int) -> None:
    """Position-control the arm+gripper to the policy's target for n_sim_steps."""
    action = np.asarray(action, dtype=np.float64).reshape(-1)
    for _ in range(n_sim_steps):
        bundle.robot.control_dofs_position(action)
        bundle.scene.step()
        bundle.update_wrist_cam()


@dataclass
class EpisodeResult:
    success: bool
    frames: list[np.ndarray] = field(default_factory=list)
    n_policy_steps: int = 0


def run_episode(
    bundle,
    pb: PolicyBundle,
    task: TaskSpec,
    *,
    task_text: str | None,
    max_seconds: float,
    record_video: bool = False,
) -> EpisodeResult:
    """One closed-loop rollout. Policy queried at pb.fps; action held in between."""
    pb.reset()

    steps_per_frame = CONTROL_FPS / pb.fps
    max_frames = int(round(max_seconds * pb.fps))

    result = EpisodeResult(success=False)
    accum = 0.0
    settle_frames = max(1, int(round(0.4 * pb.fps)))   # dwell before starting the tail
    success_streak = 0
    tail_left: int | None = None    # frames of post-success policy rollout remaining
    for _ in range(max_frames):
        obs = build_observation(bundle, pb)
        if record_video:
            result.frames.append(_record_frame(bundle, pb, obs))

        action = pb.select_action(obs, task_text)

        accum += steps_per_frame
        n_sub = int(accum)
        accum -= n_sub
        apply_action(bundle, action, max(1, n_sub))
        result.n_policy_steps += 1

        if tail_left is not None:
            tail_left -= 1
            if tail_left <= 0:
                break
        elif check_success(bundle, task):
            success_streak += 1
            if success_streak >= settle_frames:
                tail_left = max(1, int(round(POST_SUCCESS_SECONDS * pb.fps)))
        else:
            success_streak = 0

    # Final verdict AFTER the tail: the cube must still be on the sheet once the
    # policy has released and retreated (a release that flicks it off = failure).
    result.success = check_success(bundle, task)
    return result


def _save_video(frames: list[np.ndarray], path: Path, fps: int) -> None:
    """H.264/yuv420p mp4 (plays in browsers and VSCode's viewer)."""
    if not frames:
        return
    import imageio.v2 as imageio

    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    h_even, w_even = h - (h % 2), w - (w % 2)
    writer = imageio.get_writer(
        str(path), fps=fps, codec="libx264", format="ffmpeg",
        pixelformat="yuv420p", macro_block_size=None,
    )
    try:
        for f in frames:
            writer.append_data(np.ascontiguousarray(f[:h_even, :w_even]))
    finally:
        writer.close()


def evaluate_policy(
    bundle,
    pb: PolicyBundle,
    *,
    episodes: int,
    seed: int = 1000,
    max_seconds: float = 45.0,
    no_task: bool = False,
    randomizer: EnvRandomizer | None = None,
    save_video: bool = False,
    video_dir: Path | None = None,
    label: str = "",
) -> dict:
    """Run `episodes` closed-loop rollouts and return a structured results dict.

    Initial conditions are fully determined by `seed` (randomizer.reset(seed+ep)),
    so the same seed evaluates different checkpoints on identical episodes.
    """
    if randomizer is None:
        randomizer = EnvRandomizer(bundle, RandomizationConfig(seed=seed))
    prefix = f"[eval:{label}]" if label else "[eval]"

    n_success = 0
    n_diverged = 0
    episodes_detail: list[dict] = []
    for ep in range(episodes):
        episode_seed = seed + ep
        task = TaskSpec()
        task_text = None if no_task else TASK

        try:
            randomizer.reset(seed=episode_seed)
            result = run_episode(
                bundle, pb, task,
                task_text=task_text,
                max_seconds=max_seconds,
                record_video=save_video,
            )
        except gs.GenesisException as exc:
            # Physics divergence aborts only this episode; the next reset() rewrites
            # all poses to finite values and the sim self-heals without a rebuild.
            n_diverged += 1
            episodes_detail.append({"ep": ep, "seed": episode_seed, "steps": 0,
                                    "success": False, "diverged": True})
            print(f"{prefix} ep {ep:03d} seed={episode_seed} -> DIVERGED ({exc}); counted as failure")
            continue

        n_success += int(result.success)
        episodes_detail.append({"ep": ep, "seed": episode_seed,
                                "steps": result.n_policy_steps,
                                "success": bool(result.success), "diverged": False})

        if save_video and video_dir is not None:
            tag = "success" if result.success else "fail"
            _save_video(result.frames, Path(video_dir) / f"ep{ep:03d}_{tag}.mp4", pb.fps)

        print(f"{prefix} ep {ep:03d} seed={episode_seed} "
              f"steps={result.n_policy_steps} -> success={result.success}")

    rate = n_success / max(1, episodes)
    diverged_note = f" ({n_diverged} diverged)" if n_diverged else ""
    print(f"{prefix} success rate: {n_success}/{episodes} = {rate:.1%}{diverged_note}")

    return {
        "episodes": episodes,
        "n_success": n_success,
        "n_diverged": n_diverged,
        "success_rate": rate,
        "episodes_detail": episodes_detail,
        "params": {"seed": seed, "max_seconds": max_seconds, "no_task": no_task},
    }


def checkpoint_label(policy_path: str) -> str:
    p = Path(policy_path)
    if p.name == "pretrained_model" and p.parent.name:
        return p.parent.name
    return p.name


def write_results(results: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[eval] results -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy-agnostic closed-loop eval (SO101).")
    parser.add_argument("--policy-path", required=True,
                        help="Checkpoint dir (contains config.json + model.safetensors).")
    parser.add_argument("--repo-id", required=True, help="Repo id of the training dataset.")
    parser.add_argument("--dataset-root", default=None,
                        help="Local dataset dir (for feature shapes/stats/fps).")
    parser.add_argument("--device", default=default_policy_device(),
                        help="cuda | mps | cpu (defaults to what this machine has).")
    parser.add_argument("--use-amp", action="store_true")
    parser.add_argument("--rename-map", default=None,
                        help="JSON dict mapping dataset image keys to the policy's keys "
                             "(default: auto-recovered from train_config.json).")
    parser.add_argument("-c", "--cpu", action="store_true", help="Genesis sim on CPU backend.")
    parser.add_argument("-v", "--vis", action="store_true")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1000,
                        help="Base RNG seed (offset from the training seeds).")
    parser.add_argument("--max-seconds", type=float, default=45.0,
                        help="Sim-time budget per episode (scripted expert takes ~26-39 s).")
    parser.add_argument("--no-task", action="store_true",
                        help="Send an empty task string (ignore language conditioning).")
    # -- eval-time scene appearance (held-out color evaluation) --
    parser.add_argument("--cube-color", default=None,
                        help="Cube RGB 'r,g,b' in 0-1 (e.g. '0.9,0.7,0.05' yellow; "
                             "default: training red).")
    parser.add_argument("--dr-appearance-seed", type=int, default=None,
                        help="Build the scene from sample_appearance(seed) instead of defaults.")
    # -- Layer-B runtime DR during eval (robustness measurement) --
    parser.add_argument("--dr-runtime", action="store_true")
    parser.add_argument("--dr-friction", type=float, nargs=2, metavar=("LO", "HI"), default=(0.8, 1.2))
    parser.add_argument("--dr-mass", type=float, nargs=2, metavar=("LO", "HI"), default=(0.8, 1.2))
    parser.add_argument("--dr-cam-pos", type=float, default=0.0)
    parser.add_argument("--dr-cam-lookat", type=float, default=0.0)
    parser.add_argument("--save-video", action="store_true",
                        help="Save each rollout to mp4 (world + wrist side by side).")
    parser.add_argument("--video-dir", default=None)
    parser.add_argument("--results-out", default=None,
                        help="Structured results JSON (default: eval_results/<repo>/<ckpt>.json; "
                             "'none' to skip).")
    args = parser.parse_args()

    repo_name = args.repo_id.split("/")[-1]
    gs.init(backend=default_backend(force_cpu=args.cpu))

    build_kwargs: dict = {}
    if args.dr_appearance_seed is not None:
        build_kwargs = sample_appearance(args.dr_appearance_seed)
    if args.cube_color:
        r, g, b = (float(v) for v in args.cube_color.split(","))
        build_kwargs["cube_color"] = (r, g, b, 1.0)
    elif "cube_color" not in build_kwargs:
        build_kwargs["cube_color"] = CUBE_COLOR_RED
    bundle = build_scene_so101(show_viewer=args.vis, **build_kwargs)

    # Same PD gains / torque clamps the demonstrations were recorded under —
    # without these the policy runs on Genesis defaults (no 4.0 jaw clamp, softer
    # tracking) and the learned actions land in different dynamics.
    bundle.robot.set_dofs_kp(SO101_KP)
    bundle.robot.set_dofs_kv(SO101_KV)
    bundle.robot.set_dofs_force_range(-SO101_FORCE, SO101_FORCE)

    rename_map = json.loads(args.rename_map) if args.rename_map else None
    pb = load_policy(
        args.policy_path, args.repo_id, args.dataset_root, args.device,
        use_amp=args.use_amp, rename_map=rename_map,
    )

    video_dir = Path(args.video_dir) if args.video_dir else EVAL_VIDEOS_DIR / repo_name

    dr = DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
        cam_pos_jitter=args.dr_cam_pos,
        cam_lookat_jitter=args.dr_cam_lookat,
    )
    randomizer = EnvRandomizer(bundle, RandomizationConfig(seed=args.seed, dr=dr))

    results = evaluate_policy(
        bundle, pb,
        episodes=args.episodes,
        seed=args.seed,
        max_seconds=args.max_seconds,
        no_task=args.no_task,
        randomizer=randomizer,
        save_video=args.save_video,
        video_dir=video_dir,
    )
    if args.save_video:
        print(f"[eval] rollout videos -> {video_dir}")

    if args.results_out != "none":
        label = checkpoint_label(args.policy_path)
        out = Path(args.results_out) if args.results_out else EVAL_RESULTS_DIR / repo_name / f"{label}.json"
        results["meta"] = {
            "policy_path": args.policy_path,
            "policy_type": pb.policy_type,
            "checkpoint": label,
            "repo_id": args.repo_id,
            "dataset_root": args.dataset_root,
            "device": str(pb.device),
            "cube_color": args.cube_color or "red (training)",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        write_results(results, out)


if __name__ == "__main__":
    main()
