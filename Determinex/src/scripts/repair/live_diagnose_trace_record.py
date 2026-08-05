"""Records for LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001.

The diagnose-only trace captures an advisory response from a live or
fixture model. The response is ADVISORY ONLY — it never produces a
patch, it never authorizes source mutation, it never opens corpus
write or training eligibility. The verifier remains the source of
truth; the model's role here is to *suggest*, not to *fix*.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LIVE_DIAGNOSE_STATUS_TOKENS = (
    "LIVE_DIAGNOSE_TRACE_WRITTEN",
    "LIVE_DIAGNOSE_BLOCKED_MODEL_NOT_ADMITTED",
    "LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
    "LIVE_DIAGNOSE_RESPONSE_CAPTURED_ADVISORY_ONLY",
    "LIVE_DIAGNOSE_NO_SOURCE_MUTATION",
    "LIVE_DIAGNOSE_BLOCKED_PROVIDER_REJECTED",
)


_ALLOWED_TASK_CLASSES: frozenset[str] = frozenset(
    {
        "BUILD_DIAGNOSIS",
        "TEST_FAILURE_LOCALIZATION",
    }
)


def allowed_task_classes() -> frozenset[str]:
    return _ALLOWED_TASK_CLASSES


@dataclass(frozen=True)
class LiveDiagnoseTrace:
    decision: str
    workspace: str
    task_class: str
    admission_decision_ref: str
    provider: str
    model_id: str
    response_status: str
    advisory_payload: dict[str, object] = field(default_factory=dict)
    advisory_only: bool = True
    patch_generated: bool = False
    source_mutation_authorized: bool = False
    corpus_write_authorized: bool = False
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
    def is_written(self) -> bool:
        return self.decision == "LIVE_DIAGNOSE_TRACE_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LIVE_DIAGNOSE_BLOCKED_")
