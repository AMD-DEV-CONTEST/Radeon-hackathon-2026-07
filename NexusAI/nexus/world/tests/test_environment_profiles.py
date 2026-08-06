from nexus.world import BiomeType
from nexus.world.environment_profiles import ENVIRONMENT_PROFILES, get_environment_profile


def test_every_biome_has_environment_profile():
    assert set(ENVIRONMENT_PROFILES) == set(BiomeType)


def test_desert_profile_contains_desert_rendering_context():
    profile = get_environment_profile(BiomeType.DESERT)
    assert "sand" in profile.terrain_materials
    assert "dunes" in profile.terrain_features
    assert "dust_haze" in profile.atmosphere
    assert profile.character_context == "desert_travel"


def test_arctic_profile_contains_frozen_rendering_context():
    profile = get_environment_profile("arctic")
    assert "snow" in profile.terrain_materials
    assert "snowfall" in profile.weather_effects
    assert profile.character_context == "cold_weather"


def test_unknown_profile_falls_back_to_generic():
    assert get_environment_profile("volcanic").biome == BiomeType.GENERIC
