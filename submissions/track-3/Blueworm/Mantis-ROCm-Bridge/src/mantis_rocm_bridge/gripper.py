"""Guarded conversion between 16D virtual and 18D physical Mantis vectors."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .contracts import ContractError


def _mapping(port: dict[str, Any], allow_unverified: bool) -> dict[str, Any]:
    mapping = port["assets"]["virtual_gripper_mapping"]
    if mapping.get("status") != "verified" and not allow_unverified:
        raise ContractError(
            "virtual gripper mapping is not verified; use allow_unverified only for offline tests"
        )
    return mapping


def _finite_vector(values: Sequence[float], expected: int, context: str) -> list[float]:
    if len(values) != expected:
        raise ContractError(f"{context} length must be {expected}, got {len(values)}")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ContractError(f"{context} contains a non-finite value")
    return result


def virtual_to_physical(
    values: Sequence[float],
    port: dict[str, Any],
    *,
    allow_unverified: bool = False,
    range_tolerance: float = 1e-7,
) -> list[float]:
    """Expand a 16D policy vector into 14 arm plus four physical clamp targets."""
    mapping = _mapping(port, allow_unverified)
    virtual_order = port["target"]["joint_order"]
    physical_order = port["target"]["physical_joint_order"]
    vector = _finite_vector(values, len(virtual_order), "virtual Mantis vector")
    by_virtual = dict(zip(virtual_order, vector))
    coefficients = mapping["coefficients"]
    offsets = mapping["offsets"]

    by_physical: dict[str, float] = {
        name: by_virtual[name] for name in virtual_order if name not in coefficients
    }
    for virtual_name, physical_coefficients in coefficients.items():
        value = by_virtual[virtual_name]
        if value < -range_tolerance or value > 1.0 + range_tolerance:
            raise ContractError(f"{virtual_name} must be in [0, 1], got {value}")
        value = min(1.0, max(0.0, value))
        for physical_name, coefficient in physical_coefficients.items():
            by_physical[physical_name] = (
                float(offsets[virtual_name][physical_name]) + value * float(coefficient)
            )

    if set(by_physical) != set(physical_order):
        raise ContractError("virtual-to-physical mapping does not exactly cover physical_joint_order")
    return [by_physical[name] for name in physical_order]


@dataclass(frozen=True)
class VirtualGripperProjection:
    """Per virtual gripper diagnostics for the bounded symmetric projection."""

    virtual_name: str
    physical_names: list[str]
    #: Raw normalized open-fraction estimates, one per physical finger, before clamping.
    estimates: list[float]
    #: Symmetric least-squares projection (mean of the clamped estimates).
    projected_mean: float
    #: Asymmetry spread: ``max(estimates) - min(estimates)``.
    spread: float


@dataclass(frozen=True)
class GripperProjection:
    """Result of :func:`project_physical_to_virtual`."""

    #: 16D virtual Mantis vector (arm channels pass through; gripper channels are projected means).
    vector: list[float]
    #: Per virtual gripper diagnostics, in the mapping's coefficient order.
    grippers: list[VirtualGripperProjection] = field(default_factory=list)


def project_physical_to_virtual(
    values: Sequence[float],
    port: dict[str, Any],
    *,
    allow_unverified: bool = False,
    range_tolerance: float = 1e-7,
) -> GripperProjection:
    """Bounded symmetric projection of an 18D physical vector onto 16D virtual.

    Each virtual gripper is resolved into one normalized open-fraction estimate per
    physical finger.  Every estimate must lie within ``[-range_tolerance, 1 + range_tolerance]``
    (a strict per-finger gate); the estimates are then clamped to ``[0, 1]`` and averaged
    to produce the symmetric least-squares projection.  The function never rejects on
    *asymmetry* (the residual / spread is reported in the diagnostics); callers that
    require strict symmetry enforce their own ``pair_tolerance`` on the returned spread.

    Returns the 16D vector together with per-gripper diagnostics (physical names,
    estimates, projected mean, and spread).
    """
    mapping = _mapping(port, allow_unverified)
    virtual_order = port["target"]["joint_order"]
    physical_order = port["target"]["physical_joint_order"]
    vector = _finite_vector(values, len(physical_order), "physical Mantis vector")
    by_physical = dict(zip(physical_order, vector))
    coefficients = mapping["coefficients"]
    offsets = mapping["offsets"]

    by_virtual: dict[str, float] = {
        name: by_physical[name] for name in virtual_order if name not in coefficients
    }
    grippers: list[VirtualGripperProjection] = []
    for virtual_name, physical_coefficients in coefficients.items():
        physical_names: list[str] = []
        estimates: list[float] = []
        for physical_name, coefficient in physical_coefficients.items():
            coefficient = float(coefficient)
            if coefficient == 0:
                raise ContractError(f"zero gripper coefficient for {physical_name}")
            offset = float(offsets[virtual_name][physical_name])
            estimate = (by_physical[physical_name] - offset) / coefficient
            if estimate < -range_tolerance or estimate > 1.0 + range_tolerance:
                raise ContractError(
                    f"physical finger {physical_name} for {virtual_name} resolves to "
                    f"{estimate} outside [0, 1] (range tolerance {range_tolerance})"
                )
            physical_names.append(physical_name)
            estimates.append(estimate)
        clamped = [min(1.0, max(0.0, estimate)) for estimate in estimates]
        projected_mean = sum(clamped) / len(clamped)
        spread = max(estimates) - min(estimates)
        by_virtual[virtual_name] = projected_mean
        grippers.append(
            VirtualGripperProjection(
                virtual_name=virtual_name,
                physical_names=physical_names,
                estimates=estimates,
                projected_mean=projected_mean,
                spread=spread,
            )
        )

    if set(by_virtual) != set(virtual_order):
        raise ContractError("physical-to-virtual mapping does not exactly cover virtual order")
    return GripperProjection(vector=[by_virtual[name] for name in virtual_order], grippers=grippers)


def physical_to_virtual(
    values: Sequence[float],
    port: dict[str, Any],
    *,
    allow_unverified: bool = False,
    pair_tolerance: float = 1e-5,
    range_tolerance: float = 1e-7,
) -> list[float]:
    """Collapse four clamp positions into two virtual open-fraction channels.

    This is the strict runtime adapter: it delegates to
    :func:`project_physical_to_virtual` for the bounded projection (which keeps the
    strict per-finger range gate) and then rejects any virtual gripper whose physical
    fingers are asymmetric beyond ``pair_tolerance``.  The default ``pair_tolerance``
    is tight, so ordinary runtime callers must not silently absorb large asymmetry.
    """
    projection = project_physical_to_virtual(
        values,
        port,
        allow_unverified=allow_unverified,
        range_tolerance=range_tolerance,
    )
    for gripper in projection.grippers:
        if gripper.spread > pair_tolerance:
            raise ContractError(
                f"physical fingers for {gripper.virtual_name} are asymmetric: "
                f"estimates={gripper.estimates}, spread={gripper.spread}"
            )
    return projection.vector
