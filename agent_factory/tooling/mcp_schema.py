from __future__ import annotations

from dataclasses import dataclass
from typing import Any


JSON_SCHEMA_TYPES = frozenset(
    {
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }
)

_SCHEMA_MAP_KEYWORDS = frozenset(
    {
        "$defs",
        "definitions",
        "dependentSchemas",
        "patternProperties",
        "properties",
    }
)
_SCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_VALUE_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)


@dataclass(frozen=True, slots=True)
class MCPSchemaRepair:
    path: str
    original: str
    replacement: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "original": self.original,
            "replacement": dict(self.replacement),
        }


@dataclass(frozen=True, slots=True)
class NormalizedMCPSchema:
    schema: dict[str, Any]
    repairs: tuple[MCPSchemaRepair, ...]


def normalize_mcp_schema(schema: dict[str, Any]) -> NormalizedMCPSchema:
    """Normalize safe, unambiguous MCP JSON Schema shorthand.

    MCP tool schemas are JSON Schema objects at the root. Some servers emit a
    JSON type name directly where a nested schema object is required, for
    example ``"properties": {"name": "string"}``. A JSON type name in a
    schema position has one unambiguous structural expansion, so it is safe to
    convert it to ``{"type": "string"}``.

    Other invalid values are intentionally preserved so the standards
    validator can reject them instead of silently changing parameter meaning.
    """

    if not schema:
        return NormalizedMCPSchema(
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            repairs=(),
        )
    repairs: list[MCPSchemaRepair] = []
    normalized = _normalize_schema_node(schema, path="", repairs=repairs)
    if not isinstance(normalized, dict):
        return NormalizedMCPSchema(schema=schema, repairs=tuple(repairs))
    normalized.setdefault("type", "object")
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
    return NormalizedMCPSchema(schema=normalized, repairs=tuple(repairs))


def _normalize_schema_node(
    value: Any,
    *,
    path: str,
    repairs: list[MCPSchemaRepair],
) -> Any:
    if isinstance(value, str) and value in JSON_SCHEMA_TYPES:
        replacement = {"type": value}
        repairs.append(
            MCPSchemaRepair(
                path=path or "/",
                original=value,
                replacement=replacement,
            )
        )
        return replacement
    if isinstance(value, bool) or not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for keyword, keyword_value in value.items():
        keyword_path = _pointer(path, keyword)
        if keyword in _SCHEMA_MAP_KEYWORDS and isinstance(keyword_value, dict):
            normalized[keyword] = {
                name: _normalize_schema_node(
                    child,
                    path=_pointer(keyword_path, name),
                    repairs=repairs,
                )
                for name, child in keyword_value.items()
            }
        elif keyword in _SCHEMA_LIST_KEYWORDS and isinstance(keyword_value, list):
            normalized[keyword] = [
                _normalize_schema_node(
                    child,
                    path=_pointer(keyword_path, str(index)),
                    repairs=repairs,
                )
                for index, child in enumerate(keyword_value)
            ]
        elif keyword in _SCHEMA_VALUE_KEYWORDS:
            normalized[keyword] = _normalize_schema_node(
                keyword_value,
                path=keyword_path,
                repairs=repairs,
            )
        else:
            normalized[keyword] = keyword_value
    return normalized


def _pointer(parent: str, value: str) -> str:
    escaped = value.replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}" if parent else f"/{escaped}"
