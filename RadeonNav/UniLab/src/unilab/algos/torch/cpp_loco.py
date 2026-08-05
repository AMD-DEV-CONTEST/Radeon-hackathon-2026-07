"""Inference adapter for the frozen CPP Go2 MoE locomotion policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch


@dataclass(frozen=True)
class CppLocoContract:
    """Numeric contract shared by the CPP policy and UniLab Go2 rough task."""

    command_scale: tuple[float, ...] = (2.0, 2.0, 0.25)
    cpp_action_scale: float = 0.25
    clip_observations: float = 100.0
    clip_actions: float = 100.0
    unilab_clip_actions: float = 201.0
    cpp_default_dof: tuple[float, ...] = (
        0.1,
        0.8,
        -1.5,
        -0.1,
        0.8,
        -1.5,
        0.1,
        1.0,
        -1.5,
        -0.1,
        1.0,
        -1.5,
    )
    unilab_default_dof: tuple[float, ...] = (
        0.0,
        0.8,
        -1.5,
        0.0,
        0.8,
        -1.5,
        0.0,
        1.0,
        -1.5,
        0.0,
        1.0,
        -1.5,
    )
    actuator_to_dof: tuple[int, ...] = (3, 4, 5, 0, 1, 2, 9, 10, 11, 6, 7, 8)
    unilab_action_scale_actuator: tuple[float, ...] = (
        0.125,
        0.25,
        0.25,
        0.125,
        0.25,
        0.25,
        0.125,
        0.25,
        0.25,
        0.125,
        0.25,
        0.25,
    )


DEFAULT_CPP_LOCO_CONTRACT = CppLocoContract()


def _batch(value: np.ndarray, *, width: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must have shape (N, {width}), got {array.shape}")
    return array


def build_cpp_observation(
    unilab_observation: np.ndarray,
    previous_cpp_action: np.ndarray,
    projected_gravity: np.ndarray,
    contract: CppLocoContract = DEFAULT_CPP_LOCO_CONTRACT,
) -> np.ndarray:
    """Convert the UniLab Go2 rough 45-D observation to the CPP contract."""
    obs = _batch(unilab_observation, width=45, name="unilab_observation")
    previous = _batch(previous_cpp_action, width=12, name="previous_cpp_action")
    gravity = _batch(projected_gravity, width=3, name="projected_gravity")
    if obs.shape[0] != previous.shape[0] or obs.shape[0] != gravity.shape[0]:
        raise ValueError("observation, previous action, and gravity batch sizes differ")

    cpp_obs = obs.copy()
    cpp_obs[:, 3:6] = gravity
    cpp_obs[:, 6:9] *= np.asarray(contract.command_scale, dtype=np.float32)
    cpp_obs[:, 9:21] += np.asarray(contract.unilab_default_dof, dtype=np.float32)
    cpp_obs[:, 9:21] -= np.asarray(contract.cpp_default_dof, dtype=np.float32)
    cpp_obs[:, 33:45] = previous
    return np.clip(
        cpp_obs,
        -float(contract.clip_observations),
        float(contract.clip_observations),
    )


def cpp_action_to_unilab(
    cpp_action: np.ndarray,
    contract: CppLocoContract = DEFAULT_CPP_LOCO_CONTRACT,
) -> np.ndarray:
    """Map CPP actions to UniLab actions while preserving absolute joint targets."""
    action = np.clip(
        _batch(cpp_action, width=12, name="cpp_action"),
        -float(contract.clip_actions),
        float(contract.clip_actions),
    )
    cpp_target_dof = (
        np.asarray(contract.cpp_default_dof, dtype=np.float32)
        + float(contract.cpp_action_scale) * action
    )
    actuator_to_dof = np.asarray(contract.actuator_to_dof, dtype=np.int64)
    target_actuator = cpp_target_dof[:, actuator_to_dof]
    default_actuator = np.asarray(contract.unilab_default_dof, dtype=np.float32)[
        actuator_to_dof
    ]
    action_scale = np.asarray(contract.unilab_action_scale_actuator, dtype=np.float32)
    return (target_actuator - default_actuator) / action_scale


def unilab_action_to_canonical_target(
    unilab_action: np.ndarray,
    contract: CppLocoContract = DEFAULT_CPP_LOCO_CONTRACT,
) -> np.ndarray:
    """Reconstruct the canonical physical target for contract checks."""
    action = _batch(unilab_action, width=12, name="unilab_action")
    actuator_to_dof = np.asarray(contract.actuator_to_dof, dtype=np.int64)
    default_actuator = np.asarray(contract.unilab_default_dof, dtype=np.float32)[
        actuator_to_dof
    ]
    scale = np.asarray(contract.unilab_action_scale_actuator, dtype=np.float32)
    target_actuator = default_actuator + scale * action
    target_dof = np.empty_like(target_actuator)
    target_dof[:, actuator_to_dof] = target_actuator
    return target_dof


class CppLocoPolicyAdapter:
    """Run the single-environment CPP TorchScript policy inside UniLab."""

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        device: str | torch.device = "cpu",
        contract: CppLocoContract = DEFAULT_CPP_LOCO_CONTRACT,
    ) -> None:
        self.device = torch.device(device)
        self.contract = contract
        self.policy = torch.jit.load(str(checkpoint), map_location=self.device).eval()
        self.previous_cpp_action = np.zeros((1, 12), dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        self.policy.reset()
        self.previous_cpp_action.fill(0.0)

    def act(
        self,
        unilab_observation: np.ndarray,
        *,
        projected_gravity: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        obs = _batch(unilab_observation, width=45, name="unilab_observation")
        if obs.shape[0] != 1:
            raise ValueError(
                "the exported CPP TorchScript checkpoint is stateful and supports one environment"
            )
        cpp_obs = build_cpp_observation(
            obs, self.previous_cpp_action, projected_gravity, self.contract
        )
        with torch.inference_mode():
            output = self.policy(torch.as_tensor(cpp_obs, device=self.device))
        if not isinstance(output, tuple) or len(output) != 2:
            raise RuntimeError("CPP policy must return (actions, (expert_weights, latent))")
        cpp_action_tensor, aux = output
        if not isinstance(aux, tuple) or len(aux) != 2:
            raise RuntimeError("CPP policy auxiliary output must contain weights and latent")
        weights_tensor, latent_tensor = aux
        cpp_action_raw = (
            cpp_action_tensor.detach().cpu().numpy().astype(np.float32, copy=False)
        )
        weights = weights_tensor.detach().cpu().numpy().astype(np.float32, copy=False)
        latent = latent_tensor.detach().cpu().numpy().astype(np.float32, copy=False)
        if (
            cpp_action_raw.shape != (1, 12)
            or weights.shape != (1, 8)
            or latent.shape != (1, 32)
        ):
            raise RuntimeError(
                "unexpected CPP output shapes: "
                f"actions={cpp_action_raw.shape}, weights={weights.shape}, latent={latent.shape}"
            )
        if not all(np.isfinite(value).all() for value in (cpp_action_raw, weights, latent)):
            raise FloatingPointError("CPP policy produced NaN or Inf")

        cpp_action = np.clip(
            cpp_action_raw,
            -float(self.contract.clip_actions),
            float(self.contract.clip_actions),
        )
        self.previous_cpp_action[:] = cpp_action
        return cpp_action_to_unilab(cpp_action, self.contract), {
            "cpp_observation": cpp_obs,
            "cpp_action": cpp_action,
            "cpp_action_raw": cpp_action_raw,
            "expert_weights": weights,
            "latent": latent,
        }


__all__ = [
    "CppLocoContract",
    "CppLocoPolicyAdapter",
    "DEFAULT_CPP_LOCO_CONTRACT",
    "build_cpp_observation",
    "cpp_action_to_unilab",
    "unilab_action_to_canonical_target",
]
