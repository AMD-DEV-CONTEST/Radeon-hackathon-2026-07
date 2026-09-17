"""
Closed-loop BC evaluation for Franka Panda in Genesis.

Adapted from 05_sim_evaluation/scripts/22_bc_act_eval.py for Franka 7-DOF.
Supports:
  - MLP BC (state-only, joint-position action space)
  - E1 N-step GT action correction (--n-step-correction N)
  - Warm-start from dataset (--warm-start-from-dataset)

Usage:
  python 03_eval.py \
    --checkpoint output/train/smolvla_pick/final \
    --dataset-id local/franka-genesis-pick \
    --n-episodes 10 --max-steps 150
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from vision_utils import ablate_camera, augment_image, resolve_domain_randomization


# ---- constants (must match 01_franka_pick_data.py) ----
JOINT_NAMES = [
    "joint1", "joint2", "joint3", "joint4",
    "joint5", "joint6", "joint7",
    "finger_joint1", "finger_joint2",
]
HOME_QPOS = np.array([0, -0.3, 0, -2.2, 0, 2.0, 0.79, 0.04, 0.04], dtype=np.float32)
KP = np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100], dtype=np.float32)
KV = np.array([450, 450, 350, 350, 200, 200, 200, 10, 10], dtype=np.float32)
FORCE_LOWER = np.array([-87, -87, -87, -87, -12, -12, -12, -100, -100], dtype=np.float32)
FORCE_UPPER = np.array([87, 87, 87, 87, 12, 12, 12, 100, 100], dtype=np.float32)
CUBE_SIZE = (0.04, 0.04, 0.04)


def ensure_display():
    if os.environ.get("DISPLAY"):
        return
    xvfb = subprocess.run(["which", "Xvfb"], capture_output=True)
    if xvfb.returncode != 0:
        return
    proc = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-ac", "+extension", "GLX"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    time.sleep(2)
    if proc.poll() is None:
        print(f"[display] Xvfb started (PID={proc.pid})")


def to_numpy(t):
    arr = t.cpu().numpy() if hasattr(t, "cpu") else np.array(t)
    return arr[0] if arr.ndim > 1 else arr


def render_cam(cam):
    rgb, _, _, _ = cam.render(rgb=True, depth=False, segmentation=False, normal=False)
    arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
    if arr.ndim == 4:
        arr = arr[0]
    return arr.astype(np.uint8)


def smooth_action(prev, target, max_delta=0.15):
    """Clamp per-joint change to max_delta (radians)."""
    delta = np.clip(target - prev, -max_delta, max_delta)
    return prev + delta


def _write_video(path, frames, fps=30):
    """Write list of uint8 HWC numpy arrays to MP4 via ffmpeg subprocess."""
    if not frames:
        return
    h, w = frames[0].shape[:2]
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "23",
        str(path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()


# ---- MLP BC (must match 04_train_bc.py) ----
class MLPBCPolicy(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dims=(256, 256)):
        super().__init__()
        layers = []
        prev = state_dim
        for h in hidden_dims:
            layers += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        layers.append(nn.Linear(prev, action_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, state):
        return self.net(state)


class MLPBCChunkPolicy(nn.Module):
    def __init__(self, state_dim, action_dim, chunk_size, hidden_dims=(256, 256)):
        super().__init__()
        self.chunk_size = chunk_size
        self.action_dim = action_dim
        layers = []
        prev = state_dim
        for h in hidden_dims:
            layers += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        layers.append(nn.Linear(prev, chunk_size * action_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, state):
        return self.net(state).view(-1, self.chunk_size, self.action_dim)


def main():
    ap = argparse.ArgumentParser(description="Franka closed-loop BC/ACT eval")
    ap.add_argument("--policy-type", default="bc", choices=["bc", "act", "smolvla"])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--dataset-id", default="local/franka-genesis-pick")
    ap.add_argument("--n-episodes", type=int, default=10)
    ap.add_argument("--max-steps", type=int, default=150)
    ap.add_argument("--action-horizon", type=int, default=1)
    ap.add_argument("--max-delta-rad", type=float, default=0.15,
                    help="Max per-joint change per step (radians)")
    ap.add_argument("--cube-x-min", type=float, default=0.4)
    ap.add_argument("--cube-x-max", type=float, default=0.7)
    ap.add_argument("--cube-y-min", type=float, default=-0.2)
    ap.add_argument("--cube-y-max", type=float, default=0.2)
    ap.add_argument("--success-lift-m", type=float, default=0.02)
    ap.add_argument("--success-sustain", type=int, default=8)
    ap.add_argument("--success-final-m", type=float, default=0.01)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cube-friction", type=float, default=1.5)
    ap.add_argument("--warm-start-from-dataset", action="store_true")
    ap.add_argument("--warm-start-frame", type=int, default=0)
    ap.add_argument("--episode-labels", type=str, default=None)
    ap.add_argument("--n-step-correction", type=int, default=0)
    ap.add_argument("--prefix-gt-steps", type=int, default=0,
                    help="Inject GT action for the first K steps only, then free-fly "
                         "(0=disabled, requires --warm-start-from-dataset)")
    ap.add_argument("--output-dir", default="./output")
    ap.add_argument("--run-name", default="franka_eval",
                    help="Subfolder under output-dir/eval/ for this run")
    ap.add_argument("--record-video", action="store_true")
    ap.add_argument("--task", type=str, default="Pick up the red cube.",
                    help="Language instruction for VLA models (e.g. SmolVLA)")
    ap.add_argument("--domain-randomization", action="store_true",
                    help="Enable default brightness and sensor-noise perturbations")
    ap.add_argument("--image-noise-std", type=float, default=0.0,
                    help="RGB Gaussian noise standard deviation in pixel values")
    ap.add_argument("--brightness-range", type=float, nargs=2, default=None,
                    metavar=("MIN", "MAX"),
                    help="Per-episode image brightness multiplier range")
    ap.add_argument("--camera-ablation", default="both",
                    choices=["both", "overhead_only", "wrist_only"],
                    help="Mask one visual input while keeping the policy schema unchanged")
    ap.add_argument("--camera-ablation-fill", type=float, default=127.5,
                    help="Neutral pixel value used for the masked camera")
    ap.add_argument("--no-bbox-detection", action="store_true",
                    help="Disable box_box_detection (workaround for AMD LLVM fatal)")
    ap.add_argument("--camera-layout", type=str, default="up_side",
                    choices=["up_side", "up_wrist"],
                    help="Camera layout matching training data.")
    ap.add_argument("--wrist-cam-pos", type=float, nargs=3, default=[0.05, 0.0, -0.08],
                    help="Wrist cam pos (x,y,z) in hand-link frame")
    ap.add_argument("--wrist-cam-lookat", type=float, nargs=3, default=[0.0, 0.0, 0.10],
                    help="Wrist cam lookat (x,y,z) in hand-link frame")
    ap.add_argument("--wrist-cam-up", type=float, nargs=3, default=[0.0, 0.0, -1.0],
                    help="Wrist cam up vector in hand-link frame")
    ap.add_argument("--wrist-cam-fov", type=float, default=65.0)
    args = ap.parse_args()

    args.image_noise_std, args.brightness_range = resolve_domain_randomization(
        args.domain_randomization,
        args.image_noise_std,
        tuple(args.brightness_range) if args.brightness_range else None,
    )

    ensure_display()
    import genesis as gs

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")

    # ---- load policy ----
    policy_type = args.policy_type
    goal_extra_dims = 0  # extra dims in observation beyond n_dofs (e.g. cube_xy)

    if policy_type == "bc":
        ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
        cfg = ckpt["config"]
        state_dim = cfg["state_dim"]
        action_dim = cfg["action_dim"]
        hidden_dims = tuple(cfg["hidden_dims"])
        chunk_size = cfg.get("chunk_size", 1)
        history_steps = cfg.get("history_steps", 0)

        if state_dim > action_dim:
            goal_extra_dims = state_dim - action_dim
            print(f"[eval] goal conditioning detected: state_dim={state_dim} > action_dim={action_dim} "
                  f"(extra {goal_extra_dims} dims)")

        input_dim = state_dim * (2 * history_steps + 1)
        if chunk_size > 1:
            bc_policy = MLPBCChunkPolicy(input_dim, action_dim, chunk_size, hidden_dims)
        else:
            bc_policy = MLPBCPolicy(input_dim, action_dim, hidden_dims)
        bc_policy.load_state_dict(ckpt["model_state_dict"])
        bc_policy.eval().to(device)

        stats = ckpt["stats"]
        bc_stats = {
            "state_mean": torch.tensor(stats["state_mean"], dtype=torch.float32, device=device),
            "state_std": torch.tensor(stats["state_std"], dtype=torch.float32, device=device).clamp(min=1e-6),
            "action_mean": torch.tensor(stats["action_mean"], dtype=torch.float32, device=device),
            "action_std": torch.tensor(stats["action_std"], dtype=torch.float32, device=device).clamp(min=1e-6),
        }
        total_params = sum(p.numel() for p in bc_policy.parameters())
        print(f"[eval] BC loaded: {total_params:,} params, hidden={hidden_dims}, "
              f"chunk={chunk_size}, history={history_steps}")

        prev_states = []  # history buffer for eval

        @torch.no_grad()
        def predict(state_np):
            if history_steps > 0:
                prev_states.append(state_np.copy())
                s_t = state_np
                parts = [s_t]
                for k in range(1, history_steps + 1):
                    idx = max(0, len(prev_states) - 1 - k)
                    parts.append(prev_states[idx])
                for k in range(1, history_steps + 1):
                    idx_cur = max(0, len(prev_states) - k)
                    idx_prev = max(0, len(prev_states) - 1 - k)
                    parts.append(prev_states[idx_cur] - prev_states[idx_prev])
                full_input = np.concatenate(parts)
                state_t = torch.from_numpy(full_input).unsqueeze(0).float().to(device)
                # normalize: state blocks with (mean, std), delta blocks with (0, std)
                chunks_list = state_t.split(state_dim, dim=-1)
                normed = []
                n_state_blocks = history_steps + 1
                for i, c in enumerate(chunks_list):
                    if i < n_state_blocks:
                        normed.append((c - bc_stats["state_mean"]) / bc_stats["state_std"])
                    else:
                        normed.append(c / bc_stats["state_std"])
                s_norm = torch.cat(normed, dim=-1)
            else:
                state_t = torch.from_numpy(state_np).unsqueeze(0).float().to(device)
                s_norm = (state_t - bc_stats["state_mean"]) / bc_stats["state_std"]
            pred_norm = bc_policy(s_norm)
            pred = pred_norm * bc_stats["action_std"] + bc_stats["action_mean"]
            out = pred.squeeze(0).cpu().numpy()
            if out.ndim == 1:
                out = out[np.newaxis, :]
            return out

    elif policy_type == "act":
        try:
            from lerobot.configs.types import FeatureType
            from lerobot.common.datasets.lerobot_dataset import LeRobotDatasetMetadata
            from lerobot.common.datasets.utils import dataset_to_policy_features
            from lerobot.policies.act.configuration_act import ACTConfig
            from lerobot.policies.act.modeling_act import ACTPolicy
            from lerobot.policies.factory import make_pre_post_processors
        except ImportError:
            from lerobot.configs.types import FeatureType
            from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
            from lerobot.datasets.utils import dataset_to_policy_features
            from lerobot.policies.act.configuration_act import ACTConfig
            from lerobot.policies.act.modeling_act import ACTPolicy
            from lerobot.policies.factory import make_pre_post_processors

        dataset_metadata = LeRobotDatasetMetadata(args.dataset_id)
        features = dataset_to_policy_features(dataset_metadata.features)
        output_features = {k: ft for k, ft in features.items() if ft.type is FeatureType.ACTION}
        input_features = {k: ft for k, ft in features.items() if k not in output_features}

        ckpt_dir = Path(args.checkpoint)
        config_path = ckpt_dir / "config.json"
        saved_cfg = {}
        if config_path.exists():
            import json as _json
            saved_cfg = _json.loads(config_path.read_text(encoding="utf-8"))
        chunk_size = saved_cfg.get("chunk_size", 10)

        cfg = ACTConfig(
            input_features=input_features,
            output_features=output_features,
            chunk_size=chunk_size,
            n_action_steps=chunk_size,
            n_obs_steps=1,
            dim_model=saved_cfg.get("dim_model", 256),
            n_heads=saved_cfg.get("n_heads", 8),
            n_encoder_layers=saved_cfg.get("n_encoder_layers", 4),
            n_decoder_layers=saved_cfg.get("n_decoder_layers", 1),
        )
        act_policy = ACTPolicy(cfg)
        try:
            loaded = ACTPolicy.from_pretrained(str(ckpt_dir))
            act_policy.load_state_dict(loaded.state_dict(), strict=False)
        except Exception as e:
            print(f"[eval] from_pretrained failed ({e}), loading safetensors directly")
            from safetensors.torch import load_file
            st = load_file(str(ckpt_dir / "model.safetensors"))
            act_policy.load_state_dict(st, strict=False)
        act_policy.eval().to(device)

        preprocessor, postprocessor = make_pre_post_processors(
            cfg, dataset_stats=dataset_metadata.stats)

        act_needs_images = any("image" in k for k in input_features)
        act_state_shape = None
        for k, ft in input_features.items():
            if k == "observation.state":
                act_state_shape = ft.shape
                break
        if act_state_shape is not None:
            act_state_dim = act_state_shape[0] if isinstance(act_state_shape, (tuple, list)) else act_state_shape
            if act_state_dim > len(JOINT_NAMES):
                goal_extra_dims = act_state_dim - len(JOINT_NAMES)
                print(f"[eval] ACT goal conditioning: state_dim={act_state_dim}, "
                      f"extra {goal_extra_dims} dims (cube_xy)")
        total_params = sum(p.numel() for p in act_policy.parameters())
        print(f"[eval] ACT loaded: {total_params:,} params, chunk_size={chunk_size}, "
              f"needs_images={act_needs_images}")

        @torch.no_grad()
        def predict(state_np, images=None):
            obs = {"observation.state": torch.from_numpy(state_np).unsqueeze(0).float().to(device)}
            if images:
                for k, img in images.items():
                    img_t = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(device) / 255.0
                    obs[k] = img_t
            obs = preprocessor(obs)
            raw = act_policy.select_action(obs)
            raw = postprocessor(raw)
            if isinstance(raw, dict):
                actions = raw["action"]
            else:
                actions = raw
            actions = actions.detach().cpu().numpy()
            if actions.ndim == 3:
                actions = actions[0]
            elif actions.ndim == 1:
                actions = actions[np.newaxis, :]
            return actions

    elif policy_type == "smolvla":
        try:
            from lerobot.configs.types import FeatureType
            from lerobot.common.datasets.lerobot_dataset import LeRobotDatasetMetadata
            from lerobot.common.datasets.utils import dataset_to_policy_features
            from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            from lerobot.policies.factory import make_pre_post_processors
        except ImportError:
            from lerobot.configs.types import FeatureType
            from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
            from lerobot.datasets.utils import dataset_to_policy_features
            from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            from lerobot.policies.factory import make_pre_post_processors

        dataset_metadata = LeRobotDatasetMetadata(args.dataset_id)
        features = dataset_to_policy_features(dataset_metadata.features)
        output_features = {k: ft for k, ft in features.items() if ft.type is FeatureType.ACTION}
        input_features = {k: ft for k, ft in features.items() if k not in output_features}

        ckpt_dir = Path(args.checkpoint)
        config_path = ckpt_dir / "config.json"
        saved_cfg = {}
        if config_path.exists():
            import json as _json
            saved_cfg = _json.loads(config_path.read_text(encoding="utf-8"))
        chunk_size = saved_cfg.get("chunk_size", 50)

        cfg = SmolVLAConfig(
            input_features=input_features,
            output_features=output_features,
            chunk_size=chunk_size,
            n_action_steps=chunk_size,
            # Keep evaluation offline and consistent with training. Without this
            # explicit local path, SmolVLA falls back to Hugging Face downloads.
            vlm_model_name="/workspace/models/SmolVLM2-500M-Video-Instruct",
        )
        try:
            vla_policy = SmolVLAPolicy.from_pretrained(str(ckpt_dir), config=cfg, strict=False)
        except Exception as e:
            print(f"[eval] from_pretrained failed ({e}), trying safetensors")
            from safetensors.torch import load_file
            vla_policy = SmolVLAPolicy(cfg)
            st = load_file(str(ckpt_dir / "model.safetensors"))
            vla_policy.load_state_dict(st, strict=False)
        vla_policy.eval().to(device)

        preprocessor, postprocessor = make_pre_post_processors(
            cfg, dataset_stats=dataset_metadata.stats)

        vla_state_shape = None
        for k, ft in input_features.items():
            if k == "observation.state":
                vla_state_shape = ft.shape
                break
        if vla_state_shape is not None:
            vla_state_dim = vla_state_shape[0] if isinstance(vla_state_shape, (tuple, list)) else vla_state_shape
            if vla_state_dim > len(JOINT_NAMES):
                goal_extra_dims = vla_state_dim - len(JOINT_NAMES)
                print(f"[eval] SmolVLA goal conditioning: state_dim={vla_state_dim}, "
                      f"extra {goal_extra_dims} dims")

        total_params = sum(p.numel() for p in vla_policy.parameters())
        print(f"[eval] SmolVLA loaded: {total_params:,} params, chunk_size={chunk_size}")

        vla_task = args.task
        print(f"[eval] SmolVLA task instruction: '{vla_task}'")

        @torch.no_grad()
        def predict(state_np, images=None):
            obs = {
                "observation.state": torch.from_numpy(state_np).unsqueeze(0).float().to(device),
                "task": [vla_task],
            }
            if images:
                for k, img in images.items():
                    img_t = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(device) / 255.0
                    obs[k] = img_t
            obs = preprocessor(obs)
            raw = vla_policy.select_action(obs)
            raw = postprocessor(raw)
            if isinstance(raw, dict):
                actions = raw["action"]
            else:
                actions = raw
            actions = actions.detach().cpu().numpy()
            if actions.ndim == 3:
                actions = actions[0]
            elif actions.ndim == 1:
                actions = actions[np.newaxis, :]
            return actions

    # ---- warm-start / GT trajectories ----
    warm_start_episodes = None
    gt_trajectories = None
    if args.warm_start_from_dataset:
        try:
            from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
        except ImportError:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset

        if not args.episode_labels:
            print("[error] --episode-labels required for warm-start"); sys.exit(1)
        episode_labels = json.loads(Path(args.episode_labels).read_text(encoding="utf-8"))
        success_labels = [e for e in episode_labels if e.get("success")]
        ds = LeRobotDataset(args.dataset_id)
        if hasattr(ds, "episode_data_index"):
            ep_from = {i: ds.episode_data_index["from"][i].item() for i in range(ds.num_episodes)}
            ep_to = {i: ds.episode_data_index["to"][i].item() for i in range(ds.num_episodes)}
        else:
            fpe = len(ds) // ds.num_episodes
            ep_from = {i: i * fpe for i in range(ds.num_episodes)}
            ep_to = {i: (i+1) * fpe for i in range(ds.num_episodes)}

        warm_start_episodes = []
        gt_traj_list = [] if args.n_step_correction > 0 else None
        chosen = success_labels[:args.n_episodes]
        for lab in chosen:
            ep_id = lab["episode_index"]
            cx, cy = lab["cube_xy"]
            frame_idx = ep_from[ep_id] + args.warm_start_frame
            frame = ds[frame_idx]
            state = frame["observation.state"].cpu().numpy().astype(np.float32)
            warm_start_episodes.append({
                "episode_id": ep_id, "cube_xy": (cx, cy), "init_state": state,
            })
            if args.n_step_correction > 0:
                ep_actions = []
                for f_idx in range(ep_from[ep_id], ep_to[ep_id]):
                    ep_actions.append(ds[f_idx]["action"].cpu().numpy().astype(np.float32))
                gt_traj_list.append(ep_actions)
        gt_trajectories = gt_traj_list
        print(f"[eval] warm-start: {len(warm_start_episodes)} episodes, frame={args.warm_start_frame}")

    # ---- build Genesis scene ----
    gs.init(backend=(gs.cpu if args.cpu else gs.gpu), logging_level="warning")
    cube_z = CUBE_SIZE[2] / 2.0
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / args.fps, substeps=4),
        rigid_options=gs.options.RigidOptions(
            enable_collision=True, enable_joint_limit=True,
            box_box_detection=(not args.no_bbox_detection),
        ),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    cube = scene.add_entity(
        morph=gs.morphs.Box(size=CUBE_SIZE, pos=(0.55, 0.0, cube_z)),
        material=gs.materials.Rigid(friction=args.cube_friction),
        surface=gs.surfaces.Default(color=(1.0, 0.3, 0.3, 1.0)),
    )
    franka = scene.add_entity(
        gs.morphs.MJCF(file="xml/franka_emika_panda/panda.xml"),
    )
    cam_up = scene.add_camera(
        res=(640, 480), pos=(0.55, 0.55, 0.55),
        lookat=(0.55, 0.0, 0.10), fov=45, GUI=False,
    )
    if args.camera_layout == "up_side":
        cam_side = scene.add_camera(
            res=(640, 480), pos=(0.55, -0.55, cube_z + 0.25),
            lookat=(0.55, 0.0, cube_z + 0.10), fov=50, GUI=False,
        )
    else:
        cam_side = scene.add_camera(
            res=(640, 480),
            pos=tuple(args.wrist_cam_pos),
            lookat=tuple(args.wrist_cam_lookat),
            fov=args.wrist_cam_fov, GUI=False,
        )
    scene.build()
    _needs_images = policy_type in ("act", "smolvla")

    motors_dof = [franka.get_joint(name).dofs_idx_local[0] for name in JOINT_NAMES]
    n_dofs = len(JOINT_NAMES)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)

    if args.camera_layout == "up_wrist":
        from genesis.utils.geom import pos_lookat_up_to_T
        end_effector = franka.get_link("hand")
        wrist_pos = torch.tensor(args.wrist_cam_pos, dtype=gs.tc_float, device=gs.device)
        wrist_lookat = torch.tensor(args.wrist_cam_lookat, dtype=gs.tc_float, device=gs.device)
        wrist_up = torch.tensor(args.wrist_cam_up, dtype=gs.tc_float, device=gs.device)
        wrist_offset_T = pos_lookat_up_to_T(wrist_pos, wrist_lookat, wrist_up)
        try:
            cam_side.attach(rigid_link=end_effector, offset_T=wrist_offset_T)
        except TypeError:
            cam_side.attach(end_effector, wrist_offset_T)

    def reset_scene(cx, cy, init_state=None):
        init_q = init_state if init_state is not None else HOME_QPOS
        franka.set_dofs_position(init_q, motors_dof)
        franka.control_dofs_position(init_q, motors_dof)
        franka.zero_all_dofs_velocity()
        cube.set_pos(
            torch.tensor([cx, cy, cube_z], dtype=torch.float32,
                         device=gs.device).unsqueeze(0))
        cube.set_quat(
            torch.tensor([1, 0, 0, 0], dtype=torch.float32,
                         device=gs.device).unsqueeze(0))
        cube.zero_all_dofs_velocity()
        for _ in range(args.settle_steps):
            scene.step()

    # ---- build episode init list ----
    episode_inits = []
    if warm_start_episodes is not None:
        for i, ws in enumerate(warm_start_episodes):
            cx, cy = ws["cube_xy"]
            episode_inits.append((cx, cy, f"ep{i:03d}_ws{ws['episode_id']}", ws["init_state"]))
        args.n_episodes = len(episode_inits)
    else:
        rng = random.Random(args.seed)
        for ep in range(args.n_episodes):
            cx = rng.uniform(args.cube_x_min, args.cube_x_max)
            cy = rng.uniform(args.cube_y_min, args.cube_y_max)
            episode_inits.append((cx, cy, f"ep{ep:03d}", None))

    mode_str = "WARM-START" if warm_start_episodes else "HOME-START"
    print(f"\n[eval] {args.n_episodes} episodes (mode={mode_str})")
    if args.n_step_correction > 0:
        print(f"  n_step_correction={args.n_step_correction}")
    if args.prefix_gt_steps > 0:
        print(f"  prefix_gt_steps={args.prefix_gt_steps}")

    save_dir = Path(args.output_dir) / "eval" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)

    # ---- episode loop ----
    all_results = []
    for ep_idx, (cx, cy, label, init_state) in enumerate(episode_inits):
        image_rng = np.random.default_rng(args.seed + 100_000 + ep_idx)
        if args.brightness_range is None:
            brightness = 1.0
        else:
            brightness = float(image_rng.uniform(*args.brightness_range))
        print(f"\n{'='*60}")
        print(f"[ep {ep_idx+1}/{args.n_episodes}] cube=({cx:.3f},{cy:.3f}) "
              f"init={'warm-start' if init_state is not None else 'HOME'}")

        reset_scene(cx, cy, init_state)
        base_z = cube_z
        cube_z_hist = []
        _rec_frames_up, _rec_frames_side = [], []
        current = init_state[:n_dofs].copy() if init_state is not None else HOME_QPOS.copy()
        if policy_type == "bc":
            prev_states.clear()
        action_queue = []
        replan_count = 0

        for step in range(args.max_steps):
            state = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            cube_pos = to_numpy(cube.get_pos())
            cube_z_hist.append(float(cube_pos[2]))

            if goal_extra_dims > 0:
                extras = cube_pos[:2].astype(np.float32) if goal_extra_dims >= 2 else np.array([], dtype=np.float32)
                if goal_extra_dims > len(extras):
                    phase = np.array([(step + 1) / args.max_steps], dtype=np.float32)
                    extras = np.concatenate([extras, phase])
                state = np.concatenate([state, extras[:goal_extra_dims]])

            if len(action_queue) == 0:
                images = None
                if _needs_images:
                    images = {
                        "observation.images.up": ablate_camera(
                            augment_image(render_cam(cam_up), image_rng,
                                          args.image_noise_std, brightness),
                            "overhead", args.camera_ablation,
                            args.camera_ablation_fill),
                        "observation.images.side": ablate_camera(
                            augment_image(render_cam(cam_side), image_rng,
                                          args.image_noise_std, brightness),
                            "wrist" if args.camera_layout == "up_wrist" else "side",
                            args.camera_ablation,
                            args.camera_ablation_fill),
                    }
                chunk = predict(state) if not _needs_images else predict(state, images)
                n_use = min(args.action_horizon, len(chunk))
                action_queue = [chunk[i, :n_dofs] for i in range(n_use)]
                replan_count += 1

            target_raw = action_queue.pop(0)

            use_gt = False
            if (args.prefix_gt_steps > 0
                    and gt_trajectories is not None
                    and step < args.prefix_gt_steps):
                use_gt = True
            elif (args.n_step_correction > 0
                    and gt_trajectories is not None
                    and step % args.n_step_correction == 0):
                use_gt = True

            if use_gt:
                gt_traj = gt_trajectories[ep_idx]
                gt_frame = args.warm_start_frame + step
                if gt_frame < len(gt_traj):
                    target_raw = gt_traj[gt_frame][:n_dofs]

            target = smooth_action(current, target_raw, args.max_delta_rad)
            current = target.copy()

            franka.control_dofs_position(target, motors_dof)
            scene.step()

            if args.record_video:
                frame_up = ablate_camera(
                    augment_image(render_cam(cam_up), image_rng,
                                  args.image_noise_std, brightness),
                    "overhead", args.camera_ablation, args.camera_ablation_fill)
                frame_side = ablate_camera(
                    augment_image(render_cam(cam_side), image_rng,
                                  args.image_noise_std, brightness),
                    "wrist" if args.camera_layout == "up_wrist" else "side",
                    args.camera_ablation, args.camera_ablation_fill)
                _rec_frames_up.append(frame_up)
                _rec_frames_side.append(frame_side)

        # ---- evaluate ----
        lifted = [z >= base_z + args.success_lift_m for z in cube_z_hist]
        sustain = sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)

        cz_max = max(cube_z_hist) if cube_z_hist else base_z
        cz_end = cube_z_hist[-1] if cube_z_hist else base_z
        success = (
            (cz_max - base_z) >= args.success_lift_m
            and sustain_max >= args.success_sustain
            and (cz_end - base_z) >= args.success_final_m
        )

        result = {
            "episode": ep_idx, "label": label,
            "cube_xy": [cx, cy], "success": success,
            "max_lift_m": float(cz_max - base_z),
            "end_lift_m": float(cz_end - base_z),
            "sustain_frames": sustain_max,
            "replan_count": replan_count,
        }
        all_results.append(result)
        status = "SUCCESS" if success else "FAIL"
        print(f"  [{status}] lift={cz_max-base_z:.4f}m end={cz_end-base_z:.4f}m "
              f"sustain={sustain_max}")

        if args.record_video and _rec_frames_up:
            vid_dir = save_dir / "videos"
            vid_dir.mkdir(parents=True, exist_ok=True)
            tag = "ok" if success else "fail"
            for cam_name, frames in [("up", _rec_frames_up), ("side", _rec_frames_side)]:
                vpath = vid_dir / f"ep{ep_idx:03d}_{tag}_{cam_name}.mp4"
                _write_video(vpath, frames, fps=30)
                print(f"  -> video: {vpath}")

    n_success = sum(1 for r in all_results if r["success"])
    sr = n_success / max(len(all_results), 1)
    print(f"\n{'='*60}")
    print(f"[eval] RESULT: {n_success}/{len(all_results)} = {sr:.0%}")

    summary = {
        "n_episodes": len(all_results),
        "n_success": n_success,
        "success_rate": sr,
        "n_step_correction": args.n_step_correction,
        "prefix_gt_steps": args.prefix_gt_steps,
        "warm_start": args.warm_start_from_dataset,
        "checkpoint": args.checkpoint,
        "camera_layout": args.camera_layout,
        "camera_ablation": args.camera_ablation,
        "camera_ablation_fill": float(args.camera_ablation_fill),
        "cube_friction": args.cube_friction,
        "domain_randomization": {
            "image_noise_std": float(args.image_noise_std),
            "brightness_range": list(args.brightness_range) if args.brightness_range else [1.0, 1.0],
        },
        "results": all_results,
    }
    (save_dir / "eval_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[eval] saved → {save_dir / 'eval_summary.json'}")


if __name__ == "__main__":
    main()
