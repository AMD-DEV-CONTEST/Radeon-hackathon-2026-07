"""Immutable result record for SAFE_PATCH_DIFF_ROLLBACK_LOCK_001.

The record is the only output of ``SafePatchWorkspace.apply_and_verify``.
It is JSON-serializable, carries the unified diff and verifier status,
and explicitly records that the *original* source remained unchanged.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SAFE_PATCH_STATUS_TOKENS = (
    "PATCH_APPLIED_TO_TEMP_WORKSPACE",
    "PATCH_REJECTED",
    "PATCH_BLOCKED_PATH_ESCAPE",
    "PATCH_BLOCKED_SYMLINK_ESCAPE",
    "PATCH_BLOCKED_BINARY_CONTENT",
    "PATCH_VERIFIER_FAILED",
    "PATCH_VERIFIER_PASSED_TEMP_ONLY",
    "PATCH_VERIFIER_SKIPPED",
    "PATCH_ROLLED_BACK",
    "SOURCE_MUTATION_BLOCKED",
)


@dataclass(frozen=True)
class FilePatch:
    """A single file replacement.

    ``new_content`` must be UTF-8 decodable text. Binary patches are
    rejected with ``PATCH_BLOCKED_BINARY_CONTENT``.
    """

    path: str  # relative to workspace; no .., no absolute
    new_content: str


@dataclass(frozen=True)
class SafePatchResult:
    workspace: str
    temp_workspace: str
    status: str
    applied_patches: tuple[str, ...] = field(default_factory=tuple)
    rejected_patches: tuple[dict[str, str], ...] = field(default_factory=tuple)
    unified_diff: str = ""
    verifier_status: str = "PATCH_VERIFIER_SKIPPED"
    verifier_output: str = ""
    rolled_back: bool = False
    original_unchanged: bool = True
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["applied_patches"] = list(self.applied_patches)
        d["rejected_patches"] = [dict(r) for r in self.rejected_patches]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_blocked(self) -> bool:
        return self.status.startswith("PATCH_BLOCKED_") or self.status == "PATCH_REJECTED"

    @property
    def is_verifier_pass(self) -> bool:
        return self.verifier_status == "PATCH_VERIFIER_PASSED_TEMP_ONLY"

    @property
    def is_verifier_fail(self) -> bool:
        return self.verifier_status == "PATCH_VERIFIER_FAILED"
