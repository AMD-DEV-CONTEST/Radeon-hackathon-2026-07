"""Records for DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_LOCK_001.

Read-only Claude-side binding to the Codex Universal 100 Matrix Probe
Execution Batch 001 evidence. Exposes a deterministic JSON-serializable
view-model the React Universal 100 Matrix Probe panel may display.

The panel DISPLAYS evidence; it does NOT grant authority. No field
implies source mutation, approval, proof-execution authority, training,
release readiness, production readiness, or universal app/language/
platform support.

Fixture-local executable proof is not production readiness. Promoted
cells are smoke / repair / maintain-supported scoped to the Codex
fixture demo workspace.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_PASSED",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_BLOCKED_CELLS_HIDDEN",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_RELEASE_OVERCLAIM",
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_FIXTURE_CAVEAT_MISSING",
)


# Forbidden broad-claim phrases. Detected outside of refusal-context
# fields (claim_boundary / forbidden_claims / blocked_path_demo /
# what_remains_forbidden / does_not_mean / fallbacks_enforced).
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all apps supported",
    "all languages supported",
    "all platforms supported",
    "any language",
    "any codebase",
    "arbitrary app generation",
    "production-ready",
    "production ready",
    "release ready: true",
    "release_ready: true",
    "source_mutation_authorized: true",
    "training_eligible: true",
    "training_rows_written: true",
    "approval_authority_granted: true",
    "proof_execution_authority_granted: true",
    "broad_claims_granted: true",
    "universal execution",
    "magic generation",
    "fully autonomous app creation",
    "universal app creation",
    "scale-to-100 lock active",
)


REQUIRED_FIXTURE_CAVEATS = (
    "fixture-local",
    "not release",
    "not universal",
)


@dataclass(frozen=True)
class ProbeCellRow:
    """One row in the Matrix Probe batch table."""

    cell_id: str
    claim_state: str
    support_state: str
    workflow: str
    language: str
    app_class: str
    promoted: bool
    blocked: bool
    blocker: str
    missing_rung: str
    caveat: str


@dataclass(frozen=True)
class Universal100MatrixProbeBatchStatus:
    """Render-safe view-model the React Universal 100 Matrix Probe panel consumes."""

    decision: str
    target_surface: str
    target_workflow: str
    batch_label: str
    batch_lock_id: str
    # Counts.
    cells_probed: int
    cells_promoted: int
    blocked_or_forbidden: int
    cells_partial_or_roadmap: int
    smoke_supported_count: int
    repair_supported_count: int
    maintain_supported_count: int
    release_supported_count: int
    build_supported_count: int
    test_supported_count: int
    scaffold_only_count: int
    roadmap_count: int
    unsupported_count: int
    missing_oracle_count: int
    missing_smoke_count: int
    missing_toolchain_count: int
    missing_adapter_count: int
    # Authority bag — always all-False on PASSED.
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
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
    # Cell tables.
    promoted_cells: tuple[ProbeCellRow, ...]
    blocked_cells: tuple[ProbeCellRow, ...]
    # Truthful claims and refusal lists.
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    blocked_path_summary: tuple[str, ...]
    strongest_truthful_new_claim: str
    # Evidence health (snapshot at probe-batch time).
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
    # Evidence references.
    source_evidence_paths: tuple[str, ...]
    machine_readable_paths: tuple[str, ...]
    evidence_ref: str
    # Required Codex captions surfaced verbatim.
    captions: tuple[str, ...]
    # Required caveats (must appear in claim_boundary or captions).
    fixture_caveats_present: tuple[str, ...]
    # Next rung.
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["promoted_cells"] = [asdict(c) for c in self.promoted_cells]
        d["blocked_cells"] = [asdict(c) for c in self.blocked_cells]
        for key in (
            "claim_boundary",
            "forbidden_claims",
            "blocked_path_summary",
            "source_evidence_paths",
            "machine_readable_paths",
            "captions",
            "fixture_caveats_present",
            "notes",
        ):
            d[key] = list(getattr(self, key))
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == ("REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_PASSED")

    @property
    def is_awaiting(self) -> bool:
        return self.decision == (
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_AWAITING_EVIDENCE"
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_"
        )


__all__ = [
    "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "REQUIRED_FIXTURE_CAVEATS",
    "ProbeCellRow",
    "Universal100MatrixProbeBatchStatus",
]
