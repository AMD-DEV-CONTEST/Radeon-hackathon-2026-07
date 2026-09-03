"""Pure helpers shared by the Genesis Mantis runtime smoke tool."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .gripper import virtual_to_physical


BACKENDS = ("cpu", "cuda", "amdgpu")


def resolve_backend(genesis: Any, name: str) -> Any:
    """Return an explicit Genesis backend without silently falling back."""
    if name not in BACKENDS:
        raise ContractError(f"unsupported Genesis backend: {name}")
    if not hasattr(genesis, name):
        raise ContractError(f"installed Genesis does not expose gs.{name}")
    return getattr(genesis, name)


def physical_pose(port: dict[str, Any], open_fraction: float) -> list[float]:
    """Build an 18D zero-arm pose with both virtual grippers at one fraction."""
    fraction = float(open_fraction)
    if not math.isfinite(fraction) or fraction < 0.0 or fraction > 1.0:
        raise ContractError("open_fraction must be finite and in [0, 1]")
    policy_order = port["target"]["joint_order"]
    virtual_grippers = set(port["assets"]["virtual_gripper_mapping"]["coefficients"])
    policy_pose = [fraction if name in virtual_grippers else 0.0 for name in policy_order]
    return virtual_to_physical(policy_pose, port, allow_unverified=True)


def max_abs_error(actual: Sequence[float], expected: Sequence[float]) -> float:
    if len(actual) != len(expected):
        raise ContractError(f"vector length mismatch: {len(actual)} != {len(expected)}")
    errors = [abs(float(left) - float(right)) for left, right in zip(actual, expected)]
    if not all(math.isfinite(value) for value in errors):
        raise ContractError("non-finite value in Genesis readback")
    return max(errors, default=0.0)


def gripper_geometry(
    port: dict[str, Any],
    child_links: dict[str, str],
    closed_positions: dict[str, list[float]],
    open_positions: dict[str, list[float]],
) -> dict[str, Any]:
    """Measure simulated finger travel and link-origin separation."""
    result: dict[str, Any] = {}
    coefficients = port["assets"]["virtual_gripper_mapping"]["coefficients"]
    for virtual_name, physical_map in coefficients.items():
        joints = list(physical_map)
        links = [child_links[name] for name in joints]
        closed = [closed_positions[name] for name in links]
        opened = [open_positions[name] for name in links]
        travels = [math.dist(before, after) for before, after in zip(closed, opened)]
        closed_separation = math.dist(*closed)
        open_separation = math.dist(*opened)
        result[virtual_name] = {
            "physical_joints": joints,
            "child_links": links,
            "closed_link_positions": closed,
            "open_link_positions": opened,
            "individual_travel_m": travels,
            "symmetric_travel_error_m": abs(travels[0] - travels[1]),
            "closed_origin_separation_m": closed_separation,
            "open_origin_separation_m": open_separation,
            "separation_increase_m": open_separation - closed_separation,
            "kinematic_gate_pass": (
                abs(travels[0] - travels[1]) <= 1e-6
                and min(travels) > 0.0
                and open_separation > closed_separation
            ),
        }
    return result


def compare_joint_limits(
    joint_order: Sequence[str],
    actual_lower: Sequence[float],
    actual_upper: Sequence[float],
    frozen_limits: dict[str, Any],
) -> dict[str, Any]:
    """Compare Genesis-parsed positional limits with the frozen URDF receipt."""
    if len(actual_lower) != len(joint_order) or len(actual_upper) != len(joint_order):
        raise ContractError("Genesis joint-limit vector length mismatch")
    rows = []
    max_error = 0.0
    for name, lower, upper in zip(joint_order, actual_lower, actual_upper):
        expected = frozen_limits[name]
        lower_error = abs(float(lower) - float(expected["lower"]))
        upper_error = abs(float(upper) - float(expected["upper"]))
        if not math.isfinite(lower_error) or not math.isfinite(upper_error):
            raise ContractError(f"non-finite Genesis limit for {name}")
        max_error = max(max_error, lower_error, upper_error)
        rows.append(
            {
                "joint": name,
                "actual_lower": float(lower),
                "actual_upper": float(upper),
                "expected_lower": float(expected["lower"]),
                "expected_upper": float(expected["upper"]),
            }
        )
    return {"max_abs_error": max_error, "pass": max_error <= 1e-6, "joints": rows}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
