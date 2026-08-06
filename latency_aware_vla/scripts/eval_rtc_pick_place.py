#!/usr/bin/env python3
"""RTC / Async / Sync latency-aware closed-loop eval (Env-A fruit place).

Story-closing protocol vs Sync+delay:
  - Sync: on each replan, wall-clock sleep(delay_ms) — robot frozen during wait
  - Async: keep executing leftover queue while waiting; no RTC guidance
  - RTC: keep executing leftover; next chunk guided by prev_chunk_left_over
          with inference_delay in control steps (30 Hz)

Primary story arm: SmolVLA (has closed-loop place successes).
π0.5 supported for completeness once grasp works.
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
CONTROL_HZ = 30.0


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
        h = min(a.shape[0], b.shape[0])
        stacked.append(np.concatenate([a[:h], b[:h]], axis=1))
    _write_video(path, stacked, fps=fps)


def ms_to_steps(ms: float, hz: float = CONTROL_HZ) -> int:
    if ms <= 0:
        return 0
    return max(1, int(math.ceil(ms / 1000.0 * hz)))


def load_policy(args, device, rtc_cfg=None):
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
            rtc_config=rtc_cfg,
        )
        try:
            policy = SmolVLAPolicy.from_pretrained(str(ckpt_dir), config=cfg, strict=False)
        except Exception as e:
            print(f"[eval] from_pretrained failed ({e}); safetensors fallback")
            from safetensors.torch import load_file

            policy = SmolVLAPolicy(cfg)
            policy.load_state_dict(load_file(str(ckpt_dir / "model.safetensors")), strict=False)
        if rtc_cfg is not None and hasattr(policy, "init_rtc_processor"):
            policy.config.rtc_config = rtc_cfg
            policy.init_rtc_processor()
        policy.eval().to(device)
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
            rtc_config=rtc_cfg,
        )
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
        if rtc_cfg is not None:
            policy.config.rtc_config = rtc_cfg
            if hasattr(policy, "init_rtc_processor"):
                policy.init_rtc_processor()
            elif getattr(policy, "rtc_processor", None) is None:
                from lerobot.policies.rtc.modeling_rtc import RTCProcessor

                policy.rtc_processor = RTCProcessor(rtc_cfg)
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

    raise ValueError(args.policy)


def main():
    ap = argparse.ArgumentParser(description="RTC/Async/Sync latency eval")
    ap.add_argument("--policy", choices=["smolvla", "pi05"], default="smolvla")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--mode", choices=["sync", "async", "rtc"], default="rtc")
    ap.add_argument("--dataset-id", default="local/franka-kitchen-fruit-place-120ep")
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--vlm-model", default=DEFAULT_VLM)
    ap.add_argument("--n-episodes", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--execution-horizon", type=int, default=10, help="RTC E / Sync open-loop E")
    ap.add_argument("--max-delta-rad", type=float, default=0.15)
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--success-lift-m", type=float, default=0.02)
    ap.add_argument("--success-sustain", type=int, default=8)
    ap.add_argument("--basket-dx", type=float, default=BASKET_LOCAL_XY[0])
    ap.add_argument("--basket-dy", type=float, default=BASKET_LOCAL_XY[1])
    ap.add_argument("--delay-ms", type=float, default=0.0,
                    help="Injected inference delay (wall for Sync; steps for RTC/Async)")
    ap.add_argument("--native-infer-ms", type=float, default=None,
                    help="Override native infer estimate for delay→steps (default: measure)")
    ap.add_argument("--max-guidance-weight", type=float, default=10.0)
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--run-name", default="rtc_eval")
    ap.add_argument("--record-video", action="store_true")
    ap.add_argument("--render-cpu", action="store_true")
    add_pick_args(ap)
    ap.set_defaults(anchor="floor_origin", camera_layout="up_wrist", scene="rustic_kitchen")
    args = ap.parse_args()

    os.environ.setdefault("HF_LEROBOT_HOME", "/workspace/cache/huggingface/lerobot")
    os.environ.setdefault("HF_HOME", "/workspace/cache/huggingface")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from lerobot.configs.types import RTCAttentionSchedule
    from lerobot.policies.rtc.action_queue import ActionQueue
    from lerobot.policies.rtc.configuration_rtc import RTCConfig

    use_rtc = args.mode == "rtc"
    rtc_cfg = RTCConfig(
        enabled=use_rtc,
        execution_horizon=args.execution_horizon,
        max_guidance_weight=args.max_guidance_weight,
        prefix_attention_schedule=RTCAttentionSchedule.EXP,
    )

    n_dofs = len(JOINT_NAMES)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    policy, cfg, preprocessor, postprocessor, chunk_size, policy_name = load_policy(
        args, device, rtc_cfg=rtc_cfg if use_rtc else None
    )
    # Async uses ActionQueue without RTC guidance
    queue_cfg = rtc_cfg if use_rtc else RTCConfig(enabled=False, execution_horizon=args.execution_horizon)
    print(
        f"[eval] {policy_name} mode={args.mode} H={chunk_size} E={args.execution_horizon} "
        f"delay_ms={args.delay_ms} task='{args.task}'"
    )

    infer_latencies = []

    @torch.no_grad()
    def predict_chunk(state_np, images, *, inference_delay: int = 0, prev_left=None):
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
        kwargs = {}
        if use_rtc:
            kwargs["inference_delay"] = int(inference_delay)
            kwargs["prev_chunk_left_over"] = prev_left
            kwargs["execution_horizon"] = args.execution_horizon
        raw = policy.predict_action_chunk(obs, **kwargs)
        if device.type == "cuda":
            torch.cuda.synchronize()
        infer_ms = (time.perf_counter() - t0) * 1000.0
        infer_latencies.append(infer_ms)
        raw_t = raw.detach() if torch.is_tensor(raw) else raw
        # Keep original (model space / pre-post) for RTC leftover tracking
        if torch.is_tensor(raw_t):
            original = raw_t.squeeze(0).detach().cpu()
        else:
            original = torch.as_tensor(raw_t).squeeze(0)
        post_out = postprocessor(raw)
        actions = post_out["action"] if isinstance(post_out, dict) else post_out
        actions = actions.detach().cpu()
        if actions.ndim == 3:
            actions = actions[0]
        elif actions.ndim == 1:
            actions = actions.unsqueeze(0)
        # Original should be same shape as processed for ActionQueue; use processed
        # for both when model-space leftover is awkward across postprocessor.
        original = actions.clone()
        return actions, original, infer_ms

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
    yaw_rad = math.radians(info["yaw"])
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
    episode_inits = []
    for _ in range(args.n_episodes):
        dx = rng.uniform(*CUBE_RANGE_X)
        dy = rng.uniform(*CUBE_RANGE_Y)
        world_pos = to_world(base_xy, yaw_rad, surface_z, (dx, dy, cube_half_z))
        episode_inits.append((dx, dy, world_pos))

    save_dir = Path(args.output_dir) / "eval" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    t_wall0 = time.time()
    freeze_steps_total = 0
    moving_during_infer_total = 0

    for ep_idx, (dx, dy, (cx, cy, cz)) in enumerate(episode_inits):
        print(f"\n[ep {ep_idx+1}/{args.n_episodes}] dx={dx:.3f} dy={dy:.3f}")
        reset_episode((cx, cy, cz))
        if hasattr(policy, "reset"):
            policy.reset()
        base_z = cz
        fruit_z_hist = []
        frames_up, frames_side = [], []
        current = HOME_QPOS[:n_dofs].copy()
        action_queue = ActionQueue(queue_cfg)
        replan_count = 0
        ep_infer = []
        ep_freeze = 0
        ep_move_infer = 0
        ep_t0 = time.time()
        # Warm native latency estimate
        native_ms = args.native_infer_ms

        step = 0
        while step < args.max_steps:
            state = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            fruit_pos = to_numpy(cube.get_pos())
            fruit_z_hist.append(float(fruit_pos[2]))

            need_replan = action_queue.empty()
            if args.mode in ("rtc", "async") and not action_queue.empty():
                # Request next chunk when remaining ≈ E (keep robot fed under delay)
                threshold = args.execution_horizon
                if action_queue.qsize() <= threshold:
                    need_replan = True

            if need_replan:
                images = {
                    "observation.images.up": render_cam(cam_up),
                    "observation.images.side": render_cam(cam_side),
                }
                # Delay in control steps from injected + measured native
                if native_ms is None and infer_latencies:
                    native_ms = float(np.median(infer_latencies[-min(20, len(infer_latencies)):]))
                elif native_ms is None:
                    native_ms = 350.0 if args.policy == "smolvla" else 310.0
                delay_steps = ms_to_steps(float(native_ms) + float(args.delay_ms))

                if args.mode == "sync":
                    # Sync: freeze during infer + injected delay, then take E actions
                    actions, original, infer_ms = predict_chunk(state, images)
                    ep_infer.append(infer_ms)
                    if args.delay_ms > 0:
                        time.sleep(args.delay_ms / 1000.0)
                        ep_freeze += ms_to_steps(args.delay_ms)
                    # Also count native infer as freeze for sync semantics
                    ep_freeze += ms_to_steps(infer_ms)
                    n_use = min(args.execution_horizon if args.execution_horizon > 0 else chunk_size,
                                len(actions))
                    # For Sync-full story parity use E=chunk when execution_horizon==chunk
                    if args.execution_horizon >= chunk_size:
                        n_use = min(chunk_size, len(actions))
                    action_queue.merge(original[:n_use], actions[:n_use], real_delay=0)
                    replan_count += 1

                else:
                    # RTC / Async: capture leftover, keep executing during delay_steps
                    prev_left = action_queue.get_left_over()
                    idx_before = action_queue.get_action_index()
                    # Execute up to delay_steps from current queue while "inferring"
                    # First chunk: queue empty → must infer with freeze bootstrap
                    if action_queue.empty():
                        actions, original, infer_ms = predict_chunk(
                            state, images,
                            inference_delay=0,
                            prev_left=None,
                        )
                        ep_infer.append(infer_ms)
                        # Bootstrap: optional injected freeze only for first chunk fairness
                        # (no prior actions). Then feed full chunk.
                        action_queue.merge(original, actions, real_delay=0)
                        replan_count += 1
                    else:
                        # Simulate continuous motion for delay_steps, then merge new chunk
                        # Infer NOW (blocking) but then skip first delay_steps of new chunk
                        # while having consumed delay_steps from old queue — approximates
                        # async if we consume those steps after infer. True RTC: consume
                        # during infer. We approximate by: consume min(delay, qsize) after
                        # infer from OLD queue conceptually via merge(real_delay=d).
                        d = min(delay_steps, max(1, action_queue.qsize() - 1))
                        actions, original, infer_ms = predict_chunk(
                            state, images,
                            inference_delay=d if use_rtc else 0,
                            prev_left=prev_left if use_rtc else None,
                        )
                        ep_infer.append(infer_ms)
                        # Consume d actions from old queue (robot moved during infer)
                        for _ in range(d):
                            a = action_queue.get()
                            if a is None:
                                break
                            target = smooth_action(
                                current, a.numpy()[:n_dofs], args.max_delta_rad
                            )
                            current = target.copy()
                            franka.control_dofs_position(target, motors_dof)
                            scene.step()
                            step += 1
                            ep_move_infer += 1
                            fruit_z_hist.append(float(to_numpy(cube.get_pos())[2]))
                            if args.record_video:
                                frames_up.append(render_cam(cam_up))
                                frames_side.append(render_cam(cam_side))
                            if step >= args.max_steps:
                                break
                        action_queue.merge(
                            original, actions, real_delay=d, action_index_before_inference=idx_before
                        )
                        replan_count += 1
                        continue  # already stepped

            a = action_queue.get()
            if a is None:
                # Underrun — force replan next loop
                continue
            target = smooth_action(current, a.numpy()[:n_dofs], args.max_delta_rad)
            current = target.copy()
            franka.control_dofs_position(target, motors_dof)
            scene.step()
            step += 1
            if args.record_video:
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
        freeze_steps_total += ep_freeze
        moving_during_infer_total += ep_move_infer
        result = {
            "episode": ep_idx,
            "fruit_local_dxdy": [float(dx), float(dy)],
            "success": success,
            "lifted_ok": bool(lifted_ok),
            "placed_ok": bool(placed_ok),
            "max_lift_m": float(cz_max - base_z),
            "sustain_frames": int(sustain_max),
            "replan_count": replan_count,
            "freeze_steps": ep_freeze,
            "moving_during_infer_steps": ep_move_infer,
            "infer_ms_p50": float(np.percentile(ep_infer, 50)) if ep_infer else None,
            "wall_time_s": float(time.time() - ep_t0),
        }
        all_results.append(result)
        print(
            f"  [{'OK' if success else 'FAIL'}] lift={result['max_lift_m']:.3f}m "
            f"placed={placed_ok} replans={replan_count} move_infer={ep_move_infer}"
        )
        if args.record_video and frames_up:
            vid_dir = save_dir / "videos"
            vid_dir.mkdir(parents=True, exist_ok=True)
            tag = "ok" if success else "fail"
            _write_video(vid_dir / f"ep{ep_idx:03d}_{tag}_up.mp4", frames_up)
            _write_video(vid_dir / f"ep{ep_idx:03d}_{tag}_wrist.mp4", frames_side)
            _write_side_by_side(vid_dir / f"ep{ep_idx:03d}_{tag}_sbs.mp4", frames_up, frames_side)

    wall_s = time.time() - t_wall0
    n_ok = sum(1 for r in all_results if r["success"])
    n_lift = sum(1 for r in all_results if r["lifted_ok"])
    n_place = sum(1 for r in all_results if r["placed_ok"])
    lat = np.array(infer_latencies, dtype=float)
    peak_mb = torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else None
    ci_lo, ci_hi = wilson_ci(n_ok, len(all_results))

    summary = {
        "run_name": args.run_name,
        "policy": policy_name,
        "mode": args.mode,
        "checkpoint": args.checkpoint,
        "n_episodes": len(all_results),
        "n_success": n_ok,
        "n_lifted": n_lift,
        "n_placed": n_place,
        "success_rate": n_ok / max(len(all_results), 1),
        "lift_rate": n_lift / max(len(all_results), 1),
        "place_rate": n_place / max(len(all_results), 1),
        "wilson_ci95": [ci_lo, ci_hi],
        "chunk_size": chunk_size,
        "action_horizon_E": args.execution_horizon,
        "delay_ms": args.delay_ms,
        "native_infer_ms_used": native_ms,
        "max_steps": args.max_steps,
        "seed": args.seed,
        "wall_time_s": wall_s,
        "peak_vram_gb": float(peak_mb / 1024) if peak_mb is not None else None,
        "infer_latency_ms": {
            "n": int(len(lat)),
            "p50": float(np.percentile(lat, 50)) if len(lat) else None,
            "p95": float(np.percentile(lat, 95)) if len(lat) else None,
            "mean": float(np.mean(lat)) if len(lat) else None,
        },
        "freeze_steps_total": freeze_steps_total,
        "moving_during_infer_total": moving_during_infer_total,
        "results": all_results,
    }
    (save_dir / "eval_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    formal = _ROOT / "artifacts" / "formal" / args.run_name
    formal.mkdir(parents=True, exist_ok=True)
    (formal / "eval_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"\n[eval] RESULT {n_ok}/{len(all_results)} = {summary['success_rate']:.0%} "
        f"Wilson95=[{ci_lo:.0%},{ci_hi:.0%}] mode={args.mode}"
    )
    print(f"[eval] saved -> {save_dir / 'eval_summary.json'}")


if __name__ == "__main__":
    main()
