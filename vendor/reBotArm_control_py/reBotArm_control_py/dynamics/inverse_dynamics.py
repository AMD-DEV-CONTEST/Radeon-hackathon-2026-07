"""逆动力学模块（Inverse Dynamics）。

给定关节位置、速度、加速度，计算所需关节力矩 \\(\\tau\\)：

\\[
    \\tau = M(q) \\ddot{q} + C(q, \\dot{q}) \\dot{q} + g(q) + J^T f_{ext}
\\]

使用 RNEA（Recursive Newton-Euler Algorithm）算法，O(n) 时间复杂度。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from .inertia import _check_q_shape, _check_v_shape
from ..kinematics.robot_model import pad_q_for_model


def compute_inverse_dynamics(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    a: Optional[np.ndarray] = None,
    fext: Optional[list[pin.Force]] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算逆动力学：给定运动求力矩。

    \\[
        \\tau = M(q) \\ddot{q} + C(q, \\dot{q}) \\dot{q} + g(q)
    \\]

    使用 RNEA（Recursive Newton-Euler Algorithm）算法，
    直接累加各刚体的惯性力和外力，时间复杂度 O(n)。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        a:     关节加速度向量，shape=(nv,)。若为 None，使用零加速度。
        fext:  各关节上的外部力列表，长度为 model.njoints。
               ``fext[i]`` 作用在关节 i 的局部坐标系。
               若为 None，表示无外部力。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的关节力矩向量 \\(\\tau\\)，单位：N·m。

    示例:
        .. code-block:: python

            from reBotArm_control_py.dynamics import compute_inverse_dynamics

            q = robot.get_joint_positions()
            v = robot.get_joint_velocities()
            a = np.zeros(6)  # 零加速度 = 纯重力平衡力矩

            tau_gravity_balance = compute_inverse_dynamics(q, v, a)
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
    if a is None:
        a = np.zeros(model.nv)

    _check_q_shape(model, q, "compute_inverse_dynamics")
    _check_v_shape(model, v, "compute_inverse_dynamics")
    _check_acc_shape(model, a, "compute_inverse_dynamics")

    if fext is None:
        fext = [pin.Force.Zero() for _ in range(model.njoints)]

    pin.rnea(model, data, q, v, a, fext)
    return data.tau.copy()


def compute_generalized_gravity(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算广义重力向量 \\(g(q)\\)。

    即当前关节构型下，重力场所产生的平衡力矩。
    本质上等价于 ``compute_inverse_dynamics(q, 0, 0)``，
    但使用专用算法，不计算完整的 RNEA。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的重力补偿力矩向量，单位：N·m。

    示例:
        .. code-block:: python

            from reBotArm_control_py.dynamics import compute_generalized_gravity

            q = robot.get_joint_positions()
            tau_g = compute_generalized_gravity(q)

            # 重力补偿控制（仅重力前馈）
            tau_control = tau_g
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_generalized_gravity")

    pin.computeGeneralizedGravity(model, data, q)
    return data.g.copy()


def compute_static_torque(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    fext: Optional[list[pin.Force]] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算静止时的广义力（重力 + 外力）。

    \\[
        \\tau_{static} = g(q) - \\sum_i J_i^T(q) f_i^{ext}
    \\]

    适用于零速度、零加速度条件下的静力学分析，
    例如末端执行器受外部接触力时的关节力矩。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        fext:  各关节上的外部力列表。若为 None，表示无外部力。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的静力矩向量，单位：N·m。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_static_torque")

    if fext is None:
        fext = [pin.Force.Zero() for _ in range(model.njoints)]

    pin.computeStaticTorque(model, data, q, fext)
    return data.tau.copy()


def _check_acc_shape(model: pin.Model, a: np.ndarray, func_name: str) -> None:
    if a.shape != (model.nv,):
        raise ValueError(
            f"{func_name}: 加速度 a 必须为形状 ({model.nv},)，实际为 {a.shape}"
        )
