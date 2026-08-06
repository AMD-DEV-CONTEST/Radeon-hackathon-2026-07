"""惯性矩阵与非线性力向量模块。

封装 Pinocchio 的动力学核心量：

- **M(q)** — 关节空间质量矩阵（正定、对称）
- **C(q, q̇)** — 科氏力与离心力矩阵，满足 \\(\\dot{M} - 2C\\) 斜对称
- **g(q)** — 重力项向量
- **nle(q, q̇)** — 非线性项向量（= C·q̇ + g）

还包括一次调用计算所有项的 ``compute_all_terms``。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from ..kinematics.robot_model import pad_q_for_model


# --------------------------------------------------------------------------- #
# 质量矩阵 M(q)
# --------------------------------------------------------------------------- #

def compute_mass_matrix(
    model: Optional[pin.Model] = None,
    q: np.ndarray | None = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算关节空间质量矩阵 \\(M(q)\\)。

    \\[
        M(q) \\ddot{q} + nle(q, \\dot{q}) = \\tau
    \\]

    使用 CRBA（Composite Rigid Body Algorithm）算法，
    时间复杂度 O(n²)，其中 n=nv 为自由度数。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv, nv) 的质量矩阵 \\(M\\)，正定对称。
        nv 为关节速度维数（对于 6 轴机器人为 6）。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_mass_matrix")
    pin.crba(model, data, q)
    return data.M.copy()


# --------------------------------------------------------------------------- #
# 科氏力矩阵 C(q, q̇)
# --------------------------------------------------------------------------- #

def compute_coriolis_matrix(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算科氏力与离心力矩阵 \\(C(q, \\dot{q})\\)。

    满足 \\(c(q, \\dot{q}) = C(q, \\dot{q}) \\dot{q}\\)，
    且矩阵 \\(\\dot{M} - 2C\\) 斜对称（可用于数值验证）。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv, nv) 的科氏力矩阵 \\(C\\)。
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

    _check_q_shape(model, q, "compute_coriolis_matrix")
    _check_v_shape(model, v, "compute_coriolis_matrix")

    pin.computeCoriolisMatrix(model, data, q, v)
    return data.C.copy()


# --------------------------------------------------------------------------- #
# 重力项 g(q)
# --------------------------------------------------------------------------- #

def compute_gravity_vector(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算重力项向量 \\(g(q)\\)。

    \\[
        g_i(q) = \\frac{\\partial U}{\\partial q_i}
    \\]
    其中 U 为势能。返回结果为单位 N·m（关节力矩）。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的重力项向量 \\(g\\)，单位：N·m。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_gravity_vector")

    pin.computeGeneralizedGravity(model, data, q)
    return data.g.copy()


# --------------------------------------------------------------------------- #
# 非线性项 nle(q, q̇) = C·q̇ + g
# --------------------------------------------------------------------------- #

def compute_nle(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算非线性项向量 \\(nle(q, \\dot{q}) = C(q, \\dot{q})\\dot{q} + g(q)\\)。

    也称为 "bias force"（偏置力），是完整逆动力学在 q̈=0 时的特例：

    .. code-block:: python

        nle = pin.rnea(model, data, q, v, np.zeros(nv))
        # 等价于
        nle = compute_nle(model, q, v)

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(nv,) 的非线性项向量，单位：N·m。
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

    _check_q_shape(model, q, "compute_nle")
    _check_v_shape(model, v, "compute_nle")

    pin.nonLinearEffects(model, data, q, v)
    return data.nle.copy()


# --------------------------------------------------------------------------- #
# 一次性计算所有项
# --------------------------------------------------------------------------- #

def compute_all_terms(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """一次性计算质量矩阵、科氏力矩阵和重力向量。

    这是同时获取 (M, C, g) 的最有效方式，会复用大量中间结果，
    比连续调用三个独立函数快 3-5 倍。

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        三元组 (M, C, g)：

        - **M** — shape=(nv, nv)，质量矩阵
        - **C** — shape=(nv, nv)，科氏力矩阵
        - **g** — shape=(nv,)，重力项向量

    示例:
        .. code-block:: python

            from reBotArm_control_py.dynamics import compute_all_terms

            q = robot.get_joint_positions()
            v = robot.get_joint_velocities()

            M, C, g = compute_all_terms(q=q, v=v)

            # 逆动力学完整公式: M·q̈ + C·v + g = τ
            tau = M @ qddot_desired + C @ v + g
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

    _check_q_shape(model, q, "compute_all_terms")
    _check_v_shape(model, v, "compute_all_terms")

    pin.computeAllTerms(model, data, q, v)
    return data.M.copy(), data.C.copy(), data.g.copy()


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

def _check_q_shape(model: pin.Model, q: np.ndarray, func_name: str) -> None:
    if q.shape != (model.nq,):
        raise ValueError(
            f"{func_name}: q 必须为形状 ({model.nq},)，实际为 {q.shape}"
        )


def _check_v_shape(model: pin.Model, v: np.ndarray, func_name: str) -> None:
    if v.shape != (model.nv,):
        raise ValueError(
            f"{func_name}: v 必须为形状 ({model.nv},)，实际为 {v.shape}"
        )
