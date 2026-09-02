"""Records for IDE_BACKEND_COMMAND_SURFACE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_BACKEND_COMMAND_STATUS_TOKENS = (
    "IDE_BACKEND_COMMAND_SURFACE_READY",
    "IDE_COMMAND_BLOCKED_NOT_OPTED_IN",
    "IDE_COMMAND_BLOCKED_NO_MODEL",
    "IDE_COMMAND_SOURCE_MUTATION_BLOCKED",
    "IDE_COMMAND_TEMP_ONLY",
    "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND",
    "IDE_COMMAND_OK",
)


@dataclass(frozen=True)
class CommandResult:
    command: str
    status: str
    payload: dict[str, object] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["evidence_refs"] = list(self.evidence_refs)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
