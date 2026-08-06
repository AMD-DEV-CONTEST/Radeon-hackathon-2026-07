"""reBot-DevArm 轨迹规划统一入口。

组合采样器与 CLIK 跟踪器，提供关节空间轨迹规划与统计接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pinocchio as pin

from .clik_tracker import (
    IKParams,
    JointTrajectoryPoint,
    track_trajectory,
)
from .sampler import (
    TrajProfile,
    TrajPlanParams,
    CartesianTrajectory,
    CartesianTrajectoryResult,
    plan_cartesian_geodesic_trajectory,
)


@dataclass
class TrajStats:
    """轨迹统计信息。"""
    total_points: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    max_ik_error: float = 0.0
    avg_ik_error: float = 0.0


def plan_joint_space_trajectory(
    model: pin.Model,
    end_frame_id: int,
    q_start: np.ndarray,
    q_end: np.ndarray,
    duration: float,
    params: TrajPlanParams | None = None,
    ik_params: IKParams | None = None,
    null_gain: float = 0.0,
    start_pose: pin.SE3 | None = None,
    end_pose: pin.SE3 | None = None,
) -> List[JointTrajectoryPoint]:
    """关节空间轨迹规划（笛卡尔测地线 + CLIK 跟踪）。

    参数:
        model:          Pinocchio 模型。
        end_frame_id:   末端执行器帧 ID。
        q_start:        起始关节配置 (nq,)。
        q_end:          终止关节配置 (nq,)。
        duration:       总时长（秒）。
        params:         轨迹采样参数。
        ik_params:      CLIK 跟踪参数。
        null_gain:      零空间增益（关节限位避让）。
        start_pose:     预计算起始位姿（可选）。
        end_pose:       预计算终止位姿（可选）。

    返回:
        关节轨迹点列表。
    """
    from reBotArm_control_py.kinematics import compute_fk

    if duration <= 0.0:
        raise ValueError("duration 必须 > 0")
    if params is None:
        params = TrajPlanParams()
    if ik_params is None:
        ik_params = IKParams()

    T_start = start_pose if start_pose is not None else compute_fk(model, q_start)[2]
    T_end = end_pose if end_pose is not None else compute_fk(model, q_end)[2]

    cart_result = plan_cartesian_geodesic_trajectory(T_start, T_end, duration, params)
    return track_trajectory(
        model, end_frame_id, cart_result.trajectory, q_start, ik_params, null_gain
    )


def compute_traj_stats(
    model: pin.Model,
    end_frame_id: int,
    jt: List[JointTrajectoryPoint],
    T_start: pin.SE3,
    T_end: pin.SE3,
    duration: float,
    params: TrajPlanParams | None = None,
) -> TrajStats:
    """计算关节轨迹跟踪误差统计。

    参数:
        model:          Pinocchio 模型。
        end_frame_id:   末端帧 ID。
        jt:            :func:`plan_joint_space_trajectory` 返回的关节轨迹。
        T_start:       期望起始位姿。
        T_end:         期望终止位姿。
        duration:      轨迹时长。
        params:        轨迹参数。

    返回:
        :class:`TrajStats`，含成功率、最大/平均跟踪误差。
    """
    from reBotArm_control_py.kinematics import compute_fk

    if params is None:
        params = TrajPlanParams()

    stats = TrajStats(total_points=len(jt))
    ref_result = plan_cartesian_geodesic_trajectory(T_start, T_end, duration, params)
    ref_pts = ref_result.trajectory.points()

    sum_err = 0.0
    for i, pt in enumerate(jt):
        if i >= len(ref_pts):
            break
        if pt.ik_success:
            stats.success_count += 1
        _, _, oMf_h = compute_fk(model, pt.q)
        err_vec = pin.log6(pin.SE3(oMf_h).inverse() * ref_pts[i].pose).vector
        err_norm = float(np.linalg.norm(err_vec))
        stats.max_ik_error = max(stats.max_ik_error, err_norm)
        sum_err += err_norm

    if stats.total_points > 0:
        stats.success_rate = stats.success_count / stats.total_points
        stats.avg_ik_error = sum_err / stats.total_points
    return stats
