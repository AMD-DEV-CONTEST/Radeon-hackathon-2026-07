import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict

from nexus.retrieval.service import SemanticRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "nexusai.db"


class ToolRegistry:
    """
    Central allowlisted registry for NexusAI agent tools.
    """

    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, function: Callable[..., Any]):
        if not callable(function):
            raise TypeError(f"Tool '{name}' must be callable.")

        self._tools[name] = function

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered.")

        return self._tools[name]

    def list_tools(self):
        return list(self._tools.keys())


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def extract_candidate_names(text):
    """
    Extract likely proper names from the original user request.

    This deliberately uses the user's original text rather than the
    generated goal so names such as 'Aria' are not mutated by the LLM.
    """

    ignored = {
        "Find",
        "Show",
        "Visualize",
        "Determine",
        "WorldForge",
        "NexusAI",
    }

    candidates = re.findall(
        r"\b[A-Z][a-zA-Z]+\b",
        text
    )

    return [
        candidate
        for candidate in candidates
        if candidate not in ignored
    ]


def search_knowledge(context):
    """
    Search real source chunks stored in nexusai.db using the
    existing NexusAI SemanticRetriever.
    """

    query = context["user_request"]

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                sc.id AS chunk_id,
                sc.source_id,
                sc.world_id,
                sc.text,
                sc.chunk_index,
                s.name AS source_name,
                s.source_type
            FROM source_chunks sc
            LEFT JOIN sources s
                ON s.id = sc.source_id
            """
        ).fetchall()

    if not rows:
        return {
            "status": "success",
            "tool": "search_knowledge",
            "query": query,
            "hits": [],
            "result": "No knowledge chunks are currently stored.",
        }

    documents = [
        row["text"]
        for row in rows
    ]

    retriever = SemanticRetriever()

    hits = retriever.search(
        query=query,
        documents=documents,
        top_k=min(5, len(documents)),
    )

    results = []

    for hit in hits:
        row = rows[hit.index]

        results.append(
            {
                "chunk_id": row["chunk_id"],
                "source_id": row["source_id"],
                "world_id": row["world_id"],
                "source_name": row["source_name"],
                "source_type": row["source_type"],
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "score": hit.score,
            }
        )

    return {
        "status": "success",
        "tool": "search_knowledge",
        "query": query,
        "hits": results,
        "result": (
            f"Retrieved {len(results)} relevant knowledge chunk(s)."
        ),
    }


def query_knowledge_graph(context):
    """
    Query real entities and relationships from nexusai.db.

    Entity matching is based on names from the original user request.
    """

    query = context["user_request"]
    candidate_names = extract_candidate_names(query)

    with get_connection() as conn:
        entity_rows = conn.execute(
            """
            SELECT
                id,
                world_id,
                entity_type,
                name,
                description,
                properties,
                source_ids
            FROM entities
            """
        ).fetchall()

        relationship_rows = conn.execute(
            """
            SELECT
                id,
                world_id,
                source_entity_id,
                target_entity_id,
                relationship_type,
                properties,
                source_ids
            FROM relationships
            """
        ).fetchall()

    entities_by_id = {
        row["id"]: row
        for row in entity_rows
    }

    matched_entities = []

    for row in entity_rows:
        entity_name = row["name"] or ""

        if any(
            candidate.lower() in entity_name.lower()
            or entity_name.lower() in candidate.lower()
            for candidate in candidate_names
        ):
            matched_entities.append(row)

    relationships = []

    matched_ids = {
        row["id"]
        for row in matched_entities
    }

    for relationship in relationship_rows:
        source_id = relationship["source_entity_id"]
        target_id = relationship["target_entity_id"]

        if (
            source_id in matched_ids
            or target_id in matched_ids
        ):
            source = entities_by_id.get(source_id)
            target = entities_by_id.get(target_id)

            relationships.append(
                {
                    "id": relationship["id"],
                    "relationship_type": (
                        relationship["relationship_type"]
                    ),
                    "source": {
                        "id": source["id"],
                        "name": source["name"],
                        "entity_type": source["entity_type"],
                    } if source else None,
                    "target": {
                        "id": target["id"],
                        "name": target["name"],
                        "entity_type": target["entity_type"],
                    } if target else None,
                }
            )

    entities = [
        {
            "id": row["id"],
            "world_id": row["world_id"],
            "name": row["name"],
            "entity_type": row["entity_type"],
            "description": row["description"],
        }
        for row in matched_entities
    ]

    return {
        "status": "success",
        "tool": "query_knowledge_graph",
        "query": query,
        "candidate_names": candidate_names,
        "entities": entities,
        "relationships": relationships,
        "result": (
            f"Found {len(entities)} matching entity/entities "
            f"and {len(relationships)} relationship(s)."
        ),
    }


def retrieve_source(context):
    """
    Retrieve real source records associated with prior observations.
    """

    source_ids = set()

    for observation in context.get("observations", []):
        data = observation.get(
            "observation",
            {}
        )

        for hit in data.get(
            "hits",
            []
        ):
            source_id = hit.get("source_id")

            if source_id:
                source_ids.add(source_id)

    if not source_ids:
        return {
            "status": "success",
            "tool": "retrieve_source",
            "sources": [],
            "result": "No source IDs were available from prior observations.",
        }

    placeholders = ",".join(
        "?"
        for _ in source_ids
    )

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                world_id,
                name,
                source_type,
                uri,
                checksum,
                metadata
            FROM sources
            WHERE id IN ({placeholders})
            """,
            tuple(source_ids),
        ).fetchall()

    sources = [
        {
            "id": row["id"],
            "world_id": row["world_id"],
            "name": row["name"],
            "source_type": row["source_type"],
            "uri": row["uri"],
        }
        for row in rows
    ]

    return {
        "status": "success",
        "tool": "retrieve_source",
        "sources": sources,
        "result": (
            f"Retrieved {len(sources)} supporting source(s)."
        ),
    }


def search_memory(context):
    """
    Temporary placeholder until MemoryWeaver persistent agent memory
    is connected.
    """

    return {
        "status": "success",
        "tool": "search_memory",
        "query": context["user_request"],
        "result": (
            "MemoryWeaver agent memory integration is pending."
        ),
    }


def save_memory(context):
    """
    Temporary placeholder until MemoryWeaver persistent agent memory
    is connected.
    """

    return {
        "status": "success",
        "tool": "save_memory",
        "content": context["user_request"],
        "result": (
            "MemoryWeaver agent memory integration is pending."
        ),
    }


def explore_world(context):
    """
    Build a real WorldForge visualization payload using graph
    observations produced by earlier tools.
    """

    entities = []
    relationships = []

    for observation in context.get(
        "observations",
        []
    ):
        data = observation.get(
            "observation",
            {}
        )

        if data.get("tool") == "query_knowledge_graph":
            entities.extend(
                data.get(
                    "entities",
                    []
                )
            )

            relationships.extend(
                data.get(
                    "relationships",
                    []
                )
            )

    world_ids = list(
        {
            entity["world_id"]
            for entity in entities
            if entity.get("world_id")
        }
    )

    return {
        "status": "success",
        "tool": "explore_world",
        "world_ids": world_ids,
        "entities": entities,
        "relationships": relationships,
        "result": (
            f"Prepared WorldForge payload with "
            f"{len(entities)} entity/entities and "
            f"{len(relationships)} relationship(s)."
        ),
    }


def create_default_registry():
    registry = ToolRegistry()

    registry.register(
        "search_knowledge",
        search_knowledge
    )

    registry.register(
        "query_knowledge_graph",
        query_knowledge_graph
    )

    registry.register(
        "retrieve_source",
        retrieve_source
    )

    registry.register(
        "search_memory",
        search_memory
    )

    registry.register(
        "save_memory",
        save_memory
    )

    registry.register(
        "explore_world",
        explore_world
    )

    return registry
