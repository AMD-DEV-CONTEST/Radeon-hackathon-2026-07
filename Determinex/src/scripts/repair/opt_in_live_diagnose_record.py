"""Records for OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS = (
    "OPT_IN_LIVE_DIAGNOSE_READY",
    "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NO_MODEL_CONFIG",
    "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
    "OPT_IN_LIVE_DIAGNOSE_BLOCKED_PROVIDER_UNAVAILABLE",
    "OPT_IN_LIVE_DIAGNOSE_ADVISORY_WRITTEN",
    "OPT_IN_LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
)


@dataclass(frozen=True)
class OptInLiveDiagnoseRecord:
    decision: str
    workspace: str
    task_class: str
    config_path: str
    provider: str
    model_id: str
    advisory_payload: dict[str, object] = field(default_factory=dict)
    advisory_only: bool = True
    patch_generated: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
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
    def is_ready(self) -> bool:
        return self.decision == "OPT_IN_LIVE_DIAGNOSE_READY"
