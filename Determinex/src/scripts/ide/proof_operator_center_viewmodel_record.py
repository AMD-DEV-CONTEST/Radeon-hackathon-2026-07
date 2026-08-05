"""Records for DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PROOF_OPERATOR_CENTER_VIEWMODEL_STATUS_TOKENS = (
    "PROOF_OPERATOR_CENTER_VIEWMODEL_WRITTEN",
    "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN",
    "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
    "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION",
)


# Required sections.
PROOF_OPERATOR_CENTER_SECTIONS = (
    "evidence_ledger",
    "current_workspace_status",
    "source_mutation_gates",
    "verifier_status",
    "rollback_status",
    "operator_actions",
    "programbench_provenance_status_read_only",
    "training_eligibility_status",
    "claim_safety_status",
    "blocked_actions",
)


@dataclass(frozen=True)
class OperatorAction:
    label: str
    kind: str  # "request" or "grant" — only "request" allowed on this surface
    visible: bool
    routes_to: str  # external workflow that actually grants


@dataclass(frozen=True)
class ProofOperatorCenterViewModel:
    workspace_identity_hash: str
    evidence_count: int
    source_mutation_authorized_now: bool
    training_eligible_now: bool
    verifier_status_text: str
    rollback_status_text: str
    operator_actions: tuple[OperatorAction, ...]
    blocked_actions_visible: bool
    blocked_actions_text: str
    programbench_provenance_read_only: bool
    programbench_status_text: str
    training_status_text: str
    claim_safety_status_text: str

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["operator_actions"] = [asdict(a) for a in self.operator_actions]
        return d


@dataclass(frozen=True)
class ProofOperatorCenterViewModelRecord:
    decision: str
    view_model: ProofOperatorCenterViewModel | None
    sections_present: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sections_present"] = list(self.sections_present)
        d["notes"] = list(self.notes)
        if self.view_model is not None:
            d["view_model"] = self.view_model.to_dict()
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_")


__all__ = [
    "PROOF_OPERATOR_CENTER_VIEWMODEL_STATUS_TOKENS",
    "PROOF_OPERATOR_CENTER_SECTIONS",
    "OperatorAction",
    "ProofOperatorCenterViewModel",
    "ProofOperatorCenterViewModelRecord",
]
