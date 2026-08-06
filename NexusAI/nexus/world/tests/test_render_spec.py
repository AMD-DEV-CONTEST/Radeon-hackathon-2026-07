from nexus.world import WorldBlueprintEngine
from nexus.world.render_spec import build_render_spec


def test_render_spec_uses_blueprint_biome():
    blueprint = WorldBlueprintEngine().generate(
        "An ancient sandstone settlement stood among arid desert dunes."
    )
    spec = build_render_spec(blueprint)
    assert spec.biome == "desert"
    assert "sand" in spec.terrain_materials
    assert "desert_terrain" in spec.asset_families


def test_render_spec_preserves_source_architecture_materials():
    blueprint = WorldBlueprintEngine().generate(
        "A medieval stone castle and timber village stood in a pine forest."
    )
    spec = build_render_spec(blueprint)
    assert "stone" in spec.architecture_materials
    assert "timber" in spec.architecture_materials


def test_render_spec_carries_character_context():
    blueprint = WorldBlueprintEngine().generate(
        "Travellers crossed a frozen tundra covered in snow and ice."
    )
    spec = build_render_spec(blueprint)
    assert spec.character_context == "cold_weather"


def test_render_spec_carries_explicit_night_context():
    blueprint = WorldBlueprintEngine().generate(
        "A pine forest beneath the night sky and stars."
    )

    spec = build_render_spec(blueprint)

    assert spec.time_of_day == "night"


def test_render_spec_defaults_to_day_without_temporal_context():
    blueprint = WorldBlueprintEngine().generate(
        "A temperate pine forest surrounded the settlement."
    )

    spec = build_render_spec(blueprint)

    assert spec.time_of_day == "day"