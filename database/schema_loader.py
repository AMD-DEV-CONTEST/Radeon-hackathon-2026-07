"""Extract graph schema from Neo4j for LLM context."""

import logging
from dataclasses import dataclass, field

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


@dataclass
class NodeLabel:
    label: str
    properties: list[dict]  # [{"name": "title", "type": "STRING"}, ...]
    sample_values: dict[str, list] = field(default_factory=dict)  # {property: [sample_value, ...]}


@dataclass
class RelationshipInfo:
    type: str
    from_labels: list[str]
    to_labels: list[str]
    properties: list[dict]


def get_schema() -> list[dict]:
    """Return the full graph schema for LLM context.

    Returns a list of dictionaries describing node labels, their properties,
    relationship types, and property samples.
    """
    client = Neo4jClient()

    # Get all node labels with their properties
    node_labels = client.execute("CALL db.labels() YIELD label RETURN label ORDER BY label")

    schema_parts = []

    for row in node_labels:
        label = row["label"]
        # Get property keys for this label
        props_result = client.execute(
            f"MATCH (n:`{label}`) WITH n LIMIT 1 UNWIND keys(n) AS key RETURN key"
        )
        prop_keys = [r["key"] for r in props_result]

        # Get sample values for each property (up to 3)
        samples = {}
        for key in prop_keys:
            sample_rows = client.execute(
                f"MATCH (n:`{label}`) WHERE n.`{key}` IS NOT NULL "
                f"RETURN DISTINCT n.`{key}` AS val LIMIT 3"
            )
            samples[key] = [r["val"] for r in sample_rows if r["val"] is not None]

        schema_parts.append(
            {
                "type": "node",
                "label": label,
                "properties": prop_keys,
                "samples": samples,
            }
        )

    # Get all relationship types
    rels = client.execute(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    )
    for row in rels:
        rel_type = row["relationshipType"]
        # Get sample (from_label)-[:REL_TYPE]->(to_label) patterns
        patterns = client.execute(
            f"MATCH (a)-[r:`{rel_type}`]->(b) "
            "RETURN DISTINCT labels(a) AS from_labels, labels(b) AS to_labels LIMIT 5"
        )
        for p in patterns:
            schema_parts.append(
                {
                    "type": "relationship",
                    "name": rel_type,
                    "from_labels": p["from_labels"],
                    "to_labels": p["to_labels"],
                }
            )

    return schema_parts


def format_schema_for_llm(schema: list[dict] | None = None) -> str:
    """Format schema as a text block suitable for LLM prompt.

    Args:
        schema: Schema from get_schema(). If None, fetches automatically.

    Returns:
        Formatted schema string.
    """
    if schema is None:
        schema = get_schema()

    lines = ["## 图数据库 Schema", ""]

    nodes = [s for s in schema if s["type"] == "node"]
    rels = [s for s in schema if s["type"] == "relationship"]

    lines.append("### 节点类型 (Node Labels)")
    lines.append("")
    for node in nodes:
        props = node.get("properties", [])
        props_str = ", ".join(props) if props else "(无属性)"
        lines.append(f"- **`{node['label']}`**: 属性: {props_str}")
        if node.get("samples"):
            for prop, vals in node["samples"].items():
                if vals:
                    val_str = ", ".join(str(v) for v in vals[:3])
                    lines.append(f"  - `{prop}` 示例: {val_str}")
    lines.append("")

    lines.append("### 关系类型 (Relationships)")
    lines.append("")
    if rels:
        for rel in rels:
            from_str = ", ".join(rel["from_labels"])
            to_str = ", ".join(rel["to_labels"])
            lines.append(f"- **`{rel['name']}`**: `({from_str})-[→{rel['name']}]->({to_str})`")
    else:
        lines.append("(暂无关系数据)")
    lines.append("")

    return "\n".join(lines)
