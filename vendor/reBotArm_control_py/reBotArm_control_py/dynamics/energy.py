"""机械能计算模块。

提供机器人动能、势能和总机械能的计算接口。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from .inertia import _check_q_shape, _check_v_shape
from ..kinematics.robot_model import pad_q_for_model


def compute_kinetic_energy(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> float:
    """计算机器人当前构型的动能。

    \\[
        T(q, \\dot{q}) = \\frac{1}{2} \\dot{q}^T M(q) \\dot{q}
    \\]

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        动能值（标量），单位：焦耳 (J)。
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

    _check_q_shape(model, q, "compute_kinetic_energy")
    _check_v_shape(model, v, "compute_kinetic_energy")

    pin.computeKineticEnergy(model, data, q, v)
    return float(data.kinetic_energy)


def compute_potential_energy(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> float:
    """计算机器人当前构型的势能。

    \\[
        U(q) = - \\sum_i m_i \\mathbf{g}^T \\mathbf{p}_i(q)
    \\]

    其中 \\(\\mathbf{p}_i(q)\\) 为第 i 个连杆质心在重力方向上的位置。
    势能零点定义为各关节零位时的质心高度。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        势能值（标量），单位：焦耳 (J)。
        沿重力方向越低，势能越小。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_potential_energy")

    pin.computePotentialEnergy(model, data, q)
    return float(data.potential_energy)


def compute_total_energy(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> float:
    """计算机器人当前构型的总机械能。

    \\[
        E = T + U = \\frac{1}{2} \\dot{q}^T M(q) \\dot{q} + U(q)
    \\]

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        总机械能（标量），单位：焦耳 (J)。
    """
    T = compute_kinetic_energy(model, q, v, data)
    U = compute_potential_energy(model, q, data)
    return T + U
