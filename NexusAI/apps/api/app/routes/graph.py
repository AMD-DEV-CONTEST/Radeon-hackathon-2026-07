from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,status
from sqlalchemy.orm import Session
from app.database import get_db
from app.graph_repository import GraphRepository
from app.repository import WorldRepository
from app.schemas import EntityCreate,RelationshipCreate
from nexus.graph import KnowledgeGraph
from nexus.world import Entity,Relationship
router=APIRouter(prefix="/worlds/{world_id}",tags=["graph"])
def check(wid,db):
 if WorldRepository(db).get(wid) is None:raise HTTPException(404,"World not found")
@router.post("/entities",response_model=Entity,status_code=status.HTTP_201_CREATED)
async def create_entity(world_id:UUID,payload:EntityCreate,db:Session=Depends(get_db)):
 check(world_id,db);return GraphRepository(db).create_entity(Entity(world_id=world_id,**payload.model_dump()))
@router.get("/entities",response_model=list[Entity])
async def entities(world_id:UUID,db:Session=Depends(get_db)):
 check(world_id,db);return GraphRepository(db).list_entities(world_id)
@router.post("/relationships",response_model=Relationship,status_code=status.HTTP_201_CREATED)
async def create_relationship(world_id:UUID,payload:RelationshipCreate,db:Session=Depends(get_db)):
 check(world_id,db);repo=GraphRepository(db);a=repo.get_entity(payload.source_entity_id);b=repo.get_entity(payload.target_entity_id)
 if not a or not b:raise HTTPException(400,"Both entities must exist")
 if a.world_id!=world_id or b.world_id!=world_id:raise HTTPException(400,"Relationships cannot cross Worlds")
 return repo.create_relationship(Relationship(world_id=world_id,**payload.model_dump()))
@router.get("/graph")
async def graph(world_id:UUID,start_entity_id:UUID|None=None,depth:int=2,db:Session=Depends(get_db)):
 check(world_id,db);repo=GraphRepository(db);es=repo.list_entities(world_id);rs=repo.list_relationships(world_id);g=KnowledgeGraph(es,rs)
 ids=g.traverse(start_entity_id,min(max(depth,0),5)) if start_entity_id else {e.id for e in es}
 return {"world_id":world_id,"nodes":[{"id":e.id,"label":e.name,"node_type":e.entity_type,"properties":e.properties} for e in es if e.id in ids],"edges":[{"id":r.id,"source":r.source_entity_id,"target":r.target_entity_id,"label":r.relationship_type,"properties":r.properties} for r in rs if r.source_entity_id in ids and r.target_entity_id in ids]}


@router.get("/worldforge")
async def worldforge_data(world_id: UUID, db: Session = Depends(get_db)):
    """Return a frontend-friendly knowledge snapshot for WorldForge."""
    check(world_id, db)
    repo = GraphRepository(db)
    entities = repo.list_entities(world_id)
    relationships = repo.list_relationships(world_id)

    degree = {entity.id: 0 for entity in entities}
    for relationship in relationships:
        if relationship.source_entity_id in degree:
            degree[relationship.source_entity_id] += 1
        if relationship.target_entity_id in degree:
            degree[relationship.target_entity_id] += 1

    return {
        "world_id": world_id,
        "entities": [
            {
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "description": entity.description,
                "properties": entity.properties,
                "connection_count": degree.get(entity.id, 0),
            }
            for entity in entities
        ],
        "relationships": [
            {
                "id": relationship.id,
                "source_entity_id": relationship.source_entity_id,
                "target_entity_id": relationship.target_entity_id,
                "relationship_type": relationship.relationship_type,
                "properties": relationship.properties,
            }
            for relationship in relationships
        ],
    }
