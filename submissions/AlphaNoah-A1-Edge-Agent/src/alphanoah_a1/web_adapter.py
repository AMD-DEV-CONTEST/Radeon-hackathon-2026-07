"""JSON-neutral Web adapter over the existing restaurant golden path."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from http import HTTPStatus
from threading import RLock
from typing import Any

from .exceptions import (
    AnalysisProviderError,
    DuplicateSubmissionError,
    InvalidStateTransition,
    ObjectNotFoundError,
)
from .bounded_location import (
    MAX_LOCATION_LENGTH,
    aircon_asset_id_for_location,
    is_valid_demo_location,
)
from .fault_description import is_bounded_air_conditioner_fault
from .golden_path import (
    RestaurantAirconGoldenPath,
    restaurant_aircon_event_metadata,
    restaurant_aircon_form_fields,
)
from .models import (
    Decision,
    Event,
    EventStatus,
    HumanReviewOutcome,
    PostReviewResult,
    Task,
)
from .qr_input import IncidentReportInputError, QRIncidentInputAdapter

_EVENT_INPUT_FIELDS = frozenset({"location", "asset_type", "description"})
_REVIEW_INPUT_FIELDS = frozenset({"action", "comment"})
_TASK_CREATE_INPUT_FIELDS: frozenset[str] = frozenset()
_EVIDENCE_INPUT_FIELDS = frozenset({"description"})
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}\Z")
_FINAL_REVIEW_INPUT_FIELDS = frozenset({"action", "comment"})
_WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:[\\/]")
_UNIX_LOCAL_PATH = re.compile(
    r"(?:^|[\s\"'])/(?:home|Users|tmp|var|etc|opt)/"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|password)"
    r"\s*[:=]\s*\S+"
)
_TOKEN_SHAPE = re.compile(r"\b(?:gho_|sk-)[A-Za-z0-9_-]{8,}")


class WebErrorCode(StrEnum):
    """Stable public errors without implementation details."""

    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    ANALYSIS_NOT_AVAILABLE = "ANALYSIS_NOT_AVAILABLE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class WebAdapterError(Exception):
    """Expected API failure with a safe status and stable message."""

    def __init__(
        self,
        code: WebErrorCode,
        message: str,
        status: HTTPStatus,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict[str, str]:
        return {
            "error_code": self.code.value,
            "message": self.message,
        }


class LocalWebIncidentInputAdapter(QRIncidentInputAdapter):
    """Persist bounded local Web reports with accurate provenance."""

    source = "web_event_report"
    actor = "system:web-event-input-adapter"
    raw_input_ref = "local://web-event-report/form"
    input_adapter_id = "web_event_report_v1"


class RestaurantAirconWebAdapter:
    """Map bounded Web payloads to existing application/runtime calls."""

    def __init__(self, application: RestaurantAirconGoldenPath):
        if not isinstance(application, RestaurantAirconGoldenPath):
            raise TypeError(
                "application must be RestaurantAirconGoldenPath"
            )
        self.application = application
        self.input_adapter = LocalWebIncidentInputAdapter(
            application.runtime,
            trusted_metadata=restaurant_aircon_event_metadata(),
        )
        self._task_create_lock = RLock()

    def create_event(self, payload: object) -> dict[str, Any]:
        values = self._exact_text_payload(
            payload,
            fields=_EVENT_INPUT_FIELDS,
            required=_EVENT_INPUT_FIELDS,
            limits={
                "location": MAX_LOCATION_LENGTH,
                "asset_type": 100,
                "description": 2_000,
            },
        )
        if not is_valid_demo_location(values["location"]):
            self._invalid("location must be a valid identifier.")
        if values["asset_type"] != "air_conditioner":
            self._invalid(
                "asset_type must be air_conditioner for this demo."
            )
        if not is_bounded_air_conditioner_fault(values["description"]):
            self._invalid(
                "Description must report an observed air-conditioner "
                "fault or anomaly."
            )
        form = restaurant_aircon_form_fields()
        form["location"] = values["location"]
        form["asset_id"] = aircon_asset_id_for_location(values["location"])
        form["description"] = values["description"]
        try:
            event = self.input_adapter.submit(form)
        except IncidentReportInputError as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The incident request is invalid.",
                HTTPStatus.BAD_REQUEST,
            ) from exc
        return {
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "status": event.status.value,
        }

    def get_event(self, event_id: str) -> dict[str, Any]:
        event = self._event(event_id)
        decision = self._single_decision(event)
        context = self._audit_context(event)
        return {
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "status": event.status.value,
            "skill_id": context["skill_id"],
            "skill_version": context["skill_version"],
            "analysis": (
                self._analysis_projection(event, decision)
                if decision is not None
                else None
            ),
            "decision": (
                {
                    "decision_id": decision.decision_id,
                    "status": decision.status.value,
                    "requires_human_review": (
                        decision.requires_human_review
                    ),
                }
                if decision is not None
                else None
            ),
        }

    def analyze_event(
        self, event_id: str, payload: object
    ) -> dict[str, Any]:
        self._empty_payload(payload)
        self._event(event_id)
        try:
            self.application.analyze(event_id)
        except AnalysisProviderError:
            return self.get_analysis(event_id)
        return self.get_analysis(event_id)

    def get_analysis(self, event_id: str) -> dict[str, Any]:
        event = self._event(event_id)
        decision = self._single_decision(event)
        if decision is None:
            self._raise_missing_analysis(event)
        context = self._audit_context(event)
        return {
            "event_id": event.event_id,
            "status": event.status.value,
            "analysis": self._analysis_projection(event, decision),
            "skill": (
                {
                    "skill_id": context["skill_id"],
                    "skill_version": context["skill_version"],
                }
                if context["skill_id"] is not None
                else None
            ),
            "knowledge_sources": context["knowledge_sources"],
        }

    def submit_review(
        self,
        event_id: str,
        payload: object,
    ) -> dict[str, Any]:
        event = self._event(event_id)
        values = self._exact_text_payload(
            payload,
            fields=_REVIEW_INPUT_FIELDS,
            required=_REVIEW_INPUT_FIELDS,
            limits={"action": 20, "comment": 1_000},
        )
        outcomes = {
            "approve": HumanReviewOutcome.APPROVED,
            "reject": HumanReviewOutcome.REJECTED,
        }
        outcome = outcomes.get(values["action"])
        if outcome is None:
            self._invalid("action must be approve or reject.")
        decision = self._single_decision(event)
        if decision is None:
            raise WebAdapterError(
                WebErrorCode.HUMAN_REVIEW_REQUIRED,
                "No Decision is awaiting human review.",
                HTTPStatus.CONFLICT,
            )
        try:
            review = self.application.submit_human_review(
                decision.decision_id,
                outcome=outcome,
                comment=values["comment"],
            )
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The Event is not in a reviewable state.",
                HTTPStatus.CONFLICT,
            ) from exc
        updated = self._event(event_id)
        return {
            "event_id": updated.event_id,
            "status": updated.status.value,
            "human_review_id": review.human_review_id,
            "outcome": review.outcome.value,
            "decision_id": decision.decision_id,
        }

    def get_task(self, event_id: str) -> dict[str, Any]:
        event = self._event(event_id)
        decision = self._single_decision(event)
        if decision is None:
            return {"event_id": event.event_id, "task": None}
        tasks = self.application.runtime.store.list_tasks(
            decision.decision_id
        )
        if len(tasks) > 1:
            raise WebAdapterError(
                WebErrorCode.INTERNAL_ERROR,
                "The Event has an inconsistent Task relationship.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        if not tasks:
            return {"event_id": event.event_id, "task": None}
        return self._task_projection(event, tasks[0])

    def create_task(
        self,
        event_id: str,
        payload: object,
    ) -> dict[str, Any]:
        """Create the existing approved task through a separate command.

        Human review remains a decision-only operation.  Keeping task
        creation separate preserves the Runtime boundary and lets a client
        safely recover a lost command response by reading the existing task.
        """

        self._exact_text_payload(
            payload,
            fields=_TASK_CREATE_INPUT_FIELDS,
            required=_TASK_CREATE_INPUT_FIELDS,
            limits={},
        )
        with self._task_create_lock:
            return self._create_task(event_id)

    def _create_task(self, event_id: str) -> dict[str, Any]:
        event = self._event(event_id)
        decision = self._single_decision(event)
        if decision is None:
            raise WebAdapterError(
                WebErrorCode.HUMAN_REVIEW_REQUIRED,
                "No approved Decision is available for Task creation.",
                HTTPStatus.CONFLICT,
            )
        tasks = self.application.runtime.store.list_tasks(
            decision.decision_id
        )
        if len(tasks) > 1:
            raise WebAdapterError(
                WebErrorCode.INTERNAL_ERROR,
                "The Event has an inconsistent Task relationship.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        if tasks:
            return self._task_projection(event, tasks[0])

        try:
            task = self.application.create_approved_task(
                decision.decision_id
            )
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,

                "The Event is not ready for Task creation.",
                HTTPStatus.CONFLICT,
            ) from exc

        return self._task_projection(self._event(event_id), task)

    @staticmethod
    def _task_projection(event: Event, task: Task) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "task": {
                "task_id": task.task_id,
                "status": task.status.value,
                "owner": task.assignee,
            },
        }

    def submit_evidence(
        self,
        task_id: str,
        payload: object,
    ) -> dict[str, Any]:
        values = self._exact_text_payload(
            payload,
            fields=_EVIDENCE_INPUT_FIELDS,
            required=_EVIDENCE_INPUT_FIELDS,
            limits={"description": 2_000},
        )
        self._task(task_id)
        try:
            evidence = self.application.submit_text_evidence(
                task_id,
                description=values["description"],
            )
        except DuplicateSubmissionError as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "This evidence submission was already accepted.",
                HTTPStatus.CONFLICT,
            ) from exc
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The Task is not ready to accept evidence.",
                HTTPStatus.CONFLICT,
            ) from exc
        task = self.application.runtime.store.get_task(task_id)
        return {
            "task_id": task.task_id,
            "task_status": task.status.value,
            "evidence_id": evidence.evidence_id,
            "validation_status": evidence.validation_status.value,
        }

    def start_task(self, task_id: str, payload: object) -> dict[str, Any]:
        self._empty_payload(payload)
        self._task(task_id)
        try:
            task = self.application.start_task(task_id)
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The Task is not ready to start.",
                HTTPStatus.CONFLICT,
            ) from exc
        event = self._event_for_task(task)
        return self._task_projection(event, task)

    def begin_final_review(
        self, task_id: str, payload: object
    ) -> dict[str, Any]:
        self._empty_payload(payload)
        self._task(task_id)
        try:
            task = self.application.begin_evidence_review(task_id)
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The Task is not ready for final review.",
                HTTPStatus.CONFLICT,
            ) from exc
        event = self._event_for_task(task)
        return self._task_projection(event, task)

    def submit_final_review(
        self, task_id: str, payload: object
    ) -> dict[str, Any]:
        values = self._exact_text_payload(
            payload,
            fields=_FINAL_REVIEW_INPUT_FIELDS,
            required=_FINAL_REVIEW_INPUT_FIELDS,
            limits={"action": 40, "comment": 1_000},
        )
        results = {
            "approve": PostReviewResult.PASSED,
            "needs_more_evidence": PostReviewResult.NEEDS_MORE_EVIDENCE,
        }
        result = results.get(values["action"])
        if result is None:
            self._invalid("action must be approve or needs_more_evidence.")
        self._task(task_id)
        try:
            review = self.application.review_evidence(
                task_id,
                result=result,
                comment=values["comment"],
            )
        except InvalidStateTransition as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "The Task is not ready for a final review decision.",
                HTTPStatus.CONFLICT,
            ) from exc
        task = self.application.runtime.store.get_task(task_id)
        event = self.application.runtime.store.get_event(review.event_id)
        return {
            **self._task_projection(event, task),
            "review": {
                "review_id": review.review_id,
                "result": review.result.value,
                "closed": review.closed,
                "follow_up_required": review.follow_up_required,
            },
        }

    def _event_for_task(self, task: Task) -> Event:
        decision = self.application.runtime.store.get_decision(
            task.source_decision_id
        )
        return self.application.runtime.store.get_event(decision.event_id)

    def _empty_payload(self, payload: object) -> None:
        self._exact_text_payload(
            payload,
            fields=frozenset(),
            required=frozenset(),
            limits={},
        )
    def get_timeline(self, event_id: str) -> list[dict[str, Any]]:
        self._event(event_id)
        return [
            {
                "sequence": entry.sequence,
                "timestamp": entry.timestamp,
                "action": entry.action,
                "actor": entry.actor,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "status": entry.status,
            }
            for entry in self.application.timeline(event_id)
        ]

    def _event(self, event_id: str) -> Event:
        self._validate_identifier(event_id, "Event")
        try:
            return self.application.runtime.store.get_event(event_id)
        except ObjectNotFoundError as exc:
            raise WebAdapterError(
                WebErrorCode.EVENT_NOT_FOUND,
                "Event does not exist.",
                HTTPStatus.NOT_FOUND,
            ) from exc

    def _task(self, task_id: str) -> object:
        self._validate_identifier(task_id, "Task")
        try:
            return self.application.runtime.store.get_task(task_id)
        except ObjectNotFoundError as exc:
            raise WebAdapterError(
                WebErrorCode.TASK_NOT_FOUND,
                "Task does not exist.",
                HTTPStatus.NOT_FOUND,
            ) from exc

    def _single_decision(self, event: Event) -> Decision | None:
        decisions = self.application.runtime.store.list_decisions(
            event.event_id
        )
        if len(decisions) > 1:
            raise WebAdapterError(
                WebErrorCode.INTERNAL_ERROR,
                "The Event has an inconsistent Decision relationship.",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return decisions[0] if decisions else None

    def _raise_missing_analysis(self, event: Event) -> None:
        if event.status is EventStatus.FAILED:
            audits = self.application.runtime.store.list_audit(
                event.trace_id
            )
            provider_failure = next(
                (
                    record
                    for record in reversed(audits)
                    if record.action == "provider_analysis_failed"
                ),
                None,
            )
            if (
                provider_failure is not None
                and provider_failure.details.get("failure_type")
                == "transport"
            ):
                raise WebAdapterError(
                    WebErrorCode.PROVIDER_UNAVAILABLE,
                    "The configured Analysis Provider is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            raise WebAdapterError(
                WebErrorCode.ANALYSIS_FAILED,
                "Analysis did not produce a valid result.",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        raise WebAdapterError(
            WebErrorCode.ANALYSIS_NOT_AVAILABLE,
            "Analysis is not available for this Event.",
            HTTPStatus.CONFLICT,
        )

    def _audit_context(self, event: Event) -> dict[str, Any]:
        skill_id: str | None = None
        skill_version: str | None = None
        knowledge_sources: tuple[str, ...] = ()
        for record in self.application.runtime.store.list_audit(
            event.trace_id
        ):
            metadata = record.details.get("model_metadata")
            if not isinstance(metadata, Mapping):
                continue
            raw_skill_id = metadata.get("skill_id")
            raw_skill_version = metadata.get("skill_version")
            if isinstance(raw_skill_id, str):
                skill_id = self._public_text(raw_skill_id)
            if isinstance(raw_skill_version, str):
                skill_version = self._public_text(raw_skill_version)
            raw_sources = metadata.get("knowledge_sources")
            if isinstance(raw_sources, list):
                knowledge_sources = tuple(
                    source
                    for source in raw_sources
                    if self._safe_reference(source)
                )
        return {
            "skill_id": skill_id,
            "skill_version": skill_version,
            "knowledge_sources": list(knowledge_sources),
        }

    @staticmethod
    def _analysis_projection(
        event: Event,
        decision: Decision,
    ) -> dict[str, Any]:
        return {
            "detected_issue": RestaurantAirconWebAdapter._public_text(
                event.detected_issue
            ),
            "decision_type": RestaurantAirconWebAdapter._public_text(
                decision.decision_type
            ),
            "reasoning_summary": RestaurantAirconWebAdapter._public_text(
                decision.reasoning_summary
            ),
            "evidence": [
                RestaurantAirconWebAdapter._public_text(value)
                for value in decision.evidence
            ],
            "model_or_rule": RestaurantAirconWebAdapter._public_text(
                decision.model_or_rule
            ),
            "confidence": decision.confidence,
            "requires_human_review": decision.requires_human_review,
            "severity": decision.risk_level,
        }

    @staticmethod
    def _exact_text_payload(
        payload: object,
        *,
        fields: frozenset[str],
        required: frozenset[str],
        limits: Mapping[str, int],
    ) -> dict[str, str]:
        if not isinstance(payload, Mapping):
            RestaurantAirconWebAdapter._invalid(
                "Request body must be a JSON object."
            )
        if set(payload) != fields:
            RestaurantAirconWebAdapter._invalid(
                "Request body fields do not match the endpoint contract."
            )
        values: dict[str, str] = {}
        for field in fields:
            value = payload[field]
            if (
                not isinstance(value, str)
                or value != value.strip()
                or "\x00" in value
                or len(value) > limits[field]
                or any(ord(character) < 32 for character in value)
            ):
                RestaurantAirconWebAdapter._invalid(
                    f"{field} is invalid."
                )
            if field in required and not value:
                RestaurantAirconWebAdapter._invalid(
                    f"{field} is required."
                )
            values[field] = value
        return values

    @staticmethod
    def _validate_identifier(value: object, label: str) -> None:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-z]+_[a-f0-9]{32}", value) is None
        ):
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                f"{label} identifier is invalid.",
                HTTPStatus.BAD_REQUEST,
            )

    @staticmethod
    def _safe_reference(value: object) -> bool:
        return (
            isinstance(value, str)
            and _SAFE_REFERENCE.fullmatch(value) is not None
            and not value.startswith(("/", "\\", "file:"))
            and _WINDOWS_ABSOLUTE_PATH.search(value) is None
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
        raise WebAdapterError(
            WebErrorCode.INVALID_REQUEST,
            message,
            HTTPStatus.BAD_REQUEST,
        )
