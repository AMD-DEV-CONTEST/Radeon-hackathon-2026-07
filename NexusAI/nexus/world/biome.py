from .blueprint_models import BiomeType, BlueprintValue, ClimateType
from .context import ContextEvidence
from .models import ProvenanceType

BIOME_TERMS={
 BiomeType.DESERT:{"desert","sand","dune","dunes","arid","oasis","cactus"},
 BiomeType.ARCTIC:{"snow","ice","frozen","glacier","tundra","blizzard"},
 BiomeType.FOREST:{"forest","woods","pine","trees","jungle","canopy"},
 BiomeType.GRASSLAND:{"grassland","plains","prairie","meadow","savanna","grass"},
 BiomeType.URBAN:{"city","urban","street","streets","skyscraper","metropolis"},
 BiomeType.MOUNTAIN:{
    "mountain","mountains","cliff","cliffs","peak","peaks",
    "ridge","ridges","alpine","valley"
},

BiomeType.COASTAL:{
    "coast","coastal","ocean","sea","beach","shore","shoreline",
    "harbor","waves"
},
}
CLIMATE_HINTS={
 ClimateType.HOT:{"hot","heat","scorching","tropical"},
 ClimateType.COLD:{"cold","snow","ice","frozen","blizzard"},
 ClimateType.ARID:{"arid","dry","desert","drought"},
 ClimateType.HUMID:{"humid","rainforest","tropical","monsoon"},
 ClimateType.TEMPERATE:{"temperate","mild"},
}

def _rank(tokens:set[str], vocab:dict)->tuple[object,int,list[str]]:
    ranked=[]
    for key,words in vocab.items():
        hits=sorted(tokens&words); ranked.append((len(hits),str(key.value),key,hits))
    ranked.sort(reverse=True)
    score,_,key,hits=ranked[0]
    return key,score,hits

def infer_biome(context:ContextEvidence)->BlueprintValue:
    biome,score,hits=_rank(context.tokens,BIOME_TERMS)
    if score==0:return BlueprintValue(value=BiomeType.GENERIC.value,confidence=.25,provenance=ProvenanceType.DETERMINISTIC)
    return BlueprintValue(value=biome.value,confidence=min(.98,.55+score*.12),provenance=ProvenanceType.DETERMINISTIC,evidence=hits)

def infer_climate(context:ContextEvidence,biome:BlueprintValue)->BlueprintValue:
    climate,score,hits=_rank(context.tokens,CLIMATE_HINTS)
    if score:
        return BlueprintValue(value=climate.value,confidence=min(.95,.52+score*.13),evidence=hits)
    defaults={"desert":"arid","arctic":"cold","forest":"temperate","grassland":"temperate","coastal":"temperate","mountain":"cold","urban":"temperate"}
    value=defaults.get(biome.value,"unknown")
    return BlueprintValue(value=value,confidence=.45,evidence=[f"biome:{biome.value}"])
