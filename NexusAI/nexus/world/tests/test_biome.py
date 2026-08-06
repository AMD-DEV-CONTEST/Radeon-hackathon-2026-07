from nexus.world.biome import infer_biome,infer_climate
from nexus.world.context import extract_context

def test_desert_biome():
 c=extract_context("The caravan crossed arid sand dunes through the desert.")
 b=infer_biome(c)
 assert b.value=="desert" and b.confidence>.7
 assert infer_climate(c,b).value=="arid"

def test_arctic_biome():
 assert infer_biome(extract_context("Snow and ice covered the frozen tundra.")).value=="arctic"


 def test_infers_coastal_from_shoreline_context():
    context = extract_context(
        "Waves crashed against the rocky shoreline beneath tall cliffs."
    )

    result = infer_biome(context)

    assert result.value == "coastal"
    assert "shoreline" in result.evidence
