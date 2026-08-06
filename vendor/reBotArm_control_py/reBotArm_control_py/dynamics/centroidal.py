"""质心动力学模块。

提供质心位置、质心速度和质心动量等 centroidal 量级的计算接口。

质心动量描述了机器人整体运动（平移 + 转动）的最简洁表达：

\\[
    \\begin{bmatrix} \\mathbf{h}_{lin} \\\\ \\mathbf{h}_{ang} \\end{bmatrix}
    =
    \\begin{bmatrix} m \\dot{c} \\\\ I_c \\omega + c \\times m \\dot{c} \\end{bmatrix}
    = A_c(q, \\dot{q}) \\dot{q}
\\]

其中 \\(A_c(q, \\dot{q})\\) 为质心矩阵（Centroidal Momentum Matrix）。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pinocchio as pin

from .robot_model import load_dynamics_model, create_data
from .inertia import _check_q_shape, _check_v_shape
from ..kinematics.robot_model import pad_q_for_model


# --------------------------------------------------------------------------- #
# 质心（Center of Mass）
# --------------------------------------------------------------------------- #

def compute_center_of_mass(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    center_zero: bool = False,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算质心在基坐标系（世界坐标系）下的位置。

    参数:
        model:       动力学模型。若为 None，则自动加载。
        q:           关节位置向量，shape=(nq,)。若为 None，使用零位。
        center_zero: 若为 True，返回相对于基坐标系原点的位置。
                     若为 False，返回全局绝对坐标。
        data:        Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(3,) 的质心位置向量（单位：米）。
    """
    if model is None:
        model = load_dynamics_model()
    if data is None:
        data = create_data(model)
    if q is None:
        q = pin.neutral(model)
    else:
        q = pad_q_for_model(model, q)

    _check_q_shape(model, q, "compute_center_of_mass")

    if center_zero:
        pin.centerOfMass(model, data, q, False)
    else:
        pin.centerOfMass(model, data, q)

    return data.com[0].copy()


def compute_com_velocity(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算质心速度。

    \\[
        \\dot{c} = \\frac{\\partial com(q)}{\\partial q} \\dot{q}
    \\]

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(3,) 的质心速度向量（单位：m/s）。
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

    _check_q_shape(model, q, "compute_com_velocity")
    _check_v_shape(model, v, "compute_com_velocity")

    pin.computeCentroidalVelocities(model, data, q, v)
    return data.vcom[0].copy()


# --------------------------------------------------------------------------- #
# 质心动量（Centroidal Momentum）
# --------------------------------------------------------------------------- #

def compute_centroidal_momentum(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算质心动量向量（线性动量 + 角动量）。

    \\[
        h = \\begin{bmatrix} h_{lin} \\\\ h_{ang} \\end{bmatrix}
          = \\begin{bmatrix} m \\dot{c} \\\\ A_c(q, \\dot{q}) \\dot{q} \\end{bmatrix}
    \\]

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(6,) 的动量向量：
        - 前 3 个分量为线性动量 \\(h_{lin} = m \\dot{c}\\)（单位：kg·m/s）
        - 后 3 个分量为角动量 \\(h_{ang}\\)（单位：kg·m²/s）
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

    _check_q_shape(model, q, "compute_centroidal_momentum")
    _check_v_shape(model, v, "compute_centroidal_momentum")

    pin.ccrba(model, data, q, v)
    return data.hg.vector.copy()


# --------------------------------------------------------------------------- #
# 质心矩阵（Centroidal Momentum Matrix）
# --------------------------------------------------------------------------- #

def compute_centroidal_matrix(
    model: Optional[pin.Model] = None,
    q: Optional[np.ndarray] = None,
    v: Optional[np.ndarray] = None,
    data: Optional[pin.Data] = None,
) -> np.ndarray:
    """计算质心矩阵 \\(A_c(q, \\dot{q})\\)。

    \\[
        h = A_c(q, \\dot{q}) \\dot{q}
    \\]

    \\(A_c\\) 是 6×nv 的矩阵，将关节速度映射为质心动量。
    分为两个部分：

    - \\(A_c = \\begin{bmatrix} A_{lin} \\\\ A_{ang} \\end{bmatrix}\\)
    - \\(A_{lin} = m J_{com}(q)\\)（线性动量部分）
    - \\(A_{ang}\\)（角动量部分）

    参数:
        model: 动力学模型。若为 None，则自动加载。
        q:     关节位置向量，shape=(nq,)。若为 None，使用零位。
        v:     关节速度向量，shape=(nv,)。若为 None，使用零速度。
        data:  Pinocchio 数据对象。若为 None，则自动创建。

    返回:
        shape=(6, nv) 的质心矩阵 \\(A_c\\)。
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

    _check_q_shape(model, q, "compute_centroidal_matrix")
    _check_v_shape(model, v, "compute_centroidal_matrix")

    pin.ccrba(model, data, q, v)
    return data.Ag.copy()
