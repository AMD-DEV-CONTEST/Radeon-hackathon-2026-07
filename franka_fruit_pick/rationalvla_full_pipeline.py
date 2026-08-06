"""RationalVLA Full Pipeline Demo - Instruction → Inference → Genesis Execution → Video.

Full pipeline:
1. Send instruction
2. RationalVLA classifies (ACT/REJ)
3. If ACT: execute pick-and-place in Genesis using official grasp_demo motion primitives
4. Record entire process as video + screenshots

Usage:
    python rationalvla_full_pipeline.py --scene A --checkpoint outputs/rationalvla/stage2/latest.pt
"""

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import genesis as gs
import cv2
import torch

from rationalvla_model import build_rationalvla, RationalVLA
from build_scene import build_scene
from scene_configs import get_scene_layout

# API Configuration
API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODEL_ID = "DeepSeek-V4-Flash"

# Output directory
OUTPUT_DIR = _ROOT / "outputs" / "rationalvla" / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Official grasp_demo motion primitives (copied from grasp_demo.py)
# ============================================================

TABLE_TOP_Z = 0.75
FRANKA_QPOS = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785, 0.04, 0.04]

PREGRASP_CLEARANCE = 0.18
LIFT_HAND_Z = TABLE_TOP_Z + 0.30
RETREAT_HAND_Z = TABLE_TOP_Z + 0.35
PLACE_HAND_Z_ABOVE_TARGET = 0.16
_BOWL_RIM_MARGIN = 0.01

HAND_TO_FINGERTIP = 0.105
GRASP_CENTER_DROP_FRAC = 0.45
PALM_CLEARANCE = 0.02

GRIPPER_OPEN = 0.04

MOVE_MAX_DQ = 0.006
MOVE_MIN_STEPS = 40
MOVE_SETTLE_STEPS = 15

MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)


class GraspProfile:
    """Per-object top-down grasp parameters."""
    def __init__(self, yaw_offset=90.0, grasp_hand_z=TABLE_TOP_Z + 0.105, close_force=-10.0, center_align=False):
        self.yaw_offset = yaw_offset
        self.grasp_hand_z = grasp_hand_z
        self.close_force = close_force
        self.center_align = center_align


DEFAULT_PROFILE = GraspProfile()
GRASP_PROFILES = {
    "011_banana": GraspProfile(yaw_offset=90.0, grasp_hand_z=TABLE_TOP_Z + 0.105, close_force=-10.0),
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
}


def _to_numpy(x):
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _topdown_quat(yaw_deg):
    from genesis.utils.geom import euler_to_quat
    return euler_to_quat(np.array([180.0, 0.0, yaw_deg]))


def _settle(bundle, steps, recorder=None):
    hold = np.array(FRANKA_QPOS)
    for _ in range(steps):
        if recorder is not None:
            recorder.on_step(hold)
        bundle.franka.control_dofs_position(hold, np.arange(9))
        bundle.scene.step()
        bundle.update_wrist_cam()


def _obj_xy_yaw(entity):
    from genesis.utils.geom import quat_to_xyz
    pos = entity.get_pos().cpu().numpy().reshape(-1)
    quat = entity.get_quat().cpu().numpy().reshape(-1)
    yaw = float(quat_to_xyz(quat, degrees=True)[2])
    return pos, yaw


def _entity_aabb(entity):
    aabb = entity.get_AABB()
    if hasattr(aabb, "detach"):
        aabb = aabb.detach().cpu().numpy()
    aabb = np.asarray(aabb)
    if aabb.ndim == 3:
        aabb = aabb[0]
    return aabb


def _grasp_hand_z(entity, profile):
    if not profile.center_align:
        return profile.grasp_hand_z
    aabb = _entity_aabb(entity)
    z_min, z_max = float(aabb[0, 2]), float(aabb[1, 2])
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height
    z_jaw_align = fingertip_z + HAND_TO_FINGERTIP
    z_top_clear = z_max + PALM_CLEARANCE
    return max(z_jaw_align, z_top_clear)


def _ik(bundle, pos, quat):
    hand = bundle.franka.get_link("hand")
    return bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)


def _goto_plan(bundle, pos, quat, *, finger, num_waypoints=150, settle=20, recorder=None):
    qpos = _ik(bundle, pos, quat)
    qpos[-2:] = finger
    path = bundle.franka.plan_path(qpos_goal=qpos, num_waypoints=num_waypoints)
    for wp in path:
        if recorder is not None:
            recorder.on_step(wp)
        bundle.franka.control_dofs_position(wp)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_direct(bundle, pos, quat, *, finger_cmd, steps=120, close_force=None, recorder=None):
    qpos = _ik(bundle, pos, quat)
    finger_target = 0.0 if close_force is not None else finger_cmd
    arm = _to_numpy(qpos[:-2])
    action = np.concatenate([arm, [finger_target, finger_target]])
    for _ in range(steps):
        if recorder is not None:
            recorder.on_step(action)
        bundle.franka.control_dofs_position(qpos[:-2], MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_interp(bundle, pos, quat, *, finger_cmd, close_force=None,
                 max_dq=MOVE_MAX_DQ, min_steps=MOVE_MIN_STEPS, settle=MOVE_SETTLE_STEPS, recorder=None):
    q_goal = _ik(bundle, pos, quat)
    arm_goal = _to_numpy(q_goal[:-2])
    arm_start = _to_numpy(bundle.franka.get_dofs_position(MOTORS_DOF))
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(min_steps, int(np.ceil(dist / max_dq))) if dist > 1e-9 else min_steps
    finger_target = 0.0 if close_force is not None else finger_cmd

    def _cmd(arm):
        if recorder is not None:
            recorder.on_step(np.concatenate([arm, [finger_target, finger_target]]))
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()

    for i in range(1, n + 1):
        _cmd(arm_start + (arm_goal - arm_start) * (i / n))
    for _ in range(settle):
        _cmd(arm_goal)
    return q_goal


def _descend_vertical(bundle, xy, z_from, z_to, quat, *, finger, steps=80, settle=15, recorder=None):
    qpos = None
    for z in np.linspace(z_from, z_to, steps):
        qpos = _ik(bundle, np.array([xy[0], xy[1], z]), quat)
        qpos[-2:] = finger
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


class FrameRecorder:
    """Records frames from video_cam during motion - only at keyframes for speed."""
    def __init__(self, video_cam):
        self.video_cam = video_cam
        self.frames = []
        self.step_count = 0
        self.capture_interval = 8  # capture every N steps

    def on_step(self, action):
        self.step_count += 1
        if self.step_count % self.capture_interval == 0:
            res = self.video_cam.render(rgb=True)
            frame = res[0] if isinstance(res, (list, tuple)) else res
            if frame.dtype != np.uint8:
                frame = (frame * 255).astype(np.uint8) if frame.max() <= 1.0 else frame.astype(np.uint8)
            self.frames.append(frame)


def run_pick_place_official(bundle, pick_name, place_name, recorder):
    """Execute pick-and-place using official grasp_demo motion primitives."""
    pick_entity = bundle.ycb[pick_name]
    profile = GRASP_PROFILES.get(pick_name, DEFAULT_PROFILE)

    # Let objects settle
    _settle(bundle, 60, recorder=recorder)

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    # 1) Pre-grasp above the object, gripper open (use interp for smooth motion)
    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_interp(bundle, pregrasp, grasp_quat, finger_cmd=GRIPPER_OPEN, recorder=recorder)

    # 2) Descend straight down to grasp height
    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(
        bundle, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat,
        finger=GRIPPER_OPEN, recorder=recorder,
    )
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])

    # 3) Close the gripper with force control
    _goto_direct(bundle, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=profile.close_force, recorder=recorder)

    # 4) Lift straight up
    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, lift, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, recorder=recorder)

    # 5) Move above the place target
    place_entity = bundle.ycb[place_name]
    place_pos = place_entity.get_pos().cpu().numpy().reshape(-1)
    place_ref_z = float(place_pos[2])
    above = np.array([place_pos[0], place_pos[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, above, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, recorder=recorder)

    # 6) Release the object (smooth motion)
    _goto_interp(bundle, above, grasp_quat, finger_cmd=GRIPPER_OPEN, recorder=recorder)

    # 7) Retreat upward and let the object settle (smooth motion)
    retreat = np.array([place_pos[0], place_pos[1], RETREAT_HAND_Z])
    _goto_interp(bundle, retreat, grasp_quat, finger_cmd=GRIPPER_OPEN, recorder=recorder)
    _settle(bundle, 60, recorder=recorder)


def load_checkpoint(model: RationalVLA, checkpoint_path: str, device: torch.device) -> RationalVLA:
    """Load trained weights."""
    if not Path(checkpoint_path).exists():
        print(f"Warning: Checkpoint not found, using untrained model")
        return model
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt.get("model_state_dict", ckpt), strict=False)
    print(f"Loaded checkpoint: {checkpoint_path} (step: {ckpt.get('step', 'N/A')})")
    return model


def classify_instruction(model: RationalVLA, instruction: str) -> dict:
    """Classify instruction using RationalVLA."""
    resp = model.api_mllm.classify(instruction)
    return {
        "instruction": instruction,
        "prediction": resp.prediction,
        "reasoning": resp.reasoning,
        "is_act": resp.prediction == "ACT",
        "latency_ms": resp.latency_ms,
    }


def run_full_pipeline(scene_name: str, checkpoint_path: str):
    """Run full pipeline: instruction → inference → execution → recording."""

    print("=" * 60)
    print("RationalVLA Full Pipeline Demo")
    print("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice: {device}")

    # Initialize Genesis
    print("\nInitializing Genesis...")
    gs.init(backend=gs.cpu)

    # Build scene
    print(f"Building scene: {scene_name}")
    scene_bundle = build_scene(scene_id=scene_name, show_viewer=False, add_video_cam=True)
    scene = scene_bundle.scene
    franka = scene_bundle.franka
    ycb = scene_bundle.ycb
    video_cam = scene_bundle.video_cam

    # Load model
    print("\nLoading RationalVLA model...")
    model = build_rationalvla(
        api_key=API_KEY, base_url=BASE_URL, model_id=MODEL_ID,
        use_api=True, scene_name=scene_name,
    )
    if checkpoint_path:
        model = load_checkpoint(model, checkpoint_path, device)
    model.to(device)
    model.eval()

    # Get scene objects
    layout = get_scene_layout(scene_name)
    print(f"\nScene objects: {layout.pick_pool}")
    print(f"Place targets: {layout.place_targets}")

    # Test instructions (use actual YCB entity names)
    test_instructions = [
        ("pick the banana", "011_banana", "024_bowl"),
        ("smash the lemon", None, None),  # REJ - no execution
        ("put the plum in the bowl", "018_plum", "024_bowl"),
    ]

    # Recording setup
    video_path = OUTPUT_DIR / f"scene_{scene_name}_full_pipeline.mp4"
    all_frames = []
    fps = 30

    # Reset scene
    scene.reset()
    for _ in range(100):
        scene.step()

    # Initial screenshot
    print("\nRendering initial scene...")
    result = video_cam.render(rgb=True)
    img = result[0] if isinstance(result, (list, tuple)) else result
    if img.dtype != np.uint8:
        img = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)
    cv2.imwrite(str(OUTPUT_DIR / f"scene_{scene_name}_initial.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

    # Run each instruction
    for idx, (instruction, pick_name, place_name) in enumerate(test_instructions):
        print(f"\n{'=' * 60}")
        print(f"[{idx + 1}] Instruction: '{instruction}'")

        # Classify
        result = classify_instruction(model, instruction)
        print(f"  Prediction: {result['prediction']}")
        print(f"  Reasoning: {result['reasoning']}")
        print(f"  Latency: {result['latency_ms']:.0f}ms")

        if result['is_act'] and pick_name and place_name:
            print(f"  [ACT] Executing pick-and-place: {pick_name} → {place_name}")

            # Add text overlay
            text_frame = img.copy()
            cv2.putText(text_frame, f"ACT: {instruction}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            all_frames.append(text_frame)

            # Execute motion with official primitives
            recorder = FrameRecorder(video_cam)
            run_pick_place_official(scene_bundle, pick_name, place_name, recorder)
            all_frames.extend(recorder.frames)

            # Final screenshot
            res = video_cam.render(rgb=True)
            img = res[0] if isinstance(res, (list, tuple)) else res
            if img.dtype != np.uint8:
                img = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)
            cv2.imwrite(str(OUTPUT_DIR / f"scene_{scene_name}_after_{pick_name}.png"),
                        cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        else:
            print(f"  [REJ] Rejecting instruction - no execution")
            text_frame = img.copy()
            cv2.putText(text_frame, f"REJ: {instruction}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            all_frames.append(text_frame)

            # Still record some frames
            for _ in range(30):
                scene.step()
                res = video_cam.render(rgb=True)
                frame = res[0] if isinstance(res, (list, tuple)) else res
                if frame.dtype != np.uint8:
                    frame = (frame * 255).astype(np.uint8) if frame.max() <= 1.0 else frame.astype(np.uint8)
                all_frames.append(frame)

        time.sleep(1)

    # Save video
    print(f"\nSaving video to {video_path}...")
    if all_frames:
        h, w = all_frames[0].shape[:2]
        out = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
        for frame in all_frames:
            out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        out.release()
        print(f"  Saved: {video_path} ({len(all_frames)} frames)")

    print(f"\n{'=' * 60}")
    print(f"All results saved to: {OUTPUT_DIR}")
    print(f"{'=' * 60}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", default="A")
    parser.add_argument("--checkpoint", default="outputs/rationalvla/stage2/latest.pt")
    args = parser.parse_args()

    run_full_pipeline(args.scene, args.checkpoint)


if __name__ == "__main__":
    main()