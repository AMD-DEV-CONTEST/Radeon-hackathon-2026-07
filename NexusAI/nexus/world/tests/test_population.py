from nexus.world.population import infer_population
from nexus.world.context import extract_context

def test_population_uses_climate_for_clothing():
 p=infer_population(extract_context("Travellers crossed the snow."),"cold")
 assert p.clothing_context=="cold_weather"
