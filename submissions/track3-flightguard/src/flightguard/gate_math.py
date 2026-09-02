"""Tensor-only geometric gate crossing for Genesis DroneEntity.

Genesis DroneEntity has no collision checking. Gate strikes must therefore be
computed geometrically instead of inferred from contact forces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class GateCrossing:
    crossed_plane: torch.Tensor
    passed: torch.Tensor
    struck_frame: torch.Tensor
    local_crossing_yz: torch.Tensor


def gate_lookthrough_target(
    gate_center: torch.Tensor,
    gate_yaw: torch.Tensor,
    distance_m: float,
) -> torch.Tensor:
    """Move a controller waypoint beyond a gate without moving its scoring plane."""

    if gate_center.ndim != 2 or gate_center.shape[1] != 3:
        raise ValueError("gate_center must have shape [N, 3]")
    if gate_yaw.shape != (gate_center.shape[0],):
        raise ValueError("gate_yaw must have shape [N]")
    distance = float(distance_m)
    if not math.isfinite(distance) or distance < 0.0:
        raise ValueError("distance_m must be finite and non-negative")
    if distance == 0.0:
        return gate_center
    forward = torch.stack(
        (
            torch.cos(gate_yaw),
            torch.sin(gate_yaw),
            torch.zeros_like(gate_yaw),
        ),
        dim=1,
    )
    return gate_center + distance * forward


def world_to_gate(
    points: torch.Tensor, gate_center: torch.Tensor, gate_yaw: torch.Tensor
) -> torch.Tensor:
    """Transform world points into a yaw-only gate frame."""

    delta = points - gate_center
    c = torch.cos(gate_yaw)
    s = torch.sin(gate_yaw)
    x = c * delta[:, 0] + s * delta[:, 1]
    y = -s * delta[:, 0] + c * delta[:, 1]
    return torch.stack((x, y, delta[:, 2]), dim=1)


def gate_crossing(
    previous_position: torch.Tensor,
    current_position: torch.Tensor,
    gate_center: torch.Tensor,
    gate_yaw: torch.Tensor,
    *,
    half_width: float,
    half_height: float,
    proxy_radius: float,
) -> GateCrossing:
    """Classify forward crossings through a rectangular aperture."""

    if previous_position.shape != current_position.shape or previous_position.ndim != 2:
        raise ValueError("positions must have matching shape [N, 3]")
    if previous_position.shape[1] != 3:
        raise ValueError("positions must have shape [N, 3]")
    if gate_center.shape != previous_position.shape:
        raise ValueError("gate_center must have shape [N, 3]")
    if gate_yaw.shape != (previous_position.shape[0],):
        raise ValueError("gate_yaw must have shape [N]")
    if half_width <= proxy_radius or half_height <= proxy_radius:
        raise ValueError("gate aperture must exceed proxy radius")

    previous_local = world_to_gate(previous_position, gate_center, gate_yaw)
    current_local = world_to_gate(current_position, gate_center, gate_yaw)
    crossed = (previous_local[:, 0] < 0) & (current_local[:, 0] >= 0)

    denominator = current_local[:, 0] - previous_local[:, 0]
    safe_denominator = torch.where(
        denominator.abs() > 1e-9, denominator, torch.ones_like(denominator)
    )
    alpha = (-previous_local[:, 0] / safe_denominator).clamp(0.0, 1.0)
    crossing_yz = previous_local[:, 1:] + alpha[:, None] * (
        current_local[:, 1:] - previous_local[:, 1:]
    )

    inside = (crossing_yz[:, 0].abs() <= half_width - proxy_radius) & (
        crossing_yz[:, 1].abs() <= half_height - proxy_radius
    )
    passed = crossed & inside
    struck = crossed & ~inside
    return GateCrossing(crossed, passed, struck, crossing_yz)
