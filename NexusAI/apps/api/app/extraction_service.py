from uuid import UUID
from sqlalchemy.orm import Session

from app.database.models import SourceChunkRecord
from app.graph_repository import GraphRepository
from nexus.extraction import extract
from nexus.world import Entity, Relationship

def extract_source_to_graph(db: Session, world_id: UUID, source_id: UUID):
    chunks = (
        db.query(SourceChunkRecord)
        .filter(
            SourceChunkRecord.world_id == str(world_id),
            SourceChunkRecord.source_id == str(source_id),
        )
        .order_by(SourceChunkRecord.chunk_index)
        .all()
    )
    if not chunks:
        return None

    text = " ".join(chunk.text for chunk in chunks)
    result = extract(text)
    repo = GraphRepository(db)

    existing = {e.name.lower(): e for e in repo.list_entities(world_id)}
    created_entities = []

    for candidate in result.entities:
        entity = existing.get(candidate.name.lower())
        if entity is None:
            entity = Entity(
                world_id=world_id,
                entity_type=candidate.entity_type,
                name=candidate.name,
                description=candidate.description,
                properties=candidate.properties,
                source_ids=[source_id],
            )
            repo.create_entity(entity)
            existing[candidate.name.lower()] = entity
            created_entities.append(entity)

    existing_edges = {
        (r.source_entity_id, r.target_entity_id, r.relationship_type)
        for r in repo.list_relationships(world_id)
    }
    created_relationships = []

    for candidate in result.relationships:
        source = existing.get(candidate.source_name.lower())
        target = existing.get(candidate.target_name.lower())
        if not source or not target:
            continue
        key = (source.id, target.id, candidate.relationship_type)
        if key in existing_edges:
            continue
        relationship = Relationship(
            world_id=world_id,
            source_entity_id=source.id,
            target_entity_id=target.id,
            relationship_type=candidate.relationship_type,
            properties=candidate.properties,
            source_ids=[source_id],
        )
        repo.create_relationship(relationship)
        existing_edges.add(key)
        created_relationships.append(relationship)

    return {
        "entities_detected": len(result.entities),
        "entities_created": len(created_entities),
        "relationships_detected": len(result.relationships),
        "relationships_created": len(created_relationships),
        "observations_detected": len(result.observations),
    }
