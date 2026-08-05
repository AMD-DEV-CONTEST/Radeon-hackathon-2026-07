"""Records for POST_APPLY_VERIFIER_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

POST_APPLY_VERIFIER_STATUS_TOKENS = (
    "POST_APPLY_VERIFIER_PASSED",
    "POST_APPLY_VERIFIER_FAILED",
    "POST_APPLY_ROLLBACK_RECOMMENDED",
    "POST_APPLY_VERIFIER_BLOCKED_NO_APPLY",
    "POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER",
    "POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH",
    "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED",
)


@dataclass(frozen=True)
class PostApplyVerifierRecord:
    decision: str
    workspace_identity: str
    verifier_status: str
    verifier_output: str
    post_apply_source_hash: str
    apply_ref: str
    rollback_snapshot_ref: str
    rollback_recommended: bool
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "POST_APPLY_VERIFIER_PASSED"

    @property
    def is_failed(self) -> bool:
        return self.decision == "POST_APPLY_VERIFIER_FAILED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("POST_APPLY_VERIFIER_BLOCKED_")


__all__ = [
    "POST_APPLY_VERIFIER_STATUS_TOKENS",
    "PostApplyVerifierRecord",
]
