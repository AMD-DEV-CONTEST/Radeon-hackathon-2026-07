"""Records for IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_END_TO_END_UI_FLOW_TOKENS = (
    "IDE_UI_FLOW_TRACE_WRITTEN",
    "IDE_UI_FLOW_SOURCE_UNCHANGED",
    "IDE_UI_FLOW_APPROVAL_REQUIRED",
    "IDE_UI_FLOW_TRAINING_ELIGIBLE_FALSE",
)


@dataclass(frozen=True)
class IDEUIFlowStage:
    name: str
    status: str
    evidence_ref: str = ""


@dataclass(frozen=True)
class IDEEndToEndUIFlowTrace:
    workspace: str
    stages: tuple[IDEUIFlowStage, ...]
    source_unchanged: bool
    approval_required: bool
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["stages"] = [asdict(s) for s in self.stages]
        d["statuses_seen"] = list(self.statuses_seen)
        d["evidence_refs"] = list(self.evidence_refs)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
