from __future__ import annotations

from dataclasses import asdict, dataclass
import random

from .config import ParcelProfileConfig, RandomizationConfig


@dataclass(frozen=True)
class ParcelSample:
    episode_index: int
    size_scale_xyz: tuple[float, float, float]
    mass_kg: float
    friction: float
    position_xy: tuple[float, float]
    yaw_rad: float
    camera_noise_xyz_m: tuple[float, float, float]
    action_delay_steps: int
    destination: str
    profile_id: str = "legacy_box"
    shape: str = "box"
    orientation_mode: str = "yaw"
    handling_class: str = "parallel_jaw"
    material: str = "rigid_cardboard_proxy"
    dimensions_m: tuple[float, float, float] | None = None
    provenance: str = "legacy configured scale range"
    rolling_friction: float = 0.0
    final_approach_step_m: float | None = None
    lift_step_m: float | None = None
    finger_friction: float | None = None
    close_force_n: float | None = None
    pregrasp_tolerance_m: float | None = None
    grasp_stability_steps: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DomainRandomizer:
    """Produces reproducible, per-episode parcel and sensor parameters."""

    def __init__(
        self,
        config: RandomizationConfig,
        seed: int,
        parcel_profiles: tuple[ParcelProfileConfig, ...] = (),
    ) -> None:
        self.config = config
        self.seed = seed
        self.parcel_profiles = parcel_profiles

    def sample(self, episode_index: int) -> ParcelSample:
        if episode_index < 0:
            raise ValueError("episode_index cannot be negative")
        rng = random.Random(self.seed + episode_index * 1_000_003)
        cfg = self.config

        if not cfg.enabled:
            return ParcelSample(
                episode_index=episode_index,
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
                destination="left" if episode_index % 2 == 0 else "right",
            )

        if self.parcel_profiles:
            return self._sample_profile(self._training_profile(episode_index), episode_index, rng)

        uniform = rng.uniform
        size = tuple(
            uniform(cfg.parcel_size_scale_min, cfg.parcel_size_scale_max)
            for _ in range(3)
        )
        camera_noise = tuple(
            uniform(-cfg.camera_position_noise_m, cfg.camera_position_noise_m)
            for _ in range(3)
        )
        return ParcelSample(
            episode_index=episode_index,
            size_scale_xyz=size,
            mass_kg=uniform(cfg.parcel_mass_kg_min, cfg.parcel_mass_kg_max),
            friction=uniform(cfg.friction_min, cfg.friction_max),
            position_xy=(
                uniform(cfg.parcel_position_x_min, cfg.parcel_position_x_max),
                uniform(cfg.parcel_position_y_min, cfg.parcel_position_y_max),
            ),
            yaw_rad=uniform(cfg.parcel_yaw_rad_min, cfg.parcel_yaw_rad_max),
            camera_noise_xyz_m=camera_noise,
            action_delay_steps=rng.randint(0, cfg.action_delay_steps_max),
            destination="left" if rng.random() < 0.5 else "right",
        )

    def sample_profile(self, profile_id: str, episode_index: int) -> ParcelSample:
        if episode_index < 0:
            raise ValueError("episode_index cannot be negative")
        profile = next(
            (item for item in self.parcel_profiles if item.profile_id == profile_id),
            None,
        )
        if profile is None:
            raise ValueError(f"unknown parcel profile: {profile_id}")
        rng = random.Random(self.seed + episode_index * 1_000_003)
        return self._sample_profile(profile, episode_index, rng)

    def _training_profile(self, episode_index: int) -> ParcelProfileConfig:
        profiles = tuple(profile for profile in self.parcel_profiles if not profile.evaluation_only)
        block_size = self.config.catalog_block_size
        schedule = [
            profile
            for profile in profiles
            for _ in range(round(profile.selection_weight * block_size))
        ]
        block_index, offset = divmod(episode_index, block_size)
        random.Random(self.seed + block_index * 104_729).shuffle(schedule)
        return schedule[offset]

    def _sample_profile(
        self,
        profile: ParcelProfileConfig,
        episode_index: int,
        rng: random.Random,
    ) -> ParcelSample:
        cfg = self.config
        uniform = rng.uniform
        dimensions = tuple(
            uniform(lower, upper)
            for lower, upper in zip(
                profile.dimensions_min_m,
                profile.dimensions_max_m,
                strict=True,
            )
        )
        if profile.shape == "cylinder":
            if profile.orientation_mode == "upright":
                dimensions = (dimensions[0], dimensions[0], dimensions[2])
            else:
                dimensions = (dimensions[0], dimensions[1], dimensions[1])
        camera_noise = tuple(
            uniform(-cfg.camera_position_noise_m, cfg.camera_position_noise_m)
            for _ in range(3)
        )
        return ParcelSample(
            episode_index=episode_index,
            size_scale_xyz=(1.0, 1.0, 1.0),
            mass_kg=uniform(profile.mass_kg_min, profile.mass_kg_max),
            friction=uniform(profile.friction_min, profile.friction_max),
            position_xy=(
                uniform(cfg.parcel_position_x_min, cfg.parcel_position_x_max),
                uniform(cfg.parcel_position_y_min, cfg.parcel_position_y_max),
            ),
            yaw_rad=uniform(cfg.parcel_yaw_rad_min, cfg.parcel_yaw_rad_max),
            camera_noise_xyz_m=camera_noise,
            action_delay_steps=rng.randint(0, cfg.action_delay_steps_max),
            destination="left" if rng.random() < 0.5 else "right",
            profile_id=profile.profile_id,
            shape=profile.shape,
            orientation_mode=profile.orientation_mode,
            handling_class=profile.handling_class,
            material=profile.material,
            dimensions_m=dimensions,
            provenance=profile.provenance,
            rolling_friction=profile.rolling_friction,
            final_approach_step_m=profile.final_approach_step_m,
            lift_step_m=profile.lift_step_m,
            finger_friction=profile.finger_friction,
            close_force_n=profile.close_force_n,
            pregrasp_tolerance_m=profile.pregrasp_tolerance_m,
            grasp_stability_steps=profile.grasp_stability_steps,
        )
