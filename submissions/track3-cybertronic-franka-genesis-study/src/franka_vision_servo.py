import argparse
import json
import math
import time
from pathlib import Path

import genesis as gs
import imageio.v2 as imageio
import numpy as np
import torch

from vision_tracking import ExponentialSmoother
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
    candidates = list(
        Path.cwd().glob("franka_fruit_follow_cam_*.mp4")
    )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def load_config(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_rgb(camera):
    try:
        rendered = camera.render(rgb=True)
    except TypeError:
        rendered = camera.render()

    return normalize_rgb_frame(rendered)


def clip_target(target, initial_target, servo_config):
    clipped = target.copy()
    clipped[1] = np.clip(
        clipped[1],
        initial_target[1] - servo_config["max_y_offset"],
        initial_target[1] + servo_config["max_y_offset"],
    )
    clipped[2] = np.clip(
        clipped[2],
        initial_target[2] - servo_config["max_z_offset"],
        initial_target[2] + servo_config["max_z_offset"],
    )
    return clipped.astype(np.float32)


def fruit_position_at_frame(frame):
    phase = 2.0 * math.pi * frame / 300.0
    return np.array(
        [
            0.55 + 0.06 * math.sin(phase),
            0.17 * math.sin(phase),
            0.43 + 0.10 * math.sin(2.0 * phase),
        ],
        dtype=np.float32,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Vision-guided Genesis Franka fruit tracking on AMD ROCm"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/franka_vision_tracking.json",
    )
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--video", type=str, default=None)
    parser.add_argument("--annotated-video", type=str, default=None)
    parser.add_argument("--metrics", type=str, default=None)
    parser.add_argument("--summary", type=str, default=None)
    parser.add_argument(
        "--mode",
        choices=("vision", "vision_smooth", "baseline"),
        default="vision_smooth",
        help="baseline uses simulation coordinates for comparison.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
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

    backend = (
        gs.amdgpu
        if hasattr(gs, "amdgpu")
        else gs.gpu
    )

    print("=" * 60)
    print("Vision-Guided Genesis Franka Fruit Tracking")
    print("=" * 60)
    print("Mode:", args.mode)
    print("Genesis backend:", backend)
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)
    print(
        "GPU:",
        torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else "Not available",
    )

    gs.init(
        backend=backend,
        seed=seed,
    )

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(
            dt=0.01,
            substeps=2,
        ),
        rigid_options=gs.options.RigidOptions(
            gravity=(0.0, 0.0, 0.0),
            enable_collision=False,
        ),
        viewer_options=gs.options.ViewerOptions(
            camera_pos=(2.1, -2.1, 1.5),
            camera_lookat=(0.45, 0.0, 0.4),
            camera_fov=40,
        ),
        show_viewer=False,
    )

    scene.add_entity(
        gs.morphs.Plane(),
    )

    franka = scene.add_entity(
        gs.morphs.MJCF(
            file="xml/franka_emika_panda/panda.xml",
        ),
    )

    fruit_start = fruit_position_at_frame(0)

    fruit = scene.add_entity(
        morph=gs.morphs.Sphere(
            radius=0.055,
            pos=fruit_start,
            fixed=True,
        ),
        surface=gs.surfaces.Rough(
            color=(0.95, 0.05, 0.03),
        ),
    )

    camera = scene.add_camera(
        res=(960, 540),
        pos=(2.1, -2.1, 1.45),
        lookat=(0.45, 0.0, 0.4),
        fov=40,
        GUI=False,
    )

    print("\n[1/5] Building Genesis scene...")
    scene.build()

    arm_dofs = np.arange(7)

    initial_qpos = np.array(
        [
            0.0,
            -0.45,
            0.0,
            -2.10,
            0.0,
            1.75,
            0.80,
            0.04,
            0.04,
        ],
        dtype=np.float32,
    )

    franka.set_qpos(initial_qpos)
    franka.set_dofs_kp(
        np.array(
            [
                4500,
                4500,
                3500,
                3500,
                2000,
                2000,
                2000,
                100,
                100,
            ],
            dtype=np.float32,
        )
    )
    franka.set_dofs_kv(
        np.array(
            [
                450,
                450,
                350,
                350,
                200,
                200,
                200,
                10,
                10,
            ],
            dtype=np.float32,
        )
    )

    end_effector = franka.get_link("hand")
    target_quat = np.array(
        [0.0, 1.0, 0.0, 0.0],
        dtype=np.float32,
    )

    servo_config = config["servo"]
    initial_target = fruit_start + np.array(
        [0.0, 0.0, servo_config["tool_height_offset"]],
        dtype=np.float32,
    )

    print("[2/5] Moving to initial tracking pose...")
    initial_ik = franka.inverse_kinematics(
        link=end_effector,
        pos=initial_target,
        quat=target_quat,
    )
    franka.set_qpos(initial_ik)
    franka.control_dofs_position(
        initial_ik[:7],
        arm_dofs,
    )

    for _ in range(100):
        scene.step()

    tracker = RedObjectTracker(**config["tracker"])
    smoother = ExponentialSmoother(
        alpha=servo_config["smoothing_alpha"],
    )

    print("[3/5] Calibrating visual reference...")
    calibration_frame = render_rgb(camera)
    calibration_detection = tracker.detect(calibration_frame)

    if calibration_detection.found:
        reference_center = np.array(
            [
                calibration_detection.center_x,
                calibration_detection.center_y,
            ],
            dtype=np.float32,
        )
    elif calibration_frame is not None:
        height, width = calibration_frame.shape[:2]
        reference_center = np.array(
            [width / 2.0, height / 2.0],
            dtype=np.float32,
        )
    else:
        reference_center = np.array(
            [480.0, 270.0],
            dtype=np.float32,
        )

    print("Visual reference center:", np.round(reference_center, 2))
    print(
        "Calibration detection:",
        "found" if calibration_detection.found else "not found",
    )

    print("[4/5] Recording vision-guided trajectory...")
    camera.start_recording()

    writer = None
    if calibration_frame is not None:
        writer = imageio.get_writer(
            annotated_video_path,
            fps=fps,
            macro_block_size=1,
        )

    current_target = initial_target.copy()
    tracking_errors = []
    vision_target_errors = []
    pixel_errors = []
    ik_times_ms = []
    detections = []
    frame_records = []
    annotated_frames = 0

    start_time = time.perf_counter()

    for frame in range(frames):
        fruit_pos = fruit_position_at_frame(frame)
        fruit.set_pos(fruit_pos)

        true_target = fruit_pos + np.array(
            [0.0, 0.0, servo_config["tool_height_offset"]],
            dtype=np.float32,
        )

        camera_frame = render_rgb(camera)
        detection = tracker.detect(camera_frame)
        detections.append(detection.found)

        if args.mode == "baseline":
            target_pos = true_target
            pixel_error = None
        elif detection.found:
            detected_center = np.array(
                [detection.center_x, detection.center_y],
                dtype=np.float32,
            )
            image_error = detected_center - reference_center
            pixel_error = float(np.linalg.norm(image_error))

            estimated_target = np.array(
                [
                    servo_config["fixed_x"],
                    initial_target[1]
                    + servo_config["pixel_gain_y"] * image_error[0],
                    initial_target[2]
                    - servo_config["pixel_gain_z"] * image_error[1],
                ],
                dtype=np.float32,
            )
            estimated_target = clip_target(
                estimated_target,
                initial_target,
                servo_config,
            )

            if args.mode == "vision_smooth":
                target_pos = smoother.update(estimated_target)
            else:
                target_pos = estimated_target

            current_target = target_pos.copy()
        else:
            target_pos = current_target
            pixel_error = None

        if pixel_error is not None:
            pixel_errors.append(pixel_error)

        vision_target_error = float(
            np.linalg.norm(target_pos - true_target)
        )
        vision_target_errors.append(vision_target_error)

        ik_start = time.perf_counter()
        qpos = franka.inverse_kinematics(
            link=end_effector,
            pos=target_pos,
            quat=target_quat,
        )
        ik_elapsed_ms = (
            time.perf_counter() - ik_start
        ) * 1000.0
        ik_times_ms.append(ik_elapsed_ms)

        franka.control_dofs_position(
            qpos[:7],
            arm_dofs,
        )

        for _ in range(4):
            scene.step()

        actual_pos = to_numpy(
            end_effector.get_pos()
        ).reshape(-1)[:3]

        tracking_error = float(
            np.linalg.norm(actual_pos - true_target)
        )
        tracking_errors.append(tracking_error)

        if writer is not None and camera_frame is not None:
            annotated = draw_detection_overlay(
                camera_frame,
                detection,
                reference_center=reference_center,
                target_center=(
                    (detection.center_x, detection.center_y)
                    if detection.found
                    else None
                ),
            )
            if annotated is not None:
                writer.append_data(annotated)
                annotated_frames += 1

        frame_records.append(
            {
                "frame": frame,
                "detection": detection.to_dict(),
                "pixel_error": pixel_error,
                "target_pos": target_pos.tolist(),
                "true_target": true_target.tolist(),
                "actual_pos": actual_pos.tolist(),
                "tracking_error_mm": tracking_error * 1000.0,
                "vision_target_error_mm": (
                    vision_target_error * 1000.0
                ),
                "ik_time_ms": ik_elapsed_ms,
            }
        )

        if (
            frame == 0
            or frame % 30 == 0
            or frame == frames - 1
        ):
            status = "detected" if detection.found else "fallback"
            print(
                f"frame={frame:4d}/{frames} | "
                f"{status} | "
                f"pixel_error={pixel_error} | "
                f"target={np.round(target_pos, 3)} | "
                f"true={np.round(true_target, 3)} | "
                f"actual={np.round(actual_pos, 3)} | "
                f"error={tracking_error * 1000:.1f} mm | "
                f"IK={ik_elapsed_ms:.2f} ms"
            )

    camera.stop_recording()

    if writer is not None:
        writer.close()

    generated_video = find_latest_recording()

    if generated_video is not None:
        video_path.unlink(missing_ok=True)
        generated_video.replace(video_path)

    total_time = time.perf_counter() - start_time
    detection_rate = (
        float(np.mean(detections))
        if detections
        else 0.0
    )

    metrics = {
        "demo": "Vision-guided Franka fruit tracking",
        "description": (
            "Franka Panda follows a moving red fruit using camera-based "
            "detection, image-space visual servoing, Genesis IK, and joint "
            "PD control."
        ),
        "mode": args.mode,
        "genesis_version": getattr(
            gs,
            "__version__",
            "unknown",
        ),
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
        "detection_rate": detection_rate,
        "annotated_frames": annotated_frames,
        "video": str(video_path),
        "annotated_video": (
            str(annotated_video_path)
            if annotated_frames > 0
            else None
        ),
        "execution_time_seconds": total_time,
        "mean_pixel_error": (
            float(np.mean(pixel_errors))
            if pixel_errors
            else None
        ),
        "p95_pixel_error": (
            float(np.percentile(pixel_errors, 95))
            if pixel_errors
            else None
        ),
        "mean_tracking_error_mm": float(
            np.mean(tracking_errors) * 1000.0
        ),
        "max_tracking_error_mm": float(
            np.max(tracking_errors) * 1000.0
        ),
        "p95_tracking_error_mm": float(
            np.percentile(tracking_errors, 95) * 1000.0
        ),
        "mean_vision_target_error_mm": float(
            np.mean(vision_target_errors) * 1000.0
        ),
        "p95_vision_target_error_mm": float(
            np.percentile(vision_target_errors, 95) * 1000.0
        ),
        "mean_ik_time_ms": float(np.mean(ik_times_ms)),
        "p95_ik_time_ms": float(
            np.percentile(ik_times_ms, 95)
        ),
        "frame_records": frame_records,
    }

    summary = {
        key: value
        for key, value in metrics.items()
        if key != "frame_records"
    }

    metrics_path.write_text(
        json.dumps(
            metrics,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n[5/5] Vision demo completed")
    print("=" * 60)
    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
    )
    print("=" * 60)
    print("Video:", video_path)
    print("Annotated video:", summary["annotated_video"])
    print("Metrics:", metrics_path)
    print("Summary:", summary_path)


if __name__ == "__main__":
    main()
