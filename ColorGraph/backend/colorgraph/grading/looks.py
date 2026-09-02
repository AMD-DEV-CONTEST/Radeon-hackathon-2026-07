from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from math import isclose, isfinite
from typing import Any

from colorgraph.domain.grade_graph import GradeGraph, GradeNode, NodeType

LOOK_RECIPE_SCHEMA = "colorgraph.look-recipes/v1"
LOOK_RECIPE_VERSION = "2026-07-29.1"
LOOK_INSTANCE_SCHEMA = "colorgraph.look-instance/v1"

LOOK_RECIPES: dict[str, dict[str, float | str]] = {
    "natural": {
        "label": "Natural Travel",
        "strength": 0.72,
        "contrast": 0.12,
        "saturation": 0.08,
        "temperature": 0.04,
        "highlights": -0.18,
    },
    "cool": {
        "label": "Cool Documentary",
        "strength": 0.84,
        "contrast": 0.18,
        "saturation": -0.05,
        "temperature": -0.18,
        "highlights": -0.28,
    },
    "warm": {
        "label": "Warm Sunset",
        "strength": 0.78,
        "contrast": 0.12,
        "saturation": 0.08,
        "temperature": 0.18,
        "highlights": -0.24,
    },
    "foggy": {
        "label": "Foggy Cinematic",
        "strength": 0.66,
        "contrast": -0.04,
        "saturation": -0.12,
        "temperature": -0.08,
        "highlights": -0.22,
    },
}

LOOK_PARAMETER_KEYS = (
    "strength",
    "contrast",
    "saturation",
    "temperature",
    "highlights",
)


def look_parameters(recipe_id: str) -> dict[str, float]:
    recipe = LOOK_RECIPES[recipe_id]
    return {key: float(recipe[key]) for key in LOOK_PARAMETER_KEYS}


def look_recipe_catalog() -> dict[str, Any]:
    return {
        "schema_version": LOOK_RECIPE_SCHEMA,
        "recipe_version": LOOK_RECIPE_VERSION,
        "recipes": [
            {
                "id": recipe_id,
                "label": str(recipe["label"]),
                "parameters": look_parameters(recipe_id),
            }
            for recipe_id, recipe in LOOK_RECIPES.items()
        ],
    }


def _inferred_recipe_id(node: GradeNode) -> str:
    instance = node.metadata.get("look_instance")
    if isinstance(instance, dict):
        base_recipe_id = instance.get("base_recipe_id")
        if isinstance(base_recipe_id, str) and base_recipe_id in LOOK_RECIPES:
            return base_recipe_id
    legacy_recipe_id = node.metadata.get("recipe_id")
    if isinstance(legacy_recipe_id, str) and legacy_recipe_id in LOOK_RECIPES:
        return legacy_recipe_id

    def distance(recipe_id: str) -> float:
        parameters = look_parameters(recipe_id)
        return sum(
            abs(float(node.parameters.get(key, parameters[key])) - parameters[key])
            for key in LOOK_PARAMETER_KEYS
        )

    return min(LOOK_RECIPES, key=distance)


def look_instance_for_node(node: GradeNode) -> dict[str, Any]:
    if node.type != NodeType.LOOK:
        raise ValueError(f"node {node.id!r} is not a Look node")
    base_recipe_id = _inferred_recipe_id(node)
    base_parameters = look_parameters(base_recipe_id)
    overrides: dict[str, float] = {}
    for key, base_value in base_parameters.items():
        actual_value = float(node.parameters.get(key, base_value))
        if not isclose(actual_value, base_value, rel_tol=0, abs_tol=1e-12):
            overrides[key] = actual_value
    return {
        "schema_version": LOOK_INSTANCE_SCHEMA,
        "recipe_version": LOOK_RECIPE_VERSION,
        "base_recipe_id": base_recipe_id,
        "user_overrides": overrides,
        "dirty": bool(overrides),
    }


def sync_look_instances(
    graph: GradeGraph,
    *,
    touch: bool = False,
) -> GradeGraph:
    payload = graph.model_dump(mode="python")
    changed = False
    for node_payload, node in zip(payload["nodes"], graph.nodes, strict=True):
        if node.type != NodeType.LOOK:
            continue
        instance = look_instance_for_node(node)
        metadata = node_payload["metadata"]
        if metadata.get("look_instance") != instance:
            metadata["look_instance"] = instance
            changed = True
        if metadata.get("recipe_id") != instance["base_recipe_id"]:
            metadata["recipe_id"] = instance["base_recipe_id"]
            changed = True
    if touch or changed:
        payload["updated_at"] = datetime.now(UTC)
    return GradeGraph.model_validate(payload)


def active_look_node(graph: GradeGraph, time_seconds: float) -> GradeNode | None:
    timestamp = min(max(0.0, time_seconds), graph.media.duration_seconds)
    shot = next(
        (
            item
            for item in graph.shots
            if item.time_range.start_seconds <= timestamp < item.time_range.end_seconds
        ),
        graph.shots[-1] if graph.shots else None,
    )
    scene_id = shot.scene_id if shot is not None else None
    return next(
        (
            node
            for node in graph.nodes
            if node.type == NodeType.LOOK
            and (scene_id is None or node.temporal_scope.scene_id == scene_id)
        ),
        None,
    )


def graph_digest(graph: GradeGraph) -> str:
    payload = graph.model_dump(mode="json")
    payload.pop("created_at", None)
    payload.pop("updated_at", None)
    for node in payload.get("nodes", []):
        metadata = node.get("metadata")
        if isinstance(metadata, dict):
            # This block is a deterministic projection of recipe_id + parameters.
            # Excluding it keeps legacy graphs and their normalized persistence
            # representation on the same content digest.
            metadata.pop("look_instance", None)
    payload = _canonicalize_digest_numbers(payload)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonicalize_digest_numbers(value: Any) -> Any:
    """Match JSON number semantics across Python and browser round trips."""
    if isinstance(value, dict):
        return {
            key: _canonicalize_digest_numbers(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_digest_numbers(item) for item in value]
    if (
        isinstance(value, float)
        and isfinite(value)
        and value.is_integer()
    ):
        return int(value)
    return value


def graph_with_look_recipe(
    graph: GradeGraph,
    recipe_id: str,
    *,
    time_seconds: float,
    source: str = "candidate_apply/v1",
) -> GradeGraph:
    if recipe_id not in LOOK_RECIPES:
        raise ValueError(f"unknown look recipe {recipe_id}")
    active = active_look_node(graph, time_seconds)
    if active is None:
        raise ValueError("active scene does not contain a Look node")

    payload = graph.model_dump(mode="python")
    recipe = LOOK_RECIPES[recipe_id]
    for node in payload["nodes"]:
        if node["id"] != active.id:
            continue
        node["label"] = str(recipe["label"])
        node["parameters"].update(look_parameters(recipe_id))
        node["metadata"].update(
            {
                "recipe_id": recipe_id,
                "look_instance": {
                    "schema_version": LOOK_INSTANCE_SCHEMA,
                    "recipe_version": LOOK_RECIPE_VERSION,
                    "base_recipe_id": recipe_id,
                    "user_overrides": {},
                    "dirty": False,
                },
                "candidate_source": source,
            }
        )
        break
    payload["updated_at"] = datetime.now(UTC)
    return GradeGraph.model_validate(payload)
