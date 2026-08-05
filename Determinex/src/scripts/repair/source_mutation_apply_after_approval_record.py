"""Records for SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS = (
    "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
    "SOURCE_MUTATION_BLOCKED_NO_APPROVAL",
    "SOURCE_MUTATION_BLOCKED_NO_ROLLBACK",
    "SOURCE_MUTATION_BLOCKED_SOURCE_HASH_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
    "SOURCE_MUTATION_BLOCKED_PLAN_BODY_MISSING",
    "SOURCE_MUTATION_BLOCKED_PATH_ESCAPE",
    "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH",
    "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_FIXTURE_APPROVAL",
    "SOURCE_MUTATION_BLOCKED_INVALID_SIGNATURE_KIND",
    "SOURCE_MUTATION_BLOCKED_SYMLINKS_UNSUPPORTED",
)


@dataclass(frozen=True)
class SourceMutationApplyAfterApprovalRecord:
    decision: str
    workspace_identity: str
    pre_apply_source_hash: str
    post_apply_source_hash: str
    applied_paths: tuple[str, ...]
    diff_hash: str
    approval_ref: str
    verifier_ref: str
    rollback_snapshot_ref: str
    source_mutation_applied: bool
    post_apply_verifier_required: bool
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["applied_paths"] = list(self.applied_paths)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_applied(self) -> bool:
        return self.decision == "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("SOURCE_MUTATION_BLOCKED_")


__all__ = [
    "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS",
    "SourceMutationApplyAfterApprovalRecord",
]
