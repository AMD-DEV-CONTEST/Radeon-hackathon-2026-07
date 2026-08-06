"""Tool metadata and callable boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolHandler = Callable[[BaseModel], BaseModel]


class ToolDefinition(BaseModel):
    """Validated metadata exposed selectively to planning."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=1000)
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    permission: Literal["auto", "confirm", "deny"]
    read_only: bool
    timeout_seconds: float = Field(gt=0, le=300)
    category: str = Field(min_length=1, max_length=128)
    allowed_roots: list[Path] = Field(default_factory=list)
    allowed_extensions: list[str] = Field(default_factory=list)
    max_items: int = Field(default=100, ge=1, le=100_000)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
            "output_schema": self.output_schema.model_json_schema(),
            "permission": self.permission,
            "read_only": self.read_only,
            "timeout_seconds": self.timeout_seconds,
            "category": self.category,
            "allowed_roots": [str(path) for path in self.allowed_roots],
            "allowed_extensions": self.allowed_extensions,
            "max_items": self.max_items,
        }


class RegisteredTool:
    """A definition paired with a fixed Python callable at application startup."""

    def __init__(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.definition = definition
        self.handler = handler

