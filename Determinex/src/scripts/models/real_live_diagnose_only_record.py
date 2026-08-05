"""Records for REAL_LIVE_DIAGNOSE_ONLY_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_LIVE_DIAGNOSE_ONLY_STATUS_TOKENS = (
    "REAL_LIVE_DIAGNOSE_WRITTEN",
    "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL",
    "REAL_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
    "REAL_LIVE_DIAGNOSE_ADVISORY_ONLY",
    "REAL_LIVE_DIAGNOSE_BLOCKED_TIMEOUT",
    "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
)


@dataclass(frozen=True)
class RealLiveDiagnoseOnlyRecord:
    decision: str
    workspace: str
    model_id: str
    provider: str
    task_class: str
    advisory_summary: str
    response_chars: int
    elapsed_ms: int
    output_trusted: bool = False
    advisory_only: bool = True
    patch_generated: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    network_provider_admitted: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "REAL_LIVE_DIAGNOSE_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_LIVE_DIAGNOSE_BLOCKED_")


__all__ = [
    "REAL_LIVE_DIAGNOSE_ONLY_STATUS_TOKENS",
    "RealLiveDiagnoseOnlyRecord",
]
