"""Records for SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS = (
    "SOURCE_ROLLBACK_EXECUTED",
    "SOURCE_ROLLBACK_NOT_REQUIRED",
    "SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT",
    "SOURCE_ROLLBACK_BLOCKED_SNAPSHOT_HASH_MISMATCH",
    "SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED",
)


@dataclass(frozen=True)
class SourceMutationRollbackExecutionRecord:
    decision: str
    workspace_identity: str
    snapshot_path: str
    snapshot_verified_tree_hash: str
    pre_rollback_source_hash: str
    post_rollback_source_hash: str
    rollback_snapshot_ref: str
    apply_ref: str
    verifier_ref: str
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_executed(self) -> bool:
        return self.decision == "SOURCE_ROLLBACK_EXECUTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("SOURCE_ROLLBACK_BLOCKED_")


__all__ = [
    "SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS",
    "SourceMutationRollbackExecutionRecord",
]
