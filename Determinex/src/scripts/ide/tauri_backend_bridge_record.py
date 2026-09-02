"""Records for TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

TAURI_BRIDGE_STATUS_TOKENS = (
    "TAURI_BRIDGE_READY",
    "TAURI_BRIDGE_BLOCKED_NO_TAURI_APP",
    "TAURI_BRIDGE_API_STABLE",
    "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
    "TAURI_COMMAND_TEMP_ONLY",
    "TAURI_COMMAND_OK",
    "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
    "TAURI_COMMAND_BLOCKED_NO_MODEL",
    "TAURI_COMMAND_BLOCKED_UNKNOWN",
)


@dataclass(frozen=True)
class TauriBridgeResponse:
    command: str
    status: str
    payload: dict[str, object] = field(default_factory=dict)
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
