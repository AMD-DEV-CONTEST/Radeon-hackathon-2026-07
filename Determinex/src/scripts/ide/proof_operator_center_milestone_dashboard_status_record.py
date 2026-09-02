"""Records for DETERMINEX_REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_LOCK_001.

Read-only binding to the Codex Proof / Operator Center milestone
dashboard evidence. Exposes a deterministic, JSON-serializable
view-model the React Proof / Operator Center panel may display.

The dashboard DISPLAYS authority; it does not GRANT authority. Even
when PASSED, no field implies source mutation, approval,
proof-execution authority, training, or release readiness.
Roadmap items (Cathedral Index, Columbia House Tracker, Scale-to-
100, Full Cathedral roadmap, Windows-first support matrix, public
claims ledger, release scrub, fresh install / demo workflow) are
not converted into product truth.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_STATUS_TOKENS = (
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_PASSED",
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_AWAITING_EVIDENCE",
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
)


# Phrases that, if present in the rendered binding outside of the
# legitimately-quoting subsections (blocked_path_demo,
# claim_boundary, claim_boundary_status.forbidden_claims,
# surface_statuses, source_evidence_paths, source_audit_paths),
# indicate a forbidden broadening of the scoped dashboard claim.
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all apps",
    "all codebases",
    "all languages",
    "all platforms",
    "any language",
    "any codebase",
    "arbitrary app generation",
    "arbitrary repair",
    "arbitrary maintenance",
    "autonomous repair",
    "fully autonomous maintenance",
    "production-ready arbitrary",
    "production-ready",
    "release ready: true",
    "release_ready: true",
    "release_deploy_workflow_created: true",
    "source_mutation_authorized: true",
    "training_eligible: true",
    "training_rows_written: true",
    "approval_authority_granted: true",
    "proof_execution_authority_granted: true",
    "broad_claims_granted: true",
    "columbia house tracker: built",
    "columbia house tracker: verified",
    "scale-to-100 lock active",
    "scale-to-100 is the current c&t lock",
    "full cathedral roadmap validated",
    "verified room means universal support",
)


@dataclass(frozen=True)
class SurfaceStatus:
    """One row in the five-room dashboard."""

    surface: str
    verified: bool
    react_bound: bool
    splash_status: str
    binding_status: str
    claim: str
    evidence_paths: tuple[str, ...]


@dataclass(frozen=True)
class ProofOperatorCenterMilestoneDashboardStatus:
    """Render-safe view-model the React Proof / Operator Center
    milestone dashboard consumes."""

    decision: str
    target_surface: str
    target_workflow: str
    dashboard_title: str
    # Authority bag — always all-False on PASSED.
    source_mutation_authorized: bool
    approval_authority_granted: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    training_rows_written: bool
    release_ready: bool
    broad_claims_granted: bool
    artifact_import_authorized: bool
    benchmark_execution_authorized: bool
    programbench_execution_authorized: bool
    release_deploy_workflow_created: bool
    # Five rooms.
    surfaces: tuple[SurfaceStatus, ...]
    # Release-gate status (every field is a string label).
    cathedral_index_status: str
    columbia_house_tracker_status: str
    public_claims_ledger_status: str
    release_repo_scrub_status: str
    fresh_install_demo_workflow_status: str
    windows_first_support_matrix_status: str
    release_ready_label: str
    # Scale-to-100 status.
    scale_to_100_claim_truth_status: str
    scale_to_100_normalized_as_current_ct_lock: bool
    scale_to_100_scaling_plan_exists: bool
    scale_to_100_corpus_training_reconciliation_lock: str
    scale_to_100_platform_language_appclass_expansion_queue: str
    scale_to_100_windows_first_matrix_lock: str
    scale_to_100_legacy_enterprise: str
    scale_to_100_audit_path: str
    # Evidence health.
    evidence_index_count: int
    evidence_index_entry_count_field: int
    evidence_index_valid: bool
    append_only_ledger_status: str
    append_only_ledger_chain_valid: bool
    append_only_ledger_entry_count: int
    count_drift_status: str
    count_drift_expected: int
    count_drift_actual: int
    json_parse_status: str
    # Claim-boundary lists.
    claim_boundary: tuple[str, ...]
    blocked_path_summary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    implemented_narrow_rooms: tuple[str, ...]
    implemented_with_caveats: tuple[str, ...]
    roadmap_items: tuple[str, ...]
    # Evidence references.
    source_evidence_paths: tuple[str, ...]
    source_audit_paths: tuple[str, ...]
    dashboard_report_path: str
    machine_readable_dashboard_path: str
    evidence_ref: str
    # Next rung.
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["surfaces"] = [asdict(s) for s in self.surfaces]
        for surface_dict in d["surfaces"]:
            surface_dict["evidence_paths"] = list(surface_dict["evidence_paths"])
        d["claim_boundary"] = list(self.claim_boundary)
        d["blocked_path_summary"] = list(self.blocked_path_summary)
        d["forbidden_claims"] = list(self.forbidden_claims)
        d["implemented_narrow_rooms"] = list(self.implemented_narrow_rooms)
        d["implemented_with_caveats"] = list(self.implemented_with_caveats)
        d["roadmap_items"] = list(self.roadmap_items)
        d["source_evidence_paths"] = list(self.source_evidence_paths)
        d["source_audit_paths"] = list(self.source_audit_paths)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == ("REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_PASSED")

    @property
    def is_awaiting(self) -> bool:
        return self.decision == (
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_AWAITING_EVIDENCE"
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_"
        )


__all__ = [
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "SurfaceStatus",
    "ProofOperatorCenterMilestoneDashboardStatus",
]
