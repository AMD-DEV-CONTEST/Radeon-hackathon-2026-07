from typing import Any
from uuid import UUID
from pydantic import BaseModel,Field
from nexus.world import WorldType
class WorldCreate(BaseModel):
 name:str=Field(min_length=1,max_length=120);world_type:WorldType;description:str|None=None;metadata:dict[str,Any]=Field(default_factory=dict)
class EntityCreate(BaseModel):
 entity_type:str;name:str;description:str|None=None;properties:dict[str,Any]=Field(default_factory=dict);source_ids:list[UUID]=Field(default_factory=list)
class RelationshipCreate(BaseModel):
 source_entity_id:UUID;target_entity_id:UUID;relationship_type:str;properties:dict[str,Any]=Field(default_factory=dict);source_ids:list[UUID]=Field(default_factory=list)


class WorldBlueprintRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)

    @classmethod
    def from_text(cls, text: str) -> "WorldBlueprintRequest":
        return cls(text=text.strip())
