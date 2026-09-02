"""Immutable trace record for VERIFIED_REPAIR_TRACE_LOCK_001.

The trace is the canonical end-to-end shape proof for the Claude lane:

    intake
      → adapter detection
      → verifier baseline
      → route decisions (per task class)
      → mocked patch plan
      → temp patch application
      → verifier result
      → source-preservation check
      → evidence record (this dataclass)

Every field is JSON-serializable. ``training_eligible`` is False by
design — corpus eligibility lives behind a separate gate. The
``trace_id`` is a deterministic sha256 over the workspace path, the
canned-response kind, and the salt — so a test can pin it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERIFIED_REPAIR_TRACE_STATUS_TOKENS = (
    "VERIFIED_REPAIR_TRACE_WRITTEN",
    "TRACE_BLOCKED_UNSUPPORTED_REPO",
    "TRACE_BLOCKED_NO_VERIFIER",
    "TRACE_PATCH_FAILED",
    "TRACE_VERIFIER_FAILED",
    "TRACE_VERIFIER_PASSED_TEMP_ONLY",
    "TRACE_SOURCE_UNCHANGED_CONFIRMED",
    "TRAINING_ELIGIBLE_FALSE",
    "TRACE_BLOCKED_NO_ROUTE",
)


def derive_trace_id(workspace: str, salt: str, canned_kind: str) -> str:
    """Deterministic sha256 over the inputs that define this trace."""
    h = hashlib.sha256()
    for chunk in (workspace, "\x1f", salt, "\x1f", canned_kind):
        h.update(chunk.encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True)
class VerifiedRepairTrace:
    trace_id: str
    workspace: str
    adapter_name: str
    build_system_id: str
    verifier_baseline_status: str
    route_decisions: tuple[dict[str, object], ...] = field(default_factory=tuple)
    mocked_patch_plan: dict[str, object] = field(default_factory=dict)
    safe_patch_result: dict[str, object] = field(default_factory=dict)
    final_status: str = "VERIFIED_REPAIR_TRACE_WRITTEN"
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    source_unchanged_confirmed: bool = True
    training_eligible: bool = False
    corpus_eligibility: str = "BLOCKED_BY_DEFAULT"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["route_decisions"] = [dict(r) for r in self.route_decisions]
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def trace_fingerprint(self) -> str:
        """sha256 over the canonical JSON body — stable across runs that
        share the same inputs."""
        body = self.to_json(indent=None)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()
