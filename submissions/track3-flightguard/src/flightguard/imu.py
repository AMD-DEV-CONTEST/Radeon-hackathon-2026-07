"""Quaternion-safe IMU perturbations shared by training and evaluation."""

from __future__ import annotations

import torch


def quaternion_multiply(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    """Hamilton product of batched ``[w, x, y, z]`` quaternions."""

    if left.shape != right.shape or left.ndim != 2 or left.shape[1] != 4:
        raise ValueError("quaternions must have matching shape [N, 4]")
    lw, lx, ly, lz = left.unbind(dim=1)
    rw, rx, ry, rz = right.unbind(dim=1)
    return torch.stack(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ),
        dim=1,
    )


def rotation_vector_to_quaternion(rotation_vector: torch.Tensor) -> torch.Tensor:
    """Convert batched rotation vectors to ``[w, x, y, z]`` quaternions."""

    if rotation_vector.ndim != 2 or rotation_vector.shape[1] != 3:
        raise ValueError("rotation_vector must have shape [N, 3]")
    angle = torch.linalg.vector_norm(rotation_vector, dim=1, keepdim=True)
    half_angle = 0.5 * angle
    scale = torch.sin(half_angle) / angle.clamp_min(1.0e-8)
    small_scale = 0.5 - angle.square() / 48.0
    scale = torch.where(angle < 1.0e-6, small_scale, scale)
    return torch.cat((torch.cos(half_angle), rotation_vector * scale), dim=1)


def perturb_imu(
    quaternion: torch.Tensor,
    angular_velocity: torch.Tensor,
    attitude_rotation_vector: torch.Tensor,
    angular_velocity_delta: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Apply batched world-frame attitude and angular-rate errors."""

    batch = quaternion.shape[0]
    if quaternion.shape != (batch, 4):
        raise ValueError("quaternion must have shape [N, 4]")
    for name, value in (
        ("angular_velocity", angular_velocity),
        ("attitude_rotation_vector", attitude_rotation_vector),
        ("angular_velocity_delta", angular_velocity_delta),
    ):
        if value.shape != (batch, 3):
            raise ValueError(f"{name} must have shape [N, 3]")
    delta_quaternion = rotation_vector_to_quaternion(attitude_rotation_vector)
    perturbed_quaternion = quaternion_multiply(delta_quaternion, quaternion)
    perturbed_quaternion = perturbed_quaternion / torch.linalg.vector_norm(
        perturbed_quaternion,
        dim=1,
        keepdim=True,
    ).clamp_min(1.0e-8)
    return perturbed_quaternion, angular_velocity + angular_velocity_delta
