"""Records for REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_LOCAL_MODEL_HEALTHCHECK_STATUS_TOKENS = (
    "REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
    "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_MODEL_NOT_PULLED",
    "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT",
    "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE",
    "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_NOT_SELECTED",
    "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_ERROR",
    "REAL_LOCAL_MODEL_HEALTHCHECK_OUTPUT_UNTRUSTED",
)


@dataclass(frozen=True)
class RealLocalModelHealthcheckRecord:
    decision: str
    model_id: str
    provider: str
    endpoint: str
    prompt: str
    response_chars: int
    elapsed_ms: int
    output_trusted: bool = False
    network_provider_admitted: bool = False
    patch_generated: bool = False
    repo_source_inputted: bool = False
    training_eligible: bool = False
    source_mutation_authorized: bool = False
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
        return self.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_")


__all__ = [
    "REAL_LOCAL_MODEL_HEALTHCHECK_STATUS_TOKENS",
    "RealLocalModelHealthcheckRecord",
]
