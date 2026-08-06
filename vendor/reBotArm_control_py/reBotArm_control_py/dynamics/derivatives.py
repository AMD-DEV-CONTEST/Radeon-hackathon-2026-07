"""动力学一阶导数（敏感度分析）模块。

提供各动力学量对关节状态 \\((q, \\dot{q})\\) 的雅可比矩阵：

- \\(\\frac{\\partial M}{\\partial q_j}\\) — 质量矩阵对关节位置的偏导
- \\(\\frac{\\partial nle}{\\partial q}, \\frac{\\partial nle}{\\partial \\dot{q}}\\) — 非线性项的偏导
- \\(\\frac{\\partial \\tau}{\\partial q}, \\frac{\\partial \\tau}{\\partial \\dot{q}}, \\frac{\\partial \\tau}{\\partial \\ddot{q}}\\) — RNEA 输出的偏导
- \\(\\frac{\\partial g}{\\partial q}\\) — 重力项的偏导（海森信息）

这些导数广泛用于：
- 最优控制（OCP）的解析求导 / 梯度计算
- 扩展卡尔曼滤波（EKF）的状态雅可比
- 增益调度和自适应控制
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from .inertia import _check_q_shape, _check_v_shape
from ..kinematics.robot_model import pad_q_for_model


# --------------------------------------------------------------------------- #
# 质量矩阵 M(q) 的偏导
# --------------------------------------------------------------------------- #

def compute_mass_matrix_derivatives(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算质量矩阵 \\(M(q)\\) 对关节位置 \\(q\\) 的偏导数。

    返回三维数组 ``dMdq[j]``，其中第 j 个面 (nv, nv) 为
    \\(\\frac{\\partial M}{\\partial q_j}(q)\\)。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nq, nv, nv) 的偏导数张量。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_mass_matrix_derivatives")

    dMdq = np.zeros((model.nq, model.nv, model.nv))
    for j in range(model.nq):
        pin.computeMassMatrixDerivatives(model, data, q, j)
        dMdq[j] = data.dMassdq.copy()

    return dMdq


# --------------------------------------------------------------------------- #
# RNEA 偏导（力矩对 q, q̇, q̈ 的雅可比）
# --------------------------------------------------------------------------- #

def compute_rnea_derivatives(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    a: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算 RNEA 输出 \\(\\tau = rnea(q, \\dot{q}, \\ddot{q})\\) 的偏导数。

    返回三个雅可比矩阵：
    - \\(\\frac{\\partial \\tau}{\\partial q}\\) — shape=(nv, nq)
    - \\(\\frac{\\partial \\tau}{\\partial \\dot{q}}\\) — shape=(nv, nv)
    - \\(\\frac{\\partial \\tau}{\\partial \\ddot{q}}\\) — shape=(nv, nv)，即质量矩阵 M(q)

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        a:     关节加速度向量，shape=(nv,)。若为 None，使用零加速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        三元组 ``(dTau_dq, dTau_dv, dTau_da)``。
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

    _check_q_shape(model, q, "compute_rnea_derivatives")
    _check_v_shape(model, v, "compute_rnea_derivatives")

    pin.computeRNEADerivatives(model, data, q, v, a)
    return (
        data.dtau_dq.copy(),
        data.dtau_dv.copy(),
        data.dtau_da.copy(),
    )


# --------------------------------------------------------------------------- #
# 非线性项 nle 的偏导
# --------------------------------------------------------------------------- #

def compute_coriolis_derivatives(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """计算非线性项 \\(nle(q, \\dot{q}) = C(q, \\dot{q})\\dot{q} + g(q)\\) 的偏导。

    返回：
    - \\(\\frac{\\partial nle}{\\partial q}\\) — shape=(nv, nq)
    - \\(\\frac{\\partial nle}{\\partial \\dot{q}}\\) — shape=(nv, nv)

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        二元组 ``(dnle_dq, dnle_dv)``。
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

    _check_q_shape(model, q, "compute_coriolis_derivatives")
    _check_v_shape(model, v, "compute_coriolis_derivatives")

    pin.computeRNEADerivatives(model, data, q, v, np.zeros(model.nv))
    return (
        data.dtau_dq.copy(),
        data.dtau_dv.copy(),
    )


# --------------------------------------------------------------------------- #
# 重力项 g(q) 的偏导
# --------------------------------------------------------------------------- #

def compute_generalized_gravity_derivatives(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算重力项 \\(g(q)\\) 对关节位置的偏导。

    \\[
        \\frac{\\partial g}{\\partial q} \\in \\mathbb{R}^{nv \\times nq}
    \\]

    也称为重力海森矩阵（Gravity Hessian）。
    用于最优控制的二阶近似和重力补偿的线性化。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv, nq) 的重力偏导矩阵。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_generalized_gravity_derivatives")

    pin.computeRNEADerivatives(
        model, data, q,
        np.zeros(model.nv),
        np.zeros(model.nv),
    )
    return data.dtau_dq.copy()
