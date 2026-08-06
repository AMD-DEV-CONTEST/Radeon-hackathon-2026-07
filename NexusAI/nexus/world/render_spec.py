from __future__ import annotations

from pydantic import BaseModel, Field

from .blueprint_models import WorldBlueprint
from .environment_profiles import EnvironmentProfile, profile_for_blueprint


class LightingRenderSpec(BaseModel):
    preset: str
    sun_intensity: float
    ambient_intensity: float
    fog_density: float


class EnvironmentRenderSpec(BaseModel):
    biome: str
    time_of_day: str
    terrain_materials: list[str] = Field(default_factory=list)
    terrain_features: list[str] = Field(default_factory=list)
    vegetation_assets: list[str] = Field(default_factory=list)
    prop_assets: list[str] = Field(default_factory=list)
    architecture_materials: list[str] = Field(default_factory=list)
    atmosphere: list[str] = Field(default_factory=list)
    weather_effects: list[str] = Field(default_factory=list)
    character_context: str
    asset_families: list[str] = Field(default_factory=list)
    lighting: LightingRenderSpec


def build_render_spec(blueprint: WorldBlueprint) -> EnvironmentRenderSpec:
    profile: EnvironmentProfile = profile_for_blueprint(blueprint)

    architecture_materials = list(
        dict.fromkeys(
            [
                *blueprint.architecture.materials,
                *profile.architecture_materials,
            ]
        )
    )

    return EnvironmentRenderSpec(
        biome=profile.biome.value,
        time_of_day=blueprint.environment.time_of_day.value,
        terrain_materials=list(profile.terrain_materials),
        terrain_features=list(profile.terrain_features),
        vegetation_assets=list(profile.vegetation_assets),
        prop_assets=list(profile.prop_assets),
        architecture_materials=architecture_materials,
        atmosphere=list(profile.atmosphere),
        weather_effects=list(profile.weather_effects),
        character_context=(
            blueprint.population.clothing_context or profile.character_context
        ),
        asset_families=list(profile.asset_families),
        lighting=LightingRenderSpec(
            preset=profile.lighting.preset,
            sun_intensity=profile.lighting.sun_intensity,
            ambient_intensity=profile.lighting.ambient_intensity,
            fog_density=profile.lighting.fog_density,
        ),
    )
