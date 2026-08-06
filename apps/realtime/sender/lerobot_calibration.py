"""lerobot-standard calibration loader / saver.

This is the NEW calibration path. The old `calibration.py` with its custom
`{min_pos, max_pos, home_pos, min_angle, max_angle, home_angle}` JSON format
is obsolete — it bypasses lerobot's per-motor `MotorCalibration` model and
forces us to maintain two independent tick→angle maps that inevitably
drift out of sync between leader and follower.

What this module does:
  - Loads lerobot's standard calibration JSON from
    ~/.cache/huggingface/lerobot/calibration/{category}/{robot_type}/{id}.json
    into a `dict[str, MotorCalibration]`, ready to hand to FeetechMotorsBus.
  - Creates the 6 SO101 Motor entries with the correct `MotorNormMode`
    (RANGE_M100_100 for joints, RANGE_0_100 for gripper) — matching what
    the lerobot `SO101Leader` / `SO101Follower` wrappers use, so
    sync_read/sync_write with normalize=True returns the same device-
    independent values across leader and follower.

Layout on disk (matches MakerMods + lerobot SDK conventions):
    ~/.cache/huggingface/lerobot/calibration/
        robots/so101_follower/<device_id>.json          (follower)
        teleoperators/so101_leader/<device_id>.json     (leader)

The JSON schema per motor (written by the MakerMods auto/manual calibration
scripts and by lerobot's own `write_calibration()`):
    {
      "shoulder_pan": {
          "id": 1, "drive_mode": 0, "homing_offset": -1553,
          "range_min": 660, "range_max": 3434
      },
      ...
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from lerobot.motors import Motor, MotorCalibration, MotorNormMode


# SO101 motor names + IDs, identical to MakerMods' manual_calibration.py
# (see lerobot-MakerMods-main/.../backend/services/manual_calibration.py)
SO101_MOTOR_NAMES = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]
SO101_MOTOR_IDS = {name: i + 1 for i, name in enumerate(SO101_MOTOR_NAMES)}


LEROBOT_CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"


def calibration_path(device_type: str, device_id: str) -> Path:
    """Resolve the on-disk calibration path for a device.

    device_type: "follower" or "leader"
    device_id:   free-form id the user picked during calibration
                 (e.g. "ethan_follower", "single_leader", ...)
    """
    if device_type == "follower":
        return LEROBOT_CALIB_ROOT / "robots" / "so101_follower" / f"{device_id}.json"
    if device_type == "leader":
        return LEROBOT_CALIB_ROOT / "teleoperators" / "so101_leader" / f"{device_id}.json"
    raise ValueError(f"unknown device_type {device_type!r} (expected 'follower' or 'leader')")


def load_motor_calibration(path: Path) -> Dict[str, MotorCalibration]:
    """Parse a lerobot standard calibration JSON file into a MotorCalibration dict.

    Raises FileNotFoundError if path doesn't exist — caller should handle
    this as "device not calibrated yet, push user to calibration flow".
    """
    if not path.is_file():
        raise FileNotFoundError(f"calibration file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: Dict[str, MotorCalibration] = {}
    for name, data in raw.items():
        out[name] = MotorCalibration(
            id=int(data["id"]),
            drive_mode=int(data.get("drive_mode", 0)),
            homing_offset=int(data["homing_offset"]),
            range_min=int(data["range_min"]),
            range_max=int(data["range_max"]),
        )
    return out


def build_motors_dict(motor_names: Optional[Iterable[str]] = None) -> Dict[str, Motor]:
    """Build the 6-entry Motor dict FeetechMotorsBus wants.

    Uses the same norm-mode split as lerobot's SO101Leader/SO101Follower
    and MakerMods' manual_calibration.create_bus():
      - gripper → RANGE_0_100 (one-sided, fraction of grip closure)
      - all others → RANGE_M100_100 (symmetric about home)
    """
    selected_names = list(motor_names) if motor_names is not None else list(SO101_MOTOR_NAMES)
    motors: Dict[str, Motor] = {}
    for name in selected_names:
        if name not in SO101_MOTOR_IDS:
            continue
        norm_mode = (
            MotorNormMode.RANGE_0_100 if name == "gripper"
            else MotorNormMode.RANGE_M100_100
        )
        motors[name] = Motor(SO101_MOTOR_IDS[name], "sts3215", norm_mode)
    return motors


def resolve_device_id(device_type: str, explicit: Optional[str] = None) -> Optional[str]:
    """Pick the calibration device_id to use.

    Priority:
      1. explicit arg (from CLI / API request)
      2. env: BOTVERSEX_{FOLLOWER|LEADER}_DEVICE_ID
      3. auto-discover: if exactly ONE file exists under the device_type
         folder, use its stem. If zero or multiple, return None and let
         the caller decide (usually: push user to calibration flow).
    """
    if explicit:
        return explicit
    env_key = "BOTVERSEX_FOLLOWER_DEVICE_ID" if device_type == "follower" else "BOTVERSEX_LEADER_DEVICE_ID"
    env = os.environ.get(env_key)
    if env:
        return env

    if device_type == "follower":
        folder = LEROBOT_CALIB_ROOT / "robots" / "so101_follower"
    elif device_type == "leader":
        folder = LEROBOT_CALIB_ROOT / "teleoperators" / "so101_leader"
    else:
        return None
    if not folder.is_dir():
        return None
    files = list(folder.glob("*.json"))
    if not files:
        return None
    if len(files) == 1:
        return files[0].stem
    # Ambiguous: user has multiple calibrations. Pick the most recently
    # modified so the common "I re-ran calibration" case Just Works. The
    # UI can still let the user pick explicitly and pass it as --device-id.
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].stem


def list_available(device_type: str) -> list[str]:
    """Return sorted list of available device_id for the given device_type."""
    if device_type == "follower":
        folder = LEROBOT_CALIB_ROOT / "robots" / "so101_follower"
    elif device_type == "leader":
        folder = LEROBOT_CALIB_ROOT / "teleoperators" / "so101_leader"
    else:
        return []
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json"))


def resolve_and_load(
    device_type: str,
    explicit_device_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, MotorCalibration]]]:
    """Convenience: return (device_id, calibration_dict) or (None, None) if missing.

    The `None, None` case means the user must run calibration first.
    """
    device_id = resolve_device_id(device_type, explicit_device_id)
    if device_id is None:
        return None, None
    path = calibration_path(device_type, device_id)
    try:
        cal = load_motor_calibration(path)
    except FileNotFoundError:
        return device_id, None
    return device_id, cal


__all__ = [
    "SO101_MOTOR_NAMES",
    "SO101_MOTOR_IDS",
    "LEROBOT_CALIB_ROOT",
    "calibration_path",
    "load_motor_calibration",
    "build_motors_dict",
    "resolve_device_id",
    "list_available",
    "resolve_and_load",
]
