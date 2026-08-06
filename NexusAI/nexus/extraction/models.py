from dataclasses import dataclass, field

@dataclass
class CandidateEntity:
    name: str
    entity_type: str
    description: str | None = None
    properties: dict = field(default_factory=dict)

@dataclass
class CandidateRelationship:
    source_name: str
    target_name: str
    relationship_type: str
    properties: dict = field(default_factory=dict)

@dataclass
class ExtractionResult:
    entities: list[CandidateEntity] = field(default_factory=list)
    relationships: list[CandidateRelationship] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
