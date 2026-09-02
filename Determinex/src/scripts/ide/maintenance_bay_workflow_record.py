"""Records for DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

MAINTENANCE_BAY_WORKFLOW_STATUS_TOKENS = (
    "MAINTENANCE_BAY_WORKFLOW_WRITTEN",
    "MAINTENANCE_BAY_WORKFLOW_BLOCKED_FALSE_UPDATED_LABEL",
    "MAINTENANCE_BAY_WORKFLOW_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
    "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
)


MAINTENANCE_TYPES = (
    "dependency_update",
    "security_fix",
    "docs_update",
    "test_hardening",
    "refactor",
    "migration",
    "formatting_lint_cleanup",
    "performance_cleanup",
)


MAINTENANCE_STATES = (
    "MAINTENANCE_REQUESTED",
    "MAINTENANCE_PLAN_WRITTEN",
    "UPDATE_PROPOSED_QUARANTINED",
    "COMPATIBILITY_VERIFIER_REQUIRED",
    "UPDATE_VERIFIED",
    "UPDATE_BLOCKED_UNVERIFIED",
    "UPDATE_APPLIED_AFTER_APPROVAL",
    "UPDATE_FAILED_HONESTLY",
)


@dataclass(frozen=True)
class MaintenanceBayWorkflowRecord:
    decision: str
    maintenance_type: str
    states: tuple[str, ...]
    risk_visible: bool
    compatibility_verifier_present: bool
    compatibility_verifier_passed: bool
    advisory_status_caveated: bool
    approval_present: bool
    update_proposed_quarantined: bool
    update_applied_label_enabled: bool
    updated_label_enabled: bool
    post_apply_verifier_passed: bool
    rollback_plan_present: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["states"] = list(self.states)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "MAINTENANCE_BAY_WORKFLOW_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("MAINTENANCE_BAY_WORKFLOW_BLOCKED_")


__all__ = [
    "MAINTENANCE_BAY_WORKFLOW_STATUS_TOKENS",
    "MAINTENANCE_TYPES",
    "MAINTENANCE_STATES",
    "MaintenanceBayWorkflowRecord",
]
