"""Expiring user confirmation requests."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

from buildguard.logging_system.jsonl_writer import redact
from buildguard.tools.schemas import ConfirmationRequest
from buildguard.utils.time import utc_now


class ConfirmationManager:
    def __init__(self, ttl_seconds: int = 300) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Confirmation TTL must be positive")
        self.ttl_seconds = ttl_seconds
        self._requests: dict[str, ConfirmationRequest] = {}
        self._lock = threading.RLock()

    def create(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        access_paths: list[Path],
        risk_description: str,
    ) -> ConfirmationRequest:
        request = ConfirmationRequest(
            tool_name=tool_name,
            parameter_summary=redact(arguments),
            access_paths=[path.resolve() for path in access_paths],
            risk_description=risk_description,
            expires_at=utc_now() + timedelta(seconds=self.ttl_seconds),
        )
        with self._lock:
            self._requests[request.id] = request
        return request

    def decide(self, confirmation_id: str, approved: bool) -> ConfirmationRequest:
        with self._lock:
            request = self.get(confirmation_id)
            if request.status != "pending":
                raise ValueError(f"Confirmation is already {request.status}")
            request.status = "approved" if approved else "denied"
            return request

    def get(self, confirmation_id: str) -> ConfirmationRequest:
        with self._lock:
            if confirmation_id not in self._requests:
                raise KeyError(f"Confirmation not found: {confirmation_id}")
            request = self._requests[confirmation_id]
            if request.status == "pending" and utc_now() >= request.expires_at:
                request.status = "expired"
            return request
