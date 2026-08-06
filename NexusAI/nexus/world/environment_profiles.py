from __future__ import annotations

from dataclasses import dataclass

from .blueprint_models import BiomeType, WorldBlueprint


@dataclass(frozen=True)
class LightingProfile:
    preset: str
    sun_intensity: float
    ambient_intensity: float
    fog_density: float


@dataclass(frozen=True)
class EnvironmentProfile:
    biome: BiomeType
    terrain_materials: tuple[str, ...]
    terrain_features: tuple[str, ...]
    vegetation_assets: tuple[str, ...]
    prop_assets: tuple[str, ...]
    architecture_materials: tuple[str, ...]
    atmosphere: tuple[str, ...]
    weather_effects: tuple[str, ...]
    character_context: str
    asset_families: tuple[str, ...]
    lighting: LightingProfile


ENVIRONMENT_PROFILES: dict[BiomeType, EnvironmentProfile] = {
    BiomeType.DESERT: EnvironmentProfile(
        biome=BiomeType.DESERT,
        terrain_materials=("sand", "sandstone", "dry_rock"),
        terrain_features=("dunes", "rock_outcrops", "dry_washes"),
        vegetation_assets=("dry_shrubs", "date_palms", "desert_grass"),
        prop_assets=("weathered_crates", "clay_pots", "canvas_shelters"),
        architecture_materials=("sandstone", "adobe", "weathered_wood"),
        atmosphere=("dust_haze", "heat_shimmer"),
        weather_effects=("dry_wind", "sand_gusts"),
        character_context="desert_travel",
        asset_families=("desert_terrain", "desert_foliage", "desert_architecture"),
        lighting=LightingProfile("harsh_warm_sun", 1.25, 0.42, 0.008),
    ),
    BiomeType.ARCTIC: EnvironmentProfile(
        biome=BiomeType.ARCTIC,
        terrain_materials=("snow", "ice", "frozen_rock"),
        terrain_features=("snow_drifts", "ice_sheets", "frozen_ridges"),
        vegetation_assets=("snow_pine", "frozen_shrubs", "lichen"),
        prop_assets=("snow_piles", "ice_chunks", "timber_stacks"),
        architecture_materials=("stone", "timber", "ice"),
        atmosphere=("cold_mist", "snow_haze"),
        weather_effects=("snowfall", "cold_wind"),
        character_context="cold_weather",
        asset_families=("arctic_terrain", "arctic_foliage", "arctic_architecture"),
        lighting=LightingProfile("cold_diffuse_daylight", 0.82, 0.62, 0.018),
    ),
    BiomeType.FOREST: EnvironmentProfile(
        biome=BiomeType.FOREST,
        terrain_materials=("forest_soil", "moss", "wet_rock"),
        terrain_features=("roots", "fallen_logs", "small_clearings"),
        vegetation_assets=("broadleaf_trees", "pine_trees", "ferns", "underbrush"),
        prop_assets=("fallen_branches", "mossy_stones", "tree_stumps"),
        architecture_materials=("timber", "stone", "thatch"),
        atmosphere=("ground_mist", "pollen"),
        weather_effects=("light_rain", "leaf_fall"),
        character_context="woodland",
        asset_families=("forest_terrain", "forest_foliage", "forest_architecture"),
        lighting=LightingProfile("filtered_canopy_light", 0.76, 0.48, 0.016),
    ),
    BiomeType.GRASSLAND: EnvironmentProfile(
        biome=BiomeType.GRASSLAND,
        terrain_materials=("grass", "soil", "field_rock"),
        terrain_features=("rolling_hills", "open_fields", "shallow_streams"),
        vegetation_assets=("tall_grass", "wildflowers", "scattered_trees"),
        prop_assets=("field_stones", "wooden_fences", "hay_stacks"),
        architecture_materials=("timber", "stone", "brick"),
        atmosphere=("light_haze",),
        weather_effects=("breeze", "passing_clouds"),
        character_context="temperate_outdoor",
        asset_families=("grassland_terrain", "grassland_foliage", "rural_architecture"),
        lighting=LightingProfile("open_daylight", 1.0, 0.55, 0.007),
    ),
    BiomeType.URBAN: EnvironmentProfile(
        biome=BiomeType.URBAN,
        terrain_materials=("asphalt", "concrete", "paving"),
        terrain_features=("roads", "sidewalks", "plazas"),
        vegetation_assets=("street_trees", "planters", "managed_grass"),
        prop_assets=("street_lamps", "benches", "barriers", "signage"),
        architecture_materials=("concrete", "brick", "steel", "glass"),
        atmosphere=("city_haze",),
        weather_effects=("light_wind",),
        character_context="urban",
        asset_families=("urban_roads", "urban_props", "urban_architecture"),
        lighting=LightingProfile("balanced_city_daylight", 0.95, 0.5, 0.009),
    ),
    BiomeType.MOUNTAIN: EnvironmentProfile(
        biome=BiomeType.MOUNTAIN,
        terrain_materials=("rock", "gravel", "alpine_soil"),
        terrain_features=("cliffs", "ridges", "steep_slopes"),
        vegetation_assets=("alpine_shrubs", "pine_trees", "mountain_grass"),
        prop_assets=("boulders", "fallen_rock", "trail_markers"),
        architecture_materials=("stone", "timber"),
        atmosphere=("high_altitude_haze", "valley_mist"),
        weather_effects=("mountain_wind", "cloud_banks"),
        character_context="mountain_travel",
        asset_families=("mountain_terrain", "mountain_foliage", "mountain_architecture"),
        lighting=LightingProfile("crisp_high_altitude", 1.05, 0.48, 0.012),
    ),
    BiomeType.COASTAL: EnvironmentProfile(
        biome=BiomeType.COASTAL,
        terrain_materials=("sand", "coastal_rock", "wet_sand"),
        terrain_features=("shoreline", "rock_pools", "coastal_cliffs"),
        vegetation_assets=("coastal_grass", "palms", "salt_shrubs"),
        prop_assets=("driftwood", "ropes", "boats", "dock_crates"),
        architecture_materials=("weathered_wood", "stone", "plaster"),
        atmosphere=("sea_mist", "salt_haze"),
        weather_effects=("ocean_breeze", "sea_spray"),
        character_context="coastal",
        asset_families=("coastal_terrain", "coastal_foliage", "coastal_architecture"),
        lighting=LightingProfile("bright_coastal_daylight", 1.08, 0.58, 0.011),
    ),
    BiomeType.GENERIC: EnvironmentProfile(
        biome=BiomeType.GENERIC,
        terrain_materials=("natural_ground", "soil", "rock"),
        terrain_features=("gentle_slopes", "open_ground"),
        vegetation_assets=("mixed_grass", "mixed_trees", "shrubs"),
        prop_assets=("rocks", "logs"),
        architecture_materials=("stone", "wood", "brick"),
        atmosphere=("light_haze",),
        weather_effects=("light_breeze",),
        character_context="contextual",
        asset_families=("generic_terrain", "generic_foliage", "generic_architecture"),
        lighting=LightingProfile("neutral_daylight", 0.95, 0.52, 0.008),
    ),
}


def get_environment_profile(biome: BiomeType | str) -> EnvironmentProfile:
    try:
        biome_type = biome if isinstance(biome, BiomeType) else BiomeType(biome)
    except ValueError:
        biome_type = BiomeType.GENERIC
    return ENVIRONMENT_PROFILES[biome_type]


def profile_for_blueprint(blueprint: WorldBlueprint) -> EnvironmentProfile:
    return get_environment_profile(blueprint.environment.biome.value)
