"""Records for OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OLLAMA_MODEL_PULL_OPERATOR_GUIDE_STATUS_TOKENS = (
    "OPERATOR_GUIDE_WRITTEN",
    "OPERATOR_GUIDE_NOT_NEEDED_MODEL_AVAILABLE",
    "OPERATOR_GUIDE_BLOCKED_NETWORK_PROVIDER",
    "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE",
    "OPERATOR_GUIDE_BLOCKED_STALE_ID",
    "OPERATOR_GUIDE_BLOCKED_UNPINNED",
)


@dataclass(frozen=True)
class OllamaModelPullOperatorGuideRecord:
    decision: str
    model_id: str
    provider: str
    expected_command: str
    safety_warning: str
    next_validation_command: str
    selection_decision: str
    selection_host_state: str
    network_provider_admitted: bool = False
    auto_pull_performed: bool = False
    training_eligibility_opened: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "OPERATOR_GUIDE_WRITTEN"

    @property
    def is_not_needed(self) -> bool:
        return self.decision == "OPERATOR_GUIDE_NOT_NEEDED_MODEL_AVAILABLE"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("OPERATOR_GUIDE_BLOCKED_")


__all__ = [
    "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_STATUS_TOKENS",
    "OllamaModelPullOperatorGuideRecord",
]
