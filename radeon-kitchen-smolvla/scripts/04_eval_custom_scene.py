"""
Closed-loop SmolVLA evaluation in a custom 3D scene (Genesis).

Extends 03_eval.py (flat-plane scene) with support for custom scenes
loaded via pick_common.build_scene().

Default: rustic_kitchen scene with floor_origin anchor.

Usage:
    python 04_eval_custom_scene.py \
        --policy-type smolvla \
        --checkpoint output/train/smolvla_kitchen_wrist/final \
        --dataset-id local/kitchen-pick \
        --n-episodes 10 --max-steps 150 --seed 99 \
        --record-video
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from vision_utils import (
    ablate_camera,
    apply_occlusion,
    apply_random_camera_dropout,
    augment_image,
    resolve_domain_randomization,
)


# ---------------------------------------------------------------------------
# Ensure sibling modules are importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ---------------------------------------------------------------------------
# Helpers (same as 03_eval.py)
# ---------------------------------------------------------------------------
def smooth_action(prev, target, max_delta=0.15):
    delta = np.clip(target - prev, -max_delta, max_delta)
    return prev + delta


def _write_video(path, frames, fps=30):
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


# ---------------------------------------------------------------------------
# MLP BC policies (same as 03_eval.py, kept for compatibility)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Custom-scene closed-loop eval (SmolVLA / ACT / BC)")

    # Policy args
    ap.add_argument("--policy-type", default="smolvla",
                    choices=["bc", "act", "smolvla"])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--dataset-id", default="local/kitchen-pick")
    ap.add_argument("--task", default="Pick up the red cube.")
    ap.add_argument("--domain-randomization", action="store_true",
                    help="Enable default brightness and sensor-noise perturbations")
    ap.add_argument("--image-noise-std", type=float, default=0.0)
    ap.add_argument("--brightness-range", type=float, nargs=2, default=None,
                    metavar=("MIN", "MAX"))
    ap.add_argument("--camera-ablation", default="both",
                    choices=["both", "overhead_only", "wrist_only"],
                    help="Mask one visual input while keeping the policy schema unchanged")
    ap.add_argument("--camera-ablation-fill", type=float, default=127.5)
    ap.add_argument("--camera-dropout-prob", type=float, default=0.0,
                    help="Per-observation probability of masking one camera")
    ap.add_argument("--camera-dropout-fill", type=float, default=127.5,
                    help="Neutral pixel value used for random camera dropout")
    ap.add_argument("--occlusion-prob", type=float, default=0.0,
                    help="Per-observation probability of a rectangular camera occlusion")
    ap.add_argument("--occlusion-fraction", type=float, default=0.25,
                    help="Occlusion side length as a fraction of image dimensions")
    ap.add_argument("--occlusion-fill", type=float, default=0.0,
                    help="Pixel value used for synthetic occlusion")

    # Eval args
    ap.add_argument("--n-episodes", type=int, default=10)
    ap.add_argument("--max-steps", type=int, default=150)
    ap.add_argument("--action-horizon", type=int, default=1)
    ap.add_argument("--max-delta-rad", type=float, default=0.15)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--action-delay-steps", type=int, default=0,
                    help="Delay physical action execution by this many control steps")
    ap.add_argument("--uncertainty-samples", type=int, default=0,
                    help="Extra visual perturbation passes for action disagreement")
    ap.add_argument("--uncertainty-noise-std", type=float, default=2.0,
                    help="RGB noise used for uncertainty passes")
    ap.add_argument("--uncertainty-threshold", type=float, default=0.03,
                    help="Mean first-action joint std that marks an observation uncertain")
    ap.add_argument("--uncertainty-slowdown", type=float, default=0.5,
                    help="Max-delta multiplier while uncertainty is high")
    ap.add_argument("--uncertainty-replan", action="store_true",
                    help="Use one action step instead of a full chunk when uncertain")

    # Success criteria
    ap.add_argument("--success-lift-m", type=float, default=0.02)
    ap.add_argument("--success-sustain", type=int, default=8)
    ap.add_argument("--success-final-m", type=float, default=0.01)

    # Output
    ap.add_argument("--output-dir", default="./output")
    ap.add_argument("--run-name", default="kitchen_eval",
                    help="Subfolder under output-dir/eval/ for this run")
    ap.add_argument("--record-video", action="store_true")
    ap.add_argument("--episode-manifest", type=Path, default=None,
                    help="JSON manifest with fixed robot-local cube placements")
    ap.add_argument(
        "--render-cpu",
        action="store_true",
        help="Force Genesis to use CPU (llvmpipe) backend while keeping the "
             "SmolVLA policy on CUDA. Needed on CDNA3 (MI300 series) where "
             "the host has ROCm for PyTorch but no graphics driver for "
             "Vulkan. NOTE: CPU rendering introduces a systematic ~20 pt "
             "success-rate bias vs GPU radeonsi rendering; use for debug "
             "only, not for reporting benchmark numbers.",
    )

    from pick_common import add_pick_args, build_scene, attach_wrist_cam, CUBE_SIZE
    from scene_placement import (
        CUBE_RANGE_X, CUBE_RANGE_Y, to_world,
    )
    from genesis_scene_utils import (
        ensure_display, set_franka_home, to_numpy,
        JOINT_NAMES, HOME_QPOS, KP, KV,
    )

    add_pick_args(ap)
    ap.set_defaults(anchor="floor_origin")
    args = ap.parse_args()
    args.image_noise_std, args.brightness_range = resolve_domain_randomization(
        args.domain_randomization,
        args.image_noise_std,
        tuple(args.brightness_range) if args.brightness_range else None,
    )
    if not 0.0 <= args.camera_dropout_prob <= 1.0:
        ap.error("--camera-dropout-prob must be in [0, 1]")
    if not 0.0 <= args.occlusion_prob <= 1.0:
        ap.error("--occlusion-prob must be in [0, 1]")
    if not 0.0 < args.occlusion_fraction <= 1.0:
        ap.error("--occlusion-fraction must be in (0, 1]")
    if args.action_delay_steps < 0:
        ap.error("--action-delay-steps must be >= 0")
    if args.uncertainty_samples < 0:
        ap.error("--uncertainty-samples must be >= 0")
    if args.uncertainty_noise_std < 0.0:
        ap.error("--uncertainty-noise-std must be >= 0")
    if args.uncertainty_threshold < 0.0:
        ap.error("--uncertainty-threshold must be >= 0")
    if not 0.0 < args.uncertainty_slowdown <= 1.0:
        ap.error("--uncertainty-slowdown must be in (0, 1]")

    n_dofs = len(JOINT_NAMES)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")

    # ------------------------------------------------------------------
    # Load policy (same as 03_eval.py)
    # ------------------------------------------------------------------
    policy_type = args.policy_type
    goal_extra_dims = 0

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
        prev_states = []

        @torch.no_grad()
        def predict(state_np, images=None):
            if history_steps > 0:
                prev_states.append(state_np.copy())
                parts = [state_np]
                for k in range(1, history_steps + 1):
                    idx = max(0, len(prev_states) - 1 - k)
                    parts.append(prev_states[idx])
                for k in range(1, history_steps + 1):
                    idx_cur = max(0, len(prev_states) - k)
                    idx_prev = max(0, len(prev_states) - 1 - k)
                    parts.append(prev_states[idx_cur] - prev_states[idx_prev])
                full_input = np.concatenate(parts)
                state_t = torch.from_numpy(full_input).unsqueeze(0).float().to(device)
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
            saved_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        chunk_size = saved_cfg.get("chunk_size", 10)
        cfg = ACTConfig(
            input_features=input_features, output_features=output_features,
            chunk_size=chunk_size, n_action_steps=chunk_size, n_obs_steps=1,
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
            print(f"[eval] from_pretrained failed ({e}), loading safetensors")
            from safetensors.torch import load_file
            st = load_file(str(ckpt_dir / "model.safetensors"))
            act_policy.load_state_dict(st, strict=False)
        act_policy.eval().to(device)
        preprocessor, postprocessor = make_pre_post_processors(
            cfg, dataset_stats=dataset_metadata.stats)
        for k, ft in input_features.items():
            if k == "observation.state":
                sd = ft.shape[0] if isinstance(ft.shape, (tuple, list)) else ft.shape
                if sd > n_dofs:
                    goal_extra_dims = sd - n_dofs
        print(f"[eval] ACT loaded: chunk_size={chunk_size}")

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
            actions = raw["action"] if isinstance(raw, dict) else raw
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
            saved_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        chunk_size = saved_cfg.get("chunk_size", 50)
        cfg = SmolVLAConfig(
            input_features=input_features, output_features=output_features,
            chunk_size=chunk_size, n_action_steps=chunk_size,
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
        for k, ft in input_features.items():
            if k == "observation.state":
                sd = ft.shape[0] if isinstance(ft.shape, (tuple, list)) else ft.shape
                if sd > n_dofs:
                    goal_extra_dims = sd - n_dofs
        total_params = sum(p.numel() for p in vla_policy.parameters())
        print(f"[eval] SmolVLA loaded: {total_params:,} params, chunk_size={chunk_size}")
        print(f"[eval] task: '{args.task}'")

        @torch.no_grad()
        def predict(state_np, images=None):
            obs = {
                "observation.state": torch.from_numpy(state_np).unsqueeze(0).float().to(device),
                "task": [args.task],
            }
            if images:
                for k, img in images.items():
                    img_t = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(device) / 255.0
                    obs[k] = img_t
            obs = preprocessor(obs)
            for _k, _v in list(obs.items()):
                if isinstance(_v, torch.Tensor) and _v.device != device:
                    obs[_k] = _v.to(device)
            raw = vla_policy.select_action(obs)
            raw = postprocessor(raw)
            actions = raw["action"] if isinstance(raw, dict) else raw
            actions = actions.detach().cpu().numpy()
            if actions.ndim == 3:
                actions = actions[0]
            elif actions.ndim == 1:
                actions = actions[np.newaxis, :]
            return actions

    # ------------------------------------------------------------------
    # Build custom scene
    # ------------------------------------------------------------------
    ensure_display()
    import genesis as gs
    use_cpu_render = bool(args.cpu or args.render_cpu)
    gs.init(backend=(gs.cpu if use_cpu_render else gs.gpu), logging_level="warning")
    if use_cpu_render:
        print(f"[eval] Genesis backend=cpu (llvmpipe); policy device={device}")

    scene, franka, cube, cam_ov, cam_front, cam_up, cam_side, info = build_scene(args, gs)
    scene.build()

    attach_wrist_cam(args, franka, cam_side, gs)

    motors_dof = set_franka_home(franka)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    from pick_common import FORCE_LOWER, FORCE_UPPER
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)

    surface_z = info["surface_z"]
    base_xy = info["base_xy"]
    yaw = info["yaw"]
    yaw_rad = math.radians(yaw)
    cube_half_z = CUBE_SIZE[2] / 2.0
    _needs_images = policy_type in ("act", "smolvla")

    def render_cam(cam):
        rgb, _, _, _ = cam.render(rgb=True, depth=False, segmentation=False, normal=False)
        arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
        if arr.ndim == 4:
            arr = arr[0]
        return arr.astype(np.uint8)

    def reset_episode(cube_world_pos):
        franka.set_dofs_position(HOME_QPOS, motors_dof)
        franka.control_dofs_position(HOME_QPOS, motors_dof)
        franka.zero_all_dofs_velocity()
        cx, cy, cz = cube_world_pos
        cube.set_pos(torch.tensor([cx, cy, cz], dtype=torch.float32,
                                  device=gs.device).unsqueeze(0))
        cube.set_quat(torch.tensor([1, 0, 0, 0], dtype=torch.float32,
                                   device=gs.device).unsqueeze(0))
        cube.zero_all_dofs_velocity()
        for _ in range(args.settle_steps):
            scene.step()

    # ------------------------------------------------------------------
    # Build episode init list (random cube in robot-local frame)
    # ------------------------------------------------------------------
    rng = random.Random(args.seed)
    episode_inits = []
    manifest_coords = None
    if args.episode_manifest is not None:
        manifest = json.loads(args.episode_manifest.read_text(encoding="utf-8"))
        manifest_coords = manifest.get("coordinates", manifest)
        if not isinstance(manifest_coords, list) or len(manifest_coords) < args.n_episodes:
            raise ValueError(
                f"episode manifest must contain at least {args.n_episodes} coordinates"
            )
        print(f"[eval] fixed episode manifest: {args.episode_manifest}")
    for ep in range(args.n_episodes):
        if manifest_coords is None:
            dx = rng.uniform(*CUBE_RANGE_X)
            dy = rng.uniform(*CUBE_RANGE_Y)
        else:
            item = manifest_coords[ep]
            values = item.get("cube_local_dxdy") if isinstance(item, dict) else item
            if values is None and isinstance(item, dict):
                values = item.get("cube_xy")
            if not isinstance(values, (list, tuple)) or len(values) != 2:
                raise ValueError(f"invalid manifest coordinate at index {ep}: {item!r}")
            dx, dy = float(values[0]), float(values[1])
        world_pos = to_world(base_xy, yaw_rad, surface_z, (dx, dy, cube_half_z))
        episode_inits.append((dx, dy, world_pos))

    print(f"\n[eval] scene={args.scene} anchor={args.anchor}")
    print(f"[eval] base=({base_xy[0]:.2f}, {base_xy[1]:.2f}) yaw={yaw}° "
          f"surface_z={surface_z:.3f}")
    print(f"[eval] {args.n_episodes} episodes, max_steps={args.max_steps}")

    save_dir = Path(args.output_dir) / "eval" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Episode loop
    # ------------------------------------------------------------------
    all_results = []
    for ep_idx, (dx, dy, (cx, cy, cz)) in enumerate(episode_inits):
        print(f"\n{'='*60}")
        print(f"[ep {ep_idx+1}/{args.n_episodes}] "
              f"dx={dx:.3f} dy={dy:.3f} world=({cx:.3f},{cy:.3f})")

        reset_episode((cx, cy, cz))
        base_z_cube = cz
        cube_z_hist = []
        _rec_frames_up, _rec_frames_side = [], []
        _last_policy_images = None
        current = HOME_QPOS[:n_dofs].copy()
        if policy_type == "bc":
            prev_states.clear()
        action_queue = []
        delayed_actions = []
        replan_count = 0
        uncertain_observations = 0
        uncertainty_scores = []
        camera_dropout_observations = 0
        occluded_observations = 0
        image_rng = np.random.default_rng(args.seed + 100_000 + ep_idx)
        brightness = (
            float(image_rng.uniform(*args.brightness_range))
            if args.brightness_range is not None else 1.0
        )

        for step in range(args.max_steps):
            state = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            cube_pos = to_numpy(cube.get_pos())
            cube_z_hist.append(float(cube_pos[2]))

            if goal_extra_dims > 0:
                extras = cube_pos[:2].astype(np.float32)
                state = np.concatenate([state, extras[:goal_extra_dims]])

            if len(action_queue) == 0:
                images = None
                uncertain_now = False
                if _needs_images:
                    raw_up = render_cam(cam_up)
                    raw_side = render_cam(cam_side)
                    side_camera_name = "wrist" if args.camera_layout == "up_wrist" else "side"
                    drop_camera = None
                    if image_rng.random() < args.camera_dropout_prob:
                        drop_camera = "overhead" if image_rng.random() < 0.5 else side_camera_name
                        camera_dropout_observations += 1

                    def build_images(local_noise, local_brightness):
                        local_up = augment_image(
                            raw_up, image_rng, local_noise, local_brightness)
                        local_side = augment_image(
                            raw_side, image_rng, local_noise, local_brightness)
                        local_up, occ_up = apply_occlusion(
                            local_up, image_rng, args.occlusion_prob,
                            args.occlusion_fraction, args.occlusion_fill)
                        local_side, occ_side = apply_occlusion(
                            local_side, image_rng, args.occlusion_prob,
                            args.occlusion_fraction, args.occlusion_fill)
                        local_up = ablate_camera(
                            local_up, "overhead", args.camera_ablation,
                            args.camera_ablation_fill)
                        local_side = ablate_camera(
                            local_side, side_camera_name, args.camera_ablation,
                            args.camera_ablation_fill)
                        if drop_camera == "overhead":
                            local_up = np.full_like(local_up, np.uint8(
                                np.clip(round(args.camera_dropout_fill), 0, 255)))
                        elif drop_camera == side_camera_name:
                            local_side = np.full_like(local_side, np.uint8(
                                np.clip(round(args.camera_dropout_fill), 0, 255)))
                        return {
                            "observation.images.up": local_up,
                            "observation.images.side": local_side,
                        }, bool(occ_up or occ_side)

                    images, had_occlusion = build_images(
                        args.image_noise_std, brightness)
                    # Record the exact perturbed observation seen by the
                    # policy, rather than a clean post-action render.
                    _last_policy_images = images
                    occluded_observations += int(had_occlusion)

                    n_passes = max(1, args.uncertainty_samples)
                    sampled_chunks = []
                    for sample_idx in range(n_passes):
                        if sample_idx == 0:
                            sample_images = images
                        else:
                            sample_images, _ = build_images(
                                args.uncertainty_noise_std,
                                brightness * float(image_rng.uniform(0.98, 1.02)),
                            )
                        sampled_chunks.append(predict(state, sample_images))
                    chunk = sampled_chunks[0]
                    if len(sampled_chunks) > 1:
                        first_actions = np.stack([
                            item[0, :n_dofs] if item.ndim == 2 else item[:n_dofs]
                            for item in sampled_chunks
                        ])
                        uncertainty_score = float(np.mean(np.std(first_actions, axis=0)))
                        uncertainty_scores.append(uncertainty_score)
                        uncertain_now = uncertainty_score >= args.uncertainty_threshold
                        if uncertain_now:
                            uncertain_observations += 1
                    else:
                        uncertainty_score = 0.0
                else:
                    chunk = predict(state)
                    uncertainty_score = 0.0
                uncertain_action = uncertain_now
                n_use = 1 if uncertain_now and args.uncertainty_replan else min(args.action_horizon, len(chunk))
                action_queue = [chunk[i, :n_dofs] for i in range(n_use)]
                replan_count += 1

            target_raw = action_queue.pop(0)
            if args.action_delay_steps > 0:
                delayed_actions.append(target_raw)
                if len(delayed_actions) > args.action_delay_steps:
                    target_command = delayed_actions.pop(0)
                else:
                    target_command = current.copy()
            else:
                target_command = target_raw
            delta_limit = args.max_delta_rad * (
                args.uncertainty_slowdown if uncertain_action else 1.0)
            target = smooth_action(current, target_command, delta_limit)
            current = target.copy()

            franka.control_dofs_position(target, motors_dof)
            scene.step()

            if args.record_video:
                if _last_policy_images is not None:
                    _rec_frames_up.append(
                        _last_policy_images["observation.images.up"].copy())
                    _rec_frames_side.append(
                        _last_policy_images["observation.images.side"].copy())
                else:
                    _rec_frames_up.append(
                        ablate_camera(
                            augment_image(render_cam(cam_up), image_rng,
                                          args.image_noise_std, brightness),
                            "overhead", args.camera_ablation,
                            args.camera_ablation_fill,
                        )
                    )
                    _rec_frames_side.append(
                        ablate_camera(
                            augment_image(render_cam(cam_side), image_rng,
                                          args.image_noise_std, brightness),
                            "wrist" if args.camera_layout == "up_wrist" else "side",
                            args.camera_ablation, args.camera_ablation_fill,
                        )
                    )

        # ---- evaluate ----
        lifted = [z >= base_z_cube + args.success_lift_m for z in cube_z_hist]
        sustain = sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)

        cz_max = max(cube_z_hist) if cube_z_hist else base_z_cube
        cz_end = cube_z_hist[-1] if cube_z_hist else base_z_cube
        success = (
            (cz_max - base_z_cube) >= args.success_lift_m
            and sustain_max >= args.success_sustain
            and (cz_end - base_z_cube) >= args.success_final_m
        )

        result = {
            "episode": ep_idx,
            "cube_local_dxdy": [float(dx), float(dy)],
            "cube_world_xy": [float(cx), float(cy)],
            "success": bool(success),
            "max_lift_m": float(cz_max - base_z_cube),
            "end_lift_m": float(cz_end - base_z_cube),
            "sustain_frames": sustain_max,
            "replan_count": replan_count,
            "uncertain_observations": int(uncertain_observations),
            "uncertainty_rate": float(
                uncertain_observations / max(replan_count, 1)),
            "mean_action_uncertainty": float(
                np.mean(uncertainty_scores) if uncertainty_scores else 0.0),
            "camera_dropout_observations": int(camera_dropout_observations),
            "occluded_observations": int(occluded_observations),
            "action_delay_steps": int(args.action_delay_steps),
        }
        all_results.append(result)
        status = "SUCCESS" if success else "FAIL"
        print(f"  [{status}] lift={cz_max - base_z_cube:.4f}m "
              f"end={cz_end - base_z_cube:.4f}m sustain={sustain_max}")

        if args.record_video and _rec_frames_up:
            vid_dir = save_dir / "videos"
            vid_dir.mkdir(parents=True, exist_ok=True)
            tag = "ok" if success else "fail"
            for cam_name, frames in [("up", _rec_frames_up), ("side", _rec_frames_side)]:
                vpath = vid_dir / f"ep{ep_idx:03d}_{tag}_{cam_name}.mp4"
                _write_video(vpath, frames, fps=30)
                print(f"  -> video: {vpath}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_success = sum(1 for r in all_results if r["success"])
    sr = n_success / max(len(all_results), 1)
    print(f"\n{'='*60}")
    print(f"[eval] RESULT: {n_success}/{len(all_results)} = {sr:.0%}")

    summary = {
        "n_episodes": len(all_results),
        "n_success": n_success,
        "success_rate": sr,
        "scene": args.scene,
        "anchor": args.anchor,
        "base_xy": list(base_xy),
        "yaw": yaw,
        "surface_z": surface_z,
        "checkpoint": args.checkpoint,
        "policy_type": policy_type,
        "camera_layout": args.camera_layout,
        "camera_ablation": args.camera_ablation,
        "camera_ablation_fill": float(args.camera_ablation_fill),
        "camera_dropout": {
            "probability": float(args.camera_dropout_prob),
            "fill_value": float(args.camera_dropout_fill),
        },
        "occlusion": {
            "probability": float(args.occlusion_prob),
            "fraction": float(args.occlusion_fraction),
            "fill_value": float(args.occlusion_fill),
        },
        "action_delay_steps": int(args.action_delay_steps),
        "uncertainty": {
            "samples": int(args.uncertainty_samples),
            "noise_std": float(args.uncertainty_noise_std),
            "threshold": float(args.uncertainty_threshold),
            "slowdown": float(args.uncertainty_slowdown),
            "replan": bool(args.uncertainty_replan),
        },
        "cube_friction": float(args.cube_friction),
        "domain_randomization": {
            "image_noise_std": float(args.image_noise_std),
            "brightness_range": list(args.brightness_range)
            if args.brightness_range else [1.0, 1.0],
        },
        "episode_manifest": str(args.episode_manifest)
        if args.episode_manifest else None,
        "episode_coordinates": [
            {"episode": i, "cube_local_dxdy": [float(dx), float(dy)]}
            for i, (dx, dy, _) in enumerate(episode_inits)
        ],
        "results": all_results,
    }
    (save_dir / "eval_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[eval] saved -> {save_dir / 'eval_summary.json'}")


if __name__ == "__main__":
    main()
