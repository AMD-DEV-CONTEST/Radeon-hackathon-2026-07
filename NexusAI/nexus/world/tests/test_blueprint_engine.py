from nexus.world import WorldBlueprintEngine

def test_engine_builds_contextual_desert_world():
 b=WorldBlueprintEngine().generate("An ancient sandstone city stood beyond the arid desert dunes. A caravan approached.")
 assert b.environment.biome.value=="desert"
 assert b.environment.climate.value=="arid"
 assert b.architecture.style.value=="ancient"
 assert "sandstone" in b.architecture.materials
 assert b.population.clothing_context=="desert_travel"

def test_engine_builds_frozen_world():
 b=WorldBlueprintEngine().generate("A village sat beneath frozen mountains. Snow and ice surrounded a pine forest.")
 assert b.environment.biome.value=="arctic"
 assert b.environment.climate.value=="cold"
 assert b.population.clothing_context=="cold_weather"
