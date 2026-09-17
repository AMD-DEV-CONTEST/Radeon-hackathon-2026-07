"""
Franka Panda pick-cube data generation for LeRobot.

Genesis scene: Franka 7-DOF + cube + 2 cameras.
IK trajectory: home -> pre-hover -> descend -> grasp -> lift.
Output: LeRobot dataset with observation.state (9D), action (9D), images.

Based on:
  - Genesis IK tutorial: https://genesis-world.readthedocs.io/en/latest/user_guide/getting_started/inverse_kinematics_motion_planning.html
  - SO-101 pipeline: 03_pose_randomization/scripts/01_gen_pick_data.py

Usage:
  python 01_franka_pick_data.py --n-episodes 10 --repo-id local/franka-genesis-pick
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


# ---- constants ----
JOINT_NAMES = [
    "joint1", "joint2", "joint3", "joint4",
    "joint5", "joint6", "joint7",
    "finger_joint1", "finger_joint2",
]
MOTOR_NAMES = [f"{j}.pos" for j in JOINT_NAMES]

HOME_QPOS = np.array([0, -0.3, 0, -2.2, 0, 2.0, 0.79, 0.04, 0.04], dtype=np.float32)
KP = np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100], dtype=np.float32)
KV = np.array([450, 450, 350, 350, 200, 200, 200, 10, 10], dtype=np.float32)
FORCE_LOWER = np.array([-87, -87, -87, -87, -12, -12, -12, -100, -100], dtype=np.float32)
FORCE_UPPER = np.array([87, 87, 87, 87, 12, 12, 12, 100, 100], dtype=np.float32)

CUBE_SIZE = (0.04, 0.04, 0.04)
GRASP_QUAT = np.array([0, 1, 0, 0], dtype=np.float32)  # top-down grasp
FINGER_OPEN = 0.04
FINGER_CLOSED = 0.01
GRASP_FORCE = -0.5


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


def lerp(a, b, n):
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    return [a + (b - a) * (i + 1) / max(n, 1) for i in range(n)]


def render_cam(cam):
    rgb, _, _, _ = cam.render(rgb=True, depth=False, segmentation=False, normal=False)
    arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
    if arr.ndim == 4:
        arr = arr[0]
    return arr.astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description="Franka pick-cube data generation")
    ap.add_argument("--n-episodes", type=int, default=10)
    ap.add_argument("--repo-id", default="local/franka-genesis-pick")
    ap.add_argument("--output-dir", default="./output")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cube-x-min", type=float, default=0.4)
    ap.add_argument("--cube-x-max", type=float, default=0.7)
    ap.add_argument("--cube-y-min", type=float, default=-0.2)
    ap.add_argument("--cube-y-max", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cube-friction", type=float, default=1.5)
    ap.add_argument("--hover-z", type=float, default=0.25)
    ap.add_argument("--grasp-z", type=float, default=0.135)
    ap.add_argument("--lift-z", type=float, default=0.30)
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--approach-steps", type=int, default=40)
    ap.add_argument("--descend-steps", type=int, default=30)
    ap.add_argument("--grasp-hold-steps", type=int, default=20)
    ap.add_argument("--lift-steps", type=int, default=30)
    ap.add_argument("--lift-hold-steps", type=int, default=15)
    ap.add_argument("--success-lift-delta", type=float, default=0.02)
    ap.add_argument("--success-sustain-frames", type=int, default=8)
    ap.add_argument("--success-final-delta", type=float, default=0.01)
    ap.add_argument("--task", default="Pick up the cube.")
    ap.add_argument(
        "--camera-layout",
        type=str,
        default="up_side",
        choices=["up_side", "up_wrist"],
        help="Camera layout: fixed top-down+side or top-down+wrist(camera attached to hand link).",
    )
    ap.add_argument("--wrist-cam-pos-x", type=float, default=0.05,
                    help="Wrist camera offset x in hand-link frame (meters)")
    ap.add_argument("--wrist-cam-pos-y", type=float, default=0.00,
                    help="Wrist camera offset y in hand-link frame (meters)")
    ap.add_argument("--wrist-cam-pos-z", type=float, default=-0.08,
                    help="Wrist camera offset z in hand-link frame (meters). Negative = above hand.")
    ap.add_argument("--wrist-cam-lookat-x", type=float, default=0.00,
                    help="Wrist camera lookat x in hand-link frame (meters)")
    ap.add_argument("--wrist-cam-lookat-y", type=float, default=0.00,
                    help="Wrist camera lookat y in hand-link frame (meters)")
    ap.add_argument("--wrist-cam-lookat-z", type=float, default=0.10,
                    help="Wrist camera lookat z in hand-link frame (meters). Positive = below hand.")
    ap.add_argument("--wrist-cam-up-x", type=float, default=0.0,
                    help="Wrist camera up-vector x in hand-link frame")
    ap.add_argument("--wrist-cam-up-y", type=float, default=0.0,
                    help="Wrist camera up-vector y in hand-link frame")
    ap.add_argument("--wrist-cam-up-z", type=float, default=-1.0,
                    help="Wrist camera up-vector z in hand-link frame. -1 = world-up when hand-local z points down.")
    ap.add_argument("--wrist-cam-fov", type=float, default=65.0,
                    help="Wrist camera field-of-view in degrees")
    ap.add_argument("--add-phase", action="store_true",
                    help="Append normalized time t/T to observation.state (9D→10D)")
    ap.add_argument("--add-goal", action="store_true",
                    help="Append cube (x,y) to observation.state (9D→11D)")
    ap.add_argument("--no-bbox-detection", action="store_true",
                    help="Disable box_box_detection (workaround for AMD LLVM fatal)")
    ap.add_argument("--no-videos", action="store_true",
                    help="Store images as PNG instead of video (faster, more disk)")
    args = ap.parse_args()

    ensure_display()
    import genesis as gs
    import torch
    from genesis.utils.geom import pos_lookat_up_to_T

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
        cam_aux = scene.add_camera(
            res=(640, 480), pos=(0.55, -0.55, cube_z + 0.25),
            lookat=(0.55, 0.0, cube_z + 0.10), fov=50, GUI=False,
        )
    else:
        # For wrist camera, these are link-local pose parameters.
        cam_aux = scene.add_camera(
            res=(640, 480),
            pos=(args.wrist_cam_pos_x, args.wrist_cam_pos_y, args.wrist_cam_pos_z),
            lookat=(args.wrist_cam_lookat_x, args.wrist_cam_lookat_y, args.wrist_cam_lookat_z),
            fov=args.wrist_cam_fov,
            GUI=False,
        )
    scene.build()

    motors_dof = [franka.get_joint(name).dofs_idx_local[0] for name in JOINT_NAMES]
    arm_dof = motors_dof[:7]
    finger_dof = motors_dof[7:]

    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)

    n_dofs = len(JOINT_NAMES)
    end_effector = franka.get_link("hand")

    if args.camera_layout == "up_wrist":
        # Define wrist camera in hand-link frame so it follows the arm dynamically.
        wrist_pos = torch.tensor(
            [args.wrist_cam_pos_x, args.wrist_cam_pos_y, args.wrist_cam_pos_z],
            dtype=gs.tc_float,
            device=gs.device,
        )
        wrist_lookat = torch.tensor(
            [args.wrist_cam_lookat_x, args.wrist_cam_lookat_y, args.wrist_cam_lookat_z],
            dtype=gs.tc_float,
            device=gs.device,
        )
        wrist_up = torch.tensor(
            [args.wrist_cam_up_x, args.wrist_cam_up_y, args.wrist_cam_up_z],
            dtype=gs.tc_float,
            device=gs.device,
        )
        wrist_offset_T = pos_lookat_up_to_T(wrist_pos, wrist_lookat, wrist_up)
        try:
            cam_aux.attach(rigid_link=end_effector, offset_T=wrist_offset_T)
        except TypeError:
            # Backward-compatible path for older Genesis attach signature.
            cam_aux.attach(end_effector, wrist_offset_T)

    def reset_scene(cx, cy):
        franka.set_dofs_position(HOME_QPOS, motors_dof)
        franka.control_dofs_position(HOME_QPOS, motors_dof)
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

    def solve_ik(pos, quat=GRASP_QUAT, finger_pos=FINGER_OPEN):
        """Solve IK for arm, append finger positions."""
        qpos = to_numpy(franka.inverse_kinematics(
            link=end_effector,
            pos=np.array(pos, dtype=np.float32),
            quat=np.array(quat, dtype=np.float32),
        ))
        target = np.zeros(n_dofs, dtype=np.float32)
        target[:7] = qpos[:7]
        target[7] = finger_pos
        target[8] = finger_pos
        return target

    def plan_pick_trajectory(cx, cy):
        """Plan full pick trajectory: approach -> descend -> grasp -> lift."""
        hover_pos = [cx, cy, args.hover_z]
        grasp_pos = [cx, cy, args.grasp_z]
        lift_pos = [cx, cy, args.lift_z]

        q_home = HOME_QPOS.copy()
        q_hover = solve_ik(hover_pos, finger_pos=FINGER_OPEN)
        q_grasp_open = solve_ik(grasp_pos, finger_pos=FINGER_OPEN)
        q_grasp_closed = solve_ik(grasp_pos, finger_pos=FINGER_CLOSED)
        q_lift = solve_ik(lift_pos, finger_pos=FINGER_CLOSED)

        traj = []
        traj += lerp(q_home, q_hover, args.approach_steps)
        traj += lerp(q_hover, q_grasp_open, args.descend_steps)
        traj += lerp(q_grasp_open, q_grasp_closed, args.grasp_hold_steps)
        traj += lerp(q_grasp_closed, q_lift, args.lift_steps)
        traj += [q_lift.copy() for _ in range(args.lift_hold_steps)]
        return traj

    # ---- create LeRobot dataset ----
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

    # ---- generate episodes ----
    rng = random.Random(args.seed)
    x_range = (args.cube_x_min, args.cube_x_max)
    y_range = (args.cube_y_min, args.cube_y_max)

    episode_points = []
    for _ in range(args.n_episodes):
        cx = rng.uniform(x_range[0], x_range[1])
        cy = rng.uniform(y_range[0], y_range[1])
        episode_points.append((cx, cy))

    out_dir = Path(args.output_dir) / "data" / "franka_gen_pick"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[gen] cube x_range={x_range}, y_range={y_range}")
    print(f"[gen] {args.n_episodes} episodes to generate")

    frames_per_episode = None
    episode_labels = []

    for ep in range(args.n_episodes):
        cx, cy = episode_points[ep]

        reset_scene(cx, cy)

        traj = plan_pick_trajectory(cx, cy)
        if frames_per_episode is None:
            frames_per_episode = len(traj)
            print(f"[gen] trajectory: {frames_per_episode} frames/episode")

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
            img_side = render_cam(cam_aux)

            franka.control_dofs_position(target, motors_dof)
            scene.step()

            cz = float(to_numpy(cube.get_pos())[2])
            cube_z_hist.append(cz)

            dataset.add_frame({
                "observation.state": state,
                "action": np.array(target, dtype=np.float32),
                "observation.images.up": img_up,
                "observation.images.side": img_side,
                "task": args.task,
            })

        base_z = cube_z
        cz_max = max(cube_z_hist) if cube_z_hist else base_z
        cz_end = cube_z_hist[-1] if cube_z_hist else base_z
        lifted = [z >= base_z + args.success_lift_delta for z in cube_z_hist]
        sustain = 0
        sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)

        success = (
            (cz_max - base_z) >= args.success_lift_delta
            and sustain_max >= args.success_sustain_frames
            and (cz_end - base_z) >= args.success_final_delta
        )
        fail_reasons = []
        if (cz_max - base_z) < args.success_lift_delta:
            fail_reasons.append("max_lift_too_small")
        if sustain_max < args.success_sustain_frames:
            fail_reasons.append("lift_not_sustained")
        if (cz_end - base_z) < args.success_final_delta:
            fail_reasons.append("final_height_too_low")

        episode_labels.append({
            "episode_index": ep,
            "cube_xy": [float(cx), float(cy)],
            "base_z": float(base_z),
            "cube_z_max": float(cz_max),
            "cube_z_end": float(cz_end),
            "max_lift_delta": float(cz_max - base_z),
            "end_lift_delta": float(cz_end - base_z),
            "sustain_frames": int(sustain_max),
            "success": bool(success),
            "failure_reasons": fail_reasons,
        })

        dataset.save_episode()
        status = "OK" if success else "FAIL"
        print(f"[gen] ep {ep+1}/{args.n_episodes} [{status}] "
              f"cube=({cx:.3f},{cy:.3f}) lift={cz_max-base_z:.4f}m "
              f"sustain={sustain_max}")

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
        "camera_layout": args.camera_layout,
        "camera_keys": ["observation.images.up", "observation.images.side"],
        "cube_xy_range": {"x": list(x_range), "y": list(y_range)},
        "hover_z": args.hover_z,
        "grasp_z": args.grasp_z,
        "lift_z": args.lift_z,
        "success_episode_ids": success_ids,
        "failure_episode_ids": failure_ids,
        "success_rate": sr,
    }

    (out_dir / "gen_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "episode_labels.json").write_text(json.dumps(episode_labels, indent=2), encoding="utf-8")
    (out_dir / "success_episode_ids.json").write_text(
        json.dumps({"success_episode_ids": success_ids}, indent=2), encoding="utf-8")
    print(f"\n[gen] success_rate: {len(success_ids)}/{args.n_episodes} = {sr:.0%}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
