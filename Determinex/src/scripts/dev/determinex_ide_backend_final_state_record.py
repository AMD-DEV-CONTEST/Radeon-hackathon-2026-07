"""Final backend apparatus state record.

Captures the campaign-end roll-up: which architecture hardening rungs
have landed, which apparatus pieces compose, and where the next
unblocker is. Purely descriptive; produced by reading lock-manifest
file presence under ``locks/sentinel/``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS = (
    "DETERMINEX_IDE_BACKEND_FINAL_STATE_WRITTEN",
    "EXECUTION_SURFACE_CLEAN",
    "MODEL_ROUTING_READY_DRY_RUN",
    "REPO_INTAKE_READY_FIXTURES",
    "VERIFIER_MATRIX_PARTIAL_BACKED",
    "MOCKED_REPAIR_LOOP_READY",
    "SAFE_PATCH_WORKSPACE_READY_TEMP_ONLY",
    "SOURCE_MUTATION_BLOCKED_PENDING_HUMAN_APPROVAL",
    "IDE_BACKEND_STATE_READY",
    "LIVE_MODEL_CALLS_NOT_ADMITTED",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class FinalBackendState:
    """The campaign-end backend apparatus snapshot."""

    generated_at: str
    execution_surface: str
    model_routing: str
    repo_intake: str
    verifier_matrix: str
    mocked_repair_loop: str
    safe_patch_workspace: str
    source_mutation: str
    ide_backend_state: str
    live_model_calls: str
    training_eligibility: str
    release_readiness: str
    next_unblocker: str
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
