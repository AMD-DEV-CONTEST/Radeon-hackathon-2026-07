"""Read-only public projections over persisted Runtime facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .golden_path import RestaurantAirconGoldenPath
from .models import Event, EventStatus
from .notifications import NotificationStatus
from .responsibility import (
    ResponsibilityAssignment,
    ResponsibilityDirectory,
)

WORKSPACE_PROJECTION_VERSION = "workspace-v1"
MAX_PROJECTED_EVENTS = 100
MAX_PUBLIC_TEXT_LENGTH = 200

_TERMINAL_EVENT_STATUSES = frozenset(
    {
        EventStatus.CLOSED,
        EventStatus.REJECTED,
        EventStatus.FAILED,
        EventStatus.CANCELLED,
    }
)
_PULSE_EVENT_STATUSES = frozenset(
    {
        EventStatus.PENDING_HUMAN_REVIEW,
        EventStatus.NEEDS_MORE_EVIDENCE,
        EventStatus.ESCALATED,
    }
)
_PUBLIC_SEVERITIES = frozenset(
    {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
)
_EVENT_ID = re.compile(r"event_[a-f0-9]{32}\Z")
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
)
_UNIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9/])/(?![/\s])"
)
_UNC_PATH = re.compile(
    r"(?:^|[\s\"'(\[=])(?:\\\\|//)[^\\/\s]+[\\/][^\s]+"
)
_PARENT_PATH = re.compile(
    r"(?:^|[\\/])\.\.(?:[\\/]|$)"
    r"|(?:^|[\s\"'(\[=:])\.\.[\\/]"
)
_FILE_REFERENCE = re.compile(r"(?i)(?<![A-Za-z0-9])file:")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:[a-z][a-z0-9]*[_-])*"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|token)"
    r"\s*[:=]\s*\S+"
)
_BEARER_AUTHORIZATION = re.compile(
    r"(?i)\b(?:authorization|auth)\s*[:=]\s*bearer\s+\S+"
)
_AWS_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\bAWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)"
    r"\s*[:=]\s*\S+"
)
_TOKEN_SHAPE = re.compile(
    r"\b(?:gho_|sk-|github_pat_)[A-Za-z0-9_-]{8,}"
)
_COMMON_TOKEN_SHAPE = re.compile(
    r"(?i)\b(?:"
    r"bearer\s+"
    r"(?=[A-Za-z0-9._~+/-]{8,}={0,2}(?:\s|$))"
    r"(?=[^\s]*[0-9._~+/\-])"
    r"[A-Za-z0-9._~+/-]{8,}={0,2}"
    r"|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"
    r"|xox[baprsce]-[A-Za-z0-9-]{8,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r")"
)


class RuntimeProjectionWebAdapter:
    """Expose bounded View Models without returning internal Runtime objects."""

    def __init__(
        self,
        application: RestaurantAirconGoldenPath,
        *,
        responsibility_directory: ResponsibilityDirectory,
    ) -> None:
        if not isinstance(application, RestaurantAirconGoldenPath):
            raise TypeError(
                "application must be RestaurantAirconGoldenPath"
            )
        if not isinstance(
            responsibility_directory,
            ResponsibilityDirectory,
        ):
            raise TypeError(
                "responsibility_directory must be ResponsibilityDirectory"
            )
        self.application = application
        self.responsibility_directory = responsibility_directory

    def get_workspace(self) -> dict[str, Any]:
        """Return one internally consistent projection of current read facts."""

        all_events = self._all_events_newest_first()
        events = all_events[:MAX_PROJECTED_EVENTS]
        assignments = self._assignments(all_events)
        projected_events = [
            self._event_projection(event, assignments[event.event_id])
            for event in events
        ]
        active_event = next(
            (
                self._event_projection(
                    event,
                    assignments[event.event_id],
                )
                for event in all_events
                if event.status not in _TERMINAL_EVENT_STATUSES
            ),
            None,
        )
        return {
            "version": WORKSPACE_PROJECTION_VERSION,
            "events": projected_events,
            "active_event": active_event,
            "pulse": self._pulse_projection(all_events),
            "employees": self._employee_projections(
                all_events,
                assignments,
            ),
        }

    def get_events(self) -> list[dict[str, Any]]:
        """Return persisted Events with the most recently changed first."""

        events = self._recent_events_newest_first()
        assignments = self._assignments(events)
        return [
            self._event_projection(event, assignments[event.event_id])
            for event in events
        ]

    def get_digital_employees(self) -> list[dict[str, Any]]:
        """Map event-backed responsibility facts into product employees."""

        events = self._all_events_newest_first()
        return self._employee_projections(
            events,
            self._assignments(events),
        )

    def get_pulse(self) -> dict[str, str] | None:
        """Return the newest persisted outbox item requiring attention."""

        return self._pulse_projection(self._all_events_newest_first())

    def _all_events_newest_first(self) -> list[Event]:
        # SQLiteStore.list_events() has the stable inverse ordering:
        # updated_at ASC, event_id ASC.
        return [
            event
            for event in reversed(
                self.application.runtime.store.list_events()
            )
            if (
                isinstance(event.event_id, str)
                and _EVENT_ID.fullmatch(event.event_id) is not None
            )
        ]

    def _recent_events_newest_first(self) -> list[Event]:
        return self._all_events_newest_first()[:MAX_PROJECTED_EVENTS]

    def _assignments(
        self,
        events: list[Event],
    ) -> dict[str, ResponsibilityAssignment | None]:
        assignments: dict[str, ResponsibilityAssignment | None] = {}
        for event in events:
            assignment = self.responsibility_directory.resolve(event)
            safe_owner_id = self._safe_public_text(assignment.owner_id)
            safe_owner_name = self._safe_public_text(assignment.owner_name)
            if (
                assignment.owner_id
                == ResponsibilityDirectory.UNASSIGNED.owner_id
                or safe_owner_id is None
                or safe_owner_name is None
            ):
                assignments[event.event_id] = None
                continue
            assignments[event.event_id] = ResponsibilityAssignment(
                owner_id=safe_owner_id,
                owner_name=safe_owner_name,
                match_type=assignment.match_type,
                matched_key=assignment.matched_key,
            )
        return assignments

    @classmethod
    def _event_projection(
        cls,
        event: Event,
        assignment: ResponsibilityAssignment | None,
    ) -> dict[str, Any]:
        return {
            "id": event.event_id,
            "type": cls._public_text(event.event_type),
            "status": event.status.value,
            "timestamp": cls._public_text(event.timestamp),
            "severity": cls._public_severity(event.severity),
            "location": cls._public_text(event.location),
            "asset_id": cls._public_text(event.asset_id),
            "description": cls._public_text(
                (
                    event.description
                    if event.event_type == "equipment_fault_report"
                    else "[REDACTED]"
                ),
                maximum_length=2_000,
            ),
            "responsibility": (
                {
                    "id": assignment.owner_id,
                    "name": assignment.owner_name,
                }
                if assignment is not None
                else None
            ),
        }

    def _employee_projections(
        self,
        events: list[Event],
        assignments: dict[str, ResponsibilityAssignment | None],
    ) -> list[dict[str, Any]]:
        employees: dict[str, dict[str, Any]] = {}
        for event in events:
            assignment = assignments[event.event_id]
            if assignment is None:
                continue
            employee = employees.setdefault(
                assignment.owner_id,
                {
                    "name": assignment.owner_name,
                    "current_event_id": None,
                    "skills": set(),
                },
            )
            if (
                employee["current_event_id"] is None
                and event.status not in _TERMINAL_EVENT_STATUSES
            ):
                employee["current_event_id"] = event.event_id
            employee["skills"].update(self._event_skill_ids(event))

        return [
            {
                "id": owner_id,
                "name": employee["name"],
                "status": (
                    "working"
                    if employee["current_event_id"] is not None
                    else "unknown"
                ),
                "current_event_id": employee["current_event_id"],
                "responsibility": employee["name"],
                "skills": [
                    {"name": self._public_text(skill_id)}
                    for skill_id in sorted(employee["skills"])
                ],
            }
            for owner_id, employee in sorted(employees.items())
        ]

    def _event_skill_ids(self, event: Event) -> set[str]:
        definitions = {
            (definition.skill_id, definition.version)
            for definition in self.application.skill_resolver.definitions
        }
        selected: set[str] = set()
        for record in self.application.runtime.store.list_audit(
            event.trace_id
        ):
            if (
                record.action != "decision_created"
                or record.object_type != "Decision"
                or not isinstance(record.details, Mapping)
            ):
                continue
            metadata = record.details.get("model_metadata")
            if not isinstance(metadata, Mapping):
                continue
            skill_id = metadata.get("skill_id")
            skill_version = metadata.get("skill_version")
            if (
                isinstance(skill_id, str)
                and isinstance(skill_version, str)
                and (skill_id, skill_version) in definitions
            ):
                selected.add(skill_id)
        return selected

    def _pulse_projection(
        self,
        events: list[Event],
    ) -> dict[str, str] | None:
        candidates = []
        for event in events:
            if event.status not in _PULSE_EVENT_STATUSES:
                continue
            for notification in (
                self.application.runtime.store.list_notifications(
                    event.event_id
                )
            ):
                if notification.status is NotificationStatus.CREATED:
                    level = self._pulse_level(event)
                    candidates.append((level, notification, event))
        if not candidates:
            return None

        level, notification, event = max(
            candidates,
            key=lambda item: (
                item[0] == "critical",
                (
                    item[1].created_at
                    if isinstance(item[1].created_at, str)
                    else ""
                ),
                (
                    item[2].event_id
                    if isinstance(item[2].event_id, str)
                    else ""
                ),
            ),
        )
        return {
            "level": level,
            "title": self._public_text(notification.title),
            "event_id": event.event_id,
        }

    @classmethod
    def _pulse_level(cls, event: Event) -> str:
        if (
            event.status is EventStatus.ESCALATED
            or cls._public_severity(event.severity) == "CRITICAL"
        ):
            return "critical"
        return "attention"

    @staticmethod
    def _public_severity(value: object) -> str:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in _PUBLIC_SEVERITIES:
                return normalized
        return "UNKNOWN"

    @staticmethod
    def _safe_public_text(
        value: object,
        *,
        maximum_length: int = MAX_PUBLIC_TEXT_LENGTH,
    ) -> str | None:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > maximum_length
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            or _WINDOWS_ABSOLUTE_PATH.search(value)
            or _UNIX_ABSOLUTE_PATH.search(value)
            or _UNC_PATH.search(value)
            or _PARENT_PATH.search(value)
            or _FILE_REFERENCE.search(value)
            or _SECRET_ASSIGNMENT.search(value)
            or _BEARER_AUTHORIZATION.search(value)
            or _AWS_CREDENTIAL_ASSIGNMENT.search(value)
            or _TOKEN_SHAPE.search(value)
            or _COMMON_TOKEN_SHAPE.search(value)
        ):
            return None
        return value

    @classmethod
    def _public_text(
        cls,
        value: object,
        *,
        maximum_length: int = MAX_PUBLIC_TEXT_LENGTH,
    ) -> str:
        safe = cls._safe_public_text(
            value,
            maximum_length=maximum_length,
        )
        return safe if safe is not None else "[REDACTED]"
