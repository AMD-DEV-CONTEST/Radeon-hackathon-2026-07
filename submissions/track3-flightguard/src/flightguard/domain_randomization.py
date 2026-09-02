"""Deterministic physics-domain profiles shared by training and evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch

DOMAIN_PROFILE_NAMES = (
    "off",
    "train",
    "heldout",
    "kill",
    "adversarial",
    "adversarial_v3",
)
ADVERSARIAL_PROFILE_VERSION = "compositional-heldout-edge-v2"
ADVERSARIAL_V3_PROFILE_VERSION = "dropout-onset-compositional-edge-v3"
CPU_DEVICE = torch.device("cpu")


@dataclass(frozen=True)
class DomainParameters:
    """Per-environment physical parameters sampled on CPU."""

    mass_scale: torch.Tensor
    thrust_scale: torch.Tensor
    wind_acceleration_mps2: torch.Tensor
    action_delay_steps: torch.Tensor
    stratum: torch.Tensor
    profile: str
    seed: int
    scheduled_thrust_scale: torch.Tensor | None = None
    scheduled_wind_acceleration_mps2: torch.Tensor | None = None
    scheduled_action_delay_steps: torch.Tensor | None = None

    def __post_init__(self) -> None:
        count = int(self.mass_scale.numel())
        if self.mass_scale.shape != (count,):
            raise ValueError("mass_scale must have shape [N]")
        if self.thrust_scale.shape != (count,):
            raise ValueError("thrust_scale must have shape [N]")
        if self.wind_acceleration_mps2.shape != (count, 3):
            raise ValueError("wind_acceleration_mps2 must have shape [N, 3]")
        if self.action_delay_steps.shape != (count,):
            raise ValueError("action_delay_steps must have shape [N]")
        if self.stratum.shape != (count,):
            raise ValueError("stratum must have shape [N]")
        if self.profile not in DOMAIN_PROFILE_NAMES:
            raise ValueError(f"unsupported domain profile: {self.profile}")
        if not bool(torch.isfinite(self.mass_scale).all()):
            raise ValueError("mass_scale must be finite")
        if not bool(torch.isfinite(self.thrust_scale).all()):
            raise ValueError("thrust_scale must be finite")
        if not bool(torch.isfinite(self.wind_acceleration_mps2).all()):
            raise ValueError("wind acceleration must be finite")
        if not bool((self.mass_scale > 0.0).all()):
            raise ValueError("mass_scale must be positive")
        if not bool((self.thrust_scale > 0.0).all()):
            raise ValueError("thrust_scale must be positive")
        if self.action_delay_steps.dtype != torch.long:
            raise TypeError("action_delay_steps must use torch.long")
        if not bool((self.action_delay_steps >= 0).all()):
            raise ValueError("action_delay_steps must be non-negative")
        scheduled = (
            self.scheduled_thrust_scale,
            self.scheduled_wind_acceleration_mps2,
            self.scheduled_action_delay_steps,
        )
        scheduled_count = sum(value is not None for value in scheduled)
        if scheduled_count not in (0, len(scheduled)):
            raise ValueError("scheduled targets must be all None or all non-None")
        if scheduled_count and self.profile != "adversarial_v3":
            raise ValueError("scheduled targets are only supported by adversarial_v3")
        if self.profile == "adversarial_v3" and scheduled_count != len(scheduled):
            raise ValueError("adversarial_v3 requires all scheduled targets")
        if scheduled_count:
            scheduled_thrust = self.scheduled_thrust_scale
            scheduled_wind = self.scheduled_wind_acceleration_mps2
            scheduled_delay = self.scheduled_action_delay_steps
            assert scheduled_thrust is not None
            assert scheduled_wind is not None
            assert scheduled_delay is not None
            if scheduled_thrust.shape != (count,):
                raise ValueError("scheduled_thrust_scale must have shape [N]")
            if scheduled_wind.shape != (count, 3):
                raise ValueError("scheduled_wind_acceleration_mps2 must have shape [N, 3]")
            if scheduled_delay.shape != (count,):
                raise ValueError("scheduled_action_delay_steps must have shape [N]")
            if not bool(torch.isfinite(scheduled_thrust).all()):
                raise ValueError("scheduled_thrust_scale must be finite")
            if not bool((scheduled_thrust > 0.0).all()):
                raise ValueError("scheduled_thrust_scale must be positive")
            if not bool(torch.isfinite(scheduled_wind).all()):
                raise ValueError("scheduled wind acceleration must be finite")
            if scheduled_delay.dtype != torch.long:
                raise TypeError("scheduled_action_delay_steps must use torch.long")
            if not bool((scheduled_delay >= 0).all()):
                raise ValueError("scheduled_action_delay_steps must be non-negative")
        if self.profile == "adversarial_v3":
            if not bool((self.mass_scale == 1.0).all()):
                raise ValueError("adversarial_v3 base mass_scale must stay nominal")
            if not bool((self.thrust_scale == 1.0).all()):
                raise ValueError("adversarial_v3 base thrust_scale must stay nominal")
            if not bool((self.wind_acceleration_mps2 == 0.0).all()):
                raise ValueError("adversarial_v3 base wind acceleration must stay nominal")
            if not bool((self.action_delay_steps == 0).all()):
                raise ValueError("adversarial_v3 base action delay must stay nominal")

    @property
    def count(self) -> int:
        return int(self.mass_scale.numel())

    def repeat(self, groups: int) -> DomainParameters:
        """Repeat one paired block without drawing new random numbers."""

        if groups <= 0:
            raise ValueError("groups must be positive")
        scheduled_thrust = self.scheduled_thrust_scale
        scheduled_wind = self.scheduled_wind_acceleration_mps2
        scheduled_delay = self.scheduled_action_delay_steps
        return DomainParameters(
            mass_scale=self.mass_scale.repeat(groups),
            thrust_scale=self.thrust_scale.repeat(groups),
            wind_acceleration_mps2=self.wind_acceleration_mps2.repeat(groups, 1),
            action_delay_steps=self.action_delay_steps.repeat(groups),
            stratum=self.stratum.repeat(groups),
            profile=self.profile,
            seed=self.seed,
            scheduled_thrust_scale=(
                scheduled_thrust.repeat(groups) if scheduled_thrust is not None else None
            ),
            scheduled_wind_acceleration_mps2=(
                scheduled_wind.repeat(groups, 1) if scheduled_wind is not None else None
            ),
            scheduled_action_delay_steps=(
                scheduled_delay.repeat(groups) if scheduled_delay is not None else None
            ),
        )

    def summary(self) -> dict[str, Any]:
        wind_norm = torch.linalg.vector_norm(self.wind_acceleration_mps2, dim=1)
        unique_strata, stratum_counts = torch.unique(self.stratum, return_counts=True)
        summary = {
            "profile": self.profile,
            "seed": self.seed,
            "count": self.count,
            "mass_scale": {
                "min": float(self.mass_scale.min().item()),
                "max": float(self.mass_scale.max().item()),
            },
            "thrust_scale": {
                "min": float(self.thrust_scale.min().item()),
                "max": float(self.thrust_scale.max().item()),
            },
            "wind_acceleration_norm_mps2": {
                "min": float(wind_norm.min().item()),
                "max": float(wind_norm.max().item()),
            },
            "action_delay_steps": {
                "min": int(self.action_delay_steps.min().item()),
                "max": int(self.action_delay_steps.max().item()),
            },
            "stratum_counts": {
                str(int(index.item())): int(count.item())
                for index, count in zip(unique_strata, stratum_counts)
            },
        }
        if self.profile == "adversarial":
            summary["definition_version"] = ADVERSARIAL_PROFILE_VERSION
            summary["ood_source"] = (
                "coupled composition of previously audited heldout-edge marginals"
            )
        elif self.profile == "adversarial_v3":
            summary["definition_version"] = ADVERSARIAL_V3_PROFILE_VERSION
            summary["ood_source"] = (
                "dropout-onset coupled composition of previously audited heldout-edge marginals"
            )
            summary["fault_timing"] = (
                "dropout_onset_after_context_freeze_before_first_blackout_step"
            )
            summary["base_switchable_parameters_nominal"] = True
            scheduled_thrust = self.scheduled_thrust_scale
            scheduled_wind = self.scheduled_wind_acceleration_mps2
            scheduled_delay = self.scheduled_action_delay_steps
            if (
                scheduled_thrust is not None
                and scheduled_wind is not None
                and scheduled_delay is not None
            ):
                scheduled_wind_norm = torch.linalg.vector_norm(
                    scheduled_wind,
                    dim=1,
                )
                summary["scheduled_targets"] = {
                    "thrust_scale": {
                        "min": float(scheduled_thrust.min().item()),
                        "max": float(scheduled_thrust.max().item()),
                    },
                    "wind_acceleration_mps2": {
                        "component_min": [
                            float(value) for value in scheduled_wind.min(dim=0).values
                        ],
                        "component_max": [
                            float(value) for value in scheduled_wind.max(dim=0).values
                        ],
                        "norm_min": float(scheduled_wind_norm.min().item()),
                        "norm_max": float(scheduled_wind_norm.max().item()),
                    },
                    "action_delay_steps": {
                        "min": int(scheduled_delay.min().item()),
                        "max": int(scheduled_delay.max().item()),
                    },
                }
        return summary


def _uniform(
    count: int,
    low: float,
    high: float,
    *,
    generator: torch.Generator,
) -> torch.Tensor:
    if low == high:
        return torch.full((count,), low, dtype=torch.float32, device=CPU_DEVICE)
    return low + (high - low) * torch.rand(
        count,
        generator=generator,
        dtype=torch.float32,
        device=CPU_DEVICE,
    )


def _signed_magnitude(
    count: int,
    low: float,
    high: float,
    *,
    generator: torch.Generator,
) -> torch.Tensor:
    magnitude = _uniform(count, low, high, generator=generator)
    sign = torch.where(
        torch.rand(count, generator=generator, device=CPU_DEVICE) < 0.5,
        -torch.ones(count, device=CPU_DEVICE),
        torch.ones(count, device=CPU_DEVICE),
    )
    return sign * magnitude


def _edge_scale(
    count: int,
    *,
    outer_low: float,
    inner_low: float,
    inner_high: float,
    outer_high: float,
    generator: torch.Generator,
) -> torch.Tensor:
    lower = _uniform(count, outer_low, inner_low, generator=generator)
    upper = _uniform(count, inner_high, outer_high, generator=generator)
    choose_upper = torch.rand(count, generator=generator, device=CPU_DEVICE) >= 0.5
    return torch.where(choose_upper, upper, lower)


def _wind(
    count: int,
    *,
    xy_min: float,
    xy_max: float,
    z_min: float,
    z_max: float,
    generator: torch.Generator,
) -> torch.Tensor:
    magnitude = _uniform(count, xy_min, xy_max, generator=generator)
    angle = 2.0 * math.pi * torch.rand(count, generator=generator, device=CPU_DEVICE)
    wind = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
    wind[:, 0] = magnitude * torch.cos(angle)
    wind[:, 1] = magnitude * torch.sin(angle)
    wind[:, 2] = _signed_magnitude(count, z_min, z_max, generator=generator)
    return wind


def sample_domain_parameters(
    count: int,
    *,
    profile: str,
    seed: int,
) -> DomainParameters | None:
    """Sample a pre-registered profile without touching global RNG state.

    ``off`` returns ``None`` and consumes no RNG, which preserves exact
    compatibility with the accepted fixed-domain baseline.
    """

    if count <= 0:
        raise ValueError("count must be positive")
    if profile not in DOMAIN_PROFILE_NAMES:
        raise ValueError(f"unsupported domain profile: {profile}")
    if profile == "off":
        return None

    generator = torch.Generator(device=CPU_DEVICE)
    generator.manual_seed(seed)
    mass_scale = torch.ones(count, dtype=torch.float32, device=CPU_DEVICE)
    thrust_scale = torch.ones(count, dtype=torch.float32, device=CPU_DEVICE)
    wind = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
    delay = torch.zeros(count, dtype=torch.long, device=CPU_DEVICE)
    stratum = torch.full((count,), -1, dtype=torch.long, device=CPU_DEVICE)

    if profile == "train":
        mass_scale = _uniform(count, 0.90, 1.10, generator=generator)
        thrust_scale = _uniform(count, 0.90, 1.10, generator=generator)
        wind = _wind(
            count,
            xy_min=0.0,
            xy_max=0.30,
            z_min=0.0,
            z_max=0.10,
            generator=generator,
        )
        delay = torch.randint(
            0,
            4,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )
    elif profile == "heldout":
        # One edge factor per environment; the remaining factors stay nominal.
        # Cycling strata makes the paired evaluator exactly auditable.
        stratum = torch.arange(count, dtype=torch.long, device=CPU_DEVICE) % 5
        edge_mass = _edge_scale(
            count,
            outer_low=0.80,
            inner_low=0.90,
            inner_high=1.10,
            outer_high=1.20,
            generator=generator,
        )
        edge_thrust = _edge_scale(
            count,
            outer_low=0.80,
            inner_low=0.90,
            inner_high=1.10,
            outer_high=1.20,
            generator=generator,
        )
        edge_wind = _wind(
            count,
            xy_min=0.30,
            xy_max=0.60,
            z_min=0.0,
            z_max=0.0,
            generator=generator,
        )
        edge_vertical = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
        edge_vertical[:, 2] = _signed_magnitude(count, 0.10, 0.20, generator=generator)
        edge_delay = torch.randint(
            4,
            7,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )
        mass_scale = torch.where(stratum == 0, edge_mass, mass_scale)
        thrust_scale = torch.where(stratum == 1, edge_thrust, thrust_scale)
        wind = torch.where((stratum == 2)[:, None], edge_wind, wind)
        wind = torch.where((stratum == 3)[:, None], edge_vertical, wind)
        delay = torch.where(stratum == 4, edge_delay, delay)
    elif profile == "kill":
        mass_scale.fill_(1.50)
        thrust_scale.fill_(0.70)
        wind = _wind(
            count,
            xy_min=1.0,
            xy_max=1.0,
            z_min=0.30,
            z_max=0.30,
            generator=generator,
        )
        delay.fill_(10)
        stratum.fill_(5)
    elif profile == "adversarial":
        # Compositional edge cases for falsification.  Unlike ``heldout``,
        # every environment changes at least two coupled factors.
        stratum = (torch.arange(count, dtype=torch.long, device=CPU_DEVICE) % 6) + 6
        # Keep every marginal inside the already-audited heldout edges.  The
        # OOD challenge comes from composing factors that were previously
        # varied one at a time, rather than from controller-infeasible
        # single-factor magnitudes.
        coupled_mass = _uniform(count, 1.10, 1.18, generator=generator)
        coupled_thrust = _uniform(count, 0.94, 0.98, generator=generator)
        coupled_horizontal_wind = _wind(
            count,
            xy_min=0.30,
            xy_max=0.60,
            z_min=0.0,
            z_max=0.0,
            generator=generator,
        )
        coupled_vertical_wind = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
        coupled_vertical_wind[:, 2] = _signed_magnitude(count, 0.10, 0.20, generator=generator)
        coupled_delay = torch.randint(
            4,
            7,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )
        joint_mass = _uniform(count, 1.05, 1.12, generator=generator)
        joint_thrust = _uniform(count, 0.93, 0.99, generator=generator)
        joint_horizontal_wind = _wind(
            count,
            xy_min=0.30,
            xy_max=0.50,
            z_min=0.0,
            z_max=0.0,
            generator=generator,
        )
        joint_vertical_wind = _signed_magnitude(count, 0.08, 0.15, generator=generator)
        joint_delay = torch.randint(
            3,
            6,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )

        mass_scale = torch.where(
            torch.isin(stratum, stratum.new_tensor((6, 9, 11))),
            coupled_mass,
            mass_scale,
        )
        thrust_scale = torch.where(
            torch.isin(stratum, stratum.new_tensor((6, 10, 11))),
            coupled_thrust,
            thrust_scale,
        )
        wind = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((7, 9, 10, 11)),
            )[:, None],
            coupled_horizontal_wind,
            wind,
        )
        wind = torch.where(
            (stratum == 8)[:, None],
            coupled_vertical_wind,
            wind,
        )
        delay = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((7, 8, 10, 11)),
            ),
            coupled_delay,
            delay,
        )
        joint = stratum == 11
        mass_scale[joint] = joint_mass[joint]
        thrust_scale[joint] = joint_thrust[joint]
        wind[joint] = joint_horizontal_wind[joint]
        wind[joint, 2] = joint_vertical_wind[joint]
        delay[joint] = joint_delay[joint]
    else:
        # The vehicle stays nominal while the causal context is fitted.  These
        # targets are applied atomically at dropout onset by the evaluator.
        stratum = (torch.arange(count, dtype=torch.long, device=CPU_DEVICE) % 6) + 12
        scheduled_thrust = torch.ones(count, dtype=torch.float32, device=CPU_DEVICE)
        scheduled_wind = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
        scheduled_delay = torch.zeros(count, dtype=torch.long, device=CPU_DEVICE)

        coupled_thrust = _uniform(count, 0.94, 0.98, generator=generator)
        coupled_horizontal_wind = _wind(
            count,
            xy_min=0.30,
            xy_max=0.60,
            z_min=0.0,
            z_max=0.0,
            generator=generator,
        )
        coupled_vertical_wind = torch.zeros((count, 3), dtype=torch.float32, device=CPU_DEVICE)
        coupled_vertical_wind[:, 2] = _signed_magnitude(count, 0.10, 0.20, generator=generator)
        coupled_delay = torch.randint(
            4,
            7,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )
        joint_thrust = _uniform(count, 0.93, 0.99, generator=generator)
        joint_horizontal_wind = _wind(
            count,
            xy_min=0.30,
            xy_max=0.50,
            z_min=0.0,
            z_max=0.0,
            generator=generator,
        )
        joint_vertical_wind = _signed_magnitude(count, 0.08, 0.15, generator=generator)
        joint_delay = torch.randint(
            3,
            6,
            (count,),
            generator=generator,
            dtype=torch.long,
            device=CPU_DEVICE,
        )

        scheduled_thrust = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((12, 13, 16, 17)),
            ),
            coupled_thrust,
            scheduled_thrust,
        )
        scheduled_wind = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((12, 14, 16, 17)),
            )[:, None],
            coupled_horizontal_wind,
            scheduled_wind,
        )
        scheduled_wind = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((13, 15)),
            )[:, None],
            coupled_vertical_wind,
            scheduled_wind,
        )
        scheduled_delay = torch.where(
            torch.isin(
                stratum,
                stratum.new_tensor((14, 15, 16, 17)),
            ),
            coupled_delay,
            scheduled_delay,
        )
        joint = stratum == 17
        scheduled_thrust[joint] = joint_thrust[joint]
        scheduled_wind[joint] = joint_horizontal_wind[joint]
        scheduled_wind[joint, 2] = joint_vertical_wind[joint]
        scheduled_delay[joint] = joint_delay[joint]

    return DomainParameters(
        mass_scale=mass_scale,
        thrust_scale=thrust_scale,
        wind_acceleration_mps2=wind,
        action_delay_steps=delay,
        stratum=stratum,
        profile=profile,
        seed=seed,
        scheduled_thrust_scale=(scheduled_thrust if profile == "adversarial_v3" else None),
        scheduled_wind_acceleration_mps2=(scheduled_wind if profile == "adversarial_v3" else None),
        scheduled_action_delay_steps=(scheduled_delay if profile == "adversarial_v3" else None),
    )
