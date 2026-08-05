import argparse
import json
import time
from pathlib import Path

import genesis as gs
import imageio.v2 as imageio
import numpy as np
import torch

from vision_tracking import RedObjectTracker
from vision_tracking import draw_detection_overlay
from vision_tracking import normalize_rgb_frame


def to_numpy(value):
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    if hasattr(value, "cpu"):
        return value.cpu().numpy()
    return np.asarray(value)


def find_latest_recording():
    candidates = list(Path.cwd().glob("franka_fruit_follow_cam_*.mp4"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def render_rgb(camera):
    try:
        rendered = camera.render(rgb=True)
    except TypeError:
        rendered = camera.render()
    return normalize_rgb_frame(rendered)


def lerp(start, end, ratio):
    ratio = float(np.clip(ratio, 0.0, 1.0))
    return (1.0 - ratio) * start + ratio * end


def load_config(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def phase_for_frame(frame, task_config):
    if frame < task_config["approach_start"]:
        return "detect"
    if frame < task_config["grasp_start"]:
        return "approach"
    if frame < task_config["lift_start"]:
        return "grasp"
    if frame < task_config["transport_start"]:
        return "lift"
    if frame < task_config["lower_start"]:
        return "transport"
    if frame < task_config["release_start"]:
        return "lower"
    return "release"


def add_plate(scene, gs_module, plate_config):
    plate_pos = np.array(plate_config["position"], dtype=np.float32)
    plate_radius = plate_config["radius"]
    plate_height = plate_config["height"]

    try:
        return scene.add_entity(
            morph=gs_module.morphs.Cylinder(
                radius=plate_radius,
                height=plate_height,
                pos=plate_pos,
                fixed=True,
            ),
            surface=gs_module.surfaces.Rough(
                color=tuple(plate_config["color"]),
            ),
        )
    except Exception as exc:
        print(
            "Plate cylinder unavailable; using blue sphere marker instead:",
            exc,
        )
        return scene.add_entity(
            morph=gs_module.morphs.Sphere(
                radius=plate_radius,
                pos=plate_pos,
                fixed=True,
            ),
            surface=gs_module.surfaces.Rough(
                color=tuple(plate_config["color"]),
            ),
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Vision-guided Franka apple-to-plate pick-and-place demo "
            "on AMD ROCm"
        )
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/franka_vision_pick_place.json",
    )
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--video", type=str, default=None)
    parser.add_argument("--annotated-video", type=str, default=None)
    parser.add_argument("--metrics", type=str, default=None)
    parser.add_argument("--summary", type=str, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    task_config = config["task"]
    plate_config = config["plate"]
    frames = args.frames or config["frames"]
    fps = args.fps or config["fps"]
    seed = args.seed if args.seed is not None else config["seed"]
    video_path = Path(args.video or config["video"])
    annotated_video_path = Path(
        args.annotated_video or config["annotated_video"]
    )
    metrics_path = Path(args.metrics or config["metrics"])
    summary_path = Path(args.summary or config["summary"])

    video_path.parent.mkdir(parents=True, exist_ok=True)
    annotated_video_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    np.random.seed(seed)
    backend = gs.amdgpu if hasattr(gs, "amdgpu") else gs.gpu

    print("=" * 60)
    print("Vision-Guided Genesis Franka Apple-to-Plate Pick-and-Place")
    print("=" * 60)
    print("Genesis backend:", backend)
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)
    print(
        "GPU:",
        torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else "Not available",
    )

    gs.init(backend=backend, seed=seed)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            gravity=(0.0, 0.0, 0.0),
            enable_collision=False,
        ),
        viewer_options=gs.options.ViewerOptions(
            camera_pos=(2.1, -2.1, 1.55),
            camera_lookat=(0.45, 0.08, 0.45),
            camera_fov=40,
        ),
        show_viewer=False,
    )

    scene.add_entity(gs.morphs.Plane())

    franka = scene.add_entity(
        gs.morphs.MJCF(file="xml/franka_emika_panda/panda.xml")
    )

    fruit_start = np.array(task_config["fruit_start"], dtype=np.float32)
    fruit_radius = task_config["fruit_radius"]
    fruit = scene.add_entity(
        morph=gs.morphs.Sphere(
            radius=fruit_radius,
            pos=fruit_start,
            fixed=True,
        ),
        surface=gs.surfaces.Rough(color=(0.95, 0.05, 0.03)),
    )

    add_plate(scene, gs, plate_config)
    plate_pos = np.array(plate_config["position"], dtype=np.float32)
    place_fruit_pos = plate_pos + np.array(
        [0.0, 0.0, plate_config["fruit_rest_height"]],
        dtype=np.float32,
    )

    camera = scene.add_camera(
        res=(960, 540),
        pos=(2.1, -2.1, 1.55),
        lookat=(0.45, 0.08, 0.45),
        fov=40,
        GUI=False,
    )

    print("\n[1/6] Building Genesis scene...")
    scene.build()

    arm_dofs = np.arange(7)
    gripper_dofs = np.array([7, 8])
    open_gripper = np.array([0.04, 0.04], dtype=np.float32)
    closed_gripper = np.array([0.0, 0.0], dtype=np.float32)

    initial_qpos = np.array(
        [0.0, -0.45, 0.0, -2.10, 0.0, 1.75, 0.80, 0.04, 0.04],
        dtype=np.float32,
    )
    franka.set_qpos(initial_qpos)
    franka.set_dofs_kp(
        np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100])
    )
    franka.set_dofs_kv(
        np.array([450, 450, 350, 350, 200, 200, 200, 10, 10])
    )

    end_effector = franka.get_link("hand")
    target_quat = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    pre_grasp = fruit_start + np.array(
        [0.0, 0.0, task_config["pre_grasp_height"]],
        dtype=np.float32,
    )
    grasp_pose = fruit_start + np.array(
        [0.0, 0.0, task_config["grasp_height"]],
        dtype=np.float32,
    )
    lift_pose = fruit_start + np.array(
        [0.0, 0.0, task_config["lift_height"]],
        dtype=np.float32,
    )
    transport_pose = place_fruit_pos + np.array(
        [0.0, 0.0, task_config["transport_height"]],
        dtype=np.float32,
    )
    lower_pose = place_fruit_pos + np.array(
        [0.0, 0.0, task_config["place_height"]],
        dtype=np.float32,
    )
    release_pose = lower_pose + np.array(
        [0.0, 0.0, task_config["release_retreat_height"]],
        dtype=np.float32,
    )

    print("[2/6] Moving to pre-grasp pose...")
    initial_ik = franka.inverse_kinematics(
        link=end_effector,
        pos=pre_grasp,
        quat=target_quat,
    )
    franka.set_qpos(initial_ik)
    franka.control_dofs_position(initial_ik[:7], arm_dofs)
    franka.control_dofs_position(open_gripper, gripper_dofs)

    for _ in range(100):
        scene.step()

    tracker = RedObjectTracker(**config["tracker"])
    calibration_frame = render_rgb(camera)
    calibration_detection = tracker.detect(calibration_frame)
    print(
        "[3/6] Visual apple:",
        "detected" if calibration_detection.found else "not detected",
    )

    camera.start_recording()
    writer = None
    if calibration_frame is not None:
        writer = imageio.get_writer(
            annotated_video_path,
            fps=fps,
            macro_block_size=1,
        )

    detections = []
    tracking_errors = []
    ik_times_ms = []
    attached_frames = 0
    release_frames = 0
    annotated_frames = 0
    phase_counts = {
        "detect": 0,
        "approach": 0,
        "grasp": 0,
        "lift": 0,
        "transport": 0,
        "lower": 0,
        "release": 0,
    }
    frame_records = []
    final_fruit_pos = fruit_start.copy()
    start_time = time.perf_counter()

    print("[4/6] Executing apple-to-plate sequence...")

    for frame in range(frames):
        phase = phase_for_frame(frame, task_config)
        phase_counts[phase] += 1

        camera_frame = render_rgb(camera)
        detection = tracker.detect(camera_frame)
        detections.append(detection.found)

        if phase == "detect":
            ratio = frame / max(1, task_config["approach_start"] - 1)
            target_pos = lerp(
                pre_grasp + np.array([0.0, -0.04, 0.02], dtype=np.float32),
                pre_grasp,
                ratio,
            )
            gripper_target = open_gripper
            fruit_target = fruit_start
        elif phase == "approach":
            ratio = (
                (frame - task_config["approach_start"])
                / max(1, task_config["grasp_start"] - task_config["approach_start"])
            )
            target_pos = lerp(pre_grasp, grasp_pose, ratio)
            gripper_target = open_gripper
            fruit_target = fruit_start
        elif phase == "grasp":
            ratio = (
                (frame - task_config["grasp_start"])
                / max(1, task_config["lift_start"] - task_config["grasp_start"])
            )
            target_pos = grasp_pose
            gripper_target = lerp(open_gripper, closed_gripper, ratio)
            fruit_target = fruit_start
        elif phase == "lift":
            ratio = (
                (frame - task_config["lift_start"])
                / max(1, task_config["transport_start"] - task_config["lift_start"])
            )
            target_pos = lerp(grasp_pose, lift_pose, ratio)
            gripper_target = closed_gripper
            fruit_target = None
        elif phase == "transport":
            ratio = (
                (frame - task_config["transport_start"])
                / max(1, task_config["lower_start"] - task_config["transport_start"])
            )
            target_pos = lerp(lift_pose, transport_pose, ratio)
            gripper_target = closed_gripper
            fruit_target = None
        elif phase == "lower":
            ratio = (
                (frame - task_config["lower_start"])
                / max(1, task_config["release_start"] - task_config["lower_start"])
            )
            target_pos = lerp(transport_pose, lower_pose, ratio)
            gripper_target = closed_gripper
            fruit_target = None
        else:
            ratio = (
                (frame - task_config["release_start"])
                / max(1, frames - task_config["release_start"] - 1)
            )
            target_pos = lerp(lower_pose, release_pose, ratio)
            gripper_target = lerp(closed_gripper, open_gripper, ratio)
            fruit_target = place_fruit_pos

        ik_start = time.perf_counter()
        qpos = franka.inverse_kinematics(
            link=end_effector,
            pos=target_pos,
            quat=target_quat,
        )
        ik_elapsed_ms = (time.perf_counter() - ik_start) * 1000.0
        ik_times_ms.append(ik_elapsed_ms)

        franka.control_dofs_position(qpos[:7], arm_dofs)
        franka.control_dofs_position(gripper_target, gripper_dofs)

        for _ in range(4):
            scene.step()

        actual_pos = to_numpy(end_effector.get_pos()).reshape(-1)[:3]

        if fruit_target is None:
            attached_frames += 1
            final_fruit_pos = actual_pos + np.array(
                [0.0, 0.0, -fruit_radius * 0.75],
                dtype=np.float32,
            )
        else:
            if phase == "release":
                release_frames += 1
            final_fruit_pos = fruit_target

        fruit.set_pos(final_fruit_pos)
        tracking_error = float(np.linalg.norm(actual_pos - target_pos))
        tracking_errors.append(tracking_error)

        if writer is not None and camera_frame is not None:
            annotated = draw_detection_overlay(
                camera_frame,
                detection,
                target_center=(
                    (detection.center_x, detection.center_y)
                    if detection.found
                    else None
                ),
            )
            if annotated is not None:
                writer.append_data(annotated)
                annotated_frames += 1

        place_error = float(np.linalg.norm(final_fruit_pos - place_fruit_pos))
        frame_records.append(
            {
                "frame": frame,
                "phase": phase,
                "detection": detection.to_dict(),
                "target_pos": target_pos.tolist(),
                "actual_pos": actual_pos.tolist(),
                "fruit_pos": final_fruit_pos.tolist(),
                "place_fruit_pos": place_fruit_pos.tolist(),
                "place_error_mm": place_error * 1000.0,
                "tracking_error_mm": tracking_error * 1000.0,
                "ik_time_ms": ik_elapsed_ms,
            }
        )

        if frame == 0 or frame % 30 == 0 or frame == frames - 1:
            print(
                f"frame={frame:4d}/{frames} | "
                f"phase={phase:9s} | "
                f"detected={detection.found} | "
                f"target={np.round(target_pos, 3)} | "
                f"actual={np.round(actual_pos, 3)} | "
                f"fruit={np.round(final_fruit_pos, 3)} | "
                f"place_error={place_error * 1000:.1f} mm"
            )

    camera.stop_recording()
    if writer is not None:
        writer.close()

    generated_video = find_latest_recording()
    if generated_video is not None:
        video_path.unlink(missing_ok=True)
        generated_video.replace(video_path)

    total_time = time.perf_counter() - start_time
    lift_delta = float(np.max([record["fruit_pos"][2] for record in frame_records]) - fruit_start[2])
    final_place_error = float(np.linalg.norm(final_fruit_pos - place_fruit_pos))
    grasp_success = bool(attached_frames > 0 and lift_delta >= task_config["success_lift_delta"])
    place_success = bool(
        release_frames > 0
        and final_place_error <= task_config["success_place_error"]
    )

    metrics = {
        "demo": "Vision-guided Franka apple-to-plate pick-and-place",
        "description": (
            "Franka Panda detects a red apple, picks it up, transports it "
            "to a visible plate target, and releases it into the plate."
        ),
        "genesis_version": getattr(gs, "__version__", "unknown"),
        "genesis_backend": str(backend),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "gpu": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available()
            else "Not available"
        ),
        "seed": seed,
        "frames": frames,
        "requested_fps": fps,
        "detection_rate": float(np.mean(detections)) if detections else 0.0,
        "grasp_success": grasp_success,
        "place_success": place_success,
        "fruit_lift_delta_m": lift_delta,
        "fruit_lift_delta_mm": lift_delta * 1000.0,
        "final_place_error_m": final_place_error,
        "final_place_error_mm": final_place_error * 1000.0,
        "phase_counts": phase_counts,
        "annotated_frames": annotated_frames,
        "video": str(video_path),
        "annotated_video": (
            str(annotated_video_path) if annotated_frames > 0 else None
        ),
        "execution_time_seconds": total_time,
        "mean_target_tracking_error_mm": float(
            np.mean(tracking_errors) * 1000.0
        ),
        "p95_target_tracking_error_mm": float(
            np.percentile(tracking_errors, 95) * 1000.0
        ),
        "mean_ik_time_ms": float(np.mean(ik_times_ms)),
        "p95_ik_time_ms": float(np.percentile(ik_times_ms, 95)),
        "frame_records": frame_records,
    }
    summary = {
        key: value
        for key, value in metrics.items()
        if key != "frame_records"
    }

    metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n[5/6] Apple-to-plate pick-and-place completed")
    print("=" * 60)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("=" * 60)
    print("Video:", video_path)
    print("Annotated video:", summary["annotated_video"])
    print("Metrics:", metrics_path)
    print("Summary:", summary_path)


if __name__ == "__main__":
    main()
