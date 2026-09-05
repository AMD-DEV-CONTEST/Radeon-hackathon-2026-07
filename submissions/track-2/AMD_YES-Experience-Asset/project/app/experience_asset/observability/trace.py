"""Sanitized JSONL traces with raw content disabled by construction."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from app.experience_asset.domain.models import ContractModel, NonEmptyText

ALLOWED_ATTRIBUTE_KEYS = {
    "asset_id",
    "version_id",
    "stage",
    "model_id",
    "model_config_hash",
    "code_commit",
    "fixture_id",
    "input_hash",
    "input_size",
    "output_hash",
    "output_size",
    "elapsed_ms",
    "prompt_tokens",
    "completion_tokens",
    "policy_decision",
    "validation_outcome",
    "error_class",
    "retry_count",
    "terminal_state",
}


def sanitize_attributes(attributes: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], list[str]]:
    """Keep the approved metadata allowlist and report every dropped key."""

    clean = {key: value for key, value in attributes.items() if key in ALLOWED_ATTRIBUTE_KEYS}
    dropped = sorted(set(attributes) - ALLOWED_ATTRIBUTE_KEYS)
    return clean, dropped


class TraceEventV1(ContractModel):
    schema_version: str = "1.0.0"
    event_id: UUID
    run_id: UUID
    event_type: NonEmptyText
    occurred_at: AwareDatetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    redacted_fields: list[str] = Field(default_factory=list)


class JsonlTraceSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def emit(self, event: TraceEventV1) -> TraceEventV1:
        attributes, dropped = sanitize_attributes(event.attributes)
        sanitized = event.model_copy(
            update={
                "attributes": attributes,
                "redacted_fields": sorted(set(event.redacted_fields) | set(dropped)),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(sanitized.model_dump_json())
            handle.write("\n")
        return sanitized
