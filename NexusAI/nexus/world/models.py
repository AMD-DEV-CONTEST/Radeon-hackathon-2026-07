from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

def utc_now(): return datetime.now(timezone.utc)

class WorldType(str, Enum):
    MEMORYWEAVER="memoryweaver"; WORLDFORGE="worldforge"; DETECTIVE="detective"; CODEVERSE="codeverse"

class ProvenanceType(str, Enum):
    SOURCE="source"; DETERMINISTIC="deterministic"; AI="ai"; USER="user"

class World(BaseModel):
    id: UUID=Field(default_factory=uuid4)
    name: str
    world_type: WorldType
    description: str|None=None
    created_at: datetime=Field(default_factory=utc_now)
    metadata: dict[str,Any]=Field(default_factory=dict)

class Source(BaseModel):
    id: UUID=Field(default_factory=uuid4); world_id: UUID; name: str; source_type: str
    uri: str|None=None; metadata: dict[str,Any]=Field(default_factory=dict)

class Entity(BaseModel):
    id: UUID=Field(default_factory=uuid4); world_id: UUID; entity_type: str; name: str
    description: str|None=None; properties: dict[str,Any]=Field(default_factory=dict)
    source_ids: list[UUID]=Field(default_factory=list)

class Relationship(BaseModel):
    id: UUID=Field(default_factory=uuid4); world_id: UUID; source_entity_id: UUID; target_entity_id: UUID
    relationship_type: str; properties: dict[str,Any]=Field(default_factory=dict); source_ids: list[UUID]=Field(default_factory=list)

class Event(BaseModel):
    id: UUID=Field(default_factory=uuid4); world_id: UUID; event_type: str; title: str
    description: str|None=None; occurred_at: datetime|None=None
    entity_ids: list[UUID]=Field(default_factory=list); source_ids: list[UUID]=Field(default_factory=list)

class Observation(BaseModel):
    id: UUID=Field(default_factory=uuid4); world_id: UUID; text: str; provenance_type: ProvenanceType; producer: str
    confidence: float|None=Field(default=None,ge=0,le=1); source_ids: list[UUID]=Field(default_factory=list)
    entity_ids: list[UUID]=Field(default_factory=list)
