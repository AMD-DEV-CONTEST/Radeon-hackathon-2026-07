#!/usr/bin/env python3
"""Closed-loop Sync eval for Env-A fruit pick-and-place (SmolVLA / π0.5).

Conference protocol (EXPERIMENT_PROTOCOL):
  - Success = lift AND fruit_in_basket
  - chunk_size=50, execution horizon E=10, smooth_action(0.15)
  - GPU render only for formal numbers
  - Optional --delay-ms injects wall-clock sleep after each replan (latency study)
  - Uses predict_action_chunk + take first E steps (fair Sync / RTC baseline)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from gen_pick_place import (  # noqa: E402
    BASKET_LOCAL_XY,
    DEFAULT_TASK,
    _add_basket,
    fruit_in_basket,
)
from pick_common import (  # noqa: E402
    CUBE_SIZE,
    FORCE_LOWER,
    FORCE_UPPER,
    add_pick_args,
    attach_wrist_cam,
    build_scene,
)
from scene_placement import CUBE_RANGE_X, CUBE_RANGE_Y, to_world  # noqa: E402
from genesis_scene_utils import (  # noqa: E402
    HOME_QPOS,
    JOINT_NAMES,
    KP,
    KV,
    ensure_display,
    set_franka_home,
    to_numpy,
)

DEFAULT_VLM = "/workspace/models/SmolVLM2-500M-Video-Instruct"


def smooth_action(prev, target, max_delta=0.15):
    delta = np.clip(target - prev, -max_delta, max_delta)
    return prev + delta


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


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
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()


def _write_side_by_side(path, frames_a, frames_b, fps=30):
    if not frames_a or not frames_b:
        return
    n = min(len(frames_a), len(frames_b))
    stacked = []
    for i in range(n):
        a, b = frames_a[i], frames_b[i]
        if a.shape[0] != b.shape[0]:
            # resize b height to match a via simple nearest if needed — skip if mismatch rare
            h = min(a.shape[0], b.shape[0])
            a, b = a[:h], b[:h]
        stacked.append(np.concatenate([a, b], axis=1))
    _write_video(path, stacked, fps=fps)


def load_policy(args, device):
    from lerobot.configs.types import FeatureType
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
    from lerobot.datasets.utils import dataset_to_policy_features
    from lerobot.policies.factory import make_pre_post_processors

    dataset_metadata = LeRobotDatasetMetadata(args.dataset_id)
    features = dataset_to_policy_features(dataset_metadata.features)
    output_features = {k: ft for k, ft in features.items() if ft.type is FeatureType.ACTION}
    input_features = {k: ft for k, ft in features.items() if k not in output_features}

    ckpt_dir = Path(args.checkpoint)
    saved_cfg = {}
    if (ckpt_dir / "config.json").exists():
        saved_cfg = json.loads((ckpt_dir / "config.json").read_text())
    chunk_size = int(saved_cfg.get("chunk_size", 50))

    if args.policy == "smolvla":
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

        vlm_name = args.vlm_model if Path(args.vlm_model).exists() else args.vlm_model
        cfg = SmolVLAConfig(
            input_features=input_features,
            output_features=output_features,
            chunk_size=chunk_size,
            n_action_steps=chunk_size,
            vlm_model_name=vlm_name,
        )
        try:
            policy = SmolVLAPolicy.from_pretrained(str(ckpt_dir), config=cfg, strict=False)
        except Exception as e:
            print(f"[eval] from_pretrained failed ({e}); safetensors fallback")
            from safetensors.torch import load_file

            policy = SmolVLAPolicy(cfg)
            policy.load_state_dict(load_file(str(ckpt_dir / "model.safetensors")), strict=False)
        policy.eval().to(device)
        # Prefer checkpoint processors (saved q01/q99); fall back to dataset stats.
        try:
            preprocessor, postprocessor = make_pre_post_processors(
                cfg, pretrained_path=str(ckpt_dir)
            )
        except Exception:
            preprocessor, postprocessor = make_pre_post_processors(
                cfg, dataset_stats=dataset_metadata.stats
            )
        return policy, cfg, preprocessor, postprocessor, chunk_size, "smolvla"

    if args.policy == "pi05":
        from lerobot.policies.pi05.configuration_pi05 import PI05Config
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        cfg = PI05Config(
            input_features=input_features,
            output_features=output_features,
            chunk_size=chunk_size,
            n_action_steps=chunk_size,
            dtype="bfloat16",
        )
        # Prefer checkpoint config fields if present
        for key in ("max_action_dim", "max_state_dim", "tokenizer_max_length"):
            if key in saved_cfg:
                setattr(cfg, key, saved_cfg[key])
        try:
            policy = PI05Policy.from_pretrained(str(ckpt_dir), config=cfg, strict=False)
        except Exception as e:
            print(f"[eval] pi05 from_pretrained failed ({e}); safetensors fallback")
            from safetensors.torch import load_file

            policy = PI05Policy(cfg)
            policy.load_state_dict(load_file(str(ckpt_dir / "model.safetensors")), strict=False)
        policy.eval().to(device)
        try:
            preprocessor, postprocessor = make_pre_post_processors(
                cfg, pretrained_path=str(ckpt_dir)
            )
        except Exception:
            preprocessor, postprocessor = make_pre_post_processors(
                cfg, dataset_stats=dataset_metadata.stats
            )
        return policy, cfg, preprocessor, postprocessor, chunk_size, "pi05"

    raise ValueError(f"Unknown policy: {args.policy}")


def main():
    ap = argparse.ArgumentParser(description="Fruit pick-place Sync eval")
    ap.add_argument("--policy", choices=["smolvla", "pi05"], default="smolvla")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--dataset-id", default="local/franka-kitchen-fruit-place-120ep")
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--vlm-model", default=DEFAULT_VLM)
    ap.add_argument("--n-episodes", type=int, default=5)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument(
        "--action-horizon",
        type=int,
        default=50,
        help="Execution horizon E: steps taken from each predicted chunk before replan. "
        "Use E=chunk_size for Sync-full (avoids start-of-chunk attractor). "
        "E=10 matches RTC protocol but can stall gradual-approach policies.",
    )
    ap.add_argument("--max-delta-rad", type=float, default=0.15)
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--success-lift-m", type=float, default=0.02)
    ap.add_argument("--success-sustain", type=int, default=8)
    ap.add_argument("--basket-dx", type=float, default=BASKET_LOCAL_XY[0])
    ap.add_argument("--basket-dy", type=float, default=BASKET_LOCAL_XY[1])
    ap.add_argument("--delay-ms", type=float, default=0.0,
                    help="Injected wall-clock delay after each replan inference")
    ap.add_argument(
        "--env-b",
        action="store_true",
        help="Env-B: after sampling the Env-A fruit pose (same seed), apply a held-out "
        "runtime XY shift of magnitude in [--perturb-m-min, --perturb-m-max]. "
        "Basket fixed; shift never appears in training.",
    )
    ap.add_argument("--perturb-m-min", type=float, default=0.03, help="Env-B shift min (m)")
    ap.add_argument("--perturb-m-max", type=float, default=0.05, help="Env-B shift max (m)")
    ap.add_argument(
        "--perturb-seed-offset",
        type=int,
        default=7919,
        help="Extra seed offset for the perturbation RNG (independent of fruit-init seed)",
    )
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--run-name", default="sync_eval")
    ap.add_argument("--record-video", action="store_true")
    ap.add_argument("--record-all-videos", action="store_true",
                    help="Record every episode (default with --record-video)")
    ap.add_argument("--render-cpu", action="store_true")
    add_pick_args(ap)
    ap.set_defaults(anchor="floor_origin", camera_layout="up_wrist", scene="rustic_kitchen")
    args = ap.parse_args()
    if args.record_video:
        args.record_all_videos = True
    if args.env_b and args.perturb_m_min > args.perturb_m_max:
        raise SystemExit("--perturb-m-min must be <= --perturb-m-max")

    os.environ.setdefault("HF_LEROBOT_HOME", "/workspace/cache/huggingface/lerobot")
    os.environ.setdefault("HF_HOME", "/workspace/cache/huggingface")
    if args.policy == "smolvla" and Path(args.vlm_model).exists():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    if args.policy == "pi05":
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    n_dofs = len(JOINT_NAMES)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    policy, cfg, preprocessor, postprocessor, chunk_size, policy_name = load_policy(args, device)
    env_name = "env_b" if args.env_b else "env_a"
    print(
        f"[eval] {policy_name} env={env_name} chunk_size={chunk_size} E={args.action_horizon} "
        f"delay_ms={args.delay_ms} task='{args.task}'"
    )
    if args.env_b:
        print(
            f"[eval] Env-B runtime XY shift ∈ [{args.perturb_m_min:.3f}, "
            f"{args.perturb_m_max:.3f}] m (held-out; basket fixed)"
        )

    infer_latencies = []

    @torch.no_grad()
    def predict_chunk(state_np, images):
        obs = {
            "observation.state": torch.from_numpy(state_np).unsqueeze(0).float().to(device),
            "task": [args.task],
        }
        for k, img in images.items():
            obs[k] = (
                torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(device) / 255.0
            )
        obs = preprocessor(obs)
        for k, v in list(obs.items()):
            if isinstance(v, torch.Tensor) and v.device != device:
                obs[k] = v.to(device)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        # Prefer full chunk for fair E-horizon Sync protocol
        if hasattr(policy, "predict_action_chunk"):
            raw = policy.predict_action_chunk(obs)
        else:
            raw = policy.select_action(obs)
        if device.type == "cuda":
            torch.cuda.synchronize()
        infer_ms = (time.perf_counter() - t0) * 1000.0
        infer_latencies.append(infer_ms)
        if args.delay_ms > 0:
            time.sleep(args.delay_ms / 1000.0)
        raw = postprocessor(raw)
        actions = raw["action"] if isinstance(raw, dict) else raw
        actions = actions.detach().cpu().numpy()
        if actions.ndim == 3:
            actions = actions[0]
        elif actions.ndim == 1:
            actions = actions[np.newaxis, :]
        return actions, infer_ms

    ensure_display()
    import genesis as gs

    use_cpu_render = bool(args.cpu or args.render_cpu)
    gs.init(backend=(gs.cpu if use_cpu_render else gs.gpu), logging_level="warning")
    scene, franka, cube, cam_ov, cam_front, cam_up, cam_side, info = build_scene(args, gs)
    basket_info = _add_basket(
        scene, gs, info["base_xy"], math.radians(info["yaw"]), info["surface_z"],
        (args.basket_dx, args.basket_dy),
    )
    scene.build()
    attach_wrist_cam(args, franka, cam_side, gs)
    motors_dof = set_franka_home(franka)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)

    surface_z = info["surface_z"]
    base_xy = info["base_xy"]
    yaw = info["yaw"]
    yaw_rad = math.radians(yaw)
    cube_half_z = CUBE_SIZE[2] / 2.0

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
        cube.set_pos(
            torch.tensor([cx, cy, cz], dtype=torch.float32, device=gs.device).unsqueeze(0)
        )
        cube.set_quat(
            torch.tensor([1, 0, 0, 0], dtype=torch.float32, device=gs.device).unsqueeze(0)
        )
        cube.zero_all_dofs_velocity()
        for _ in range(args.settle_steps):
            scene.step()

    rng = random.Random(args.seed)
    # Independent stream so Env-A fruit inits stay bit-identical when --env-b is set.
    rng_perturb = random.Random(args.seed + args.perturb_seed_offset)
    episode_inits = []
    for ep_i in range(args.n_episodes):
        dx = rng.uniform(*CUBE_RANGE_X)
        dy = rng.uniform(*CUBE_RANGE_Y)
        world_nom = to_world(base_xy, yaw_rad, surface_z, (dx, dy, cube_half_z))
        cx_n, cy_n, cz_n = world_nom
        pdx = pdy = 0.0
        mag = 0.0
        ang = 0.0
        if args.env_b:
            mag = rng_perturb.uniform(args.perturb_m_min, args.perturb_m_max)
            ang = rng_perturb.uniform(0.0, 2.0 * math.pi)
            pdx = mag * math.cos(ang)
            pdy = mag * math.sin(ang)
        cx, cy, cz = cx_n + pdx, cy_n + pdy, cz_n
        episode_inits.append(
            {
                "episode": ep_i,
                "dx_local": float(dx),
                "dy_local": float(dy),
                "world_nominal": [float(cx_n), float(cy_n), float(cz_n)],
                "perturb_xy_m": [float(pdx), float(pdy)],
                "perturb_mag_m": float(mag),
                "perturb_angle_rad": float(ang),
                "world": [float(cx), float(cy), float(cz)],
            }
        )

    save_dir = Path(args.output_dir) / "eval" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)
    init_payload = {
        "env": env_name,
        "seed": args.seed,
        "perturb_seed_offset": args.perturb_seed_offset if args.env_b else None,
        "perturb_m_range": [args.perturb_m_min, args.perturb_m_max] if args.env_b else None,
        "n": len(episode_inits),
        "note": (
            "Env-B: same nominal fruit inits as Env-A (seed), then held-out world-XY shift; "
            "basket fixed; never in training."
            if args.env_b
            else "Env-A: training-distribution fruit inits."
        ),
        "inits": episode_inits,
    }
    (save_dir / "episode_inits.json").write_text(json.dumps(init_payload, indent=2) + "\n")
    if args.env_b:
        formal_manifest = _ROOT / "artifacts" / "env_b_manifest.json"
        formal_manifest.parent.mkdir(parents=True, exist_ok=True)
        # Merge/overwrite with latest Env-B schedule (shared across policies).
        formal_manifest.write_text(json.dumps(init_payload, indent=2) + "\n")
    print(f"[eval] {args.n_episodes} eps max_steps={args.max_steps} basket={basket_info['center_xy']}")
    if args.env_b and episode_inits:
        mags = [e["perturb_mag_m"] for e in episode_inits]
        print(f"[eval] Env-B |Δxy| mean={np.mean(mags):.3f}m range=[{min(mags):.3f},{max(mags):.3f}]")

    all_results = []
    t_wall0 = time.time()
    for init in episode_inits:
        ep_idx = init["episode"]
        dx, dy = init["dx_local"], init["dy_local"]
        cx, cy, cz = init["world"]
        cx_n, cy_n, _ = init["world_nominal"]
        pdx, pdy = init["perturb_xy_m"]
        print(
            f"\n[ep {ep_idx+1}/{args.n_episodes}] nom=({cx_n:.3f},{cy_n:.3f}) "
            f"Δ=({pdx:+.3f},{pdy:+.3f}) → ({cx:.3f},{cy:.3f})"
        )
        reset_episode((cx, cy, cz))
        if hasattr(policy, "reset"):
            policy.reset()
        base_z = cz
        fruit_z_hist = []
        frames_up, frames_side = [], []
        current = HOME_QPOS[:n_dofs].copy()
        action_queue = []
        replan_count = 0
        ep_infer = []
        ep_t0 = time.time()

        for step in range(args.max_steps):
            state = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            fruit_pos = to_numpy(cube.get_pos())
            fruit_z_hist.append(float(fruit_pos[2]))

            if len(action_queue) == 0:
                images = {
                    "observation.images.up": render_cam(cam_up),
                    "observation.images.side": render_cam(cam_side),
                }
                chunk, infer_ms = predict_chunk(state, images)
                n_use = min(args.action_horizon, len(chunk))
                action_queue = [chunk[i, :n_dofs] for i in range(n_use)]
                replan_count += 1
                ep_infer.append(infer_ms)

            target = smooth_action(current, action_queue.pop(0), args.max_delta_rad)
            current = target.copy()
            franka.control_dofs_position(target, motors_dof)
            scene.step()
            if args.record_all_videos:
                frames_up.append(render_cam(cam_up))
                frames_side.append(render_cam(cam_side))

        final_pos = to_numpy(cube.get_pos())
        lifted = [z >= base_z + args.success_lift_m for z in fruit_z_hist]
        sustain = sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)
        cz_max = max(fruit_z_hist) if fruit_z_hist else base_z
        lifted_ok = (cz_max - base_z) >= args.success_lift_m and sustain_max >= args.success_sustain
        placed_ok = fruit_in_basket(final_pos, basket_info)
        success = bool(lifted_ok and placed_ok)
        result = {
            "episode": ep_idx,
            "env": env_name,
            "fruit_local_dxdy": [float(dx), float(dy)],
            "fruit_world_xy_nominal": [float(cx_n), float(cy_n)],
            "fruit_world_xy": [float(cx), float(cy)],
            "perturb_xy_m": [float(pdx), float(pdy)],
            "perturb_mag_m": float(init["perturb_mag_m"]),
            "final_xyz": [float(final_pos[0]), float(final_pos[1]), float(final_pos[2])],
            "success": success,
            "lifted_ok": bool(lifted_ok),
            "placed_ok": bool(placed_ok),
            "max_lift_m": float(cz_max - base_z),
            "sustain_frames": int(sustain_max),
            "replan_count": replan_count,
            "infer_ms_p50": float(np.percentile(ep_infer, 50)) if ep_infer else None,
            "infer_ms_mean": float(np.mean(ep_infer)) if ep_infer else None,
            "wall_time_s": float(time.time() - ep_t0),
        }
        all_results.append(result)
        msg = (
            f"  [{'OK' if success else 'FAIL'}] lift={result['max_lift_m']:.3f}m "
            f"sustain={sustain_max} placed={placed_ok} replans={replan_count}"
        )
        if result["infer_ms_p50"] is not None:
            msg += f" infer_p50={result['infer_ms_p50']:.1f}ms"
        print(msg)
        if args.record_all_videos and frames_up:
            vid_dir = save_dir / "videos"
            vid_dir.mkdir(parents=True, exist_ok=True)
            tag = "ok" if success else "fail"
            _write_video(vid_dir / f"ep{ep_idx:03d}_{tag}_up.mp4", frames_up)
            _write_video(vid_dir / f"ep{ep_idx:03d}_{tag}_wrist.mp4", frames_side)
            _write_side_by_side(
                vid_dir / f"ep{ep_idx:03d}_{tag}_sbs.mp4", frames_up, frames_side
            )

    wall_s = time.time() - t_wall0
    n_ok = sum(1 for r in all_results if r["success"])
    n_lift = sum(1 for r in all_results if r["lifted_ok"])
    n_place = sum(1 for r in all_results if r["placed_ok"])
    lat = np.array(infer_latencies, dtype=float)
    peak_mb = None
    if torch.cuda.is_available():
        peak_mb = torch.cuda.max_memory_allocated() / 1024**2
    ci_lo, ci_hi = wilson_ci(n_ok, len(all_results))

    summary = {
        "run_name": args.run_name,
        "policy": policy_name,
        "mode": "sync",
        "env": env_name,
        "env_b": bool(args.env_b),
        "perturb_m_range": [args.perturb_m_min, args.perturb_m_max] if args.env_b else None,
        "perturb_seed_offset": args.perturb_seed_offset if args.env_b else None,
        "checkpoint": args.checkpoint,
        "dataset_id": args.dataset_id,
        "task": args.task,
        "n_episodes": len(all_results),
        "n_success": n_ok,
        "n_lifted": n_lift,
        "n_placed": n_place,
        "success_rate": n_ok / max(len(all_results), 1),
        "lift_rate": n_lift / max(len(all_results), 1),
        "place_rate": n_place / max(len(all_results), 1),
        "wilson_ci95": [ci_lo, ci_hi],
        "mean_perturb_mag_m": float(np.mean([r["perturb_mag_m"] for r in all_results]))
        if all_results
        else None,
        "chunk_size": chunk_size,
        "action_horizon_E": args.action_horizon,
        "delay_ms": args.delay_ms,
        "max_steps": args.max_steps,
        "seed": args.seed,
        "smooth_max_delta": args.max_delta_rad,
        "wall_time_s": wall_s,
        "peak_vram_mb": float(peak_mb) if peak_mb is not None else None,
        "peak_vram_gb": float(peak_mb / 1024) if peak_mb is not None else None,
        "infer_latency_ms": {
            "n": int(len(lat)),
            "p50": float(np.percentile(lat, 50)) if len(lat) else None,
            "p95": float(np.percentile(lat, 95)) if len(lat) else None,
            "mean": float(np.mean(lat)) if len(lat) else None,
        },
        "basket_center_xy": list(basket_info["center_xy"]),
        "results": all_results,
    }
    (save_dir / "eval_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    formal = _ROOT / "artifacts" / "formal" / args.run_name
    formal.mkdir(parents=True, exist_ok=True)
    (formal / "eval_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"\n[eval] RESULT {n_ok}/{len(all_results)} = {summary['success_rate']:.0%} "
        f"Wilson95=[{ci_lo:.0%},{ci_hi:.0%}]"
    )
    p50 = summary["infer_latency_ms"]["p50"]
    vram = summary["peak_vram_gb"]
    print(
        f"[eval] lift={n_lift}/{len(all_results)} place={n_place}/{len(all_results)} "
        f"wall={wall_s:.1f}s peak_vram={vram:.2f}GB "
        f"infer_p50={p50:.1f}ms"
        if p50 is not None and vram is not None
        else f"[eval] wall={wall_s:.1f}s"
    )
    print(f"[eval] saved -> {save_dir / 'eval_summary.json'}")


if __name__ == "__main__":
    main()
