"""Records for REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_STATUS_TOKENS = (
    "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN",
    "REAL_MODEL_DIAGNOSE_BLOCKED_NO_MODEL",
    "REAL_MODEL_DIAGNOSE_BLOCKED_HEALTHCHECK_FAILED",
    "REAL_MODEL_DIAGNOSE_BLOCKED_NO_VERIFIER",
    "REAL_MODEL_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
    "REAL_MODEL_DIAGNOSE_BLOCKED_TIMEOUT",
    "REAL_MODEL_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
    "REAL_MODEL_DIAGNOSE_ADVISORY_ONLY",
)


@dataclass(frozen=True)
class RealModelDiagnoseWithBuildVerifierRecord:
    decision: str
    workspace: str
    model_id: str
    provider: str
    build_system_id: str
    verifier_command: tuple[str, ...]
    advisory_summary: str
    response_chars: int
    elapsed_ms: int
    output_trusted: bool = False
    advisory_only: bool = True
    patch_generated: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    verifier_remains_source_of_truth: bool = True
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["verifier_command"] = list(self.verifier_command)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_MODEL_DIAGNOSE_BLOCKED_")


__all__ = [
    "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_STATUS_TOKENS",
    "RealModelDiagnoseWithBuildVerifierRecord",
]
