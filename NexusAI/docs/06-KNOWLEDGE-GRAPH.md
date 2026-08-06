# NexusAI Knowledge Graph Engine
Version 1.0

v0.4.0 adds persistent Entities and Relationships plus a domain-independent graph projection.

## Rules
- Entities belong to one World.
- Relationships connect existing Entities in the same World.
- Graph traversal is deterministic and depth-limited.
- The graph endpoint returns visualization-ready nodes and edges.

## Endpoint
`GET /api/worlds/{world_id}/graph`

Optional query parameters: `start_entity_id`, `depth`.

Durable graph data currently uses SQLAlchemy. A specialized graph database can be added behind the graph interface later if real benchmarks justify the operational complexity.
