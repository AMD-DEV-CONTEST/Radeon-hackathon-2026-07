import argparse
import json
import math
import time
from pathlib import Path

import genesis as gs
import numpy as np
import torch


def to_numpy(value):
    """将 Genesis/PyTorch 张量转换为 NumPy。"""
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    if hasattr(value, "cpu"):
        return value.cpu().numpy()
    return np.asarray(value)


def find_latest_recording():
    """查找 Genesis 1.3.1 自动生成的最新录像。"""
    candidates = list(
        Path.cwd().glob("franka_fruit_follow_cam_*.mp4")
    )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Genesis Franka fruit-following demo on AMD ROCm"
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=300,
        help="需要渲染的视频帧数",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="目标视频帧率（用于指标记录）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--video",
        type=str,
        default="outputs/videos/franka_fruit_follow.mp4",
    )
    args = parser.parse_args()

    np.random.seed(args.seed)

    video_path = Path(args.video)
    metrics_path = Path(
        "outputs/metrics/franka_fruit_follow.json"
    )

    video_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    # 在 AMD GPU 上使用 Genesis amdgpu 后端。
    backend = (
        gs.amdgpu
        if hasattr(gs, "amdgpu")
        else gs.gpu
    )

    print("=" * 60)
    print("Genesis Franka Fruit Follow Demo")
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

    gs.init(
        backend=backend,
        seed=args.seed,
    )

    # 本 Demo 重点展示逆运动学和轨迹跟随。
    # 关闭重力与碰撞，降低无关动力学因素的干扰。
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

    # 地面。
    scene.add_entity(
        gs.morphs.Plane(),
    )

    # Franka Panda 机械臂。
    franka = scene.add_entity(
        gs.morphs.MJCF(
            file="xml/franka_emika_panda/panda.xml",
        ),
    )

    # 用红色球体表示水果。
    fruit_start = np.array(
        [0.55, 0.0, 0.43],
        dtype=np.float32,
    )

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

    # 离屏录像相机。
    camera = scene.add_camera(
        res=(960, 540),
        pos=(2.1, -2.1, 1.45),
        lookat=(0.45, 0.0, 0.4),
        fov=40,
        GUI=False,
    )

    print("\n[1/4] Building Genesis scene...")
    scene.build()

    # Franka 前七维是机械臂关节，后两维是夹爪。
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

    # PD 控制器增益。
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

    # Panda 的 hand link 作为末端执行器。
    end_effector = franka.get_link("hand")

    # 让机械臂末端保持向下。
    target_quat = np.array(
        [0.0, 1.0, 0.0, 0.0],
        dtype=np.float32,
    )

    print("[2/4] Moving to initial tracking pose...")

    initial_target = fruit_start + np.array(
        [0.0, 0.0, 0.08],
        dtype=np.float32,
    )

    initial_ik = franka.inverse_kinematics(
        link=end_effector,
        pos=initial_target,
        quat=target_quat,
    )

    # 先直接设置初始关节位置。
    franka.set_qpos(initial_ik)

    # 同时设置控制目标，避免 warm-up 时偏离。
    franka.control_dofs_position(
        initial_ik[:7],
        arm_dofs,
    )

    # 让控制器稳定。
    for _ in range(100):
        scene.step()

    actual_initial_pos = to_numpy(
        end_effector.get_pos()
    ).reshape(-1)[:3]

    initial_error = float(
        np.linalg.norm(actual_initial_pos - initial_target)
    )

    print(
        "Initial target:",
        np.round(initial_target, 3),
    )
    print(
        "Initial end-effector:",
        np.round(actual_initial_pos, 3),
    )
    print(
        f"Initial tracking error: "
        f"{initial_error * 1000:.2f} mm"
    )

    print("[3/4] Recording fruit-following trajectory...")

    camera.start_recording()

    tracking_errors = []
    ik_times_ms = []

    start_time = time.perf_counter()

    for frame in range(args.frames):
        # 始终按照 300 帧完成一条完整轨迹。
        # 60 帧 smoke test 只运行轨迹的前 1/5。
        phase = 2.0 * math.pi * frame / 300.0

        # 水果沿三维“8”字形轨迹运动。
        fruit_pos = np.array(
            [
                0.55 + 0.06 * math.sin(phase),
                0.17 * math.sin(phase),
                0.43 + 0.10 * math.sin(2.0 * phase),
            ],
            dtype=np.float32,
        )

        fruit.set_pos(fruit_pos)

        # 机械臂末端跟随水果上方 8 cm 的位置。
        target_pos = fruit_pos + np.array(
            [0.0, 0.0, 0.08],
            dtype=np.float32,
        )

        # 计算逆运动学。
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

        # 控制七个机械臂关节。
        franka.control_dofs_position(
            qpos[:7],
            arm_dofs,
        )

        # 每个控制目标运行四个物理仿真步，
        # 给 PD 控制器足够的跟随时间。
        for _ in range(4):
            scene.step()

        camera.render()

        actual_pos = to_numpy(
            end_effector.get_pos()
        ).reshape(-1)[:3]

        tracking_error = float(
            np.linalg.norm(actual_pos - target_pos)
        )

        tracking_errors.append(tracking_error)

        if (
            frame == 0
            or frame % 30 == 0
            or frame == args.frames - 1
        ):
            print(
                f"frame={frame:4d}/{args.frames} | "
                f"target={np.round(target_pos, 3)} | "
                f"actual={np.round(actual_pos, 3)} | "
                f"error={tracking_error * 1000:.1f} mm | "
                f"IK={ik_elapsed_ms:.2f} ms"
            )

    # Genesis 1.3.1 的 stop_recording() 不接收文件名参数，
    # 会自动在当前目录生成 MP4。
    camera.stop_recording()

    generated_video = find_latest_recording()

    if generated_video is None:
        raise RuntimeError(
            "Genesis 没有生成录像文件"
        )

    # 将自动生成的视频移动到标准输出目录。
    video_path.unlink(missing_ok=True)
    generated_video.replace(video_path)

    total_time = time.perf_counter() - start_time

    metrics = {
        "demo": "Franka fruit following",
        "description": (
            "Franka Panda follows a moving fruit using "
            "Genesis inverse kinematics and joint PD control."
        ),
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
        "seed": args.seed,
        "frames": args.frames,
        "requested_fps": args.fps,
        "nominal_video_duration_seconds": (
            args.frames / args.fps
        ),
        "physics_steps_per_frame": 4,
        "simulation_dt": 0.01,
        "execution_time_seconds": total_time,
        "initial_tracking_error_mm": (
            initial_error * 1000.0
        ),
        "mean_tracking_error_mm": float(
            np.mean(tracking_errors) * 1000.0
        ),
        "max_tracking_error_mm": float(
            np.max(tracking_errors) * 1000.0
        ),
        "p95_tracking_error_mm": float(
            np.percentile(
                tracking_errors,
                95,
            )
            * 1000.0
        ),
        "mean_ik_time_ms": float(
            np.mean(ik_times_ms)
        ),
        "p95_ik_time_ms": float(
            np.percentile(
                ik_times_ms,
                95,
            )
        ),
        "video": str(video_path),
    }

    metrics_path.write_text(
        json.dumps(
            metrics,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n[4/4] Demo completed")
    print("=" * 60)
    print(
        json.dumps(
            metrics,
            indent=2,
            ensure_ascii=False,
        )
    )
    print("=" * 60)
    print("Video:", video_path)
    print("Metrics:", metrics_path)


if __name__ == "__main__":
    main()