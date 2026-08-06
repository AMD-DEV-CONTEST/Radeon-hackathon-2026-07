from .architecture import infer_architecture
from .biome import infer_biome,infer_climate
from .blueprint_models import EnvironmentBlueprint,WorldBlueprint
from .context import extract_context
from .population import infer_population
from .temporal import infer_time_of_day

TERRAIN={"desert":["sand","dunes"],"arctic":["snow","ice"],"forest":["soil","forest_floor"],"grassland":["grass","rolling_plains"],"urban":["roads","developed_ground"],"mountain":["rock","slopes"],"coastal":["sand","rock","shore"],"generic":["natural_ground"]}
VEGETATION={"desert":["dry_shrubs"],"arctic":["sparse_pine"],"forest":["trees","underbrush"],"grassland":["grass","wildflowers"],"urban":["managed_trees"],"mountain":["alpine_shrubs"],"coastal":["coastal_grass"],"generic":["mixed_vegetation"]}

class WorldBlueprintEngine:
    def generate(self,text:str)->WorldBlueprint:
        context=extract_context(text)
        biome=infer_biome(context)
        climate=infer_climate(context,biome)
        time_of_day=infer_time_of_day(context)
        environment=EnvironmentBlueprint(
    biome=biome,
    climate=climate,
    time_of_day=time_of_day,
    terrain=TERRAIN[biome.value],
    vegetation=VEGETATION[biome.value],
)
        return WorldBlueprint(environment=environment,architecture=infer_architecture(context),population=infer_population(context,climate.value),source_text_available=bool(text.strip()))
