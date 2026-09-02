"""Connector abstraction — every integration follows: read → preview → confirm → execute → rollback → audit."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ConnectorStatus(Enum):
    IDLE = auto()
    READING = auto()
    PREVIEW_READY = auto()
    CONFIRMED = auto()
    EXECUTING = auto()
    EXECUTED = auto()
    FAILED = auto()
    ROLLED_BACK = auto()


class ConfirmationRequired(Exception):
    """Raised when a human-confirmation gate is reached."""

    def __init__(self, diff_summary: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(diff_summary)
        self.diff_summary = diff_summary
        self.details = details or {}


@dataclass
class ConnectorResult:
    status: ConnectorStatus
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""


class BaseConnector(ABC):
    """Abstract connector with the mandatory six-step lifecycle."""

    def __init__(self, connector_id: str = "") -> None:
        self.connector_id: str = connector_id or self.__class__.__name__
        self._status: ConnectorStatus = ConnectorStatus.IDLE

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def read(self, **kwargs: Any) -> dict[str, Any]:
        """Read external state (e.g. fetch issues, list webhooks)."""

    @abstractmethod
    def preview_diff(self, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Preview the change that would be applied. Raises ConfirmationRequired or returns diff."""

    @abstractmethod
    def execute(self, data: dict[str, Any], confirmation_id: str, **kwargs: Any) -> ConnectorResult:
        """Apply the change after confirmation."""

    @abstractmethod
    def rollback(self, execution_context: dict[str, Any], **kwargs: Any) -> ConnectorResult:
        """Undo the last successful execute()."""

    @abstractmethod
    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit entries for this connector."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def status(self) -> ConnectorStatus:
        return self._status

    def _set_status(self, s: ConnectorStatus) -> None:
        self._status = s
