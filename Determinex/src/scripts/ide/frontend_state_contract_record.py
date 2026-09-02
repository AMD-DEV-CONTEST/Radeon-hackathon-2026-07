"""Records for IDE_FRONTEND_STATE_CONTRACT_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_STATE_CONTRACT_STATUS_TOKENS = (
    "FRONTEND_STATE_CONTRACT_READY",
    "FRONTEND_STATE_BLOCKED_FIELDS_MISSING",
    "FRONTEND_STATE_RISK_WARNINGS_PRESENT",
    "FRONTEND_STATE_SOURCE_MUTATION_BLOCKED_VISIBLE",
)


REQUIRED_SECTIONS = (
    "workspace",
    "adapter",
    "verifier",
    "model_route",
    "diagnosis",
    "patch_plan",
    "temp_verifier",
    "human_approval",
    "source_apply",
    "corpus_eligibility",
    "evidence",
    "risk_warnings",
)


@dataclass(frozen=True)
class FrontendStateContractRecord:
    decision: str
    sections_present: tuple[str, ...]
    sections_missing: tuple[str, ...]
    risk_warnings: tuple[str, ...]
    source_mutation: str
    training_eligibility: str
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sections_present"] = list(self.sections_present)
        d["sections_missing"] = list(self.sections_missing)
        d["risk_warnings"] = list(self.risk_warnings)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
