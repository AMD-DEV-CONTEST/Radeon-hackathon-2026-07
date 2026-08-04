"""Policy-agnostic closed-loop evaluation of a trained lerobot policy.

Based on franka_fruit_pick_demo's eval_policy.py. Key changes:
- Uses color_sort's build_scene / sk_grasp_demo / randomize
- Pick objects drawn from PICKABLE_GEOMETRIES of the split colors
- Task text = "pick the <color> <geom> into the <color> bin"

Usage:
    python eval_policy.py \
        --policy-path ../outputs/train/act_train/checkpoints/010000/pretrained_model \
        --repo-id color_sort/train \
        --dataset-root ../datasets/train \
        --episodes 20 --split train
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

from build_scene import build_scene
from sk_grasp_demo import TaskSpec, check_success
from paths import EVAL_RESULTS_DIR, EVAL_VIDEOS_DIR
from randomize import EnvRandomizer, RandomizationConfig
from record_dataset import CONTROL_FPS, task_description
from scene_config import YCB_LAYOUT, get_ycb_names_for_split

STATE_KEY = "observation.state"
POST_SUCCESS_SECONDS = 0.8

MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)


@dataclass
class PolicyBundle:
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
            robot_type="franka",
        )
        return action.detach().cpu().numpy().reshape(-1).astype(np.float32)


def _load_rename_map(policy_path: str) -> dict:
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
    return np.asarray(x)


def _render_camera(cam, size_wh: tuple[int, int]) -> np.ndarray:
    img = _to_np(cam.render(rgb=True)[0])
    w, h = size_wh
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def build_observation(bundle, pb: PolicyBundle) -> dict[str, np.ndarray]:
    h, w = pb.image_hw
    obs: dict[str, np.ndarray] = {
        STATE_KEY: _to_np(bundle.franka.get_qpos()).reshape(-1).astype(np.float32),
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


def apply_action(bundle, action: np.ndarray, n_sim_steps: int) -> None:
    action = np.asarray(action, dtype=np.float64).reshape(-1)
    arm = action[:7]
    finger = action[7:9]
    # Symbolic dual semantics, matching what the expert recorded:
    #   finger < 0  -> force command (symbolic -0.04 → -12 N clamping)
    #   finger >= 0 -> position target (e.g. 0.04 open during approach/release)
    # The symbolic encoding keeps the finger value range (±0.04) consistent
    # with the v6 baseline, so normalization statistics are similar.
    # Gain = 12 / 0.04 = 300 maps symbolic -0.04 to -12 N clamping force.
    force_mask = finger < 0
    force_idx = FINGERS_DOF[force_mask]
    pos_idx = FINGERS_DOF[~force_mask]
    for _ in range(n_sim_steps):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if force_idx.size:
            bundle.franka.control_dofs_force(finger[force_mask] * 300.0, force_idx)
        if pos_idx.size:
            bundle.franka.control_dofs_position(finger[~force_mask], pos_idx)
        bundle.scene.step()
        bundle.update_wrist_cam()


@dataclass
class EpisodeResult:
    success: bool
    n_policy_steps: int = 0
    before_frame: np.ndarray | None = None
    after_frame: np.ndarray | None = None


def run_episode(
    bundle,
    pb: PolicyBundle,
    task: TaskSpec,
    *,
    task_text: str | None,
    max_seconds: float,
) -> EpisodeResult:
    pb.reset()
    steps_per_frame = CONTROL_FPS / pb.fps
    max_frames = int(round(max_seconds * pb.fps))
    result = EpisodeResult(success=False)
    accum = 0.0
    settle_frames = max(1, int(round(0.4 * pb.fps)))
    success_streak = 0
    # Capture BEFORE frame at full world-cam resolution for Qwen verifier.
    result.before_frame = _to_np(bundle.world_cam.render(rgb=True)[0]).astype(np.uint8)
    for _ in range(max_frames):
        obs = build_observation(bundle, pb)
        action = pb.select_action(obs, task_text)
        accum += steps_per_frame
        n_sub = int(accum)
        accum -= n_sub
        apply_action(bundle, action, max(1, n_sub))
        result.n_policy_steps += 1
        if check_success(bundle, task):
            success_streak += 1
            if success_streak >= settle_frames:
                result.success = True
                break
        else:
            success_streak = 0
    if not result.success:
        result.success = check_success(bundle, task)
    # Capture AFTER frame regardless of policy outcome.
    result.after_frame = _to_np(bundle.world_cam.render(rgb=True)[0]).astype(np.uint8)
    return result


def evaluate_policy(
    bundle,
    pb: PolicyBundle,
    *,
    episodes: int,
    seed: int = 1000,
    max_seconds: float = 15.0,
    ycb_names: tuple[str, ...] | None = None,
    tol: float = 0.06,
    jitter: float = 0.04,
    label: str = "",
    qwen_verifier=None,
) -> dict:
    if ycb_names is None:
        ycb_names = tuple(YCB_LAYOUT.keys())
    pick_pool = list(ycb_names)
    randomizer = EnvRandomizer(
        bundle, RandomizationConfig(pos_jitter=jitter, randomize_pick=False, seed=seed)
    )
    pick_rng = np.random.default_rng(seed)
    prefix = f"[eval:{label}]" if label else "[eval]"

    n_success = 0
    n_qwen_success = 0
    n_qwen_agree = 0
    failure_types: dict[str, int] = {}
    per_object: dict[str, list[int]] = {}
    episodes_detail: list[dict] = []
    for ep in range(episodes):
        episode_seed = seed + ep
        pick_object = str(pick_rng.choice(pick_pool))
        pick_color = YCB_LAYOUT[pick_object]["color"]
        task = TaskSpec(pick_object=pick_object, place_target=pick_color, success_tol=tol)
        task_text = task_description(pick_object, pick_color)

        try:
            randomizer.reset(seed=episode_seed)
            result = run_episode(bundle, pb, task, task_text=task_text, max_seconds=max_seconds)
        except gs.GenesisException as exc:
            n_success += 0
            per_object.setdefault(pick_object, []).append(0)
            episodes_detail.append({"ep": ep, "seed": episode_seed, "pick": pick_object, "success": False, "diverged": True})
            print(f"{prefix} ep {ep:03d} pick={pick_object} -> DIVERGED ({exc})")
            continue

        n_success += int(result.success)
        per_object.setdefault(pick_object, []).append(int(result.success))

        rec: dict = {
            "ep": ep, "seed": episode_seed, "pick": pick_object,
            "steps": result.n_policy_steps, "success": bool(result.success),
        }

        # Optional Qwen3-VL verifier.
        if qwen_verifier is not None and result.before_frame is not None and result.after_frame is not None:
            v = qwen_verifier.verify(result.before_frame, result.after_frame, task_text or "")
            rec["qwen_success"] = bool(v.get("success", False))
            rec["qwen_failure_type"] = str(v.get("failure_type", "unknown"))
            rec["qwen_confidence"] = float(v.get("confidence", 0.0))
            rec["qwen_reasoning"] = str(v.get("reasoning", ""))
            n_qwen_success += int(rec["qwen_success"])
            n_qwen_agree += int(rec["qwen_success"] == result.success)
            ft = rec["qwen_failure_type"]
            failure_types[ft] = failure_types.get(ft, 0) + 1
            qtag = "Q+ " if rec["qwen_success"] else "Q- "
        else:
            qtag = ""

        episodes_detail.append(rec)
        qstr = qtag + (f"Q:{rec['qwen_failure_type']} " if qwen_verifier else "")
        print(f"{prefix} ep {ep:03d} pick={pick_object} steps={result.n_policy_steps} -> success={result.success} {qstr}")

    rate = n_success / max(1, episodes)
    print(f"{prefix} success rate: {n_success}/{episodes} = {rate:.1%}")
    if qwen_verifier is not None:
        qrate = n_qwen_success / max(1, episodes)
        agree_rate = n_qwen_agree / max(1, episodes)
        print(f"{prefix} qwen rate: {n_qwen_success}/{episodes} = {qrate:.1%} (agree {n_qwen_agree}/{episodes} = {agree_rate:.1%})")
        if failure_types:
            print(f"{prefix} qwen failure_types: {failure_types}")
    per_object_summary = {
        obj: {"n": len(hits), "success": int(sum(hits)), "rate": sum(hits) / len(hits)}
        for obj, hits in sorted(per_object.items())
    }
    if len(per_object_summary) > 1:
        for obj, s in per_object_summary.items():
            print(f"{prefix}   {obj}: {s['success']}/{s['n']} = {s['rate']:.1%}")

    out = {
        "episodes": episodes,
        "n_success": n_success,
        "success_rate": rate,
        "per_object": per_object_summary,
        "episodes_detail": episodes_detail,
        "params": {"seed": seed, "max_seconds": max_seconds, "split_colors": list(split_colors), "tol": tol, "jitter": jitter},
    }
    if qwen_verifier is not None:
        out["qwen"] = {
            "n_qwen_success": n_qwen_success,
            "qwen_success_rate": n_qwen_success / max(1, episodes),
            "agree_rate": n_qwen_agree / max(1, episodes),
            "failure_types": failure_types,
        }
    return out


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
    parser = argparse.ArgumentParser(description="Policy-agnostic closed-loop eval.")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--use-amp", action="store_true")
    parser.add_argument("--rename-map", default=None)
    parser.add_argument("-c", "--cpu", action="store_true")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--split", choices=["train", "eval", "all"], default="train")
    parser.add_argument("--tol", type=float, default=0.06)
    parser.add_argument("--jitter", type=float, default=0.03)
    parser.add_argument("--results-out", default=None)
    parser.add_argument("--qwen-verify", action="store_true",
                        help="Enable Qwen3-VL episode-end verifier (Stage C2).")
    args = parser.parse_args()

    ycb_names = get_ycb_names_for_split(args.split)

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(ycb_names=ycb_names)

    rename_map = json.loads(args.rename_map) if args.rename_map else None
    pb = load_policy(
        args.policy_path, args.repo_id, args.dataset_root,
        args.device, use_amp=args.use_amp, rename_map=rename_map,
    )

    qwen_verifier = None
    if args.qwen_verify:
        from qwen_verifier import Qwen3VLVerifier
        print("[eval] loading Qwen3-VL-8B verifier ...")
        qwen_verifier = Qwen3VLVerifier().load()
        print(f"[eval] Qwen verifier loaded ({qwen_verifier.last_inference_ms:.0f}ms cold start)")

    results = evaluate_policy(
        bundle, pb,
        episodes=args.episodes, seed=args.seed, max_seconds=args.max_seconds,
        ycb_names=ycb_names, tol=args.tol, jitter=args.jitter,
        label=f"{pb.policy_type}_{checkpoint_label(args.policy_path)}",
        qwen_verifier=qwen_verifier,
    )

    results["meta"] = {
        "policy_path": args.policy_path,
        "policy_type": pb.policy_type,
        "checkpoint": checkpoint_label(args.policy_path),
        "repo_id": args.repo_id,
        "dataset_root": args.dataset_root,
        "device": str(pb.device),
        "split": args.split,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    if args.results_out != "none":
        out = Path(args.results_out) if args.results_out else (
            EVAL_RESULTS_DIR / args.repo_id.split("/")[-1] / f"{checkpoint_label(args.policy_path)}.json"
        )
        write_results(results, out)


if __name__ == "__main__":
    main()