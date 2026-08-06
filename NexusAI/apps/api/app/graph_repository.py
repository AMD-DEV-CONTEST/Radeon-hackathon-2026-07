from uuid import UUID
from sqlalchemy import select
from app.database.models import EntityRecord,RelationshipRecord
from nexus.world import Entity,Relationship
class GraphRepository:
 def __init__(self,db):self.db=db
 def list_entities(self,wid):
  return [Entity(id=UUID(r.id),world_id=UUID(r.world_id),entity_type=r.entity_type,name=r.name,description=r.description,properties=r.properties_json or {},source_ids=[UUID(x) for x in r.source_ids_json or []]) for r in self.db.scalars(select(EntityRecord).where(EntityRecord.world_id==str(wid))).all()]
 def get_entity(self,eid):
  r=self.db.get(EntityRecord,str(eid)); return None if not r else Entity(id=UUID(r.id),world_id=UUID(r.world_id),entity_type=r.entity_type,name=r.name,description=r.description,properties=r.properties_json or {},source_ids=[UUID(x) for x in r.source_ids_json or []])
 def create_entity(self,e):
  self.db.add(EntityRecord(id=str(e.id),world_id=str(e.world_id),entity_type=e.entity_type,name=e.name,description=e.description,properties_json=e.properties,source_ids_json=[str(x) for x in e.source_ids]));self.db.commit();return e
 def list_relationships(self,wid):
  return [Relationship(id=UUID(r.id),world_id=UUID(r.world_id),source_entity_id=UUID(r.source_entity_id),target_entity_id=UUID(r.target_entity_id),relationship_type=r.relationship_type,properties=r.properties_json or {},source_ids=[UUID(x) for x in r.source_ids_json or []]) for r in self.db.scalars(select(RelationshipRecord).where(RelationshipRecord.world_id==str(wid))).all()]
 def create_relationship(self,r):
  self.db.add(RelationshipRecord(id=str(r.id),world_id=str(r.world_id),source_entity_id=str(r.source_entity_id),target_entity_id=str(r.target_entity_id),relationship_type=r.relationship_type,properties_json=r.properties,source_ids_json=[str(x) for x in r.source_ids]));self.db.commit();return r
