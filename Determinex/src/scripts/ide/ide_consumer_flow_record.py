"""Records for IDE_CONSUMER_FLOW_TRACE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_CONSUMER_FLOW_TRACE_TOKENS = (
    "IDE_CONSUMER_FLOW_TRACE_WRITTEN",
    "IDE_CONSUMER_FLOW_SOURCE_UNCHANGED",
    "IDE_CONSUMER_FLOW_HUMAN_APPROVAL_REQUIRED",
    "IDE_CONSUMER_FLOW_TRAINING_ELIGIBLE_FALSE",
)


@dataclass(frozen=True)
class IDEConsumerFlowStage:
    name: str
    status: str
    evidence_ref: str = ""


@dataclass(frozen=True)
class IDEConsumerFlowTrace:
    workspace: str
    stages: tuple[IDEConsumerFlowStage, ...]
    source_unchanged: bool
    human_approval_required: bool
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["stages"] = [asdict(s) for s in self.stages]
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
