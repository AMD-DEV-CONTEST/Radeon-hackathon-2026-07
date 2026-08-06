"""Story Graph - compact generalized narrative graph schema v2.

Schema:
  Entity {name, type, description}
    types: person, object, place, concept, skill, body_part, feeling, trait
  Event {label, description, order, time_period}
  Phase {label, description, order}  -- groups events into life phases

Relationships:
  (:Entity)-[:RELATES_TO {type, context}]->(:Entity)
  (:Entity)-[:IN_EVENT {role}]->(:Event)
  (:Event)-[:NEXT]->(:Event)           -- temporal sequence
  (:Event)-[:CAUSES {context}]->(:Event) -- causality
  (:Event)-[:IN_PHASE]->(:Phase)       -- event belongs to a phase
  (:Entity)-[:SYMBOLIZES {context}]->(:Entity)

Usage:
  from memory.story_graph import StoryGraphBuilder, query_story, reconstruct_narrative
"""

import logging

from database.neo4j_client import Neo4jClient
from utils.timing import timing

logger = logging.getLogger(__name__)


# ─── Schema Creation ─────────────────────────────────────────────


def ensure_schema():
    """Create constraints for the story graph schema."""
    driver = Neo4jClient.get_driver()
    with driver.session(database="neo4j") as s:
        try:
            s.run(
                "CREATE CONSTRAINT entity_name_type IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE (e.name, e.type) IS NODE KEY"
            )
        except Exception:
            pass
        try:
            s.run(
                "CREATE CONSTRAINT event_label_order IF NOT EXISTS "
                "FOR (e:Event) REQUIRE (e.label, e.order) IS NODE KEY"
            )
        except Exception:
            pass
        try:
            s.run(
                "CREATE CONSTRAINT phase_label_order IF NOT EXISTS "
                "FOR (p:Phase) REQUIRE (p.label, p.order) IS NODE KEY"
            )
        except Exception:
            pass
    logger.info("Story graph schema ready")


# ─── Ingestion API ───────────────────────────────────────────────


class StoryGraphBuilder:
    """Build a story graph from extracted entities and events."""

    def __init__(self, story_title: str):
        self.title = story_title
        self.entities: list[dict] = []
        self.events: list[dict] = []
        self.phases: list[dict] = []
        self.relationships: list[dict] = []  # (from, to, type, props)
        self.symbols: list[dict] = []  # (entity, symbolizes, context)
        self.event_entities: list[dict] = []  # (entity, event, role)
        self.event_phases: list[dict] = []  # (event, phase)
        self.causal_links: list[dict] = []  # (from_event, to_event, context)

    def add_entity(self, name: str, etype: str, description: str = ""):
        self.entities.append({"name": name, "type": etype, "description": description})
        return self

    def add_event(self, label: str, description: str, order: int = 0, time_period: str = ""):
        self.events.append(
            {
                "label": label,
                "description": description,
                "order": order,
                "time_period": time_period,
            }
        )
        return self

    def add_phase(self, label: str, description: str = "", order: int = 0):
        self.phases.append({"label": label, "description": description, "order": order})
        return self

    def relate(
        self, from_entity: str, to_entity: str, rel_type: str = "related_to", context: str = ""
    ):
        self.relationships.append(
            {
                "from": from_entity,
                "to": to_entity,
                "type": rel_type,
                "context": context,
            }
        )
        return self

    def symbol(self, entity: str, concept: str, context: str = ""):
        self.symbols.append({"entity": entity, "concept": concept, "context": context})
        return self

    def participate(self, entity: str, event_label: str, role: str = "participant"):
        self.event_entities.append(
            {
                "entity": entity,
                "event": event_label,
                "role": role,
            }
        )
        return self

    def in_phase(self, event_label: str, phase_label: str):
        self.event_phases.append({"event": event_label, "phase": phase_label})
        return self

    def causes(self, from_event: str, to_event: str, context: str = ""):
        self.causal_links.append(
            {
                "from": from_event,
                "to": to_event,
                "context": context,
            }
        )
        return self

    @timing(name="story_graph_build")
    def build(self):
        """Commit the entire story graph to Neo4j."""
        ensure_schema()
        driver = Neo4jClient.get_driver()

        with driver.session(database="neo4j") as s:
            # Create entities
            for e in self.entities:
                s.run(
                    "MERGE (n:Entity {name: $name, type: $type}) SET n.description = $desc",
                    {"name": e["name"], "type": e["type"], "desc": e["description"]},
                )

            # Create events (with rank and priority)
            for ev in self.events:
                rank = max(1, 100 - ev["order"])  # earlier events rank higher
                s.run(
                    "MERGE (e:Event {label: $label, order: $order}) "
                    "SET e.description = $desc, e.time_period = $tp, "
                    "e.rank = $rank, e.priority = $priority",
                    {
                        "label": ev["label"],
                        "order": ev["order"],
                        "desc": ev["description"],
                        "tp": ev["time_period"],
                        "rank": rank,
                        "priority": "medium",
                    },
                )

            # Create phases
            for ph in self.phases:
                s.run(
                    "MERGE (p:Phase {label: $label, order: $order}) SET p.description = $desc",
                    {"label": ph["label"], "order": ph["order"], "desc": ph["description"]},
                )

            # Entity-entity relationships
            for r in self.relationships:
                s.run(
                    "MATCH (a:Entity {name: $a}), (b:Entity {name: $b}) "
                    "MERGE (a)-[r:RELATES_TO {type: $t, context: $c}]->(b)",
                    {"a": r["from"], "b": r["to"], "t": r["type"], "c": r["context"]},
                )

            # Event chains (NEXT)
            sorted_events = sorted(self.events, key=lambda x: x["order"])
            for i in range(len(sorted_events) - 1):
                s.run(
                    "MATCH (a:Event {label: $a}), (b:Event {label: $b}) MERGE (a)-[:NEXT]->(b)",
                    {"a": sorted_events[i]["label"], "b": sorted_events[i + 1]["label"]},
                )

            # Cause-effect links
            for cl in self.causal_links:
                s.run(
                    "MATCH (a:Event {label: $a}), (b:Event {label: $b}) "
                    "MERGE (a)-[:CAUSES {context: $c}]->(b)",
                    {"a": cl["from"], "b": cl["to"], "c": cl["context"]},
                )

            # Entity → Event participation
            for pe in self.event_entities:
                s.run(
                    "MATCH (n:Entity {name: $name}), (e:Event {label: $label}) "
                    "MERGE (n)-[:IN_EVENT {role: $role}]->(e)",
                    {"name": pe["entity"], "label": pe["event"], "role": pe["role"]},
                )

            # Event → Phase
            for ep in self.event_phases:
                s.run(
                    "MATCH (e:Event {label: $el}), (p:Phase {label: $pl}) "
                    "MERGE (e)-[:IN_PHASE]->(p)",
                    {"el": ep["event"], "pl": ep["phase"]},
                )

            # Symbolic relationships
            for sy in self.symbols:
                s.run(
                    "MATCH (a:Entity {name: $a}), (b:Entity {name: $b}) "
                    "MERGE (a)-[:SYMBOLIZES {context: $c}]->(b)",
                    {"a": sy["entity"], "b": sy["concept"], "c": sy["context"]},
                )

        logger.info(
            "Story graph built: %d entities, %d events, %d phases",
            len(self.entities),
            len(self.events),
            len(self.phases),
        )


# ─── Query API ──────────────────────────────────────────────────


@timing(name="query_story")
def query_story(question: str) -> str:
    """Answer a natural language question about the story graph."""
    from agents.tools.cypher_generator import generate_cypher
    from agents.tools.db_executor import execute_db
    from agents.tools.result_interpreter import interpret_result
    from database.schema_loader import format_schema_for_llm, get_schema

    schema = format_schema_for_llm(get_schema())
    cypher = generate_cypher(user_query=question, db_schema=schema)
    if cypher == "NOT_A_QUERY":
        return "没有找到相关的故事内容。"

    result = execute_db(cypher)
    if not result["success"]:
        return result["error"] or "查询故事图失败。"

    return interpret_result(result["data"], question)


@timing(name="reconstruct_narrative")
def reconstruct_narrative(topic: str | None = None) -> str:
    """Reconstruct a loose narrative from the graph around a topic.

    Traverses the event chain and collects related entities.
    Groups events by phase if phases exist.
    """
    driver = Neo4jClient.get_driver()

    # Load all phases
    phases = {}
    try:
        with driver.session(database="neo4j") as s:
            for r in s.run(
                "MATCH (p:Phase) RETURN p.label AS l, p.description AS d, p.order AS o ORDER BY o"
            ):
                phases[r["l"]] = {"desc": r["d"], "events": []}
    except Exception:
        pass

    # Load events (filtered by topic or all)
    if topic:
        query = (
            "MATCH (e:Entity {name: $topic})-[:IN_EVENT]->(ev:Event) "
            "OPTIONAL MATCH (ev)-[:IN_PHASE]->(p:Phase) "
            "RETURN ev.label AS label, ev.description AS desc, ev.order AS order, "
            "ev.time_period AS time, p.label AS phase "
            "ORDER BY ev.order"
        )
        events = []
        with driver.session(database="neo4j") as s:
            for r in s.run(query, {"topic": topic}):
                events.append(
                    {
                        "label": r["label"],
                        "desc": r["desc"],
                        "order": r["order"],
                        "time": r["time"],
                        "phase": r["phase"],
                    }
                )
    else:
        raw = Neo4jClient.execute(
            "MATCH (ev:Event) OPTIONAL MATCH (ev)-[:IN_PHASE]->(p:Phase) "
            "RETURN ev.label AS label, ev.description AS desc, "
            "ev.order AS order, ev.time_period AS time, p.label AS phase "
            "ORDER BY ev.order"
        )
        events = [
            {
                "label": r["label"],
                "desc": r["desc"],
                "order": r["order"],
                "time": r["time"],
                "phase": r["phase"],
            }
            for r in raw
        ]

    if not events:
        return "故事图中还没有事件数据。"

    # Get entities per event
    entity_map = {}
    with driver.session(database="neo4j") as s:
        for e in events:
            result = s.run(
                "MATCH (en:Entity)-[:IN_EVENT]->(ev:Event {label: $label}) "
                "RETURN en.name AS name, en.type AS type",
                {"label": e["label"]},
            )
            entity_map[e["label"]] = [{"name": r["name"], "type": r["type"]} for r in result]

    # Get traits for persons
    trait_map = {}
    try:
        with driver.session(database="neo4j") as s:
            for r in s.run(
                "MATCH (p:Entity {type: 'person'})-[rel:RELATES_TO]->(t:Entity {type: 'trait'}) "
                "RETURN p.name AS person, t.name AS trait, rel.context AS context"
            ):
                trait_map.setdefault(r["person"], []).append(
                    {"trait": r["trait"], "context": r["context"]}
                )
    except Exception:
        pass

    lines = ["## 故事回顾", ""]

    # Group by phase
    current_phase = None
    for ev in events:
        if ev["phase"] and ev["phase"] != current_phase:
            current_phase = ev["phase"]
            phase_desc = phases.get(current_phase, {}).get("desc", "")
            lines.append(f"### {current_phase}")
            if phase_desc:
                lines.append(f"  *{phase_desc}*")
            lines.append("")

        ents = entity_map.get(ev["label"], [])
        ents_str = ", ".join(f"{en['name']}({en['type']})" for en in ents)
        time_str = f"[{ev['time']}] " if ev["time"] else ""
        lines.append(f"**{time_str}{ev['label']}**")
        lines.append(f"  {ev['desc']}")
        if ents_str:
            lines.append(f"  *{ents_str}*")

        # Add traits for persons involved
        person_ents = [en for en in ents if en["type"] == "person"]
        if person_ents:
            trait_lines = []
            for p in person_ents:
                traits = trait_map.get(p["name"], [])
                if traits:
                    trait_str = ", ".join(
                        f"{t['trait']}({t['context']})" if t["context"] else t["trait"]
                        for t in traits
                    )
                    trait_lines.append(f"{p['name']}: {trait_str}")
            if trait_lines:
                lines.append(f"  *{'; '.join(trait_lines)}*")

        lines.append("")

    return "\n".join(lines)


def clear_story_data():
    """Remove all story graph data."""
    driver = Neo4jClient.get_driver()
    with driver.session(database="neo4j") as s:
        s.run("MATCH (e:Entity) DETACH DELETE e")
        s.run("MATCH (ev:Event) DETACH DELETE ev")
        s.run("MATCH (p:Phase) DETACH DELETE p")
    logger.info("Story graph cleared")


def update_rank(entity_name: str, increment: float = 0.1):
    """Self-updating rank: boost rank when entity/event is accessed.

    Mimics Bionic-Graph's atime-based ranking — frequently accessed
    entities naturally rise to the top of search results.
    """
    driver = Neo4jClient.get_driver()
    with driver.session(database="neo4j") as s:
        # Update atime and boost rank
        s.run(
            "MATCH (n) WHERE n.name = $name OR n.label = $name "
            "SET n.atime = timestamp(), n.rank = coalesce(n.rank, 50) + $inc",
            {"name": entity_name, "inc": increment},
        )
    logger.debug("Rank boosted: %s +%.2f", entity_name, increment)
