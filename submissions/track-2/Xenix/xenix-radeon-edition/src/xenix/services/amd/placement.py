"""Private placement-neutral values for AMD execution sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit


class AmdPlacementError(RuntimeError):
    """A placement/session cannot safely realize the requested runtime."""

    error_code = "amd_placement_failed"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code or type(self).error_code


class AmdMaterializationCancelledError(AmdPlacementError):
    """A committed retirement revoked an in-flight materialization."""

    error_code = "amd_materialization_cancelled"


@dataclass(frozen=True, slots=True)
class AmdRuntimeKey:
    """Exact runtime lookup identity; no capability domain imports this type."""

    installation_id: str
    component_generation_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.installation_id, "Installation ID")
        _require_identifier(self.component_generation_id, "Component generation ID")


@dataclass(frozen=True, slots=True)
class RuntimeIncarnation:
    """Controller ownership fence for one volatile service realization."""

    controller_owner_id: str
    incarnation_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.controller_owner_id, "Controller owner ID")
        _require_identifier(self.incarnation_id, "Runtime incarnation ID")


@dataclass(frozen=True, slots=True)
class LoopbackHttpBinding:
    """Volatile authenticated HTTP binding; never persist or log this object."""

    base_url: str = field(repr=False)
    bearer_token: str = field(repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise AmdPlacementError("Runtime binding is invalid.")
        if parsed.hostname not in {"127.0.0.1", "::1"} or parsed.query or parsed.fragment:
            raise AmdPlacementError("Runtime binding must use a loopback listener.")
        if parsed.port is None or not 1 <= parsed.port <= 65_535:
            raise AmdPlacementError("Runtime binding port is invalid.")
        if not isinstance(self.bearer_token, str) or len(self.bearer_token) < 24:
            raise AmdPlacementError("Runtime binding authentication is invalid.")
        if "\r" in self.bearer_token or "\n" in self.bearer_token:
            raise AmdPlacementError("Runtime binding authentication is invalid.")

    def authorization_header(self) -> str:
        return f"Bearer {self.bearer_token}"


class AmdExecutionSession(Protocol):
    """A placement-owned live realization, used only by the AMD slice."""

    @property
    def incarnation(self) -> RuntimeIncarnation: ...

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding: ...

    def close(self) -> None: ...


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or value != value.strip()
        or any(character.isspace() or ord(character) < 0x21 for character in value)
    ):
        raise AmdPlacementError(f"{label} is invalid.")


__all__ = [
    "AmdExecutionSession",
    "AmdMaterializationCancelledError",
    "AmdPlacementError",
    "AmdRuntimeKey",
    "LoopbackHttpBinding",
    "RuntimeIncarnation",
]
