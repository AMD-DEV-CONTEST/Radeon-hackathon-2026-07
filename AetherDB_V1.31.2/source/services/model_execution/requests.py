"""Request contract for model-backed business tasks."""

from dataclasses import dataclass, field
from typing import Any, Mapping

from services.model_execution.task_types import TaskTypeResolution, resolve_task_type


ALLOWED_CLIENT_METADATA = frozenset(
    {
        "ui_source",
        "requested_output_format",
        "chapter_selection_range",
    }
)


def sanitize_client_metadata(raw: Mapping[str, object] | None) -> dict[str, object]:
    """Keep non-privileged client hints and discard routing policy fields."""
    if not raw:
        return {}
    return {key: value for key, value in raw.items() if key in ALLOWED_CLIENT_METADATA}


@dataclass(frozen=True)
class ModelTaskRequest:
    task_id: str
    task_type: str
    database_id: str
    book_id: str | None
    messages: tuple[Mapping[str, Any], ...]
    chapter_id: str | None = None
    user_selected_model_id: str | None = None
    session_id: str | None = None
    privacy_level: str = "private"
    max_cost_level: str = "medium"
    requires_json: bool = False
    requires_streaming: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    owner_id: str = "system"
    context_task_id: str | None = None
    selected_asset_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        resolve_task_type(self.task_type)
        if not self.database_id.strip():
            raise ValueError("database_id is required")
        if not self.messages:
            raise ValueError("messages are required")

    @property
    def task_type_resolution(self) -> TaskTypeResolution:
        return resolve_task_type(self.task_type)

    @property
    def canonical_task_type(self) -> str:
        return self.task_type_resolution.canonical

    @property
    def legacy_task_type(self) -> str | None:
        return self.task_type_resolution.legacy_source

    @property
    def binding_task_types(self) -> tuple[str, ...]:
        return self.task_type_resolution.binding_lookup_types
