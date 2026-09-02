"""Records for DETERMINEX_REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

Read-only binding to the Codex Repo Clinic fixture-repair splash
demo evidence. Exposes a deterministic, JSON-serializable status
the React Repo Clinic panel may display.

Hard rules: the record may surface scoped per-fixture status,
target workflow / language, baseline-failed + repair-verified
booleans, claim boundary, blocked-path summary, evidence ref,
training False — and MUST NOT broaden that into all-codebases /
all-languages / arbitrary-production-repair / real-user-repo-
mutation-authorized / training-enabled / release-ready claims.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS = (
    "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_PASSED",
    "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
    "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
)


# Phrases that, if present in the rendered binding outside of the
# claim-scanner-input or blocked-path-demo subsections, indicate a
# forbidden broadening of the scoped demo claim. Surfacing any of
# these from the binding is a refusal.
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all codebases",
    "all languages",
    "any language",
    "arbitrary repair",
    "arbitrary production repair",
    "production-ready arbitrary",
    "real user repo mutation authorized",
    "training enabled",
    "source_mutation_authorized: true",
    "release_ready: true",
    "no-followup support",
)


@dataclass(frozen=True)
class RepoClinicVerifiedDemoStatus:
    """Render-safe view-model the React Repo Clinic panel consumes."""

    decision: str
    demo_title: str
    target_surface: str
    target_workflow: str
    target_language: str
    issue_summary: str
    baseline_failed: bool
    baseline_test_command: str
    repair_test_command: str
    repair_tests_passed: bool
    repair_verified: bool
    false_fixed_claim_blocked: bool
    fixture_mutation_only: bool
    real_user_source_mutation_authorized: bool
    affected_files: tuple[str, ...]
    evidence_ref: str
    patch_body_hash: str
    fixture_workspace: str
    claim_boundary: tuple[str, ...]
    blocked_path_summary: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
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
        return self.decision == "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_PASSED"

    @property
    def is_awaiting(self) -> bool:
        return self.decision == "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_")


__all__ = [
    "REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "RepoClinicVerifiedDemoStatus",
]
