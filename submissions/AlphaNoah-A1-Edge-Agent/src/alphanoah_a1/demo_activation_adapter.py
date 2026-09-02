"""Safe JSON projection for the bounded F03-C demo activation flow."""

from __future__ import annotations

import re
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from .demo_activation import (
    DEMO_ASSET_ID,
    DEMO_LOCATION,
    DEMO_SOURCE,
    DemoActivationApplication,
    DemoActivationFailure,
    DemoActivationSnapshot,
)
from .exceptions import AnalysisProviderError, ObjectNotFoundError
from .golden_path import SCENARIO_EVENT_TYPE, SCENARIO_ID
from .models import AuditRecord, DecisionStatus, EventStatus
from .web_adapter import WebAdapterError, WebErrorCode

PROJECTION_VERSION = "f03c-demo-v1"
_REQUEST_FIELDS = frozenset(
    {"scenario_id", "description", "request_id"}
)
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EVENT_ID = re.compile(r"event_[a-f0-9]{32}\Z")
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}\Z")
_SECRET_REQUEST_ID = re.compile(
    r"(?i)(?:^sk-|^gho_|^github_pat_|api[_-]?key|password|secret|token)"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:[\\/]")
_UNIX_LOCAL_PATH = re.compile(
    r"(?:^|[\s\"'])/(?:home|Users|tmp|var|etc|opt)/"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|password)"
    r"\s*[:=]\s*\S+"
)
_TOKEN_SHAPE = re.compile(r"\b(?:gho_|sk-)[A-Za-z0-9_-]{8,}")


class DemoActivationWebError(WebAdapterError):
    """A controlled Web error that may retain a persisted Event ID."""

    def __init__(
        self,
        code: WebErrorCode,
        message: str,
        status: HTTPStatus,
        *,
        event_id: str | None = None,
    ):
        super().__init__(code, message, status)
        self.event_id = event_id

    def to_dict(self) -> dict[str, str]:
        result = super().to_dict()
        if self.event_id is not None:
            result["event_id"] = self.event_id
        return result


class DemoActivationWebAdapter:
    """Validate demo commands and expose only bounded Runtime facts."""

    def __init__(self, application: DemoActivationApplication):
        if not isinstance(application, DemoActivationApplication):
            raise TypeError(
                "application must be DemoActivationApplication"
            )
        self.application = application

    def create_event(self, payload: object) -> dict[str, Any]:
        values = self._request_payload(payload)
        try:
            activated = self.application.activate(
                description=values["description"],
                request_id=values["request_id"],
            )
        except DemoActivationFailure as exc:
            cause = exc.__cause__
            if (
                isinstance(cause, AnalysisProviderError)
                and cause.failure_type == "transport"
            ):
                raise DemoActivationWebError(
                    WebErrorCode.PROVIDER_UNAVAILABLE,
                    "The configured Analysis Provider is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    event_id=exc.event_id,
                ) from exc
            raise DemoActivationWebError(
                WebErrorCode.ANALYSIS_FAILED,
                "Demo activation did not produce a complete analysis.",
                HTTPStatus.UNPROCESSABLE_ENTITY,
                event_id=exc.event_id,
            ) from exc
        return self._projection(
            self.application.get_snapshot(activated.event_id),
            replayed=activated.replayed,
        )

    def get_event(self, event_id: str) -> dict[str, Any]:
        self._validate_event_id(event_id)
        try:
            snapshot = self.application.get_snapshot(event_id)
        except ObjectNotFoundError as exc:
            raise DemoActivationWebError(
                WebErrorCode.EVENT_NOT_FOUND,
                "Demo activation Event does not exist.",
                HTTPStatus.NOT_FOUND,
            ) from exc
        return self._projection(snapshot, replayed=False)

    @classmethod
    def _request_payload(cls, payload: object) -> dict[str, str]:
        if not isinstance(payload, Mapping):
            cls._invalid("Request body must be a JSON object.")
        if set(payload) != _REQUEST_FIELDS:
            cls._invalid(
                "Request body fields do not match the endpoint contract."
            )
        values: dict[str, str] = {}
        limits = {
            "scenario_id": len(SCENARIO_ID),
            "description": 2_000,
            "request_id": 128,
        }
        for field in _REQUEST_FIELDS:
            value = payload[field]
            if (
                not isinstance(value, str)
                or value != value.strip()
                or not value
                or len(value) > limits[field]
                or "\x00" in value
                or any(ord(character) < 32 for character in value)
            ):
                cls._invalid(f"{field} is invalid.")
            values[field] = value
        if values["scenario_id"] != SCENARIO_ID:
            cls._invalid("scenario_id is not supported.")
        request_id = values["request_id"]
        if (
            _REQUEST_ID.fullmatch(request_id) is None
            or _SECRET_REQUEST_ID.search(request_id) is not None
        ):
            cls._invalid("request_id is invalid.")
        return values

    @classmethod
    def _projection(
        cls,
        snapshot: DemoActivationSnapshot,
        *,
        replayed: bool,
    ) -> dict[str, Any]:
        event = snapshot.event
        decision = snapshot.decision
        notification = snapshot.notification
        unknown_fields: list[str] = []
        warnings: list[str] = []

        if decision is None:
            unknown_fields.extend(("analysis", "human_review"))
        if notification is None:
            unknown_fields.append("notification")
        if snapshot.decision_count > 1:
            warnings.append("multiple_decisions")
        if snapshot.notification_count > 1:
            warnings.append("multiple_notifications")
        if snapshot.task_count:
            warnings.append("task_exists_after_activation_boundary")
        if event.status is not EventStatus.PENDING_HUMAN_REVIEW:
            warnings.append("event_not_pending_human_review")

        knowledge_sources = cls._knowledge_sources(snapshot.audits)
        if decision is not None and not knowledge_sources:
            unknown_fields.append("analysis.knowledge_sources")

        availability = (
            "available"
            if not unknown_fields and not warnings
            else "partial"
        )
        return {
            "projection_version": PROJECTION_VERSION,
            "replayed": replayed,
            "event": {
                "event_id": event.event_id,
                "event_type": SCENARIO_EVENT_TYPE,
                "source": DEMO_SOURCE,
                "timestamp": event.timestamp,
                "status": event.status.value,
                "severity": event.severity,
                "asset_id": DEMO_ASSET_ID,
                "location": DEMO_LOCATION,
                "description": cls._public_text(event.description),
            },
            "responsibility": {
                "owner_id": snapshot.responsibility.owner_id,
                "owner_name": cls._public_text(
                    snapshot.responsibility.owner_name
                ),
                "match_type": snapshot.responsibility.match_type,
                "matched_key": snapshot.responsibility.matched_key,
            },
            "analysis": (
                {
                    "detected_issue": cls._public_text(
                        event.detected_issue
                    ),
                    "reasoning_summary": cls._public_text(
                        decision.reasoning_summary
                    ),
                    "confidence": decision.confidence,
                    "requires_human_review": (
                        decision.requires_human_review
                    ),
                    "knowledge_sources": knowledge_sources,
                }
                if decision is not None
                else None
            ),
            "notification": (
                {
                    "notification_id": notification.notification_id,
                    "status": notification.status.value,
                    "created_at": notification.created_at,
                }
                if notification is not None
                else None
            ),
            "human_review": (
                {
                    "decision_id": decision.decision_id,
                    "status": decision.status.value,
                    "required": decision.requires_human_review,
                    "allowed_actions": (
                        ["approve", "reject"]
                        if (
                            decision.requires_human_review
                            and decision.status
                            is DecisionStatus.PENDING_HUMAN_REVIEW
                        )
                        else []
                    ),
                }
                if decision is not None
                else None
            ),
            "work_records": cls._work_records(snapshot.audits, event.event_id),
            "quality": {
                "availability": availability,
                "unknown_fields": sorted(set(unknown_fields)),
                "contract_warnings": sorted(set(warnings)),
            },
        }

    @classmethod
    def _knowledge_sources(
        cls,
        audits: tuple[AuditRecord, ...],
    ) -> list[str]:
        sources: list[str] = []
        for record in audits:
            metadata = record.details.get("model_metadata")
            if not isinstance(metadata, Mapping):
                continue
            values = metadata.get("knowledge_sources")
            if not isinstance(values, list):
                continue
            for value in values:
                if (
                    isinstance(value, str)
                    and _SAFE_REFERENCE.fullmatch(value) is not None
                    and not value.startswith(("/", "\\", "file:"))
                    and _WINDOWS_ABSOLUTE_PATH.search(value) is None
                    and value not in sources
                ):
                    sources.append(value)
        return sources

    @classmethod
    def _work_records(
        cls,
        audits: tuple[AuditRecord, ...],
        event_id: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        mappings = {
            "event_created": (
                "event_received",
                "Site event received",
            ),
            "decision_created": (
                "knowledge_lookup",
                "Knowledge context evaluated",
            ),
            "event_analyzed": (
                "analysis",
                "Agent analysis completed",
            ),
            "request_human_review": (
                "human_review",
                "Human review requested",
            ),
            "notification_created": (
                "responsibility_matched",
                "Equipment maintenance responsibility matched",
            ),
        }
        for sequence, audit in enumerate(audits, 1):
            mapped = mappings.get(audit.action)
            if mapped is None:
                continue
            kind, title = mapped
            records.append(
                {
                    "id": audit.audit_id,
                    "sequence": sequence,
                    "occurred_at": audit.timestamp,
                    "kind": kind,
                    "title": title,
                    "event_id": event_id,
                    "task_id": None,
                }
            )
        return records

    @staticmethod
    def _validate_event_id(event_id: object) -> None:
        if (
            not isinstance(event_id, str)
            or _EVENT_ID.fullmatch(event_id) is None
        ):
            raise DemoActivationWebError(
                WebErrorCode.INVALID_REQUEST,
                "Event identifier is invalid.",
                HTTPStatus.BAD_REQUEST,
            )

    @staticmethod
    def _public_text(value: str) -> str:
        if (
            _WINDOWS_ABSOLUTE_PATH.search(value)
            or _UNIX_LOCAL_PATH.search(value)
            or _SECRET_ASSIGNMENT.search(value)
            or _TOKEN_SHAPE.search(value)
        ):
            return "[REDACTED]"
        return value

    @staticmethod
    def _invalid(message: str) -> None:
        raise DemoActivationWebError(
            WebErrorCode.INVALID_REQUEST,
            message,
            HTTPStatus.BAD_REQUEST,
        )
