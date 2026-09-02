"""Records for CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001.

The demo script is a backend-defined, declarative path the
operator/external reviewer can follow to see Determinex block source
mutation on every wrong condition and apply it ONLY when every
gate passes. The marketing phrase is 'Proof Before Mutation' —
the lock requires that phrase to appear in the demo copy.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PROOF_BEFORE_MUTATION_DEMO_STATUS_TOKENS = (
    "PROOF_BEFORE_MUTATION_DEMO_SCRIPT_WRITTEN",
    "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_PATH_INCLUDED",
    "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED",
    "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_AUTHORITY_AMBIGUITY",
    "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_BLOCKED_PATH",
    "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_PHRASE",
)


@dataclass(frozen=True)
class DemoStep:
    n: int  # 1-indexed step number
    title: str
    description: str
    is_blocked_step: bool = False  # True for blocked-path steps


@dataclass(frozen=True)
class ProofBeforeMutationDemoScriptRecord:
    decision: str
    happy_path_steps: tuple[DemoStep, ...]
    blocked_path_steps: tuple[DemoStep, ...]
    fixture_repo_path: str
    copy_phrase_present: bool
    network_required: bool
    docker_required: bool
    programbench_required: bool
    training_rows_written: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["happy_path_steps"] = [asdict(s) for s in self.happy_path_steps]
        d["blocked_path_steps"] = [asdict(s) for s in self.blocked_path_steps]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "PROOF_BEFORE_MUTATION_DEMO_SCRIPT_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("PROOF_BEFORE_MUTATION_DEMO_BLOCKED_")


__all__ = [
    "PROOF_BEFORE_MUTATION_DEMO_STATUS_TOKENS",
    "DemoStep",
    "ProofBeforeMutationDemoScriptRecord",
]
