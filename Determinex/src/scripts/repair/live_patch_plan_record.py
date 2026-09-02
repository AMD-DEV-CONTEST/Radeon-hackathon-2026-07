"""Records for LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001.

The quarantined patch plan is a structured, validated, *untrusted*
description of file replacements a live model proposed. It is stored
as evidence; it is NOT applied to source, and it is NOT applied to a
temp workspace at this rung (the temp-patch verifier gate is rung 5).
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

LIVE_PATCH_PLAN_STATUS_TOKENS = (
    "PATCH_PLAN_QUARANTINED",
    "PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
    "PATCH_PLAN_BLOCKED_PATH_ESCAPE",
    "PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION",
    "PATCH_PLAN_BLOCKED_MODEL_NOT_ADMITTED",
    "PATCH_PLAN_BLOCKED_BINARY_CONTENT",
    "PATCH_PLAN_BLOCKED_OVERSIZED",
)


class PatchOp(str, enum.Enum):
    REPLACE_FILE = "replace_file"


_SUPPORTED_OPERATIONS: frozenset[str] = frozenset({PatchOp.REPLACE_FILE.value})


def supported_operations() -> frozenset[str]:
    return _SUPPORTED_OPERATIONS


@dataclass(frozen=True)
class QuarantinedPatchEntry:
    operation: str
    path: str
    new_content_chars: int
    new_content_preview: str  # first 200 chars
    rejected_reason: str = ""


@dataclass(frozen=True)
class QuarantinedPatchPlan:
    decision: str
    admission_decision_ref: str
    provider: str
    model_id: str
    workspace: str
    entries: tuple[QuarantinedPatchEntry, ...] = field(default_factory=tuple)
    rejected_entries: tuple[QuarantinedPatchEntry, ...] = field(default_factory=tuple)
    trusted: bool = False  # always False
    applied_to_source: bool = False  # always False
    applied_to_temp_workspace: bool = False  # always False at this rung
    source_mutation_authorized: bool = False
    corpus_write_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["entries"] = [asdict(e) for e in self.entries]
        d["rejected_entries"] = [asdict(e) for e in self.rejected_entries]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_quarantined(self) -> bool:
        return self.decision == "PATCH_PLAN_QUARANTINED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("PATCH_PLAN_BLOCKED_")
