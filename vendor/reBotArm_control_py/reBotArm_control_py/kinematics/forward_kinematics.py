"""reBotArm 正运动学模块。

根据关节角度计算机器人末端执行器的空间位姿，
包括位置（x, y, z）、旋转矩阵（3×3）和齐次变换矩阵（4×4）。
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pinocchio as pin

from .robot_model import load_robot_model, get_end_effector_frame_id, pad_q_for_model


def compute_fk(
    model: pin.Model,
    q: np.ndarray,
    frame_name: str | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算正运动学，返回末端执行器位姿。

    参数:
        model:      由 :func:`load_robot_model` 返回的 Pinocchio 模型。
        q:          关节位置向量，形状 (nq,)，每个关节一个值。
                    全零向量表示机器人的零位构型。
        frame_name: 要计算位姿的帧名称，留空则使用 config/rebotarm.yaml 中定义的末端执行器帧。

    返回:
        三元组 (position, rotation, homogeneous):

        - **position** (*(3,)*) — 帧原点在世界坐标系中的 x, y, z（米）。
        - **rotation** (*(3, 3)*) — 从世界系到该帧的旋转矩阵 R_{world}^{frame}。
        - **homogeneous** (*(4, 4)*) — 从世界系到该帧的 SE(3) 齐次变换矩阵。
    """
    data = model.createData()

    if q.shape != (model.nq,):
        raise ValueError(
            f"q 必须为形状 ({model.nq},)，实际为 {q.shape}"
        )

    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)

    if frame_name is None:
        frame_id = get_end_effector_frame_id(model)
    else:
        frame_id = model.getFrameId(frame_name)

    oMf = data.oMf[frame_id]

    return (
        oMf.translation.copy(),
        oMf.rotation.copy(),
        oMf.homogeneous.copy(),
    )


def joint_to_pose(
    q: np.ndarray,
    frame_name: str | None = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """将关节角度转换为末端位置和欧拉角（XYZ）。

    参数:
        q:          关节位置向量 (nq,)。若维度小于 model.nq，自动补零。
        frame_name: 要查询的帧。

    返回:
        ``(position, euler_xyz)``，
        其中 ``euler_xyz`` 为 ``[roll, pitch, yaw]``，单位：弧度。
    """
    model = load_robot_model()
    q_padded = pad_q_for_model(model, q)
    pos, rot, _ = compute_fk(model, q_padded, frame_name=frame_name)
    euler_xyz = pin.rpy.matrixToRpy(rot)
    return pos, euler_xyz
