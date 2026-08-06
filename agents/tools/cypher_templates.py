"""Parameterized Cypher templates — safe, pre-defined queries.

Replaces raw NL-to-Cypher generation with pre-written, parameterized templates.
The LLM selects a template key + params instead of writing raw Cypher.

Also includes self-updating rank: entities get a rank boost on every access,
so frequently-queried nodes naturally rise to the top.
"""

import logging

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# ─── Template Registry ──────────────────────────────────────────

PREDEFINED_TEMPLATES = {
    # --- Entity Neighborhood: all related nodes within 1 hop ---
    "GET_ENTITY_NEIGHBORHOOD": """
        MATCH (e:Entity {name: $entity_name})-[r:RELATES_TO|IN_EVENT|SYMBOLIZES]-(target)
        RETURN e.name AS source, type(r) AS relation, r.type AS sub_type,
               labels(target)[0] AS target_type, target.name AS target_name,
               r.context AS context
        LIMIT $limit
    """,
    # --- Events in a phase ---
    "GET_PHASE_EVENTS": """
        MATCH (p:Phase {label: $phase_name})<-[:IN_PHASE]-(ev:Event)
        OPTIONAL MATCH (ev)-[:NEXT]->(next_ev:Event)
        OPTIONAL MATCH (entity:Entity)-[:IN_EVENT]->(ev)
        RETURN ev.label AS event, ev.description AS description,
               ev.time_period AS time_period, ev.order AS order,
               next_ev.label AS next_event,
               collect(DISTINCT entity.name) AS participants
        ORDER BY ev.order ASC
    """,
    # --- All events involving a specific entity ---
    "GET_ENTITY_EVENTS": """
        MATCH (e:Entity {name: $entity_name})-[:IN_EVENT]->(ev:Event)
        OPTIONAL MATCH (ev)-[:NEXT]->(next_ev:Event)
        OPTIONAL MATCH (other:Entity)-[:IN_EVENT]->(ev)
        WHERE other <> e
        RETURN ev.label AS event, ev.description AS description,
               ev.time_period AS time_period, ev.order AS order,
               collect(DISTINCT other.name) AS co_participants
        ORDER BY ev.order ASC
        LIMIT $limit
    """,
    # --- Symbolic connections ---
    "GET_SYMBOLS": """
        MATCH (e:Entity {name: $entity_name})-[s:SYMBOLIZES]->(concept:Entity)
        RETURN e.name AS entity, concept.name AS symbolizes, s.context AS meaning
        LIMIT $limit
    """,
    # --- Entity traits ---
    "GET_TRAITS": """
        MATCH (p:Entity {type: 'person', name: $entity_name})-[r:RELATES_TO {type: 'has_trait'}]->(t:Entity {type: 'trait'})
        RETURN p.name AS person, t.name AS trait, r.context AS context
        LIMIT $limit
    """,
    # --- Causal chains ---
    "GET_CAUSAL_CHAIN": """
        MATCH (e:Entity {name: $entity_name})-[:IN_EVENT]->(ev:Event)
        OPTIONAL MATCH (ev)-[:CAUSES]->(effect:Event)
        OPTIONAL MATCH (cause:Event)-[:CAUSES]->(ev)
        RETURN ev.label AS event, ev.description AS description,
               cause.label AS caused_by, effect.label AS causes
        LIMIT $limit
    """,
    # --- Phase coverage summary ---
    "GET_COVERAGE_SUMMARY": """
        MATCH (ev:Event)-[:IN_PHASE]->(p:Phase)
        WITH p, count(ev) AS event_count
        OPTIONAL MATCH (e:Entity)-[:IN_EVENT]->(:Event)-[:IN_PHASE]->(p)
        RETURN p.label AS phase, p.description AS phase_desc,
               event_count, count(DISTINCT e) AS entity_count
        ORDER BY p.order ASC
    """,
    # --- Search entity names (fuzzy) ---
    "SEARCH_ENTITIES": """
        MATCH (e:Entity)
        WHERE e.name CONTAINS $keyword OR e.description CONTAINS $keyword
        RETURN e.name AS name, e.type AS type, e.description AS description,
               coalesce(e.rank, 50) AS rank
        ORDER BY rank DESC
        LIMIT $limit
    """,
    # --- Ranked timeline (events sorted by rank) ---
    "GET_RANKED_EVENTS": """
        MATCH (ev:Event)
        WHERE $entity_name IS NULL OR ev.label CONTAINS $entity_name
        RETURN ev.label AS label, ev.description AS description,
               ev.time_period AS time_period, ev.order AS order,
               coalesce(ev.rank, 50) AS rank, ev.priority AS priority
        ORDER BY rank DESC, order ASC
        LIMIT $limit
    """,
    # --- Recent conversation messages ---
    "GET_RECENT_MESSAGES": """
        MATCH (s:Session {id: $session_id})-[:HAS_MESSAGE]->(m:Message)
        RETURN m.role AS role, m.content AS content, m.timestamp AS timestamp
        ORDER BY m.timestamp DESC
        LIMIT $limit
    """,
    # --- All entities of a specific type ---
    "LIST_ENTITIES_BY_TYPE": """
        MATCH (e:Entity {type: $entity_type})
        RETURN e.name AS name, e.description AS description
        ORDER BY e.name
        LIMIT $limit
    """,
}

# ─── Safe Query Executor ────────────────────────────────────────


def execute_safe_query(template_key: str, params: dict | None = None) -> list[dict]:
    """Execute a pre-defined, parameterized Cypher query.

    Args:
        template_key: Key from PREDEFINED_TEMPLATES.
        params: Query parameters (safe, parameterized).

    Returns:
        List of result rows as dictionaries.

    Raises:
        ValueError: If template_key is not in the registry.
    """
    if template_key not in PREDEFINED_TEMPLATES:
        raise ValueError(
            f"Unknown template key: {template_key}. Available: {list(PREDEFINED_TEMPLATES.keys())}"
        )

    query = PREDEFINED_TEMPLATES[template_key]
    params = params or {}

    # Ensure limit
    if "$limit" in query and "limit" not in params:
        params = {**params, "limit": 10}

    logger.debug("Safe query: %s %s", template_key, {k: str(v)[:50] for k, v in params.items()})
    result = Neo4jClient.execute(query, params)

    # Auto-boost: increment rank on accessed entities
    _auto_boost(template_key, params, result)

    return result


# ─── Rank Boosting ───────────────────────────────────────────────


def _auto_boost(template_key: str, params: dict, result: list[dict]):
    """Increment rank for entities accessed by a query.

    Mimics Bionic-Graph's atime/rank self-updating system.
    Selectively boosts only for entity-heavy query types.
    """
    if template_key in (
        "GET_ENTITY_NEIGHBORHOOD",
        "GET_ENTITY_EVENTS",
        "SEARCH_ENTITIES",
        "GET_RANKED_EVENTS",
    ):
        entity_name = params.get("entity_name", params.get("keyword", ""))
        if entity_name:
            from memory.story_graph import update_rank

            try:
                update_rank(entity_name, increment=0.05)
            except Exception:
                pass  # rank boost is non-critical


# ─── LLM Tool Definition ────────────────────────────────────────

QUERY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "query_life_graph",
        "description": "Query the life story graph using safe, pre-defined templates.",
        "parameters": {
            "type": "object",
            "properties": {
                "template_key": {
                    "type": "string",
                    "enum": list(PREDEFINED_TEMPLATES.keys()),
                    "description": "Which query template to use. Common choices: GET_ENTITY_NEIGHBORHOOD (explore entity), SEARCH_ENTITIES (find by keyword), GET_ENTITY_EVENTS (timeline), GET_PHASE_EVENTS (life phase), GET_RANKED_EVENTS (top events by relevance), GET_SYMBOLS (symbolic meanings), GET_TRAITS (personality), GET_CAUSAL_CHAIN (cause-effect).",
                },
                "params": {
                    "type": "object",
                    "properties": {
                        "entity_name": {
                            "type": "string",
                            "description": "Name of the entity to look up.",
                        },
                        "entity_type": {
                            "type": "string",
                            "enum": [
                                "person",
                                "object",
                                "place",
                                "concept",
                                "skill",
                                "trait",
                                "body_part",
                                "feeling",
                            ],
                        },
                        "phase_name": {
                            "type": "string",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "Search keyword for fuzzy entity matching.",
                        },
                        "session_id": {
                            "type": "string",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                        },
                    },
                },
            },
            "required": ["template_key"],
        },
    },
}


# ─── GraphRAG Helper ─────────────────────────────────────────────


def graph_rag_query(question: str, top_k: int = 3, hop_distance: int = 2) -> list[dict]:
    """GraphRAG-style retrieval: keyword search + graph traversal.

    1. Search for entry nodes by keyword/entity name
    2. Traverse 1-2 hops from each entry node
    3. Return enriched context

    This avoids the LLM needing to write perfect global Cypher queries.

    Args:
        question: Natural language question.
        top_k: Number of entry nodes to find.
        hop_distance: How many hops to traverse.

    Returns:
        List of context snippets with entity, relation, and neighbor info.
    """
    # Step 1: Extract keywords from question (simple heuristic)
    # In production, this would be an embedding vector search
    keywords = [w for w in question.split() if len(w) > 1]
    if not keywords:
        return []

    # Search for entry nodes
    all_hits = []
    for kw in keywords[:3]:  # Limit to 3 keywords
        hits = execute_safe_query("SEARCH_ENTITIES", {"keyword": kw, "limit": top_k})
        all_hits.extend(hits)

    # Deduplicate
    seen = set()
    entry_nodes = []
    for h in all_hits:
        if h["name"] not in seen:
            seen.add(h["name"])
            entry_nodes.append(h)

    # Step 2: Traverse from each entry node
    context = []
    for node in entry_nodes[:top_k]:
        # Get direct neighbors
        neighborhood = execute_safe_query(
            "GET_ENTITY_NEIGHBORHOOD",
            {"entity_name": node["name"], "limit": 10},
        )

        # Get entity events
        events = execute_safe_query(
            "GET_ENTITY_EVENTS",
            {"entity_name": node["name"], "limit": 5},
        )

        context.append(
            {
                "entry": node,
                "neighbors": neighborhood,
                "events": events,
            }
        )

    return context
