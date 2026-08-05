"""Records for DETERMINEX_REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

Read-only binding to the Codex Learning Studio teaching splash
demo evidence. Exposes a deterministic, JSON-serializable status
the React Learning Studio panel may display.

Hard rules: the record may surface scoped per-fixture teaching
status, beginner / professional / failure explanations, why-the-
verifier-passed grounding, safe next steps, what-this-does-not-
prove, claim boundary, blocked-path summary, source evidence
paths, training False — and MUST NOT broaden that into all-
projects / all-languages / all-users / arbitrary-teaching /
production-ready / autonomous-repair / source-mutation-authorized
/ training-enabled / release-ready / approval-granted claims.

Teaching outputs are NON-AUTHORIZING by construction. Even when
the binding is PASSED, no UI element may imply mutation,
approval, training, or release authorization.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS = (
    "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_PASSED",
    "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
    "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
)


# Phrases that, if present in the rendered binding outside of the
# legitimately-quoting subsections (blocked_path_demo,
# claim_scanner_result, claim_boundary, source_evidence_summary,
# explanations text that the loader already validates), indicate
# a forbidden broadening of the scoped teaching claim.
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all projects",
    "all codebases",
    "all languages",
    "all users",
    "any language",
    "arbitrary teaching",
    "arbitrary maintenance",
    "arbitrary repair",
    "autonomous repair",
    "production-ready arbitrary",
    "production-ready",
    "real user repo mutation authorized",
    "source_mutation_authorized: true",
    "training enabled",
    "training_eligible: true",
    "release_ready: true",
    "release_deploy_workflow_created: true",
    "no-followup support",
)


@dataclass(frozen=True)
class LearningStudioVerifiedDemoStatus:
    """Render-safe view-model the React Learning Studio panel consumes."""

    decision: str
    demo_title: str
    target_surface: str
    target_workflow: str
    teaching_subject: str
    # Booleans from the evidence flow + verification subsection.
    beginner_explanation_written: bool
    pro_explanation_written: bool
    failure_explanation_written: bool
    safe_next_steps_written: bool
    what_this_does_not_prove_written: bool
    verifier_grounding_present: bool
    non_authorizing_teaching_only: bool
    # The explanation text snippets (so the UI can render them).
    beginner_explanation: str
    professional_explanation: str
    what_failed: str
    why_fix_or_update_worked: str
    safe_next_steps: str
    what_this_does_not_prove: str
    # Authority bag — always all-False on PASSED.
    source_mutation_authorized: bool
    approval_authority_granted: bool
    training_eligible: bool
    training_rows_written: bool
    release_ready: bool
    broad_claims_granted: bool
    real_user_source_mutation_authorized: bool
    # Source evidence and report references.
    source_evidence_paths: tuple[str, ...]
    final_report_path: str
    evidence_manifest_path: str
    evidence_ref: str
    # Per-surface source evidence summaries.
    repo_clinic_source_summary: dict
    maintenance_bay_source_summary: dict
    # Claim and blocked-path lists.
    claim_boundary: tuple[str, ...]
    blocked_path_summary: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["source_evidence_paths"] = list(self.source_evidence_paths)
        d["claim_boundary"] = list(self.claim_boundary)
        d["blocked_path_summary"] = list(self.blocked_path_summary)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_PASSED"

    @property
    def is_awaiting(self) -> bool:
        return (
            self.decision == "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE"
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_"
        )


__all__ = [
    "LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "LearningStudioVerifiedDemoStatus",
]
