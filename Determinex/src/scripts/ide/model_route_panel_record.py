"""Records for IDE_MODEL_ROUTE_PANEL_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS = (
    "MODEL_ROUTE_PANEL_READY",
    "MODEL_ROUTE_DRY_RUN_DEFAULT",
    "MODEL_ROUTE_LIVE_OPT_IN_AVAILABLE",
    "MODEL_ROUTE_BLOCKED_NO_MODEL",
    "MODEL_ROUTE_BLOCKED_STALE_MODEL",
    "MODEL_ROUTE_BLOCKED_NETWORK_PROVIDER",
)


@dataclass(frozen=True)
class IDEModelRoutePanelRecord:
    decision: str
    task_class: str
    selected_route: str
    selected_model_id: str
    fallback_chain: tuple[str, ...]
    dry_run_default: bool
    live_opt_in_available: bool
    live_call_authorized: bool
    config_state: str
    provider_smoke_state: str
    block_reason: str = ""
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["fallback_chain"] = list(self.fallback_chain)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
