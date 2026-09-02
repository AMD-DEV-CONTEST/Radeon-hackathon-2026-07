"""Records for IDE_WORKSPACE_OPEN_FLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_WORKSPACE_OPEN_STATUS_TOKENS = (
    "WORKSPACE_OPEN_READY",
    "WORKSPACE_OPEN_BLOCKED_PATH_ESCAPE",
    "WORKSPACE_OPEN_BLOCKED_UNSUPPORTED_REPO",
    "WORKSPACE_OPEN_VERIFIER_AVAILABLE",
    "WORKSPACE_OPEN_VERIFIER_MISSING",
    "WORKSPACE_OPEN_SOURCE_UNCHANGED",
    "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY",
)


@dataclass(frozen=True)
class IDEWorkspaceOpenRecord:
    decision: str
    workspace: str
    adapter_name: str
    build_system_id: str
    test_framework_id: str
    verifier_state: str
    languages_detected: tuple[str, ...] = field(default_factory=tuple)
    source_unchanged: bool = True
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["languages_detected"] = list(self.languages_detected)
        d["statuses_seen"] = list(self.statuses_seen)
        d["evidence_refs"] = list(self.evidence_refs)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_ready(self) -> bool:
        return self.decision == "WORKSPACE_OPEN_READY"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("WORKSPACE_OPEN_BLOCKED_")
