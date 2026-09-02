"""Records for CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CANONICAL_LOCAL_MODEL_ID_SELECTION_STATUS_TOKENS = (
    "CANONICAL_LOCAL_MODEL_SELECTED",
    "CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
    "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID",
    "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
    "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE",
    "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
)


@dataclass(frozen=True)
class CanonicalLocalModelIdSelectionRecord:
    decision: str
    selected_model_id: str
    provider: str
    candidate_model_ids: tuple[str, ...]
    daemon_models_available: tuple[str, ...]
    host_state: str
    operator_action: str
    network_provider_admitted: bool = False
    live_model_called: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["candidate_model_ids"] = list(self.candidate_model_ids)
        d["daemon_models_available"] = list(self.daemon_models_available)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_selected(self) -> bool:
        return self.decision == "CANONICAL_LOCAL_MODEL_SELECTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("CANONICAL_LOCAL_MODEL_BLOCKED_")


__all__ = [
    "CANONICAL_LOCAL_MODEL_ID_SELECTION_STATUS_TOKENS",
    "CanonicalLocalModelIdSelectionRecord",
]
