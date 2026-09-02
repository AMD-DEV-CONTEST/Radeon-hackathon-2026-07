"""Records for FRONTEND_REAL_FLOW_E2E_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_REAL_FLOW_E2E_TOKENS = (
    "FRONTEND_REAL_FLOW_E2E_PASSED",
    "FRONTEND_REAL_FLOW_SOURCE_UNCHANGED",
    "FRONTEND_REAL_FLOW_APPROVAL_REQUIRED",
    "FRONTEND_REAL_FLOW_TRAINING_ELIGIBLE_FALSE",
    "FRONTEND_REAL_FLOW_NETWORK_PROVIDER_BLOCKED",
    "FRONTEND_REAL_FLOW_DOCKER_NOT_USED",
    "FRONTEND_REAL_FLOW_FE_BE_STATES_AGREE",
)


@dataclass(frozen=True)
class RealFlowE2EStage:
    name: str
    tauri_command: str
    status: str
    evidence_ref: str = ""
    source_mutation_authorized: bool = False
    training_eligible: bool = False


@dataclass(frozen=True)
class FrontendRealFlowE2ETrace:
    workspace: str
    stages: tuple[RealFlowE2EStage, ...]
    source_unchanged: bool
    approval_required: bool
    training_eligible: bool
    network_called: bool
    docker_used: bool
    frontend_backend_states_agree: bool
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
    "FRONTEND_REAL_FLOW_E2E_TOKENS",
    "RealFlowE2EStage",
    "FrontendRealFlowE2ETrace",
]
