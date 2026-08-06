"""DEPRECATED: legacy per-joint tick↔radian calibration.

Kept only for the M6 runtime regression smoke script
(_scripts/smoke_m6_runtime_regression.py). New code MUST use
`sender.lerobot_calibration` + `sender.joint_angles` which load
lerobot-standard MotorCalibration files from
~/.cache/huggingface/lerobot/calibration/ and do all tick↔normalized
conversion inside FeetechMotorsBus (normalize=True) — which is the
only way leader and follower arms can share a coordinate system
without manual JSON bookkeeping.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class JointCalibration:
    """A single joint's calibration record.

    `drive_mode` mirrors lerobot's per-motor direction flag: 0 = normal,
    1 = inverted (tick mirrored around the center of [min_pos, max_pos]).
    It's the escape hatch for a physical follower motor installed in the
    opposite orientation from the leader — most commonly the gripper, which
    users assemble by hand and sometimes end up with the jaw going the
    "wrong" way at teleop time. Flipping `drive_mode` is a runtime fix
    that doesn't require re-calibrating.
    """

    id: int
    name: str
    min_pos: int
    max_pos: int
    home_pos: int
    min_angle: float
    max_angle: float
    home_angle: float
    drive_mode: int = 0


DEFAULT_CALIB_CANDIDATES = (
    # bundled with sender package first
    os.path.join(os.path.dirname(__file__), "calibration_data.json"),
    # legacy MVP repo (rollback path)
    r"D:/Downloads/botverseX MVP/working_scripts/calibration_data.json",
)


class CalibrationLoader:
    """Reads calibration JSON produced by `calibration_tool.py`.

    JSON schema (see apps/realtime/sender/calibration_data.json):
        { "port": "COM3", "joints": [ {id, name, min_pos, max_pos, ...}, ... ] }
    """

    @staticmethod
    def resolve_path(explicit: Optional[str] = None) -> Optional[str]:
        if explicit:
            return explicit
        env = os.environ.get("BOTVERSEX_CALIB_FILE")
        if env:
            return env
        for c in DEFAULT_CALIB_CANDIDATES:
            if os.path.isfile(c):
                return c
        return None

    @staticmethod
    def load(calib_file: Optional[str] = None) -> List[JointCalibration]:
        path = CalibrationLoader.resolve_path(calib_file)
        if not path or not os.path.isfile(path):
            print(f"[WARN] calibration not found (tried {path or DEFAULT_CALIB_CANDIDATES}); using identity mapping")
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cals = [JointCalibration(**joint) for joint in data["joints"]]
            print(f"[OK] loaded {len(cals)} joint calibrations from {path}")
            return cals
        except Exception as exc:
            print(f"[ERR] failed to parse calibration {path}: {exc}")
            return []


def servo_to_angle(servo_val: float, calibration: List[JointCalibration], joint_idx: int) -> float:
    """Convert raw servo tick to radians via linear interpolation; identity fallback."""
    if joint_idx < len(calibration):
        cal = calibration[joint_idx]
        if cal.max_pos != cal.min_pos:
            ratio = (servo_val - cal.min_pos) / (cal.max_pos - cal.min_pos)
            return cal.min_angle + ratio * (cal.max_angle - cal.min_angle)
    # Fallback: assume 12-bit servo centered at 2048
    return (servo_val - 2048) / 2048 * 2.6
