"""Records for LOCAL_PROVIDER_SMOKE_TEST_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LOCAL_PROVIDER_SMOKE_STATUS_TOKENS = (
    "LOCAL_PROVIDER_SMOKE_PASSED",
    "LOCAL_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
    "LOCAL_PROVIDER_SMOKE_BLOCKED_PROVIDER_UNAVAILABLE",
    "LOCAL_PROVIDER_SMOKE_BLOCKED_TIMEOUT",
    "LOCAL_PROVIDER_SMOKE_BLOCKED_NETWORK_PROVIDER",
    "LOCAL_PROVIDER_SMOKE_OUTPUT_UNTRUSTED",
    "LOCAL_PROVIDER_SMOKE_BLOCKED_MALFORMED_OUTPUT",
)


@dataclass(frozen=True)
class LocalProviderSmokeRecord:
    decision: str
    provider: str
    model_id: str
    config_path: str
    elapsed_ms: int = 0
    response_chars: int = 0
    output_trusted: bool = False
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
        return self.decision == "LOCAL_PROVIDER_SMOKE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LOCAL_PROVIDER_SMOKE_BLOCKED_")
