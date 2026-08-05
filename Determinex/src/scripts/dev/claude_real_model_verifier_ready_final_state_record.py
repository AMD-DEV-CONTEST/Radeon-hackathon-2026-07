"""Records for CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_TOKENS = (
    "CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_WRITTEN",
    "CANONICAL_MODEL_ID_READY",
    "MODEL_AVAILABLE_OR_BLOCKED_WITH_REASON",
    "MODEL_HEALTHCHECK_READY",
    "BUILD_ADAPTER_VERIFIER_READY",
    "REAL_MODEL_DIAGNOSE_READY_ADVISORY_ONLY",
    "REAL_PATCH_PLAN_QUARANTINE_READY",
    "TEMP_VERIFY_TRACE_READY_HUMAN_APPROVAL_REQUIRED",
    "REAL_APPROVAL_APPLY_READY_GATED",
    "POST_APPLY_VERIFIER_READY",
    "SOURCE_MUTATION_GATED_BY_REAL_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "SUBORDINATE_TO_CODEX_AUDIT_REPAIR",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class ClaudeRealModelVerifierReadyFinalState:
    generated_at: str
    canonical_model_id: str
    model_available: str
    model_healthcheck: str
    build_adapter_verifier: str
    real_model_diagnose: str
    real_patch_plan_quarantine: str
    temp_verify_trace: str
    real_approval_apply: str
    post_apply_verifier: str
    source_mutation: str
    training_eligibility: str
    next_unblocker: str
    subordinate_to_codex_audit_repair: bool = True
    upstream_locks_present: tuple[str, ...] = field(default_factory=tuple)
    upstream_locks_missing: tuple[str, ...] = field(default_factory=tuple)
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["upstream_locks_present"] = list(self.upstream_locks_present)
        d["upstream_locks_missing"] = list(self.upstream_locks_missing)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


__all__ = [
    "CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_TOKENS",
    "ClaudeRealModelVerifierReadyFinalState",
]
