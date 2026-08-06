#!/usr/bin/env python3
"""Run B601 Cartesian / joint-space moves via reBotArm_control_py (when installed)."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _emit(result: Dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False), flush=True)


def _import_sdk():
    try:
        from reBotArm_control_py.arm_controller import ArmController  # type: ignore
        return ArmController
    except ImportError:
        pass
    vendor = Path(__file__).resolve().parents[1] / "vendor" / "reBotArm_control_py"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    home = Path.home() / "reBotArm_control_py"
    if home.is_dir():
        sys.path.insert(0, str(home))
    from reBotArm_control_py.arm_controller import ArmController  # type: ignore
    return ArmController


def _deg_list(joints: Dict[str, float]) -> List[float]:
    out: List[float] = []
    for i in range(1, 7):
        key = f"joint{i}"
        out.append(math.degrees(float(joints.get(key, 0.0))))
    return out


def run_move_joints(joints: Dict[str, float], duration: float, can: str) -> Dict[str, Any]:
    ArmController = _import_sdk()
    ctrl = ArmController(channel=can)
    try:
        ctrl.enable()
        targets = _deg_list(joints)
        ctrl.move_to_joint_positions(targets, duration=duration)
        return {"ok": True, "message": "joint move complete"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    finally:
        try:
            ctrl.disable()
        except Exception:
            pass


def run_move_pose(
    position: List[float],
    orientation: Optional[List[float]],
    joints: Dict[str, float],
    duration: float,
    can: str,
) -> Dict[str, Any]:
    ArmController = _import_sdk()
    ctrl = ArmController(channel=can)
    try:
        ctrl.enable()
        if hasattr(ctrl, "move_to_pose"):
            rpy = orientation or [0.0, 0.0, 0.0]
            ctrl.move_to_pose(
                float(position[0]),
                float(position[1]),
                float(position[2]),
                float(rpy[0]),
                float(rpy[1]),
                float(rpy[2]),
                duration=duration,
            )
        else:
            targets = _deg_list(joints)
            ctrl.move_to_joint_positions(targets, duration=duration)
        return {"ok": True, "message": "pose move complete"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    finally:
        try:
            ctrl.disable()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, help="JSON payload")
    args = parser.parse_args()
    try:
        spec = json.loads(args.json)
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "message": f"invalid json: {exc}"})
        return 1

    mode = spec.get("mode")
    can = spec.get("can", "can0")
    duration = float(spec.get("duration", 2.0))

    try:
        if mode == "move_joints":
            result = run_move_joints(spec["joints"], duration, can)
        elif mode == "move_pose":
            result = run_move_pose(
                spec["position"],
                spec.get("orientation"),
                spec.get("joints") or {},
                duration,
                can,
            )
        else:
            result = {"ok": False, "message": f"unknown mode {mode}"}
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}

    _emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
