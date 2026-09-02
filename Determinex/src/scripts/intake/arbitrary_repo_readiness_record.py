"""Readiness-matrix records for ARBITRARY_REPO_READINESS_MATRIX_LOCK_001.

A machine-readable matrix that says, for each (language, build_system,
test_framework) row, exactly how ready the apparatus is to repair an
arbitrary repo of that shape. Every row carries a ``ready_level``
chosen from a closed set, and a per-column truth value for the seven
apparatus checks.
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

READINESS_MATRIX_STATUS_TOKENS = (
    "READINESS_MATRIX_WRITTEN",
    "READY_MOCKED_TRACE",
    "READY_TEMP_PATCH_ONLY",
    "READY_REQUIRES_LIVE_MODEL_ADMISSION",
    "READY_REQUIRES_VERIFIER",
    "BLOCKED_UNSUPPORTED",
)


class ReadyLevel(str, enum.Enum):
    MOCKED_TRACE = "READY_MOCKED_TRACE"
    TEMP_PATCH_ONLY = "READY_TEMP_PATCH_ONLY"
    REQUIRES_LIVE_MODEL_ADMISSION = "READY_REQUIRES_LIVE_MODEL_ADMISSION"
    REQUIRES_VERIFIER = "READY_REQUIRES_VERIFIER"
    BLOCKED_UNSUPPORTED = "BLOCKED_UNSUPPORTED"


@dataclass(frozen=True)
class ReadinessRow:
    language: str
    build_system: str
    test_framework: str
    adapter_backed: bool
    verifier_backed: bool
    model_route_exists: bool
    mocked_repair_trace_exists: bool
    safe_patch_workspace_supported: bool
    human_approval_gate_exists: bool
    ide_state_exposed: bool
    corpus_guard_exists: bool
    live_model_admitted: bool
    ready_level: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessMatrix:
    generated_at: str
    rows: tuple[ReadinessRow, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "rows": [r.to_dict() for r in self.rows],
            "notes": list(self.notes),
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def rows_with_ready_level(self, level: ReadyLevel) -> tuple[ReadinessRow, ...]:
        return tuple(r for r in self.rows if r.ready_level == level.value)

    def find(self, build_system: str) -> ReadinessRow | None:
        for r in self.rows:
            if r.build_system == build_system:
                return r
        return None
