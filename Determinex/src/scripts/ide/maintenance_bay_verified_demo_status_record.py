"""Records for DETERMINEX_REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

Read-only binding to the Codex Maintenance Bay dry-run/update
splash demo evidence. Exposes a deterministic, JSON-serializable
status the React Maintenance Bay panel may display.

Hard rules: the record may surface scoped per-fixture status,
target workflow / language, baseline-failed + compatibility-
verified + post_change-tests-passed booleans, claim boundary,
blocked-path summary, evidence ref, training False — and MUST
NOT broaden that into all-projects / all-languages / all-
codebases / arbitrary-maintenance / production-ready-maintenance
/ real-user-repo-mutation-authorized / training-enabled /
release-ready claims.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS = (
    "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_PASSED",
    "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
    "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
)


# Phrases that, if present in the rendered binding outside of the
# claim-scanner-input, blocked-path-demo, or claim-boundary
# subsections, indicate a forbidden broadening of the scoped demo
# claim. Surfacing any of these from the binding is a refusal.
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all projects",
    "all codebases",
    "all languages",
    "any language",
    "arbitrary maintenance",
    "production-ready arbitrary",
    "production-ready maintenance",
    "real user repo mutation authorized",
    "training enabled",
    "source_mutation_authorized: true",
    "release_ready: true",
    "release_deploy_workflow_created: true",
    "no-followup support",
)


@dataclass(frozen=True)
class MaintenanceBayVerifiedDemoStatus:
    """Render-safe view-model the React Maintenance Bay panel consumes."""

    decision: str
    demo_title: str
    target_surface: str
    target_workflow: str
    target_language: str
    target_stack: str
    maintenance_issue_summary: str
    change_type: str
    baseline_failed: bool
    baseline_test_command: str
    compatibility_verifier_command: str
    compatibility_verified: bool
    post_change_tests_passed: bool
    false_updated_claim_blocked: bool
    false_maintained_claim_blocked: bool
    unsafe_real_repo_mutation_blocked: bool
    unsupported_all_projects_claim_blocked: bool
    training_eligibility_without_positive_gate_blocked: bool
    release_deploy_readiness_claim_blocked: bool
    fixture_mutation_only: bool
    real_user_source_mutation_authorized: bool
    affected_files: tuple[str, ...]
    evidence_ref: str
    change_body_hash: str
    fixture_workspace: str
    compatibility_workspace: str
    source_repo_workspace: str
    claim_boundary: tuple[str, ...]
    blocked_path_summary: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    training_rows_written: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["affected_files"] = list(self.affected_files)
        d["claim_boundary"] = list(self.claim_boundary)
        d["blocked_path_summary"] = list(self.blocked_path_summary)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_PASSED"

    @property
    def is_awaiting(self) -> bool:
        return (
            self.decision == "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE"
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_"
        )


__all__ = [
    "MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "MaintenanceBayVerifiedDemoStatus",
]
