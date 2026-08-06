"""reBot-DevArm 机器人模型加载模块 — 基于 Pinocchio。

urdf_path 和 end_effector_frame 从 hardware_yaml 指向的硬件配置文件中读取，
rebotarm.yaml 只提供 hardware_yaml 字段。
"""

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pinocchio as pin
import yaml

_cfg_dir = Path(__file__).resolve().parents[2] / "config"
_global_cfg = _cfg_dir / "rebotarm.yaml"
_project_root = _cfg_dir.parent

_hw_cfg_cache: dict | None = None


def _hw_config() -> dict:
    """Load kinematics fields (urdf_path, end_effector_frame) from the hardware YAML."""
    global _hw_cfg_cache
    if _hw_cfg_cache is not None:
        return _hw_cfg_cache

    hw_yaml = ""
    if _global_cfg.exists():
        global_data = yaml.safe_load(_global_cfg.read_text()) or {}
        hw_yaml = global_data.get("hardware_yaml", hw_yaml)

    hw_path = _cfg_dir / hw_yaml
    if not hw_path.exists():
        raise FileNotFoundError(f"Hardware config not found: {hw_path}")

    _hw_cfg_cache = yaml.safe_load(hw_path.read_text()) or {}
    return _hw_cfg_cache


def _resolve_urdf(urdf_path: str | None = None) -> Tuple[str, str]:
    if urdf_path is None:
        urdf_path = _hw_config().get("urdf_path", "")

    if not urdf_path:
        raise ValueError("urdf_path is empty. Set it in the hardware config file.")

    if not Path(urdf_path).is_absolute():
        urdf_path = str(_project_root / urdf_path)

    pkg_dir = str(Path(urdf_path).resolve().parent)
    if pkg_dir.endswith("/urdf") or pkg_dir.endswith("\\urdf"):
        pkg_dir = str(Path(pkg_dir).parent)
    return urdf_path, pkg_dir


def load_robot_model(urdf_path: str | None = None) -> pin.Model:
    path, _ = _resolve_urdf(urdf_path)
    return pin.buildModelFromUrdf(path)


def get_end_effector_frame() -> str:
    return _hw_config().get("end_effector_frame", "gripper_end")


def get_joint_count() -> int:
    model = load_robot_model()
    return model.nq


def get_joint_names(model: pin.Model) -> List[str]:
    return [n for n, j in zip(model.names[1:], model.joints[1:]) if j.idx_q >= 0]


def get_joint_limits(model: pin.Model) -> List[Tuple[float, float]]:
    limits = []
    for name in get_joint_names(model):
        jid = model.getJointId(name)
        lo, hi = float(model.lowerPositionLimit[jid]), float(model.upperPositionLimit[jid])
        limits.append((-np.inf, np.inf) if np.isinf(lo) and np.isinf(hi) else (lo, hi))
    return limits


def get_end_effector_frame_id(model: pin.Model) -> int:
    return model.getFrameId(get_end_effector_frame())


def get_all_frame_names(model: pin.Model) -> List[str]:
    return [f.name for f in model.frames]


def pad_q_for_model(model: pin.Model, q: np.ndarray, controlled_joints: int | None = None) -> np.ndarray:
    nq = model.nq
    n_ctrl = controlled_joints if controlled_joints is not None else nq
    padded = np.zeros(nq)
    padded[:min(q.shape[0], n_ctrl)] = q[:min(q.shape[0], n_ctrl)]
    return padded
