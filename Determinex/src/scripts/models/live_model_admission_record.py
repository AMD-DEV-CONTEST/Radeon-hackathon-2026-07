"""Live local-model admission records.

The live admission record is the opt-in gate that a future inference
caller MUST consult before invoking a model. Even an ``READY`` record
does not by itself authorize source mutation, corpus write, or
training eligibility — those gates remain independent.
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS = (
    "LOCAL_MODEL_LIVE_ADMISSION_READY",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_DRY_RUN_DEFAULT",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NO_CONFIG",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MODEL_UNAVAILABLE",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_STALE_MODEL_ID",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNPINNED_MODEL",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NETWORK_PROVIDER",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNSUPPORTED_TASK_CLASS",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNKNOWN_PROVIDER",
    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MISSING_INVENTORY",
    "LOCAL_MODEL_LIVE_ADMISSION_METADATA_ONLY",
)


class LiveAdmissionMode(str, enum.Enum):
    DRY_RUN = "dry_run"
    OPT_IN_LIVE = "opt_in_live"


@dataclass(frozen=True)
class LiveModelAdmissionRecord:
    model_id: str
    provider: str
    task_class: str
    route_decision_ref: str
    decision: str
    availability_checked: bool = False
    pinned: bool = False
    stale_model_id_detected: bool = False
    network_required: bool = False
    live_call_authorized: bool = False
    source_mutation_authorized: bool = False
    corpus_write_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_")

    @property
    def is_ready(self) -> bool:
        return self.decision == "LOCAL_MODEL_LIVE_ADMISSION_READY"

    @property
    def is_metadata_only(self) -> bool:
        return self.decision == "LOCAL_MODEL_LIVE_ADMISSION_METADATA_ONLY"
