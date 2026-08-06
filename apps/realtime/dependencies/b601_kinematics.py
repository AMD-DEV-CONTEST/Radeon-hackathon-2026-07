"""Pinocchio + reBotArm_control_py probe and FK/IK helpers for B601-RS."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REALTIME_ROOT = Path(__file__).resolve().parents[1]
URDF_PATH = REALTIME_ROOT / "static" / "urdf" / "b601_rs" / "b601_rs.urdf"
EE_FRAME = "gripper_end"
ARM_JOINT_NAMES = [f"joint{i}" for i in range(1, 7)]

# FK-validated preset: official calibration zero (folded sit pose, all joints 0 rad).
READY_JOINTS: Dict[str, float] = {
    "joint1": 0.0,
    "joint2": 0.0,
    "joint3": 0.0,
    "joint4": 0.0,
    "joint5": 0.0,
    "joint6": 0.0,
}

_VENDOR_SDK = REALTIME_ROOT.parent.parent / "vendor" / "reBotArm_control_py"
_HOME_SDK = Path.home() / "reBotArm_control_py"
_SDK_ENV = os.environ.get("REBOTARM_SDK_PATH", "")


def sdk_root() -> Optional[Path]:
    for candidate in (
        Path(_SDK_ENV).expanduser() if _SDK_ENV else None,
        _VENDOR_SDK,
        _HOME_SDK,
    ):
        if candidate and (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    return None


def pinocchio_ready() -> bool:
    try:
        import pinocchio  # noqa: F401
    except ImportError:
        return False
    return URDF_PATH.is_file()


def sdk_ready() -> bool:
    root = sdk_root()
    if not root:
        return False
    try:
        spec = importlib.util.find_spec("reBotArm_control_py")
        return spec is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        pass
    py = _resolve_lerobot_python()
    if not py:
        return False
    try:
        subprocess.run(
            [py, "-c", "from reBotArm_control_py.actuator import RebotArm"],
            capture_output=True,
            timeout=8,
            check=True,
            cwd=str(root),
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _resolve_lerobot_python() -> Optional[str]:
    for key in ("BOTVERSEX_LEROBOT_VENV", "REBOT_LEROBOT_VENV"):
        raw = os.environ.get(key)
        if raw:
            py = Path(raw).expanduser() / "bin" / "python3"
            if py.is_file():
                return str(py)
    for py in (
        Path(sys.executable),
        Path.home() / "venvs" / "lerobot" / "bin" / "python3",
        Path.home() / ".botversex" / "venv" / "bin" / "python3",
    ):
        if py.is_file():
            return str(py)
    return None


def probe_health() -> Dict[str, Any]:
    root = sdk_root()
    return {
        "ready": pinocchio_ready(),
        "pinocchio": pinocchio_ready(),
        "sdk": sdk_ready(),
        "urdf_path": str(URDF_PATH),
        "urdf_exists": URDF_PATH.is_file(),
        "sdk_path": str(root) if root else None,
        "ee_frame": EE_FRAME,
        "install_script": "scripts/b601_pinocchio_install.sh",
    }


# ---------------------------------------------------------------------------
# Pinocchio model (lazy)
# ---------------------------------------------------------------------------

_model = None
_data = None
_frame_id: Optional[int] = None
_q_joint_indices: Optional[List[int]] = None


def _load_pinocchio():
    global _model, _data, _frame_id, _q_joint_indices
    if _model is not None:
        return _model, _data
    import pinocchio as pin
    import numpy as np

    if not URDF_PATH.is_file():
        raise FileNotFoundError(f"URDF not found: {URDF_PATH}")
    _model = pin.buildModelFromUrdf(str(URDF_PATH))
    _data = _model.createData()
    _frame_id = _model.getFrameId(EE_FRAME)
    if _frame_id >= len(_model.frames):
        raise RuntimeError(f"Frame {EE_FRAME} not in URDF")
    _q_joint_indices = []
    for name in ARM_JOINT_NAMES:
        jid = _model.getJointId(name)
        if jid == 0:
            raise RuntimeError(f"Joint {name} not in model")
        _q_joint_indices.append(_model.joints[jid].idx_q)
    return _model, _data


def joints_to_q(joints: Dict[str, float]) -> Any:
    import numpy as np

    model, _ = _load_pinocchio()
    q = np.zeros(model.nq)
    for i, name in enumerate(ARM_JOINT_NAMES):
        key = name
        if key not in joints and name.replace("joint", "joint") in joints:
            key = name
        val = joints.get(key, joints.get(f"joint{i + 1}", 0.0))
        idx = _q_joint_indices[i] if _q_joint_indices else i
        q[idx] = float(val)
    return q


def q_to_joints(q: Any) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for i, name in enumerate(ARM_JOINT_NAMES):
        idx = _q_joint_indices[i] if _q_joint_indices else i
        out[name] = float(q[idx])
    return out


def _se3_to_dict(se3: Any) -> Dict[str, Any]:
    import numpy as np

    pos = se3.translation.tolist()
    R = se3.rotation
    # roll pitch yaw (intrinsic XYZ)
    sy = float(np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2))
    if sy > 1e-6:
        roll = float(np.arctan2(R[2, 1], R[2, 2]))
        pitch = float(np.arctan2(-R[2, 0], sy))
        yaw = float(np.arctan2(R[1, 0], R[0, 0]))
    else:
        roll = float(np.arctan2(-R[1, 2], R[1, 1]))
        pitch = float(np.arctan2(-R[2, 0], sy))
        yaw = 0.0
    return {
        "position": pos,
        "rotation_matrix": R.tolist(),
        "euler": [roll, pitch, yaw],
        "euler_deg": [roll * 57.2958, pitch * 57.2958, yaw * 57.2958],
    }


def compute_fk(joints: Dict[str, float]) -> Dict[str, Any]:
    import pinocchio as pin

    model, data = _load_pinocchio()
    q = joints_to_q(joints)
    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)
    se3 = data.oMf[_frame_id]
    return _se3_to_dict(se3)


def ready_pose() -> Dict[str, Any]:
    fk = compute_fk(READY_JOINTS)
    return {
        "joints": dict(READY_JOINTS),
        "position": fk["position"],
        "orientation": fk["euler"],
        "orientation_deg": fk["euler_deg"],
    }


def compute_ik(
    position: List[float],
    orientation_rpy: Optional[List[float]] = None,
    q_seed: Optional[Dict[str, float]] = None,
    max_iter: int = 200,
    tol: float = 1e-4,
) -> Dict[str, Any]:
    import numpy as np
    import pinocchio as pin

    model, data = _load_pinocchio()
    if q_seed:
        q = joints_to_q(q_seed)
    else:
        q = np.zeros(model.nq)

    target = pin.SE3.Identity()
    target.translation = np.array(position, dtype=float)
    if orientation_rpy and len(orientation_rpy) >= 3:
        r, p, y = orientation_rpy[:3]
        target.rotation = pin.rpy.rpyToMatrix(r, p, y)
    else:
        # position-only IK: keep orientation from seed
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        target.rotation = data.oMf[_frame_id].rotation

    damp = 1e-6
    for it in range(max_iter):
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        err = pin.log(data.oMf[_frame_id].inverse() * target).vector
        if np.linalg.norm(err) < tol:
            joints = q_to_joints(q)
            if _within_limits(model, q):
                return {
                    "success": True,
                    "joints": joints,
                    "iterations": it + 1,
                    "error": float(np.linalg.norm(err)),
                }
            return {
                "success": False,
                "joints": joints,
                "iterations": it + 1,
                "error": float(np.linalg.norm(err)),
                "message": "IK 解超出关节限位",
            }
        J = pin.computeFrameJacobian(model, data, q, _frame_id, pin.ReferenceFrame.LOCAL)
        v = -J.T @ np.linalg.solve(J @ J.T + damp * np.eye(6), err)
        q = pin.integrate(model, q, v * 0.5)

    pin.forwardKinematics(model, data, q)
    err_norm = float(np.linalg.norm(pin.log(data.oMf[_frame_id].inverse() * target).vector))
    return {
        "success": False,
        "joints": q_to_joints(q),
        "iterations": max_iter,
        "error": err_norm,
        "message": "IK 未收敛，请调整目标位姿",
    }


def compute_ik_multi_seed(
    position: List[float],
    orientation_rpy: Optional[List[float]] = None,
    q_seed: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Try live seed, ready preset, then zero — return first successful IK."""
    seeds: List[Optional[Dict[str, float]]] = []
    if q_seed:
        seeds.append(q_seed)
    seeds.append(READY_JOINTS)
    seeds.append({name: 0.0 for name in ARM_JOINT_NAMES})

    best: Optional[Dict[str, Any]] = None
    for seed in seeds:
        result = compute_ik(position, orientation_rpy, seed)
        if result.get("success"):
            return result
        if best is None or float(result.get("error") or 999) < float(best.get("error") or 999):
            best = result
    return best or {
        "success": False,
        "joints": {},
        "iterations": 0,
        "error": None,
        "message": "IK 未收敛，请调整目标位姿",
    }


def _within_limits(model: Any, q: Any) -> bool:
    import numpy as np

    if not hasattr(model, "lowerPositionLimit") or model.lowerPositionLimit is None:
        return True
    lo = model.lowerPositionLimit
    hi = model.upperPositionLimit
    if lo is None or hi is None:
        return True
    return bool(np.all(q >= lo - 1e-3) and np.all(q <= hi + 1e-3))
