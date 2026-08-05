"""Records for REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_STATUS_TOKENS = (
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_SOURCE_UNCHANGED",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NO_VERIFIER",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NOT_QUARANTINED",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_HARDENED_RUNNER",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_APPLY_REJECTED",
)


@dataclass(frozen=True)
class RealBuildAdapterTempVerifyTraceRecord:
    decision: str
    workspace: str
    temp_workspace: str
    build_system_id: str
    verifier_command: tuple[str, ...]
    verifier_exit_code: int
    verifier_stdout_preview: str
    verifier_stderr_preview: str
    verifier_timed_out: bool
    verifier_blocked: bool
    unified_diff: str
    applied_paths: tuple[str, ...]
    original_unchanged: bool
    original_sha256_before: str
    original_sha256_after: str
    human_approval_required: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["verifier_command"] = list(self.verifier_command)
        d["applied_paths"] = list(self.applied_paths)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED"

    @property
    def is_failed(self) -> bool:
        return self.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_")


__all__ = [
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_STATUS_TOKENS",
    "RealBuildAdapterTempVerifyTraceRecord",
]
