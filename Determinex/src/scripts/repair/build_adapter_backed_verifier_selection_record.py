"""Records for BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_STATUS_TOKENS = (
    "BUILD_ADAPTER_VERIFIER_SELECTED",
    "BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
    "BUILD_ADAPTER_VERIFIER_BLOCKED_NO_TEST_COMMAND",
    "BUILD_ADAPTER_VERIFIER_BLOCKED_HARDENED_RUNNER",
    "BUILD_ADAPTER_VERIFIER_BLOCKED_WORKSPACE_MISSING",
)


@dataclass(frozen=True)
class BuildAdapterBackedVerifierSelectionRecord:
    decision: str
    workspace: str
    adapter_name: str
    build_system_id: str
    test_framework_id: str
    verifier_command: tuple[str, ...]
    hardened_runner: str
    multi_match: bool
    matched_adapters: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["verifier_command"] = list(self.verifier_command)
        d["matched_adapters"] = list(self.matched_adapters)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_selected(self) -> bool:
        return self.decision == "BUILD_ADAPTER_VERIFIER_SELECTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("BUILD_ADAPTER_VERIFIER_BLOCKED_")


__all__ = [
    "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_STATUS_TOKENS",
    "BuildAdapterBackedVerifierSelectionRecord",
]
