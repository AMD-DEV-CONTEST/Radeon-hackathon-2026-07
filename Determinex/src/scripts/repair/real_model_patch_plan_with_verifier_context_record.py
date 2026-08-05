"""Records for REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_STATUS_TOKENS = (
    "REAL_PATCH_PLAN_CONTEXT_QUARANTINED",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NO_VERIFIER",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_HEALTHCHECK",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NOT_OPTED_IN",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_PATH_ESCAPE",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_UNSUPPORTED_OPERATION",
    "REAL_PATCH_PLAN_CONTEXT_OUTPUT_UNTRUSTED",
    "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED",
)


@dataclass(frozen=True)
class RealPatchPlanContextEntry:
    operation: str
    path: str
    new_content_chars: int
    rejection_reason: str = ""


@dataclass(frozen=True)
class RealModelPatchPlanWithVerifierContextRecord:
    decision: str
    workspace: str
    model_id: str
    provider: str
    build_system_id: str
    verifier_command: tuple[str, ...]
    accepted: tuple[RealPatchPlanContextEntry, ...]
    rejected: tuple[RealPatchPlanContextEntry, ...]
    quarantined: bool = True
    output_trusted: bool = False
    patch_applied: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["verifier_command"] = list(self.verifier_command)
        d["accepted"] = [asdict(e) for e in self.accepted]
        d["rejected"] = [asdict(e) for e in self.rejected]
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_quarantined(self) -> bool:
        return self.decision == "REAL_PATCH_PLAN_CONTEXT_QUARANTINED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_PATCH_PLAN_CONTEXT_BLOCKED_")


__all__ = [
    "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_STATUS_TOKENS",
    "RealModelPatchPlanWithVerifierContextRecord",
    "RealPatchPlanContextEntry",
]
