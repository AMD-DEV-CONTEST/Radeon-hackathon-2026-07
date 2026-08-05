"""Records for OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OLLAMA_LOCAL_PROVIDER_SMOKE_STATUS_TOKENS = (
    "OLLAMA_PROVIDER_SMOKE_PASSED",
    "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
    "OLLAMA_PROVIDER_SMOKE_BLOCKED_UNAVAILABLE",
    "OLLAMA_PROVIDER_SMOKE_BLOCKED_TIMEOUT",
    "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED",
)


@dataclass(frozen=True)
class OllamaLocalProviderSmokeRecord:
    decision: str
    endpoint: str
    elapsed_ms: int
    output_trusted: bool = False
    network_provider_admitted: bool = False
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
        return self.decision == "OLLAMA_PROVIDER_SMOKE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("OLLAMA_PROVIDER_SMOKE_BLOCKED_")


__all__ = [
    "OLLAMA_LOCAL_PROVIDER_SMOKE_STATUS_TOKENS",
    "OllamaLocalProviderSmokeRecord",
]
