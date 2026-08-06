"""reBot-DevArm CLIK 跟踪模块。

基于阻尼最小二乘（DLS）的闭环逆运动学（CLIK）跟踪笛卡尔轨迹，
通过零空间投影实现关节限位避让。与 C++ trajectory_planner_geodesic.cpp
中的 trackTrajectory() 完全对齐。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pinocchio as pin


@dataclass
class IKParams:
    """CLIK 跟踪参数"""
    max_iter: int = 200
    tolerance: float = 1e-4
    damping: float = 1e-6
    step_size: float = 0.8


@dataclass
class JointTrajectoryPoint:
    """关节轨迹中的一个采样点。"""
    time: float
    q: np.ndarray
    ik_success: bool


def _joint_limit_grad(model: pin.Model, q: np.ndarray) -> np.ndarray:
    """关节限位梯度（零空间投影用）。"""
    lo = np.array([float(x) for x in model.lowerPositionLimit])
    hi = np.array([float(x) for x in model.upperPositionLimit])
    valid = np.isfinite(lo) & np.isfinite(hi)
    dl = q - lo
    dh = hi - q
    mask = valid & (dl > 1e-6) & (dh > 1e-6)
    g = np.zeros(model.nv)
    g[mask] = (dh[mask] - dl[mask]) / (dl[mask] * dh[mask])
    return g


def _clamp_config(model: pin.Model, q: np.ndarray) -> np.ndarray:
    """将关节配置钳制到模型允许范围。

    若关节限位为 NaN（未标定），使用默认值 0（安全中位），
    避免 NaN 在 integrate/FK 中扩散导致 CLIK 完全发散。
    """
    lo = np.array([float(x) if np.isfinite(x) else 0.0 for x in model.lowerPositionLimit])
    hi = np.array([float(x) if np.isfinite(x) else 0.0 for x in model.upperPositionLimit])
    qc = q.copy()
    # NaN 位置保持 NaN（不做钳制，交给下轮迭代处理）
    valid = np.isfinite(q) & (lo <= hi)
    qc[valid] = np.clip(q[valid], lo[valid], hi[valid])
    return qc


def track_trajectory(
    model: pin.Model,
    end_frame_id: int,
    traj,  # CartesianTrajectory — avoid circular import
    q_init: np.ndarray,
    ik_params: IKParams | None = None,
    null_gain: float = 0.0,
) -> List[JointTrajectoryPoint]:
    """用 CLIK（DLS 伪逆 + 零空间投影）跟踪笛卡尔轨迹。

    与 C++ trajectory_planner_geodesic.cpp 中的 trackTrajectory() 完全一致：
      - computeJointJacobians → log6 误差 → DLS 伪逆 → 零空间投影
      - 使用自适应阻尼 λ = damping * max(1.0, ||err|| * 10)（Levenberg-Marquardt 风格）
      - LDLT 分解求解 (JJᵀ + λI)dq = err

    参数:
        model:          Pinocchio 机器人模型。
        end_frame_id:   末端执行器帧 ID。
        traj:           笛卡尔轨迹（来自 :func:`sampler.plan_cartesian_geodesic_trajectory`）。
        q_init:         初始关节配置 (nq,)。
        ik_params:      IK 参数（默认 :class:`IKParams`）。
        null_gain:      零空间关节限位梯度增益，设为 0 则禁用。

    返回:
        关节轨迹点列表，每个点含时间、关节角和 IK 收敛标记。
    """
    if ik_params is None:
        ik_params = IKParams()

    q = q_init.astype(float).copy()
    data = model.createData()
    J = np.zeros((6, model.nv))
    err = np.zeros(6)
    result: List[JointTrajectoryPoint] = []

    for pt in traj.points():
        converged = False
        for _ in range(ik_params.max_iter):
            pin.computeJointJacobians(model, data, q)
            pin.updateFramePlacements(model, data)

            oMf = data.oMf[end_frame_id]
            err = pin.log6(oMf.inverse() * pt.pose).vector

            if np.linalg.norm(err) < ik_params.tolerance:
                converged = True
                break

            J = pin.getFrameJacobian(
                model, data, end_frame_id, pin.ReferenceFrame.LOCAL
            )
            err_norm = np.linalg.norm(err)
            lam = ik_params.damping * max(1.0, err_norm * 10.0)
            JJT = J @ J.T
            JJT[np.diag_indices_from(JJT)] += lam
            dq = ik_params.step_size * J.T @ np.linalg.solve(JJT, err)

            if null_gain > 0.0:
                g = _joint_limit_grad(model, q)
                dq += null_gain * (g - J.T @ np.linalg.solve(JJT, J @ g))

            q = _clamp_config(model, pin.integrate(model, q, dq))

        result.append(JointTrajectoryPoint(pt.time, q.copy(), converged))

    return result
