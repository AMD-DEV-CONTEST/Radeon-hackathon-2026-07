from __future__ import annotations

from dataclasses import replace

from .config import ExperimentConfig
from .randomization import DomainRandomizer, ParcelSample


PROFILES = ("nominal", "in_domain", "unseen")


def sample_for_profile(
    config: ExperimentConfig,
    episode_index: int,
    profile: str,
) -> ParcelSample:
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of: {', '.join(PROFILES)}")
    base = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    ).sample(episode_index)
    if profile == "in_domain":
        return base
    if profile == "nominal":
        cfg = config.randomization
        return replace(
            base,
            size_scale_xyz=(1.0, 1.0, 1.0),
            mass_kg=(cfg.parcel_mass_kg_min + cfg.parcel_mass_kg_max) / 2,
            friction=(cfg.friction_min + cfg.friction_max) / 2,
            position_xy=(
                (cfg.parcel_position_x_min + cfg.parcel_position_x_max) / 2,
                (cfg.parcel_position_y_min + cfg.parcel_position_y_max) / 2,
            ),
            yaw_rad=0.0,
            camera_noise_xyz_m=(0.0, 0.0, 0.0),
            action_delay_steps=0,
        )

    high = episode_index % 2 == 0
    size = config.randomization.parcel_size_scale_max * 1.08 if high else max(
        0.55, config.randomization.parcel_size_scale_min * 0.90
    )
    mass = config.randomization.parcel_mass_kg_max * 1.10 if high else max(
        0.02, config.randomization.parcel_mass_kg_min * 0.80
    )
    friction = min(4.5, config.randomization.friction_max * 1.10) if high else max(
        0.05, config.randomization.friction_min * 0.85
    )
    return replace(
        base,
        size_scale_xyz=(size, size, size),
        mass_kg=mass,
        friction=friction,
        action_delay_steps=config.randomization.action_delay_steps_max + 1,
    )
