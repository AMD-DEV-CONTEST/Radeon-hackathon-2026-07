#!/usr/bin/env python3
"""Env-A: scripted Franka pick-and-place into a fixed basket (LeRobot dataset).

Reuses the workshop kitchen scene (Franka + rustic_kitchen + up/wrist cams).
Fruit = red box proxy (physically reliable); basket = fixed open receptacle.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Workshop helpers resolve their own asset paths via Path(__file__).resolve().
from pick_common import (  # noqa: E402
    CUBE_SIZE,
    FINGER_CLOSED,
    FINGER_OPEN,
    FORCE_LOWER,
    FORCE_UPPER,
    add_pick_args,
    attach_wrist_cam,
    build_scene,
)
from scene_placement import (  # noqa: E402
    CUBE_RANGE_X,
    CUBE_RANGE_Y,
    HAND_OFFSET,
    HOVER_DZ,
    LIFT_DZ,
    to_world,
)
from genesis_scene_utils import (  # noqa: E402
    HOME_QPOS,
    JOINT_NAMES,
    KP,
    KV,
    ensure_display,
    set_franka_home,
    to_numpy,
    lerp,
)


DEFAULT_TASK = "Pick up the fruit and place it in the basket."
BASKET_LOCAL_XY = (0.48, -0.28)
BASKET_OUTER = (0.16, 0.16, 0.06)
BASKET_INNER_HALF = (0.06, 0.06)
BASKET_WALL = 0.01


def _add_basket(scene, gs, base_xy, yaw_rad, surface_z, local_xy):
    """Fixed open-top basket: floor plate + four walls."""
    cx, cy, cz = to_world(
        base_xy, yaw_rad, surface_z, (local_xy[0], local_xy[1], BASKET_OUTER[2] / 2.0)
    )
    ox, oy, oz = BASKET_OUTER
    w = BASKET_WALL
    color = (0.45, 0.32, 0.18, 1.0)
    mat = gs.materials.Rigid(friction=1.2)

    # Floor
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(ox, oy, w),
            pos=(cx, cy, surface_z + w / 2.0),
            fixed=True,
        ),
        material=mat,
        surface=gs.surfaces.Default(color=color),
    )
    # Walls (+x, -x, +y, -y)
    wall_h = oz
    wall_z = surface_z + wall_h / 2.0
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(w, oy, wall_h), pos=(cx + ox / 2.0 - w / 2.0, cy, wall_z), fixed=True
        ),
        material=mat,
        surface=gs.surfaces.Default(color=color),
    )
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(w, oy, wall_h), pos=(cx - ox / 2.0 + w / 2.0, cy, wall_z), fixed=True
        ),
        material=mat,
        surface=gs.surfaces.Default(color=color),
    )
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(ox, w, wall_h), pos=(cx, cy + oy / 2.0 - w / 2.0, wall_z), fixed=True
        ),
        material=mat,
        surface=gs.surfaces.Default(color=color),
    )
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(ox, w, wall_h), pos=(cx, cy - oy / 2.0 + w / 2.0, wall_z), fixed=True
        ),
        material=mat,
        surface=gs.surfaces.Default(color=color),
    )
    place_xy = (cx, cy)
    place_z = surface_z + wall_h + 0.02
    return {
        "center_xy": place_xy,
        "surface_z": surface_z,
        "rim_z": surface_z + wall_h,
        "inner_half": BASKET_INNER_HALF,
        "place_z": place_z,
    }


def fruit_in_basket(fruit_pos, basket_info) -> bool:
    fx, fy, fz = float(fruit_pos[0]), float(fruit_pos[1]), float(fruit_pos[2])
    cx, cy = basket_info["center_xy"]
    hx, hy = basket_info["inner_half"]
    return (
        abs(fx - cx) <= hx
        and abs(fy - cy) <= hy
        and fz <= basket_info["rim_z"] + 0.02
        and fz >= basket_info["surface_z"] - 0.01
    )


def main():
    ap = argparse.ArgumentParser(description="Env-A kitchen pick-and-place data generation")
    ap.add_argument("--n-episodes", type=int, default=120)
    ap.add_argument("--repo-id", default="local/franka-kitchen-fruit-place-120ep")
    ap.add_argument("--output-dir", default=str(_PROJECT_DIR / "output"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--no-videos", action="store_true")
    ap.add_argument("--smoke-dump-pngs", type=str, default=None)
    ap.add_argument("--keep-failures", action="store_true",
                    help="Save failed episodes into the LeRobot dataset (default: only successes)")

    # Trajectory timing
    ap.add_argument("--settle-steps", type=int, default=30)
    ap.add_argument("--approach-steps", type=int, default=40)
    ap.add_argument("--descend-steps", type=int, default=30)
    ap.add_argument("--grasp-hold-steps", type=int, default=20)
    ap.add_argument("--lift-steps", type=int, default=30)
    ap.add_argument("--lift-hold-steps", type=int, default=10)
    ap.add_argument("--transport-steps", type=int, default=45)
    ap.add_argument("--place-descend-steps", type=int, default=30)
    ap.add_argument("--release-hold-steps", type=int, default=20)
    ap.add_argument("--retract-steps", type=int, default=25)

    # Success
    ap.add_argument("--success-lift-delta", type=float, default=0.02)
    ap.add_argument("--success-sustain-frames", type=int, default=8)

    # Basket / fruit ranges
    ap.add_argument("--basket-dx", type=float, default=BASKET_LOCAL_XY[0])
    ap.add_argument("--basket-dy", type=float, default=BASKET_LOCAL_XY[1])
    ap.add_argument("--fruit-x-min", type=float, default=CUBE_RANGE_X[0])
    ap.add_argument("--fruit-x-max", type=float, default=CUBE_RANGE_X[1])
    ap.add_argument("--fruit-y-min", type=float, default=-0.15)
    ap.add_argument("--fruit-y-max", type=float, default=0.20)

    add_pick_args(ap)
    ap.set_defaults(anchor="floor_origin", camera_layout="up_wrist")
    args = ap.parse_args()

    MOTOR_NAMES = [f"{j}.pos" for j in JOINT_NAMES]
    n_dofs = len(JOINT_NAMES)
    GRASP_QUAT = np.array([0, 1, 0, 0], dtype=np.float32)

    ensure_display()
    import genesis as gs
    import torch

    gs.init(backend=(gs.cpu if getattr(args, "cpu", False) else gs.gpu), logging_level="warning")

    scene, franka, fruit, cam_ov, cam_front, cam_up, cam_side, info = build_scene(args, gs)

    surface_z = info["surface_z"]
    base_xy = info["base_xy"]
    yaw = info["yaw"]
    yaw_rad = math.radians(yaw)

    basket_info = _add_basket(
        scene, gs, base_xy, yaw_rad, surface_z, (args.basket_dx, args.basket_dy)
    )
    print(
        f"[basket] center_xy={basket_info['center_xy']} rim_z={basket_info['rim_z']:.3f} "
        f"local=({args.basket_dx:.2f},{args.basket_dy:.2f})"
    )

    scene.build()
    attach_wrist_cam(args, franka, cam_side, gs)

    motors_dof = set_franka_home(franka)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)
    ee = franka.get_link("hand")

    def render_cam(cam):
        rgb, _, _, _ = cam.render(rgb=True, depth=False, segmentation=False, normal=False)
        arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
        if arr.ndim == 4:
            arr = arr[0]
        return arr.astype(np.uint8)

    def reset_episode(fruit_world_pos):
        franka.set_dofs_position(HOME_QPOS, motors_dof)
        franka.control_dofs_position(HOME_QPOS, motors_dof)
        franka.zero_all_dofs_velocity()
        cx, cy, cz = fruit_world_pos
        fruit.set_pos(
            torch.tensor([cx, cy, cz], dtype=torch.float32, device=gs.device).unsqueeze(0)
        )
        fruit.set_quat(
            torch.tensor([1, 0, 0, 0], dtype=torch.float32, device=gs.device).unsqueeze(0)
        )
        fruit.zero_all_dofs_velocity()
        for _ in range(args.settle_steps):
            scene.step()

    def solve_ik(pos, finger_pos=FINGER_OPEN):
        qpos = to_numpy(
            franka.inverse_kinematics(
                link=ee,
                pos=np.array(pos, dtype=np.float32),
                quat=GRASP_QUAT,
            )
        )
        target = np.zeros(n_dofs, dtype=np.float32)
        target[:7] = qpos[:7]
        target[7] = target[8] = finger_pos
        return target

    def plan_pick_and_place(fx, fy):
        grasp_z = surface_z + CUBE_SIZE[2] / 2.0 + HAND_OFFSET
        hover_z = grasp_z + HOVER_DZ
        lift_z = grasp_z + LIFT_DZ
        bx, by = basket_info["center_xy"]
        place_z = basket_info["place_z"]
        place_hover_z = place_z + 0.08

        traj = []
        traj += lerp(HOME_QPOS.copy(), solve_ik([fx, fy, hover_z]), args.approach_steps)
        traj += lerp(traj[-1], solve_ik([fx, fy, grasp_z]), args.descend_steps)
        traj += lerp(
            traj[-1], solve_ik([fx, fy, grasp_z], FINGER_CLOSED), args.grasp_hold_steps
        )
        traj += lerp(
            traj[-1], solve_ik([fx, fy, lift_z], FINGER_CLOSED), args.lift_steps
        )
        traj += [traj[-1].copy() for _ in range(args.lift_hold_steps)]
        traj += lerp(
            traj[-1],
            solve_ik([bx, by, place_hover_z], FINGER_CLOSED),
            args.transport_steps,
        )
        traj += lerp(
            traj[-1],
            solve_ik([bx, by, place_z], FINGER_CLOSED),
            args.place_descend_steps,
        )
        traj += lerp(
            traj[-1],
            solve_ik([bx, by, place_z], FINGER_OPEN),
            args.release_hold_steps,
        )
        traj += lerp(
            traj[-1],
            solve_ik([bx, by, place_hover_z], FINGER_OPEN),
            args.retract_steps,
        )
        return traj

    try:
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    except ImportError:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (n_dofs,),
            "names": MOTOR_NAMES,
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

    # Refuse silent appends: Env-A datasets must be generated once and frozen.
    try:
        from lerobot.datasets.lerobot_dataset import HF_LEROBOT_HOME
    except Exception:
        HF_LEROBOT_HOME = Path.home() / ".cache" / "huggingface" / "lerobot"
    existing = Path(HF_LEROBOT_HOME) / args.repo_id
    if existing.exists():
        print(f"[error] Dataset already exists at {existing}")
        print("[error] Choose a new --repo-id or delete it deliberately. Refusing to append.")
        sys.exit(2)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=features,
        robot_type="franka",
        use_videos=(not args.no_videos),
    )
    print(f"[gen] LeRobot dataset created: {args.repo_id}")

    rng = random.Random(args.seed)
    fruit_half_z = CUBE_SIZE[2] / 2.0
    episode_points = []
    for _ in range(args.n_episodes):
        dx = rng.uniform(args.fruit_x_min, args.fruit_x_max)
        dy = rng.uniform(args.fruit_y_min, args.fruit_y_max)
        world_pos = to_world(base_xy, yaw_rad, surface_z, (dx, dy, fruit_half_z))
        episode_points.append((dx, dy, world_pos))

    out_dir = Path(args.output_dir) / "data" / "env_a_pick_place"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[gen] scene={args.scene} anchor={args.anchor} cam={args.camera_layout}")
    print(f"[gen] task='{args.task}'")
    print(
        f"[gen] fruit_xy=[{args.fruit_x_min:.2f},{args.fruit_x_max:.2f}] x "
        f"[{args.fruit_y_min:.2f},{args.fruit_y_max:.2f}]"
    )
    print(f"[gen] {args.n_episodes} episodes requested (success-only default)")

    frames_per_episode = None
    episode_labels = []
    n_saved = 0
    n_attempted = 0

    smoke_dir = None
    if args.smoke_dump_pngs:
        smoke_dir = Path(args.smoke_dump_pngs)
        smoke_dir.mkdir(parents=True, exist_ok=True)

    def _save_png(path, arr):
        try:
            from PIL import Image

            Image.fromarray(arr).save(path)
        except ImportError:
            import imageio.v2 as imageio

            imageio.imwrite(path, arr)

    # Keep generating until we collect n_episodes successes (or hard cap).
    hard_cap = args.n_episodes * 3
    point_idx = 0
    while n_saved < args.n_episodes and n_attempted < hard_cap:
        if point_idx >= len(episode_points):
            dx = rng.uniform(args.fruit_x_min, args.fruit_x_max)
            dy = rng.uniform(args.fruit_y_min, args.fruit_y_max)
            world_pos = to_world(base_xy, yaw_rad, surface_z, (dx, dy, fruit_half_z))
            episode_points.append((dx, dy, world_pos))
        dx, dy, (cx, cy, cz) = episode_points[point_idx]
        point_idx += 1
        n_attempted += 1

        reset_episode((cx, cy, cz))
        traj = plan_pick_and_place(cx, cy)
        if frames_per_episode is None:
            frames_per_episode = len(traj)
            print(f"[gen] trajectory: {frames_per_episode} frames/episode")

        smoke_frames = set()
        if n_attempted == 1 and smoke_dir is not None:
            last = max(frames_per_episode - 1, 0)
            smoke_frames = {0, last // 4, last // 2, (3 * last) // 4, last}

        fruit_z_hist = []
        frame_buffer = []
        for step_idx, target in enumerate(traj):
            joints = to_numpy(franka.get_dofs_position(motors_dof)).astype(np.float32)
            img_up = render_cam(cam_up)
            img_side = render_cam(cam_side)
            if step_idx in smoke_frames:
                _save_png(smoke_dir / f"ep0_f{step_idx:03d}_up.png", img_up)
                _save_png(smoke_dir / f"ep0_f{step_idx:03d}_wrist.png", img_side)

            franka.control_dofs_position(target, motors_dof)
            scene.step()
            fpos = to_numpy(fruit.get_pos())
            fruit_z_hist.append(float(fpos[2]))
            frame_buffer.append(
                {
                    "observation.state": joints,
                    "action": np.array(target, dtype=np.float32),
                    "observation.images.up": img_up,
                    "observation.images.side": img_side,
                    "task": args.task,
                }
            )

        # Extra settle after release so fruit can rest in basket
        for _ in range(15):
            scene.step()
        final_pos = to_numpy(fruit.get_pos())

        base_z_fruit = cz
        cz_max = max(fruit_z_hist) if fruit_z_hist else base_z_fruit
        lifted = [z >= base_z_fruit + args.success_lift_delta for z in fruit_z_hist]
        sustain = sustain_max = 0
        for ok in lifted:
            sustain = sustain + 1 if ok else 0
            sustain_max = max(sustain, sustain_max)

        lifted_ok = (cz_max - base_z_fruit) >= args.success_lift_delta and (
            sustain_max >= args.success_sustain_frames
        )
        placed_ok = fruit_in_basket(final_pos, basket_info)
        success = bool(lifted_ok and placed_ok)

        fail_reasons = []
        if not lifted_ok:
            fail_reasons.append("lift_failed")
        if not placed_ok:
            fail_reasons.append("not_in_basket")

        label = {
            "attempt_index": n_attempted - 1,
            "saved_episode_index": n_saved if success or args.keep_failures else None,
            "fruit_local_dxdy": [float(dx), float(dy)],
            "fruit_world_xy": [float(cx), float(cy)],
            "fruit_final_xyz": [float(x) for x in final_pos[:3]],
            "max_lift_delta": float(cz_max - base_z_fruit),
            "sustain_frames": int(sustain_max),
            "lifted_ok": bool(lifted_ok),
            "placed_ok": bool(placed_ok),
            "success": success,
            "failure_reasons": fail_reasons,
        }
        episode_labels.append(label)

        if success or args.keep_failures:
            for fr in frame_buffer:
                dataset.add_frame(fr)
            dataset.save_episode()
            if success:
                n_saved += 1
            status = "OK" if success else "FAIL_SAVED"
        else:
            status = "FAIL_SKIP"

        print(
            f"[gen] attempt {n_attempted}/{hard_cap} saved={n_saved}/{args.n_episodes} "
            f"[{status}] dx={dx:.3f} dy={dy:.3f} "
            f"lift={cz_max - base_z_fruit:.3f}m sustain={sustain_max} "
            f"final=({final_pos[0]:.3f},{final_pos[1]:.3f},{final_pos[2]:.3f}) "
            f"reasons={fail_reasons}"
        )

    if hasattr(dataset, "consolidate"):
        dataset.consolidate(run_compute_stats=True)

    success_ids = [
        e["saved_episode_index"]
        for e in episode_labels
        if e["success"] and e["saved_episode_index"] is not None
    ]
    summary = {
        "repo_id": args.repo_id,
        "task": args.task,
        "n_episodes_requested": args.n_episodes,
        "n_attempts": n_attempted,
        "n_success_saved": n_saved,
        "frames_per_episode": frames_per_episode,
        "fps": args.fps,
        "robot": "franka_panda",
        "object": "red_box_fruit_proxy",
        "scene": args.scene,
        "anchor": args.anchor,
        "camera_layout": info.get("camera_layout"),
        "basket_local_xy": [args.basket_dx, args.basket_dy],
        "basket_center_xy": list(basket_info["center_xy"]),
        "fruit_xy_range": [
            [args.fruit_x_min, args.fruit_x_max],
            [args.fruit_y_min, args.fruit_y_max],
        ],
        "seed": args.seed,
        "success_episode_ids": success_ids,
        "dataset_root": str(getattr(dataset, "root", "")),
    }
    (out_dir / "gen_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "episode_labels.json").write_text(
        json.dumps(episode_labels, indent=2), encoding="utf-8"
    )
    print(f"[gen] saved summary -> {out_dir / 'gen_summary.json'}")
    print(f"[gen] success_saved: {n_saved}/{args.n_episodes} (attempts={n_attempted})")
    if n_saved < args.n_episodes:
        print("[warn] did not reach requested success count; inspect failures before training")
        sys.exit(1)


if __name__ == "__main__":
    main()
