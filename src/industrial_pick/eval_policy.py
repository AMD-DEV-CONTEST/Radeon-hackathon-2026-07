"""Closed-loop SmolVLA evaluation on the industrial SORTING scene (V2).

Loads a trained SmolVLA checkpoint and runs it closed-loop in the same Genesis scene
used for data collection: per-episode pose randomization via EnvRandomizer, policy
observations = (9-D qpos, world+wrist RGB at 640x360) exactly as recorded, 9-D joint
position actions replayed at ~30 Hz on the 100 Hz sim (3/3/4 step pattern, matching
the recorder's decimation).

Success uses grasp_demo.check_success (object bottom below the target box's rim +
inside the wall footprint), polled every recorded frame; an episode only counts as
successful when the test holds for ``--dwell`` consecutive frames, so a transient
graze over the box does not count.

Videos: native-resolution world + wrist mp4 per episode (h264 via ffmpeg pipe).

Usage:
    # 3-sample inspection run (one episode per object)
    python eval_policy.py --episodes 3 --picks gear nut bolt --seed 1000 \
        --video-dir /workspace/eval_videos/samples

    # formal evaluation, 10 episodes per object
    python eval_policy.py --episodes 30 --picks gear nut bolt --seed 2000 \
        --video-dir /workspace/eval_videos/formal
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs

from build_scene import build_scene
from grasp_demo import TaskSpec, check_success
from randomize import EnvRandomizer, RandomizationConfig
from scene_config import BOX_DISPLAY_NAMES, SORT_TARGET

# Sim runs at dt=0.01 (build_scene); dataset actions were recorded at 30 fps.
CONTROL_FPS = 100
FPS = 30

# Must match record_dataset.task_description / OBJECT_DISPLAY_NAMES exactly -- the
# policy conditions on this string.
OBJECT_DISPLAY_NAMES = {
    "gear": "gear",
    "nut": "hex nut",
    "bolt": "bolt",
}


def task_description(pick_object: str) -> str:
    name = OBJECT_DISPLAY_NAMES.get(pick_object, pick_object)
    box = BOX_DISPLAY_NAMES[SORT_TARGET[pick_object]]
    return f"pick the {name} and place it in the {box}"


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


class PolicyRunner:
    """SmolVLA checkpoint + pre/post processors, built from the training dataset's metadata."""

    def __init__(self, checkpoint: str, dataset_id: str, device: torch.device):
        from lerobot.configs.types import FeatureType
        from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
        from lerobot.datasets.utils import dataset_to_policy_features
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

        self.device = device
        dm = LeRobotDatasetMetadata(dataset_id)
        ft = dataset_to_policy_features(dm.features)
        of = {k: v for k, v in ft.items() if v.type is FeatureType.ACTION}
        inf = {k: v for k, v in ft.items() if k not in of}
        ckpt = Path(checkpoint)
        scfg = json.loads((ckpt / "config.json").read_text()) if (ckpt / "config.json").exists() else {}
        cs = scfg.get("chunk_size", 50)
        cfg = SmolVLAConfig(input_features=inf, output_features=of, chunk_size=cs, n_action_steps=cs)
        cfg.vlm_model_name = '/persistent/track3-robot/models/SmolVLM2-500M-Video-Instruct'
        try:
            self.policy = SmolVLAPolicy.from_pretrained(str(ckpt), config=cfg, strict=False)
        except Exception:
            from safetensors.torch import load_file

            self.policy = SmolVLAPolicy(cfg)
            self.policy.load_state_dict(load_file(str(ckpt / "model.safetensors")), strict=False)
        self.policy.eval().to(device)
        self.pre, self.post = make_pre_post_processors(cfg, dataset_stats=dm.stats)
        print(f"[eval] SmolVLA loaded from {ckpt} (chunk_size={cs})")

    def predict(self, state: np.ndarray, imgs: dict[str, np.ndarray], task: str) -> np.ndarray:
        """One observation -> (chunk_size, 9) action chunk (numpy)."""
        obs = {
            "observation.state": torch.from_numpy(state).unsqueeze(0).float().to(self.device),
            "task": [task],
        }
        for k, img in imgs.items():
            obs[k] = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(self.device) / 255.0
        with torch.no_grad():
            obs = self.pre(obs)
            for k, v in list(obs.items()):
                if isinstance(v, torch.Tensor) and v.device != self.device:
                    obs[k] = v.to(self.device)
            raw = self.policy.select_action(obs)
            raw = self.post(raw)
        acts = raw["action"] if isinstance(raw, dict) else raw
        acts = acts.detach().cpu().numpy()
        if acts.ndim == 3:
            acts = acts[0]
        elif acts.ndim == 1:
            acts = acts[np.newaxis, :]
        return acts


def save_mp4(frames: list[np.ndarray], path: Path, fps: int = FPS) -> None:
    """Write uint8 RGB frames to h264 mp4 via an ffmpeg pipe (no intermediate files)."""
    if not frames:
        return
    h, w = frames[0].shape[:2]
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23", str(path)],
        stdin=subprocess.PIPE,
    )
    for f in frames:
        proc.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Closed-loop SmolVLA eval on the industrial scene.")
    parser.add_argument("--checkpoint", required=True,
                        help="Path to the trained checkpoint dir (e.g. models/smolvla_industrial_sort_v2_ckpt20k). "
                        "Required so a silent default can never evaluate the wrong model.")
    parser.add_argument("--dataset-id", default="local/industrial_sort_v2")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--picks", nargs="+", default=["gear", "nut", "bolt"],
                        help="Pick objects, cycled across episodes.")
    parser.add_argument("--seed", type=int, default=1000, help="Base seed for episode pose randomization.")
    parser.add_argument("--max-frames", type=int, default=450,
                        help="Max recorded (30 Hz) frames per episode; training episodes were ~250.")
    parser.add_argument("--n-action-steps", type=int, default=0,
                        help="Execute only the first N actions of each predicted chunk before "
                        "re-predicting (0 = full 50-action chunk). Smaller N = more frequent "
                        "replanning, giving the final grasp approach a chance to correct.")
    parser.add_argument("--dwell", type=int, default=15,
                        help="Consecutive frames the success test must hold (0.5 s at 30 Hz).")
    parser.add_argument("--video-dir", default="./eval_videos/samples")
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=360)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    runner = PolicyRunner(args.checkpoint, args.dataset_id, device)

    gs.init(backend=gs.gpu, logging_level="warning")
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=True)
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=False, seed=args.seed))

    vdir = Path(args.video_dir)
    vdir.mkdir(parents=True, exist_ok=True)
    img_wh = (args.img_width, args.img_height)
    steps_per_frame = CONTROL_FPS / FPS

    def render_cams():
        """Native-res frames for video + resized copies for the policy."""
        w = _to_np(bundle.world_cam.render(rgb=True)[0]).astype(np.uint8)
        r = _to_np(bundle.wrist_cam.render(rgb=True)[0]).astype(np.uint8)
        w_pol = cv2.resize(w, img_wh, interpolation=cv2.INTER_AREA)
        r_pol = cv2.resize(r, img_wh, interpolation=cv2.INTER_AREA)
        return w, r, w_pol, r_pol

    results = []
    for ep in range(args.episodes):
        pick = args.picks[ep % len(args.picks)]
        seed = args.seed + ep
        randomizer.reset(seed=seed)
        task = TaskSpec(pick_object=pick, place_target=SORT_TARGET[pick])
        task_str = task_description(pick)

        frames_world: list[np.ndarray] = []
        frames_wrist: list[np.ndarray] = []
        acts, ai = None, 0
        accum = 0.0
        dwell = 0
        success = False
        success_frame = -1
        n_recorded = 0

        # Prime the observation buffers before the first prediction.
        _, _, w_pol, r_pol = render_cams()

        while n_recorded < args.max_frames:
            if acts is None or ai >= len(acts):
                state = _to_np(bundle.franka.get_qpos()).reshape(-1).astype(np.float32)
                acts = runner.predict(
                    state,
                    {"observation.images.world": w_pol, "observation.images.wrist": r_pol},
                    task_str,
                )
                if args.n_action_steps > 0:
                    acts = acts[: args.n_action_steps]
                ai = 0
            action = acts[ai].astype(np.float32)
            ai += 1

            # Replay this 30 Hz action on the 100 Hz sim (3/3/4 pattern).
            accum += steps_per_frame
            n_steps = int(accum)
            accum -= n_steps
            for _ in range(n_steps):
                bundle.franka.control_dofs_position(action)
                bundle.scene.step()
                bundle.update_wrist_cam()

            w, r, w_pol, r_pol = render_cams()
            frames_world.append(w)
            frames_wrist.append(r)
            n_recorded += 1

            if check_success(bundle, task):
                dwell += 1
                if not success and dwell >= args.dwell:
                    success = True
                    success_frame = n_recorded
            else:
                dwell = 0
            if success and n_recorded >= success_frame + FPS:  # 1 s tail after success
                break

        tag = "ok" if success else "fail"
        results.append({"ep": ep, "pick": pick, "seed": seed, "success": bool(success),
                        "frames": n_recorded})
        print(f"[eval] {ep + 1}/{args.episodes} pick={pick} seed={seed} "
              f"[{'OK' if success else 'FAIL'}] frames={n_recorded}")
        save_mp4(frames_world, vdir / f"eval_ep{ep:03d}_s{seed}_{pick}_{tag}_world.mp4")
        save_mp4(frames_wrist, vdir / f"eval_ep{ep:03d}_s{seed}_{pick}_{tag}_wrist.mp4")

    n_ok = sum(r["success"] for r in results)
    print(f"\n[eval] RESULT: {n_ok}/{len(results)} = {n_ok / len(results):.1%}")
    (vdir / "summary.json").write_text(json.dumps(
        {"checkpoint": args.checkpoint, "n_action_steps": args.n_action_steps,
         "results": results, "success_rate": n_ok / len(results)}, indent=2))
    print(f"[eval] videos + summary.json -> {vdir}")


if __name__ == "__main__":
    main()
