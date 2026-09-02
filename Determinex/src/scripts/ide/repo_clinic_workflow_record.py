"""Records for DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REPO_CLINIC_WORKFLOW_STATUS_TOKENS = (
    "REPO_CLINIC_WORKFLOW_WRITTEN",
    "REPO_CLINIC_WORKFLOW_BLOCKED_VERIFIER_MISSING",
    "REPO_CLINIC_WORKFLOW_BLOCKED_FALSE_FIXED_LABEL",
    "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION",
)


REPO_CLINIC_STATES = (
    "REPO_OPENED",
    "REPO_ANALYZED",
    "TOOLCHAIN_MISSING",
    "VERIFIER_MISSING",
    "ISSUE_DIAGNOSED_UNVERIFIED",
    "PATCH_PROPOSED_QUARANTINED",
    "TEMP_VERIFIER_PASSED",
    "APPROVAL_REQUIRED",
    "SOURCE_MUTATION_AUTHORIZED",
    "SOURCE_MUTATION_APPLIED",
    "POST_APPLY_VERIFIER_PASSED",
    "REPAIR_VERIFIED",
    "REPAIR_FAILED_HONESTLY",
)


REPO_CLINIC_FLOW_STEPS = (
    "open_existing_repo",
    "workspace_toolchain_scan",
    "language_build_detection",
    "health_report",
    "issue_failure_intake",
    "verifier_discovery",
    "diagnosis",
    "patch_refactor_update_proposal",
    "quarantine",
    "temp_apply",
    "verifier_run",
    "approval_request",
    "source_mutation_after_approval_only",
    "post_apply_verifier",
    "rollback_if_failed",
    "evidence",
    "training_remains_blocked",
)


@dataclass(frozen=True)
class RepoClinicWorkflowRecord:
    decision: str
    flow_steps: tuple[str, ...]
    states: tuple[str, ...]
    fixed_label_enabled: bool
    verifier_command_present: bool
    temp_verifier_passed: bool
    approval_present: bool
    source_mutation_attempted: bool
    source_mutation_authorized_by_gate: bool
    post_apply_verifier_passed: bool
    diagnosis_treated_as_authorization: bool
    local_model_admission_treated_as_source_authorization: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["flow_steps"] = list(self.flow_steps)
        d["states"] = list(self.states)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "REPO_CLINIC_WORKFLOW_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REPO_CLINIC_WORKFLOW_BLOCKED_")


__all__ = [
    "REPO_CLINIC_WORKFLOW_STATUS_TOKENS",
    "REPO_CLINIC_STATES",
    "REPO_CLINIC_FLOW_STEPS",
    "RepoClinicWorkflowRecord",
]
