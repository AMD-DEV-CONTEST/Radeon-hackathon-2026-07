"""Local permission and privacy controls for the emergency workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


class PermissionDenied(RuntimeError):
    """Raised when a role requests an action outside the local allowlist."""


# Secret-shaped patterns scanned in free text (review finding: key-based
# redaction alone misses tokens embedded in prose).
_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_-]?key|apikey|secret|token|password|passwd|pwd)\b\s*[=:]\s*\S+", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I),
    re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\b(?:sk|pk|ak)[-_][A-Za-z0-9]{16,}\b"),
)


def _redact_secrets(text: str) -> str:
    """Replace secret-shaped substrings in free text with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


@dataclass(frozen=True)
class PermissionPolicy:
    role: str = "analyst"
    local_only: bool = True

    _ROLE_ACTIONS = {
        "analyst": frozenset(
            {
                "validate_input",
                "assess_site",
                "retrieve_local_knowledge",
                "simulate_transport",
                "run_sensitivity",
                "read_memory",
                "write_memory",
                "generate_report",
            }
        ),
        "reviewer": frozenset(
            {"retrieve_local_knowledge", "read_memory", "generate_report"}
        ),
        "observer": frozenset({"retrieve_local_knowledge", "generate_report"}),
    }
    _NEVER_ALLOWED = frozenset(
        {"operational_control", "equipment_control", "issue_public_alert"}
    )
    _SENSITIVE_FIELDS = frozenset(
        {
            "operator_name",
            "operator_email",
            "contact_name",
            "contact_email",
            "exact_coordinates",
            "api_key",
            "token",
            "password",
        }
    )

    def __post_init__(self) -> None:
        if self.role not in self._ROLE_ACTIONS:
            raise ValueError(f"unknown role: {self.role}")

    @property
    def denied_actions(self) -> tuple[str, ...]:
        denied = set(self._NEVER_ALLOWED)
        if self.local_only:
            denied.add("external_network")
        return tuple(sorted(denied))

    def require(self, action: str) -> None:
        if action in self._NEVER_ALLOWED:
            raise PermissionDenied(f"action denied by safety policy: {action}")
        if action == "external_network" and self.local_only:
            raise PermissionDenied("action denied in local-only mode: external_network")
        if action not in self._ROLE_ACTIONS[self.role]:
            raise PermissionDenied(f"role {self.role} is not allowed to perform {action}")

    def redact_payload(self, payload: Any) -> Any:
        if isinstance(payload, Mapping):
            return {
                str(key): (
                    "[REDACTED]"
                    if str(key).lower() in self._SENSITIVE_FIELDS
                    else self.redact_payload(value)
                )
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self.redact_payload(value) for value in payload]
        if isinstance(payload, tuple):
            return tuple(self.redact_payload(value) for value in payload)
        if isinstance(payload, str):
            return _redact_secrets(payload)
        return payload
