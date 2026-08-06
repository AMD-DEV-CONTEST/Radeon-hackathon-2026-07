from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from .models import ProvenanceType

class BiomeType(str, Enum):
    DESERT="desert"; ARCTIC="arctic"; FOREST="forest"; GRASSLAND="grassland"
    URBAN="urban"; MOUNTAIN="mountain"; COASTAL="coastal"; GENERIC="generic"

class ClimateType(str, Enum):
    HOT="hot"; COLD="cold"; TEMPERATE="temperate"; ARID="arid"; HUMID="humid"; UNKNOWN="unknown"

class TimeOfDay(str, Enum):
    DAWN = "dawn"
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"

class ArchitectureStyle(str, Enum):
    ANCIENT="ancient"; MEDIEVAL="medieval"; MODERN="modern"; FUTURISTIC="futuristic"
    RURAL="rural"; INDUSTRIAL="industrial"; GENERIC="generic"

class BlueprintValue(BaseModel):
    value: str
    confidence: float=Field(ge=0,le=1)
    provenance: ProvenanceType=ProvenanceType.DETERMINISTIC
    evidence: list[str]=Field(default_factory=list)

class EnvironmentBlueprint(BaseModel):
    biome: BlueprintValue
    climate: BlueprintValue
    time_of_day: BlueprintValue
    terrain: list[str]=Field(default_factory=list)
    vegetation: list[str]=Field(default_factory=list)
    weather: list[str]=Field(default_factory=list)

class ArchitectureBlueprint(BaseModel):
    style: BlueprintValue
    materials: list[str]=Field(default_factory=list)
    settlement_type: str|None=None
    technology_level: str|None=None

class PopulationBlueprint(BaseModel):
    species: list[str]=Field(default_factory=lambda:["human"])
    clothing_context: str|None=None
    density: str="sparse"
    attributes: dict[str,Any]=Field(default_factory=dict)

class WorldBlueprint(BaseModel):
    environment: EnvironmentBlueprint
    architecture: ArchitectureBlueprint
    population: PopulationBlueprint
    source_text_available: bool=True
    metadata: dict[str,Any]=Field(default_factory=dict)
