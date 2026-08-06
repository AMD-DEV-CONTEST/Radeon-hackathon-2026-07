"""
专家示范数据生成（方案A 位置控制抓取）
使用IK逆运动学求解器生成Franka机械臂抓取球体的动作轨迹。
物体位置在指定范围内随机采样。顶视+手腕双相机录制，LeRobot格式输出。
仅成功的episode写入数据集——失败尝试自动丢弃。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Custom-scene Franka pick-cube data generation (LeRobot)")

    # Dataset args (same as 01_gen_data.py)
    ap.add_argument("--n-episodes", type=int, default=10)
    ap.add_argument("--repo-id", default="local/kitchen-pick")
    ap.add_argument("--output-dir", default="./output")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--task", default="Pick up the cube.")
    ap.add_argument("--no-videos", action="store_true",
                    help="Store images as PNG instead of video")
    ap.add_argument("--add-phase", action="store_true",
                    help="Append normalized time t/T to observation.state")
    ap.add_argument("--add-goal", action="store_true",
                    help="Append cube (x,y) to observation.state")

    # Smoke-test: dump PNGs from up + side/wrist cams at a few frames of the
    # first episode so the viewpoint can be visually inspected before a big run.
    ap.add_argument("--smoke-dump-pngs", type=str, default=None,
                    help="Dir to dump up/side PNGs at phases 0/25/50/75/100%% "
                         "of the first episode (for occlusion check).")

    # Trajectory args
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--approach-steps", type=int, default=40)
    ap.add_argument("--descend-steps", type=int, default=30)
    ap.add_argument("--grasp-hold-steps", type=int, default=20)
    ap.add_argument("--lift-steps", type=int, default=30)
    ap.add_argument("--lift-hold-steps", type=int, default=15)

    # Success criteria
    ap.add_argument("--success-lift-delta", type=float, default=0.02)
    ap.add_argument("--success-sustain-frames", type=int, default=8)
    ap.add_argument("--success-final-delta", type=float, default=0.01)

    from pick_common import add_pick_args, build_scene, attach_wrist_cam, CUBE_SIZE
    from scene_placement import (
        HAND_OFFSET, HOVER_DZ, LIFT_DZ, CUBE_RANGE_X, CUBE_RANGE_Y,
        compute_workspace, to_world,
    )
    from genesis_scene_utils import (
        ensure_display, set_franka_home, to_numpy, lerp,
        JOINT_NAMES, HOME_QPOS, KP, KV,
    )

    add_pick_args(ap)
    ap.set_defaults(anchor="floor_origin")
    args = ap.parse_args()

    MOTOR_NAMES = [f"{j}.pos" for j in JOINT_NAMES]
    FINGER_OPEN = 0.04
    FINGER_CLOSED = 0.01
    GRASP_QUAT = np.array([0, 1, 0, 0], dtype=np.float32)
    n_dofs = len(JOINT_NAMES)

    # ------------------------------------------------------------------
    # Init Genesis + build scene
    # ------------------------------------------------------------------
    ensure_display()
    import genesis as gs
    import torch

    gs.init(backend=(gs.cpu if args.cpu else gs.gpu), logging_level="warning")

    scene, franka, cube, cam_ov, cam_front, cam_up, cam_side, info = build_scene(args, gs)
    scene.build()

    attach_wrist_cam(args, franka, cam_side, gs)

    motors_dof = set_franka_home(franka)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    from pick_common import FORCE_LOWER, FORCE_UPPER
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)
    ee = franka.get_link("hand")

    surface_z = info["surface_z"]
    base_xy = info["base_xy"]
    yaw = info["yaw"]
    import math
    yaw_rad = math.radians(yaw)

    # ------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------
    def render_cam(cam):
        rgb, _, _, _ = cam.render(rgb=True, depth=False,
                                  segmentation=False, normal=False)
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

    def solve_ik(pos, finger_pos=FINGER_OPEN):
        qpos = to_numpy(franka.inverse_kinematics(
            link=ee,
            pos=np.array(pos, dtype=np.float32),
            quat=GRASP_QUAT,
        ))
        target = np.zeros(n_dofs, dtype=np.float32)
        target[:7] = qpos[:7]
        target[7] = target[8] = finger_pos
        return target

    def plan_pick(cx, cy):
        grasp_z = surface_z + CUBE_SIZE[2] / 2.0 + HAND_OFFSET
        hover_z = grasp_z + HOVER_DZ
        lift_z = grasp_z + LIFT_DZ

        traj = []
        traj += lerp(HOME_QPOS.copy(), solve_ik([cx, cy, hover_z]), args.approach_steps)
        traj += lerp(traj[-1], solve_ik([cx, cy, grasp_z]), args.descend_steps)
        traj += lerp(traj[-1], solve_ik([cx, cy, grasp_z], FINGER_CLOSED),
                     args.grasp_hold_steps)
        traj += lerp(traj[-1], solve_ik([cx, cy, lift_z], FINGER_CLOSED),
                     args.lift_steps)
        traj += [traj[-1].copy() for _ in range(args.lift_hold_steps)]
        return traj

    # ------------------------------------------------------------------
    # Create LeRobot dataset
    # ------------------------------------------------------------------
    try:
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    except ImportError:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

    extra_dims = 0
    extra_names = []
    if args.add_goal:
        extra_dims += 2
        extra_names += ["cube_x", "cube_y"]
    if args.add_phase:
        extra_dims += 1
        extra_names += ["phase_t_over_T"]
    obs_dim = n_dofs + extra_dims
    obs_names = MOTOR_NAMES + extra_names

    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (obs_dim,),
            "names": obs_names,
        },
        "action": {
            "dtype": "float32",
            "shape": (n_dofs,),
            "names": MOTOR_NAMES,
        },
        "observation.images.up": {
            "dtype": "image" if args.no_videos else "video",
            "shape": (3, 480, 640),
            "names": ["channel", "height", "width"],
        },
        "observation.images.side": {
            "dtype": "image" if args.no_videos else "video",
            "shape": (3, 480, 640),
            "names": ["channel", "height", "width"],
        },
    }

    # Try to create dataset, if it exists, load it instead
    try:
        dataset = LeRobotDataset.create(
            repo_id=args.repo_id,
            fps=args.fps,
            features=features,
            robot_type="franka",
            use_videos=(not args.no_videos),
        )
        print(f"[gen] LeRobot dataset created: {args.repo_id}")
    except FileExistsError:
        print(f"[gen] Dataset {args.repo_id} already exists, loading existing dataset...")
        dataset = LeRobotDataset(args.repo_id)
        print(f"[gen] Loaded existing dataset: {dataset.num_episodes} episodes, {len(dataset)} frames")
        print(f"[gen] WARNING: Will append new episodes to existing dataset")

    # ------------------------------------------------------------------
    # Pre-generate randomized cube positions (robot-local frame)
    # ------------------------------------------------------------------
    rng = random.Random(args.seed)
    cube_half_z = CUBE_SIZE[2] / 2.0

    episode_points = []
    for _ in range(args.n_episodes):
        dx = rng.uniform(*CUBE_RANGE_X)
        dy = rng.uniform(*CUBE_RANGE_Y)
        world_pos = to_world(base_xy, yaw_rad, surface_z, (dx, dy, cube_half_z))
        episode_points.append((dx, dy, world_pos))

    out_dir = Path(args.output_dir) / "data" / "custom_scene_gen"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[gen] scene={args.scene} anchor={args.anchor}")
    print(f"[gen] base=({base_xy[0]:.2f}, {base_xy[1]:.2f}) yaw={yaw}° "
          f"surface_z={surface_z:.3f}")
    print(f"[gen] cube_dx=[{CUBE_RANGE_X[0]:.2f}, {CUBE_RANGE_X[1]:.2f}]  "
          f"cube_dy=[{CUBE_RANGE_Y[0]:.2f}, {CUBE_RANGE_Y[1]:.2f}]")
    print(f"[gen] {args.n_episodes} episodes to generate")

    # ------------------------------------------------------------------
    # Generate episodes
    # ------------------------------------------------------------------
    frames_per_episode = None
    episode_labels = []

    smoke_dir = None
    if args.smoke_dump_pngs:
        smoke_dir = Path(args.smoke_dump_pngs)
        smoke_dir.mkdir(parents=True, exist_ok=True)
        print(f"[smoke] will dump PNGs of first episode to {smoke_dir}")

    def _save_png(path, arr):
        try:
            from PIL import Image
            Image.fromarray(arr).save(path)
        except ImportError:
            import imageio.v2 as imageio
            imageio.imwrite(path, arr)

    for ep in range(args.n_episodes):
        dx, dy, (cx, cy, cz) = episode_points[ep]

        reset_episode((cx, cy, cz))

        traj = plan_pick(cx, cy)
        if frames_per_episode is None:
            frames_per_episode = len(traj)
            print(f"[gen] trajectory: {frames_per_episode} frames/episode")

        if ep == 0 and smoke_dir is not None:
            last = max(frames_per_episode - 1, 0)
            smoke_frames = sorted({0,
                                   last // 4,
                                   last // 2,
                                   (3 * last) // 4,
                                   last})
        else:
            smoke_frames = set()
        side_tag = "wrist" if info.get("camera_layout") == "up_wrist" else "side"

        cube_z_hist = []
        total_steps = len(traj)
        for step_idx, target in enumerate(traj):
            joints = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            parts = [joints]
            if args.add_goal:
                cube_xy = to_numpy(cube.get_pos())[:2].astype(np.float32)
                parts.append(cube_xy)
            if args.add_phase:
                t_norm = np.array([(step_idx + 1) / total_steps], dtype=np.float32)
                parts.append(t_norm)
            state = np.concatenate(parts) if len(parts) > 1 else joints

            img_up = render_cam(cam_up)
            img_side = render_cam(cam_side)

            if step_idx in smoke_frames:
                _save_png(smoke_dir / f"ep0_f{step_idx:03d}_up.png", img_up)
                _save_png(smoke_dir / f"ep0_f{step_idx:03d}_{side_tag}.png", img_side)
                print(f"[smoke] dumped up+{side_tag} PNG at frame {step_idx}/{total_steps}")

            franka.control_dofs_position(target, motors_dof)
            scene.step()

            cur_cz = float(to_numpy(cube.get_pos())[2])
            cube_z_hist.append(cur_cz)

            dataset.add_frame({
                "observation.state": state,
                "action": np.array(target, dtype=np.float32),
                "observation.images.up": img_up,
                "observation.images.side": img_side,
                "task": args.task,
            })

        base_z_cube = cz
        cz_max = max(cube_z_hist) if cube_z_hist else base_z_cube
        cz_end = cube_z_hist[-1] if cube_z_hist else base_z_cube
        lifted = [z >= base_z_cube + args.success_lift_delta for z in cube_z_hist]
        sustain = 0
        sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)

        success = (
            (cz_max - base_z_cube) >= args.success_lift_delta
            and sustain_max >= args.success_sustain_frames
            and (cz_end - base_z_cube) >= args.success_final_delta
        )
        fail_reasons = []
        if (cz_max - base_z_cube) < args.success_lift_delta:
            fail_reasons.append("max_lift_too_small")
        if sustain_max < args.success_sustain_frames:
            fail_reasons.append("lift_not_sustained")
        if (cz_end - base_z_cube) < args.success_final_delta:
            fail_reasons.append("final_height_too_low")

        episode_labels.append({
            "episode_index": ep,
            "cube_local_dxdy": [float(dx), float(dy)],
            "cube_world_xy": [float(cx), float(cy)],
            "base_z_cube": float(base_z_cube),
            "cube_z_max": float(cz_max),
            "cube_z_end": float(cz_end),
            "max_lift_delta": float(cz_max - base_z_cube),
            "end_lift_delta": float(cz_end - base_z_cube),
            "sustain_frames": int(sustain_max),
            "success": bool(success),
            "failure_reasons": fail_reasons,
        })

        dataset.save_episode()
        status = "OK" if success else "FAIL"
        print(f"[gen] ep {ep+1}/{args.n_episodes} [{status}] "
              f"dx={dx:.3f} dy={dy:.3f} world=({cx:.3f},{cy:.3f}) "
              f"lift={cz_max - base_z_cube:.4f}m sustain={sustain_max}")

    # ------------------------------------------------------------------
    # Save dataset + summary
    # ------------------------------------------------------------------
    if hasattr(dataset, "consolidate"):
        dataset.consolidate(run_compute_stats=True)
    print(f"[gen] dataset saved: {dataset.root}")

    success_ids = [e["episode_index"] for e in episode_labels if e["success"]]
    failure_ids = [e["episode_index"] for e in episode_labels if not e["success"]]
    sr = len(success_ids) / max(len(episode_labels), 1)

    summary = {
        "repo_id": args.repo_id,
        "n_episodes": args.n_episodes,
        "frames_per_episode": frames_per_episode,
        "total_frames": args.n_episodes * int(frames_per_episode or 0),
        "fps": args.fps,
        "robot": "franka_panda",
        "n_dofs": n_dofs,
        "action_space": "joint_position (rad)",
        "scene": args.scene,
        "anchor": args.anchor,
        "camera_layout": info.get("camera_layout", "up_side"),
        "base_xy": list(base_xy),
        "yaw": yaw,
        "surface_z": surface_z,
        "cube_dx_range": list(CUBE_RANGE_X),
        "cube_dy_range": list(CUBE_RANGE_Y),
        "success_episode_ids": success_ids,
        "failure_episode_ids": failure_ids,
        "success_rate": sr,
    }

    (out_dir / "gen_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "episode_labels.json").write_text(
        json.dumps(episode_labels, indent=2), encoding="utf-8")
    (out_dir / "success_episode_ids.json").write_text(
        json.dumps({"success_episode_ids": success_ids}, indent=2), encoding="utf-8")
    print(f"\n[gen] success_rate: {len(success_ids)}/{args.n_episodes} = {sr:.0%}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
