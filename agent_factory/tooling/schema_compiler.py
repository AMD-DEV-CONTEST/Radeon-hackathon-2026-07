from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model


class ToolSchemaError(ValueError):
    pass


@dataclass(slots=True)
class CompiledJsonSchema:
    schema: dict[str, Any]
    pydantic_model: type[BaseModel]
    validator: Any

    def errors_for(self, value: Any) -> list[str]:
        errors = sorted(self.validator.iter_errors(value), key=lambda item: list(item.path))
        return [_format_error(error) for error in errors]

    def validate(self, value: Any) -> None:
        errors = self.errors_for(value)
        if errors:
            raise ToolSchemaError("; ".join(errors))


def compile_json_schema(*, schema: dict[str, Any], model_name: str) -> CompiledJsonSchema:
    normalized = _normalize_schema(schema)
    validator_cls = _draft_validator()
    try:
        validator_cls.check_schema(normalized)
    except Exception as exc:  # jsonschema raises several schema-specific exception types.
        raise ToolSchemaError(f"invalid JSON schema: {exc}") from exc
    return CompiledJsonSchema(
        schema=normalized,
        pydantic_model=_pydantic_model_from_schema(normalized, model_name),
        validator=validator_cls(normalized),
    )


def _draft_validator():
    try:
        return importlib.import_module("jsonschema").Draft202012Validator
    except ModuleNotFoundError as exc:
        raise ToolSchemaError("jsonschema dependency is required for tool schema validation") from exc


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if not isinstance(schema, dict):
        raise ToolSchemaError("schema must be a JSON object")
    normalized = dict(schema)
    normalized.setdefault("type", "object")
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
    return normalized


def _pydantic_model_from_schema(schema: dict[str, Any], model_name: str) -> type[BaseModel]:
    if schema.get("type") != "object":
        raise ToolSchemaError("top-level tool schema must be a JSON object")
    fields: dict[str, Any] = {}
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ToolSchemaError("object schema properties must be a JSON object")
    for field_name, field_schema in properties.items():
        if isinstance(field_schema, bool):
            annotation = Any
            default = ... if field_name in required else None
            fields[field_name] = (annotation, Field(default))
            continue
        if not isinstance(field_schema, dict):
            raise ToolSchemaError(f"field schema must be an object or boolean: {field_name}")
        annotation = _annotation_for_schema(field_schema, f"{model_name}_{field_name}")
        default = ... if field_name in required else field_schema.get("default", None)
        description = field_schema.get("description")
        fields[field_name] = (annotation, Field(default, description=description))
    extra = "forbid" if schema.get("additionalProperties") is False else "allow"
    return create_model(
        model_name,
        __config__=ConfigDict(extra=extra),
        **fields,
    )


def _annotation_for_schema(schema: dict[str, Any], model_name: str) -> Any:
    if "const" in schema:
        return Literal.__getitem__((schema["const"],))
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return Literal.__getitem__(tuple(enum_values))
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf") or []
        annotations = [
            _annotation_for_schema(option, f"{model_name}_{index}")
            for index, option in enumerate(options)
            if isinstance(option, dict) and option.get("type") != "null"
        ]
        if not annotations:
            return Any
        if len(annotations) == 1:
            return annotations[0]
        return Union.__getitem__(tuple(annotations))
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        if len(non_null) == 1:
            return _annotation_for_schema({**schema, "type": non_null[0]}, model_name)
        return Any
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        item_schema = schema.get("items")
        item_annotation = _annotation_for_schema(item_schema, f"{model_name}_item") if isinstance(item_schema, dict) else Any
        return list[item_annotation]
    if schema_type == "object":
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            return _pydantic_model_from_schema(schema, model_name)
        return dict[str, Any]
    return Any


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.path)
    if not location:
        location = "<root>"
    return f"{location}: {error.message}"
