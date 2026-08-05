"""Records for REAL_LOCAL_MODEL_ADMISSION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_LOCAL_MODEL_ADMISSION_STATUS_TOKENS = (
    "REAL_LOCAL_MODEL_ADMITTED",
    "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
    "REAL_LOCAL_MODEL_BLOCKED_UNPINNED",
    "REAL_LOCAL_MODEL_BLOCKED_STALE",
    "REAL_LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
    "REAL_LOCAL_MODEL_BLOCKED_NOT_OPTED_IN",
    "REAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
)


@dataclass(frozen=True)
class RealLocalModelAdmissionRecord:
    decision: str
    provider: str
    model_id: str
    task_classes_admitted: tuple[str, ...]
    dry_run_default: bool = True
    opt_in: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    network_provider_admitted: bool = False
    provider_detection_decision: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["task_classes_admitted"] = list(self.task_classes_admitted)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_admitted(self) -> bool:
        return self.decision == "REAL_LOCAL_MODEL_ADMITTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_LOCAL_MODEL_BLOCKED_")


__all__ = [
    "REAL_LOCAL_MODEL_ADMISSION_STATUS_TOKENS",
    "RealLocalModelAdmissionRecord",
]
