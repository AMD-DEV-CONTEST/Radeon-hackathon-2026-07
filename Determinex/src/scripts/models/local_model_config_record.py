"""Records for LOCAL_MODEL_CONFIG_WIZARD_LOCK_001.

The config record is the persistent description of a local model the
user has configured. Writing the config never opens live calls;
``dry_run_default`` is True and ``enabled`` is False by default.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LOCAL_MODEL_CONFIG_STATUS_TOKENS = (
    "LOCAL_MODEL_CONFIG_WRITTEN",
    "LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
    "LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
    "LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
    "LOCAL_MODEL_CONFIG_BLOCKED_UNSUPPORTED_TASK_CLASS",
    "LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
    "LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
    "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY",
)


@dataclass(frozen=True)
class LocalModelConfigRecord:
    provider: str
    model_id: str
    model_digest_or_revision: str
    capabilities: tuple[str, ...]
    task_classes_allowed: tuple[str, ...]
    network_required: bool
    local_only: bool
    enabled: bool
    dry_run_default: bool
    created_at: str
    stale_after: str
    decision: str
    config_path: str = ""
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
    def is_written(self) -> bool:
        return self.decision == "LOCAL_MODEL_CONFIG_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LOCAL_MODEL_CONFIG_BLOCKED_")
