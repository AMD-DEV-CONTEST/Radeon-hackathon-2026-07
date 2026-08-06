"""reBot-DevArm 逆运动学模块。

基于阻尼最小二乘（CLIK）的闭环逆运动学算法，
与 C++ 实现严格对齐：雅可比矩阵计算、自适应阻尼、回退线搜索。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pinocchio as pin

from .forward_kinematics import compute_fk


# ─── 参数与结果数据结构 ────────────────────────────────────────────────────────

@dataclass
class IKParams:
    """IK 求解器参数"""
    max_iter: int = 1000
    tolerance: float = 1e-4    # 收敛阈值 ||err||
    step_size: float = 0.5    # 每步更新的缩放系数
    damping: float = 1e-6      # Tikhonov 正则化系数 λ


@dataclass
class IKResult:
    """IK 求解结果"""
    q: np.ndarray
    success: bool
    error: float       # 最终 ||err||
    iterations: int


# Alias，与 C++ 头文件中的命名保持一致
IKSolverParams = IKParams


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def pos_rot_to_se3(
    pos: np.ndarray,
    rot: Optional[np.ndarray] = None,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
) -> pin.SE3:
    """从位置和旋转构建 pinocchio SE3 位姿。

    参数:
        pos:    (3,) 位置 [x, y, z]，单位：米。
        rot:    (3, 3) 旋转矩阵。若提供则忽略 rpy 参数。
        roll:  绕 X 轴转角（弧度），仅当 rot=None 时使用。
        pitch: 绕 Y 轴转角（弧度），仅当 rot=None 时使用。
        yaw:   绕 Z 轴转角（弧度），仅当 rot=None 时使用。

    返回:
        pin.SE3 目标末端位姿。
    """
    if rot is None:
        rot = pin.rpy.rpyToMatrix(roll, pitch, yaw)
    return pin.SE3(rot, pos)


def _clamp_config(model: pin.Model, q: np.ndarray) -> np.ndarray:
    """将 q 限制在关节限位范围内。

    NaN 限位默认用 0，防止 integrate 后出现 NaN。
    """
    lo = np.array([
        float(x) if np.isfinite(x) else 0.0 for x in model.lowerPositionLimit
    ])
    hi = np.array([
        float(x) if np.isfinite(x) else 0.0 for x in model.upperPositionLimit
    ])
    clamped = np.maximum(q, lo)
    clamped = np.minimum(clamped, hi)
    return clamped


def _compute_error(
    model: pin.Model,
    data: pin.Data,
    end_frame_id: int,
    q: np.ndarray,
    target: pin.SE3,
) -> tuple[float, np.ndarray]:
    """计算当前末端位姿与目标位姿之间的 6 维误差 twist。

    返回:
        (err_norm, err_vector)
    """
    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)
    T_cur = data.oMf[end_frame_id]
    err = pin.log6(T_cur.inverse() * target).vector
    return float(np.linalg.norm(err)), err


# ─── 核心求解器 ────────────────────────────────────────────────────────────────

def solve_ik(
    model: pin.Model,
    data: pin.Data,
    end_frame_id: int,
    target: pin.SE3,
    q_init: np.ndarray,
    params: Optional[IKParams] = None,
    controlled_joints: int | None = None,
) -> IKResult:
    """阻尼最小二乘 CLIK 求解器。

      - LOCAL 坐标系雅可比
      - 自适应阻尼 lam = params.damping * max(1.0, prev_err * 10.0)
      - 回退线搜索（最多折半 4 次）

    参数:
        model:            Pinocchio 机器人模型。
        data:             Pinocchio 数据缓存（需外部创建并传入）。
        end_frame_id:     末端帧索引。
        target:           目标 SE3 位姿。
        q_init:           初始关节配置。若维度小于 model.nq，超出部分视为被动关节补 0；
                          若维度大于 model.nq，多余部分被忽略。
        params:           IK 参数，默认 IKParams{}。
        controlled_joints: 受控关节数量（默认为 model.nq）。
                          传入比 model.nq 小的值时，IK 在完整模型空间求解，
                          但 q_init 只需提供受控关节数，返回值也只截取受控部分。
                          这使得调用方无需感知 URDF 中被动关节的存在。

    返回:
        IKResult，其中 q 为求解得到的关节角（维度与 q_init 一致）。
    """
    if params is None:
        params = IKParams()

    nq = model.nq
    n_ctrl = controlled_joints if controlled_joints is not None else nq

    # 补齐 q_init 到 model.nq
    q = np.zeros(nq)
    n_provided = min(q_init.shape[0], n_ctrl)
    q[:n_provided] = q_init[:n_provided]
    prev_err, err = _compute_error(model, data, end_frame_id, q, target)

    # 初始误差即已满足容差时直接返回
    if prev_err < params.tolerance:
        return IKResult(q=q[:n_ctrl], success=True, error=prev_err, iterations=0)

    for iteration in range(params.max_iter):

        # LOCAL 系体雅可比
        pin.computeJointJacobians(model, data, q)
        J = pin.getFrameJacobian(model, data, end_frame_id, pin.LOCAL)

        # 自适应阻尼：误差越大阻尼越小（Levenberg-Marquardt 风格）
        lam = params.damping * max(1.0, prev_err * 10.0)

        # 阻尼最小二乘 dq = step_size * J^T * (J J^T + λI)^{-1} * err
        JJT = J @ J.T
        JJT[np.arange(JJT.shape[0]), np.arange(JJT.shape[1])] += lam
        dq = params.step_size * J.T @ np.linalg.solve(JJT, err)

        # 回退线搜索：若新误差未减小则缩步，最多折半 4 次
        alpha = 1.0
        for _ in range(4):
            q_new = _clamp_config(model, pin.integrate(model, q, alpha * dq))
            new_err, err_new = _compute_error(model, data, end_frame_id, q_new, target)
            if new_err < prev_err:
                q = q_new
                err = err_new
                prev_err = new_err
                break
            alpha *= 0.5
        else:
            # 线搜索全部失败，保持当前构型继续迭代
            pass

    # 循环结束后再次检查（可能刚收敛或误差已达机器精度）
    if prev_err < params.tolerance:
        return IKResult(q=q[:n_ctrl], success=True, error=prev_err, iterations=params.max_iter)
    return IKResult(q=q[:n_ctrl], success=False, error=prev_err, iterations=params.max_iter)


def solve_ik_with_retry(
    model: pin.Model,
    data: pin.Data,
    end_frame_id: int,
    target: pin.SE3,
    q_seed: np.ndarray,
    params: Optional[IKParams] = None,
    max_retries: int = 8,
) -> IKResult:
    """带随机重试的 IK 求解器。

      - 先用 q_seed 求解一次
      - 若失败则在关节限位内随机采样最多 max_retries 次
      - 返回误差最小的结果

    参数:
        model:        Pinocchio 机器人模型。
        data:         Pinocchio 数据缓存。
        end_frame_id: 末端帧索引。
        target:       目标 SE3 位姿。
        q_seed:       种子关节配置（会被更新为本次最优解）。
        params:       IK 参数。
        max_retries:  随机重试次数。

    返回:
        IKResult。
    """
    if params is None:
        params = IKParams()

    best = solve_ik(model, data, end_frame_id, target, q_seed, params)
    if best.success:
        q_seed[:] = best.q
        return best

    lo = model.lowerPositionLimit
    hi = model.upperPositionLimit
    nq = model.nq

    for _ in range(max_retries):
        q_rand = np.zeros(nq)
        for j in range(nq):
            l = lo[j] if np.isfinite(lo[j]) else -math.pi
            h = hi[j] if np.isfinite(hi[j]) else math.pi
            q_rand[j] = random.uniform(l, h)
        r = solve_ik(model, data, end_frame_id, target, q_rand, params)
        if r.error < best.error:
            best = r
        if best.success:
            break

    q_seed[:] = best.q
    return best


# ─── 便捷函数 ──────────────────────────────────────────────────────────────────

def compute_ik(
    q_init: np.ndarray | None,
    target_pos: np.ndarray,
    target_rot: np.ndarray | None = None,
    *,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    params: IKSolverParams | None = None,
) -> IKResult:
    """使用默认模型计算 IK（便捷函数）。

    参数:
        q_init:      初始关节配置。传入 ``None`` 则自动使用零位构型。
        target_pos:  目标位置 (3,)，单位：米。
        target_rot:  目标旋转矩阵 (3, 3)，可选。
        roll:        ZYX 欧拉角之 roll，仅当 rot=None 时使用。
        pitch:       ZYX 欧拉角之 pitch。
        yaw:         ZYX 欧拉角之 yaw。
        params:      IK 参数。

    返回:
        IKResult。
    """
    from .robot_model import load_robot_model, get_end_effector_frame_id

    model = load_robot_model()
    data = model.createData()
    frame_id = get_end_effector_frame_id(model)
    target = pos_rot_to_se3(target_pos, target_rot, roll, pitch, yaw)

    if q_init is None:
        q_init = pin.neutral(model)

    return solve_ik(model, data, frame_id, target, q_init, params)
