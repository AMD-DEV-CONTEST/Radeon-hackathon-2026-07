"""正动力学模块（Forward Dynamics）。

给定关节力矩，计算关节加速度 \\(\\ddot{q}\\)：

\\[
    \\ddot{q} = M^{-1}(q) \\left( \\tau - nle(q, \\dot{q}) \\right)
\\]

使用 ABA（Articulated Body Algorithm）算法，直接在 O(n) 时间复杂度内
计算关节加速度，无需对质量矩阵求逆。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from .inertia import _check_q_shape, _check_v_shape
from ..kinematics.robot_model import pad_q_for_model


def compute_forward_dynamics(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    tau: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算正动力学：给定力矩求关节加速度。

    使用 ABA（Articulated Body Algorithm），直接输出 \\(\\ddot{q}\\)。
    无需显式求逆质量矩阵，数值稳定。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        tau:   关节力矩向量，shape=(nv,)。若为 None，使用零力矩。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的关节加速度向量 \\(\\ddot{q}\\)，单位：rad/s²。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)
    if v is None:
        v = np.zeros(model.nv)
    if tau is None:
        tau = np.zeros(model.nv)

    _check_q_shape(model, q, "compute_forward_dynamics")
    _check_v_shape(model, v, "compute_forward_dynamics")
    _check_tau_shape(model, tau, "compute_forward_dynamics")

    pin.aba(model, data, q, v, tau)
    return data.ddq.copy()


def forward_dynamics_from_nle(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    tau: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """通过显式质量矩阵求逆计算正动力学。

    等价于：
    \\[
        \\ddot{q} = M^{-1}(q) (\\tau - nle(q, \\dot{q}))
    \\]

    与 :func:`compute_forward_dynamics` 的结果相同，但使用矩阵求逆实现。
    适合需要同时获取质量矩阵的场景（见示例）。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        tau:   关节力矩向量，shape=(nv,)。若为 None，使用零力矩。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的关节加速度向量 \\(\\ddot{q}\\)，单位：rad/s²。

    示例:
        .. code-block:: python

            from reBotArm_control_py.dynamics import compute_all_terms

            M, _, nle = compute_all_terms(q, v)

            # 阻抗控制：desired_acc = M^{-1}(τ_des - nle)
            tau_des = np.array([0.0, 0.0, -5.0, 0.0, 0.0, 0.0])
            qddot = np.linalg.solve(M, tau_des - nle)
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)
    if v is None:
        v = np.zeros(model.nv)
    if tau is None:
        tau = np.zeros(model.nv)

    _check_q_shape(model, q, "forward_dynamics_from_nle")
    _check_v_shape(model, v, "forward_dynamics_from_nle")
    _check_tau_shape(model, tau, "forward_dynamics_from_nle")

    pin.computeAllTerms(model, data, q, v)
    M = data.M
    nle = data.nle
    return np.linalg.solve(M, tau - nle)


def _check_tau_shape(model: pin.Model, tau: np.ndarray, func_name: str) -> None:
    if tau.shape != (model.nv,):
        raise ValueError(
            f"{func_name}: tau 必须为形状 ({model.nv},)，实际为 {tau.shape}"
        )
