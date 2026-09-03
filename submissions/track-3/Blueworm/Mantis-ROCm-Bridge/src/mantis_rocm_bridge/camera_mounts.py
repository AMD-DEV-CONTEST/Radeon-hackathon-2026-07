"""Camera-mount transforms for the Mantis competition simulation."""

from __future__ import annotations

import math
from typing import Any

from .contracts import ContractError


def fixed_rpy_transform(xyz_m: list[float], rpy_rad: list[float]) -> list[list[float]]:
    """Return the URDF fixed-axis XYZ roll-pitch-yaw homogeneous transform."""

    if len(xyz_m) != 3 or len(rpy_rad) != 3:
        raise ContractError("camera xyz and rpy must each contain three values")
    values = [float(value) for value in xyz_m + rpy_rad]
    if not all(math.isfinite(value) for value in values):
        raise ContractError("camera transform contains a non-finite value")
    x, y, z, roll, pitch, yaw = values
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y],
        [-sp, cp * sr, cp * cr, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def genesis_wrist_mounts(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and materialize the two source-equivalent Genesis offset matrices."""

    if contract.get("scope") != "competition_simulation":
        raise ContractError("camera contract scope must be competition_simulation")
    mounts = contract.get("mounts")
    if not isinstance(mounts, dict):
        raise ContractError("camera contract mounts must be an object")
    result: dict[str, dict[str, Any]] = {}
    for name in ("left_wrist_cam", "right_wrist_cam"):
        mount = mounts.get(name)
        if not isinstance(mount, dict):
            raise ContractError(f"camera contract misses {name}")
        if mount.get("status") != "source_equivalent_sim_mount_frozen":
            raise ContractError(f"camera mount {name} is not frozen")
        parent = mount.get("parent")
        if not isinstance(parent, str) or not parent.endswith("_wrist_yaw_link"):
            raise ContractError(f"camera mount {name} has an invalid Mantis parent link")
        result[name] = {
            "parent": parent,
            "offset_T": fixed_rpy_transform(mount.get("xyz_m", []), mount.get("rpy_rad", [])),
        }
    if contract.get("hardware_boundary", {}).get("status") != (
        "not_calibrated_not_required_for_simulation_submission"
    ):
        raise ContractError("camera contract must retain the physical-calibration boundary")
    return result
