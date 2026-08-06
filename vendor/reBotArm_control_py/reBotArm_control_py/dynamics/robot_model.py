"""Dynamics 机器人模型模块 — 基于 Pinocchio 的动力学计算。

模型由 kinematics.robot_model 统一加载，此处只管理重力配置。
"""

from __future__ import annotations

import numpy as np
import pinocchio as pin

from ..kinematics.robot_model import load_robot_model

EARTH_GRAVITY: tuple[float, float, float] = (0.0, 0.0, -9.81)
ZERO_GRAVITY: tuple[float, float, float] = (0.0, 0.0, 0.0)

_CACHED_MODEL: pin.Model | None = None


def load_dynamics_model(urdf_path: str | None = None) -> pin.Model:
    global _CACHED_MODEL
    if _CACHED_MODEL is not None and urdf_path is None:
        return _CACHED_MODEL
    model = load_robot_model(urdf_path)
    if urdf_path is None:
        _CACHED_MODEL = model
    return model


def get_default_gravity() -> np.ndarray:
    return np.array(EARTH_GRAVITY)


def set_gravity(model: pin.Model, gravity: tuple[float, float, float] | np.ndarray) -> None:
    g = np.asarray(gravity, dtype=float)
    model.gravity = pin.Motion(g)


def get_gravity(model: pin.Model) -> np.ndarray:
    g = model.gravity
    return np.array([g.linear.x, g.linear.y, g.linear.z])


def neutral_configuration(model: pin.Model | None = None) -> np.ndarray:
    if model is None:
        model = load_dynamics_model()
    return pin.neutral(model)


def create_data(model: pin.Model) -> pin.Data:
    return pin.Data(model)


def random_configuration(model: pin.Model | None = None) -> np.ndarray:
    if model is None:
        model = load_dynamics_model()
    return pin.randomConfiguration(model)
