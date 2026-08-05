"""Records for FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS = (
    "FRONTEND_E2E_SMOKE_TRACE_WRITTEN",
    "FRONTEND_E2E_SMOKE_SOURCE_UNCHANGED",
    "FRONTEND_E2E_SMOKE_APPROVAL_REQUIRED",
    "FRONTEND_E2E_SMOKE_TRAINING_ELIGIBLE_FALSE",
    "FRONTEND_E2E_SMOKE_NO_LIVE_MODEL_CALL",
    "FRONTEND_E2E_SMOKE_NO_NETWORK_CALL",
)


@dataclass(frozen=True)
class FrontendStage:
    """One step of the visible frontend repair flow."""

    panel: str
    tauri_command: str
    status: str
    source_mutation_authorized: bool = False
    training_eligible: bool = False


@dataclass(frozen=True)
class FrontendEndToEndRepairFlowSmokeTrace:
    workspace: str
    stages: tuple[FrontendStage, ...]
    source_unchanged: bool
    approval_required: bool
    training_eligible: bool
    live_model_called: bool
    network_called: bool
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


__all__ = [
    "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS",
    "FrontendStage",
    "FrontendEndToEndRepairFlowSmokeTrace",
]
