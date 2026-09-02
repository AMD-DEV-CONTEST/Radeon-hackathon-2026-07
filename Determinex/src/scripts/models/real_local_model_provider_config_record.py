"""Records for REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_LOCAL_MODEL_PROVIDER_CONFIG_STATUS_TOKENS = (
    "REAL_LOCAL_MODEL_CONFIG_READY",
    "REAL_LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT",
    "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
    "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
    "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
    "REAL_LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
    "REAL_LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
    "REAL_LOCAL_MODEL_CONFIG_SAVE_NO_LIVE_CALL",
)


@dataclass(frozen=True)
class RealLocalModelProviderConfigRecord:
    """Persistent record produced by the real provider-config write path."""

    provider: str
    model_id: str
    digest: str
    capabilities: tuple[str, ...]
    task_classes_allowed: tuple[str, ...]
    dry_run_default: bool
    enabled: bool
    local_only: bool
    config_path: str
    decision: str
    live_model_called_on_save: bool = False
    network_provider_admitted: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["capabilities"] = list(self.capabilities)
        d["task_classes_allowed"] = list(self.task_classes_allowed)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_ready(self) -> bool:
        return self.decision in {
            "REAL_LOCAL_MODEL_CONFIG_READY",
            "REAL_LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT",
            "REAL_LOCAL_MODEL_CONFIG_SAVE_NO_LIVE_CALL",
        }

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_LOCAL_MODEL_CONFIG_BLOCKED_")


__all__ = [
    "REAL_LOCAL_MODEL_PROVIDER_CONFIG_STATUS_TOKENS",
    "RealLocalModelProviderConfigRecord",
]
