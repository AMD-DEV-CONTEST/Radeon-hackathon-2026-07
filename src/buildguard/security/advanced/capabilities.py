"""Task-bound, expiring, scoped capability tokens."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ConfigDict, Field, field_validator

from buildguard.schemas.common import StrictSchema, new_id
from buildguard.security.advanced.trust_labels import (
    TRUSTED_CONTROL_LABELS,
    LabeledData,
)
from buildguard.utils.time import utc_now


class CapabilityToken(StrictSchema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(default_factory=new_id)
    task_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    root: Path
    operations: tuple[str, ...] = Field(min_length=1)
    resource_ids: tuple[str, ...] = ()
    expires_at: datetime
    max_uses: int = Field(ge=1, le=10_000)
    issued_by: str = Field(min_length=1, max_length=512)

    @field_validator("operations", "resource_ids")
    @classmethod
    def unique_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("capability scopes must not contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("capability scopes must be unique")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capability expires_at must be timezone-aware")
        return value


class CapabilityDecision(StrictSchema):
    allowed: bool
    reason: str = Field(min_length=1, max_length=2000)
    remaining_uses: int = Field(ge=0)


class CapabilityManager:
    """Issue trusted capabilities and consume their use count atomically."""

    def __init__(
        self,
        *,
        max_ttl_seconds: int = 86_400,
        default_max_uses: int = 1,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_ttl_seconds <= 0:
            raise ValueError("max_ttl_seconds must be positive")
        if default_max_uses <= 0:
            raise ValueError("default_max_uses must be positive")
        self.max_ttl_seconds = max_ttl_seconds
        self.default_max_uses = default_max_uses
        self.clock = clock
        self._tokens: dict[str, CapabilityToken] = {}
        self._uses: dict[str, int] = {}
        self._revoked: set[str] = set()
        self._lock = threading.RLock()

    def issue(
        self,
        *,
        task_id: str,
        tool_name: str,
        root: Path,
        operations: list[str],
        resource_ids: list[str],
        ttl_seconds: int,
        issued_by: LabeledData,
        max_uses: int | None = None,
    ) -> CapabilityToken:
        if issued_by.label not in TRUSTED_CONTROL_LABELS:
            raise PermissionError("Capabilities may only be issued by a trusted control source")
        if ttl_seconds <= 0 or ttl_seconds > self.max_ttl_seconds:
            raise ValueError(
                f"Capability TTL must be within 1..{self.max_ttl_seconds} seconds"
            )
        uses = max_uses if max_uses is not None else self.default_max_uses
        token = CapabilityToken(
            task_id=task_id,
            tool_name=tool_name,
            root=root.resolve(),
            operations=tuple(operations),
            resource_ids=tuple(resource_ids),
            expires_at=self.clock() + timedelta(seconds=ttl_seconds),
            max_uses=uses,
            issued_by=str(issued_by.value),
        )
        with self._lock:
            self._tokens[token.capability_id] = token
            self._uses[token.capability_id] = 0
        return token

    def revoke(self, capability_id: str) -> None:
        with self._lock:
            if capability_id not in self._tokens:
                raise KeyError(f"Unknown capability: {capability_id}")
            self._revoked.add(capability_id)

    @staticmethod
    def _path_allowed(root: Path, requested: Path) -> bool:
        target = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False
        return True

    def authorize(
        self,
        capability_id: str,
        *,
        task_id: str,
        tool_name: str,
        operation: str,
        paths: list[Path] | None = None,
        resource_ids: list[str] | None = None,
        consume: bool = False,
    ) -> CapabilityDecision:
        requested_paths = paths or []
        requested_resources = set(resource_ids or [])
        with self._lock:
            token = self._tokens.get(capability_id)
            if token is None:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability does not exist",
                    remaining_uses=0,
                )
            used = self._uses[capability_id]
            remaining = max(0, token.max_uses - used)
            if capability_id in self._revoked:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability is revoked",
                    remaining_uses=remaining,
                )
            if self.clock() >= token.expires_at:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability is expired",
                    remaining_uses=remaining,
                )
            if token.task_id != task_id:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability is scoped to another task",
                    remaining_uses=remaining,
                )
            if token.tool_name != tool_name:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability is scoped to another tool",
                    remaining_uses=remaining,
                )
            if operation not in token.operations:
                return CapabilityDecision(
                    allowed=False,
                    reason=f"Capability does not allow operation: {operation}",
                    remaining_uses=remaining,
                )
            if any(
                not self._path_allowed(token.root, requested)
                for requested in requested_paths
            ):
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability path is outside its root",
                    remaining_uses=remaining,
                )
            allowed_resources = set(token.resource_ids)
            if allowed_resources and not requested_resources:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability requires an explicit resource ID",
                    remaining_uses=remaining,
                )
            if not requested_resources.issubset(allowed_resources):
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability resource is outside its scope",
                    remaining_uses=remaining,
                )
            if used >= token.max_uses:
                return CapabilityDecision(
                    allowed=False,
                    reason="Capability maximum use count is exhausted",
                    remaining_uses=0,
                )
            if consume:
                used += 1
                self._uses[capability_id] = used
                remaining = token.max_uses - used
            return CapabilityDecision(
                allowed=True,
                reason="Capability scope validated",
                remaining_uses=remaining,
            )
