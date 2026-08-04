# Implementation Notes

## Overview

The demo builds a Genesis scene with a Franka Panda arm, a fixed fruit marker, a ground plane, and an offscreen camera. The fruit follows a three-dimensional figure-eight trajectory. At each frame, inverse kinematics computes a target joint configuration for the arm so the end effector tracks a point 8 cm above the fruit.

## Control Flow

1. Initialize Genesis with the AMD ROCm backend when available.
2. Build the scene with gravity and collision disabled to focus on IK and target following.
3. Move the arm to the initial tracking pose.
4. Render the trajectory while recording the camera output.
5. Move the Genesis-generated MP4 into `outputs/videos/`.
6. Write metrics into `outputs/metrics/`.

## Metrics

The script records:

- Initial tracking error
- Mean, max, and p95 tracking error
- Mean and p95 IK latency
- Runtime
- Genesis, PyTorch, HIP, and GPU information

## Notes

The committed `results/franka_fruit_follow.json` is a lightweight sample metrics file. Generated runtime artifacts are written under `outputs/` and ignored by Git.

## Vision-Guided Extension

The enhanced demo adds a perception-control loop:

```text
Genesis camera frame
-> red fruit detection
-> image-space error
-> visual-servo target correction
-> inverse kinematics
-> joint PD control
-> metrics and annotated video
```

The detector in `src/vision_tracking.py` uses a lightweight red-pixel threshold. It avoids a model download or training step, which keeps the project reproducible for a short competition deadline. The servo controller in `src/franka_vision_servo.py` uses the first visible fruit center as the image-space reference, then maps pixel displacement into bounded Y/Z end-effector target corrections.

Run it with:

```bash
python scripts/franka_vision_servo.py
```

The same script can run a coordinate-control baseline for comparison:

```bash
python scripts/franka_vision_servo.py --mode baseline
```

The implementation intentionally keeps generated MP4 and full per-frame metrics under `outputs/`, while committing only lightweight summaries under `results/`.

# 实现说明

该 Demo 在 Genesis 中构建 Franka Panda 机械臂、固定水果标记、地面和离屏相机。水果沿三维 8 字轨迹运动；每一帧通过逆运动学计算机械臂关节目标，使末端执行器跟随水果上方 8 cm 的目标点。

程序会记录跟踪误差、IK 耗时、运行时间和 ROCm/GPU 环境信息。运行生成物写入 `outputs/`，不直接提交到 GitHub。

增强版加入了视觉闭环控制：Genesis 相机图像经过红色目标检测后，得到水果中心点和图像空间误差；控制器再将像素误差转换成机械臂末端目标修正，并继续使用 Genesis IK 和 PD 控制完成跟随。这样项目从“读取仿真真值坐标”升级为“相机感知驱动控制”。
