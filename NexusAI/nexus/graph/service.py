from uuid import UUID
from nexus.world import Entity, Relationship
class KnowledgeGraph:
    def __init__(self,entities:list[Entity],relationships:list[Relationship]):
        self.entities={e.id:e for e in entities}; self.relationships=relationships
        for r in relationships:
            if r.source_entity_id not in self.entities or r.target_entity_id not in self.entities:
                raise ValueError("Relationship references a missing entity")
    def neighbors(self,entity_id:UUID):
        ids=set()
        for r in self.relationships:
            if r.source_entity_id==entity_id: ids.add(r.target_entity_id)
            if r.target_entity_id==entity_id: ids.add(r.source_entity_id)
        return [self.entities[i] for i in ids]
    def traverse(self,start_id:UUID,max_depth:int=2):
        if start_id not in self.entities:return set()
        visited={start_id}; frontier={start_id}
        for _ in range(max_depth):
            nxt=set()
            for current in frontier:
                for n in self.neighbors(current):
                    if n.id not in visited: visited.add(n.id); nxt.add(n.id)
            if not nxt:break
            frontier=nxt
        return visited
