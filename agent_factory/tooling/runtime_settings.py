from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.factory_graph.frontend_bridge.agent_package_utils import read_json_object
from agent_factory.tooling.output_store import MIN_TOOL_OUTPUT_MAX_MODEL_CHARS
from agent_factory.tooling.spec import SNAKE_CASE_ID, ToolSpec


TOOL_RUNTIME_SETTINGS_FILENAME = "tool_settings.json"
MAX_TOOL_OUTPUT_MODEL_CHARS = 1_000_000


class ToolRuntimeOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    concurrent: bool | None = None
    max_model_chars: int | None = Field(
        default=None,
        ge=MIN_TOOL_OUTPUT_MAX_MODEL_CHARS,
        le=MAX_TOOL_OUTPUT_MODEL_CHARS,
    )

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("tool description override must not be empty")
        return normalized


class ToolRuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "tool_runtime_settings.v1"
    tools: dict[str, ToolRuntimeOverride] = Field(default_factory=dict)

    @field_validator("tools", mode="before")
    @classmethod
    def validate_tool_ids(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, object] = {}
        for raw_tool_id, override in value.items():
            tool_id = str(raw_tool_id or "").strip().lower().replace("-", "_")
            if not SNAKE_CASE_ID.fullmatch(tool_id):
                raise ValueError(f"invalid tool runtime override id: {raw_tool_id}")
            normalized[tool_id] = override
        return normalized


def tool_runtime_settings_path(extension_root: str | Path) -> Path:
    return Path(extension_root).expanduser().resolve() / TOOL_RUNTIME_SETTINGS_FILENAME


def load_tool_runtime_settings(extension_root: str | Path) -> ToolRuntimeSettings:
    payload = read_json_object(tool_runtime_settings_path(extension_root))
    return ToolRuntimeSettings.model_validate(payload or {})


def apply_tool_runtime_settings(
    specs: Iterable[ToolSpec],
    settings: ToolRuntimeSettings,
) -> list[ToolSpec]:
    configured: list[ToolSpec] = []
    for spec in specs:
        override = settings.tools.get(spec.id)
        if override is None:
            configured.append(spec)
            continue
        output_compression = spec.output_compression
        if override.max_model_chars is not None:
            output_compression = output_compression.model_copy(
                update={"max_model_chars": override.max_model_chars}
            )
        configured.append(
            spec.model_copy(
                update={
                    "description": override.description or spec.description,
                    "concurrent": spec.concurrent if override.concurrent is None else override.concurrent,
                    "output_compression": output_compression,
                }
            )
        )
    return configured
