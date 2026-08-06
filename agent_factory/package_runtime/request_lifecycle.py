from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS = 300
DEFAULT_RUNTIME_REQUEST_HEARTBEAT_SECONDS = 10
DEFAULT_RUNTIME_REQUEST_MAX_RETRIES = 5


@dataclass(frozen=True, slots=True)
class RuntimeRequestPolicy:
    timeout_seconds: int = DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS
    heartbeat_seconds: int = DEFAULT_RUNTIME_REQUEST_HEARTBEAT_SECONDS
    max_retries: int = DEFAULT_RUNTIME_REQUEST_MAX_RETRIES

    @classmethod
    def from_env(cls) -> "RuntimeRequestPolicy":
        return cls(
            timeout_seconds=_env_int(
                "AGENTFACTORY_AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS",
                DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS,
            ),
            heartbeat_seconds=_env_int(
                "AGENTFACTORY_AGENT_RUNTIME_HEARTBEAT_SECONDS",
                DEFAULT_RUNTIME_REQUEST_HEARTBEAT_SECONDS,
            ),
            max_retries=_env_int(
                "AGENTFACTORY_AGENT_RUNTIME_MAX_RETRIES",
                DEFAULT_RUNTIME_REQUEST_MAX_RETRIES,
            ),
        )

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        default: "RuntimeRequestPolicy | None" = None,
    ) -> "RuntimeRequestPolicy":
        baseline = default or cls.from_env()
        if not isinstance(payload, dict):
            return baseline
        return cls(
            timeout_seconds=_positive_int(
                payload.get("timeout_seconds"),
                baseline.timeout_seconds,
            ),
            heartbeat_seconds=_positive_int(
                payload.get("heartbeat_seconds"),
                baseline.heartbeat_seconds,
            ),
            max_retries=_positive_int(
                payload.get("max_retries"),
                baseline.max_retries,
            ),
        )

    def as_payload(self) -> dict[str, int]:
        return {
            "timeout_seconds": max(0, int(self.timeout_seconds)),
            "heartbeat_seconds": max(0, int(self.heartbeat_seconds)),
            "max_retries": max(0, int(self.max_retries)),
        }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return _positive_int(value, default)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
