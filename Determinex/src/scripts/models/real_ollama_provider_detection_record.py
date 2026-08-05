"""Records for REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_OLLAMA_PROVIDER_DETECTION_STATUS_TOKENS = (
    "REAL_OLLAMA_PROVIDER_DETECTED",
    "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_INSTALLED",
    "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
    "REAL_OLLAMA_PROVIDER_BLOCKED_TIMEOUT",
    "REAL_OLLAMA_PROVIDER_BLOCKED_NETWORK_PROVIDER",
)


@dataclass(frozen=True)
class RealOllamaProviderDetectionRecord:
    decision: str
    endpoint: str
    elapsed_ms: int
    models: tuple[str, ...] = field(default_factory=tuple)
    network_provider_admitted: bool = False
    live_inference_called: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["models"] = list(self.models)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_detected(self) -> bool:
        return self.decision == "REAL_OLLAMA_PROVIDER_DETECTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_OLLAMA_PROVIDER_BLOCKED_")


__all__ = [
    "REAL_OLLAMA_PROVIDER_DETECTION_STATUS_TOKENS",
    "RealOllamaProviderDetectionRecord",
]
