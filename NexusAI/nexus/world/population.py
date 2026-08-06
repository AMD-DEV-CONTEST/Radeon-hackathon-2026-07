from .blueprint_models import PopulationBlueprint
from .context import ContextEvidence

def infer_population(context:ContextEvidence,climate:str)->PopulationBlueprint:
    species=["human"]
    if context.tokens&{"android","robot","robots"}:species=["human","robot"]
    elif context.tokens&{"elf","elves"}:species=["human","elf"]
    clothing={"cold":"cold_weather","hot":"hot_weather","arid":"desert_travel"}.get(climate,"contextual")
    density="dense" if context.tokens&{"crowd","crowded","metropolis"} else "moderate" if context.tokens&{"town","city","village"} else "sparse"
    return PopulationBlueprint(species=species,clothing_context=clothing,density=density)
