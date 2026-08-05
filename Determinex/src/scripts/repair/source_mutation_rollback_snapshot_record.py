"""Records for SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS = (
    "ROLLBACK_SNAPSHOT_WRITTEN",
    "ROLLBACK_SNAPSHOT_BLOCKED_NO_APPROVAL",
    "ROLLBACK_SNAPSHOT_BLOCKED_SOURCE_HASH_MISMATCH",
    "ROLLBACK_SNAPSHOT_BLOCKED_NO_VERIFY",
    "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION",
    "ROLLBACK_SNAPSHOT_BLOCKED_SYMLINKS_UNSUPPORTED",
)


@dataclass(frozen=True)
class SourceMutationRollbackSnapshotRecord:
    decision: str
    workspace_identity: str
    pre_apply_source_hash: str
    snapshot_path: str
    snapshot_tree_hash: str
    diff_hash: str
    approval_ref: str
    verifier_ref: str
    source_mutation_applied: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "ROLLBACK_SNAPSHOT_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("ROLLBACK_SNAPSHOT_BLOCKED_")


__all__ = [
    "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS",
    "SourceMutationRollbackSnapshotRecord",
]
