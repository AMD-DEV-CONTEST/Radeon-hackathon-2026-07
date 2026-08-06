from __future__ import annotations

from typing import Any

from .models import CANONICAL_MODELS


def _component_schemas() -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for model in CANONICAL_MODELS:
        schema = model.model_json_schema(
            mode="validation",
            ref_template="#/components/schemas/{model}",
        )
        definitions = schema.pop("$defs", {})
        for name, definition in definitions.items():
            existing = components.get(name)
            if existing is not None and existing != definition:
                raise RuntimeError(f"conflicting JSON Schema definition: {name}")
            components[name] = definition
        components[model.__name__] = schema
    return {name: components[name] for name in sorted(components)}


def build_openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Douyin Creative Hub Shared Contracts",
            "version": "1.0.0",
        },
        "paths": {},
        "components": {"schemas": _component_schemas()},
    }
