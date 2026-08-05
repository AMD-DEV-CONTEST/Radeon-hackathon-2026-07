"""Records for CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001.

Rung 9 (finale) of the campaign. The dataclass captures the
campaign's terminal state across every authority-leak dimension
the Claude Opus 4.8 merge-audit dump raised. It is the single
record an operator (or cross-lane boundary check) can inspect to
decide ``safe_to_run_cross_lane_boundary``.

This module records — it does not mutate. The boolean dimensions
are computed by ``claude_authority_leak_remediation_final_state``
by inspecting the eight prior rungs' lock manifests and evidence
artifacts on disk. The finale never re-runs the underlying gates;
it asserts the locks are in place.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_STATUS_TOKENS = (
    "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_PASSED",
    "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_BLOCKED_MISSING_RUNG",
    "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED",
)


@dataclass(frozen=True)
class ClaudeAuthorityLeakRemediationFinalStateRecord:
    decision: str
    # Per-dimension closure. Each is True iff its rung's lock
    # manifest and evidence artifact are present AND the lock's
    # scope_discipline keys assert the safety invariant.
    diff_body_binding_closed: bool
    fixture_refusal_closed: bool
    post_apply_verifier_default_pass_closed: bool
    model_admission_bypass_closed: bool
    tauri_command_alignment_closed: bool
    diagnose_prompt_opacity_closed: bool
    approval_signature_binding_closed: bool
    rollback_symlink_semantics_closed: bool
    # Aggregate invariants. Both must remain False even after the
    # campaign — neither the campaign nor any of its rungs may
    # authorize source mutation or open training eligibility.
    source_mutation_authorized: bool
    training_eligible: bool
    # The umbrella claim. Computed from the per-dimension flags
    # plus the aggregate-invariant negatives.
    safe_for_cross_lane_boundary: bool
    # Audit findings remediated by this campaign and finding ids
    # explicitly deferred to a future campaign.
    findings_remediated: tuple[str, ...] = field(default_factory=tuple)
    findings_deferred: tuple[str, ...] = field(default_factory=tuple)
    rungs_inspected: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["findings_remediated"] = list(self.findings_remediated)
        d["findings_deferred"] = list(self.findings_deferred)
        d["rungs_inspected"] = list(self.rungs_inspected)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_BLOCKED_")


__all__ = [
    "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_STATUS_TOKENS",
    "ClaudeAuthorityLeakRemediationFinalStateRecord",
]
