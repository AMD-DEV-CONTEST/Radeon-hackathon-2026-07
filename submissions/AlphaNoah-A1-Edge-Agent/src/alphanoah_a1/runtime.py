"""Deterministic orchestration for AlphaNoah's first runnable closed loop."""

from __future__ import annotations

import json
import re
from threading import RLock
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from .decision_hook import DecisionHook
from .exceptions import (
    AnalysisProviderError,
    DuplicateSubmissionError,
    HumanActorRequired,
    InvalidAnalysisOutput,
    InvalidEventInput,
    InvalidStateTransition,
    ProviderInputError,
    ProviderOutputError,
    SkillResolutionError,
)
from .models import (
    AnalysisResult,
    AuditRecord,
    Decision,
    DecisionStatus,
    Evidence,
    EvidenceValidationStatus,
    Event,
    EventStatus,
    HookResult,
    HumanReview,
    HumanReviewOutcome,
    PostReviewResult,
    Review,
    Task,
    TaskStatus,
    utc_now,
)
from .notifications import LocalNotificationOutbox, Notification
from .responsibility import ResponsibilityDirectory
from .skill import SkillContext, SkillResolver
from .skills import FoodColdHoldingSkill
from .state_machine import ensure_transition
from .storage import SQLiteStore

if TYPE_CHECKING:
    from .providers.base import AnalysisProvider


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class AlphaNoahRuntime:
    """Run one event through analysis, approval, task, evidence and review."""

    def __init__(
        self,
        database_path: str,
        *,
        skill: FoodColdHoldingSkill | None = None,
        decision_hook: DecisionHook | None = None,
    ):
        self.store = SQLiteStore(database_path)
        self.skill = skill or FoodColdHoldingSkill()
        self.decision_hook = decision_hook or DecisionHook()
        self._human_review_lock = RLock()

    def create_event(
        self,
        *,
        source: str,
        actor: str,
        raw_input_ref: str = "",
        normalized_input: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        event_type: str | None = None,
        location: str = "",
        asset_id: str = "",
        reporter: str = "",
        description: str = "",
        timestamp: str | None = None,
        attachments: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Event:
        if not isinstance(source, str) or not source.strip():
            raise InvalidEventInput("source must be a non-empty string")

        if normalized_input is not None and not isinstance(
            normalized_input, Mapping
        ):
            raise InvalidEventInput("normalized_input must be a mapping")
        domain_input = (
            dict(normalized_input) if normalized_input is not None else {}
        )
        explicit_industrial_input = event_type is not None
        resolved_event_type = (
            event_type if explicit_industrial_input else "legacy_observation"
        )
        if (
            not isinstance(resolved_event_type, str)
            or re.fullmatch(
                r"[a-z][a-z0-9_]*", resolved_event_type
            ) is None
        ):
            raise InvalidEventInput(
                "event_type must be a non-empty snake_case string"
            )

        resolved_location = (
            domain_input.get("location", "") if location == "" else location
        )
        resolved_description = description
        if not resolved_description and not explicit_industrial_input:
            resolved_description = (
                domain_input.get("description")
                or domain_input.get("observation")
                or ""
            )
        if explicit_industrial_input and (
            not isinstance(resolved_description, str)
            or not resolved_description.strip()
        ):
            raise InvalidEventInput(
                "description is required when event_type is provided"
            )

        string_fields = {
            "location": resolved_location,
            "asset_id": asset_id,
            "reporter": reporter,
            "description": resolved_description,
        }
        invalid_string_fields = [
            name for name, value in string_fields.items()
            if not isinstance(value, str)
        ]
        if invalid_string_fields:
            raise InvalidEventInput(
                "Event string fields have invalid values: "
                + ", ".join(invalid_string_fields)
            )

        if attachments is not None and not isinstance(attachments, list):
            raise InvalidEventInput(
                "attachments must be a list of string references"
            )
        attachment_refs = list(attachments or [])
        if not all(
            isinstance(reference, str) and reference.strip()
            for reference in attachment_refs
        ):
            raise InvalidEventInput(
                "attachments must contain non-empty string references"
            )
        if metadata is not None and not isinstance(metadata, Mapping):
            raise InvalidEventInput("metadata must be a mapping")
        event_metadata = dict(metadata) if metadata is not None else {}
        if not all(isinstance(key, str) for key in event_metadata):
            raise InvalidEventInput("metadata keys must be strings")
        try:
            copied_context = json.loads(
                json.dumps(
                    {
                        "attachments": attachment_refs,
                        "metadata": event_metadata,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as exc:
            raise InvalidEventInput(
                "attachments and metadata must be JSON serializable"
            ) from exc
        attachment_refs = copied_context["attachments"]
        event_metadata = copied_context["metadata"]
        resolved_timestamp = timestamp if timestamp is not None else utc_now()
        if (
            not isinstance(resolved_timestamp, str)
            or not resolved_timestamp.strip()
        ):
            raise InvalidEventInput("timestamp must be a non-empty string")

        trace = trace_id or new_id("trace")
        event = Event(
            event_id=new_id("event"),
            source=source,
            timestamp=resolved_timestamp,
            raw_input_ref=raw_input_ref,
            normalized_input=domain_input,
            detected_issue="",
            confidence=0.0,
            severity="UNKNOWN",
            status=EventStatus.NEW,
            trace_id=trace,
            event_type=resolved_event_type,
            location=resolved_location,
            asset_id=asset_id,
            reporter=reporter,
            description=resolved_description,
            attachments=attachment_refs,
            metadata=event_metadata,
        )
        self.store.save_event(event)
        self._record(
            actor=actor,
            action="event_created",
            object_type="Event",
            object_id=event.event_id,
            previous_state=None,
            new_state=event.status.value,
            trace_id=trace,
            details={
                "source": source,
                "event_type": resolved_event_type,
                "location": resolved_location,
                "asset_id": asset_id,
                "reporter": reporter,
                "raw_input_ref": raw_input_ref,
                "data_classification": domain_input.get(
                    "data_classification",
                    event_metadata.get(
                        "data_classification", "Unconfirmed"
                    ),
                ),
            },
        )
        return event

    def analyze_event(
        self,
        event_id: str,
        *,
        analysis_payload: Mapping[str, Any] | None = None,
    ) -> tuple[Decision, HookResult]:
        event = self._require_event_status(
            event_id, {EventStatus.NEW}, "analyze_event"
        )
        try:
            result = (
                self.skill.analyze(event.normalized_input)
                if analysis_payload is None
                else self.skill.parse_analysis_output(analysis_payload)
            )
        except InvalidAnalysisOutput as exc:
            self._transition(
                event.event_id,
                EventStatus.FAILED,
                actor=f"skill:{self.skill.skill_id}",
                action="analysis_failed",
                details={"error": str(exc)},
            )
            raise

        return self._apply_analysis_result(
            event,
            result,
            actor=f"skill:{self.skill.skill_id}",
        )

    def analyze_event_with_provider(
        self,
        event_id: str,
        *,
        provider: AnalysisProvider,
        skill_resolver: SkillResolver | None = None,
    ) -> tuple[Decision, HookResult]:
        """Run one explicit provider call, then reuse runtime decision routing."""

        event = self._require_event_status(
            event_id, {EventStatus.NEW}, "analyze_event_with_provider"
        )
        provider_actor = f"provider:{provider.provider_id}"
        skill_context: SkillContext | None = None
        model_metadata: dict[str, Any] = {}
        if skill_resolver is not None:
            try:
                skill_context = skill_resolver.resolve(event)
                if not isinstance(skill_context, SkillContext):
                    raise SkillResolutionError(
                        "SkillResolver returned an invalid SkillContext.",
                        code="invalid_skill_context",
                    )
                model_metadata.update(skill_context.audit_metadata())
            except SkillResolutionError as exc:
                self._transition(
                    event.event_id,
                    EventStatus.FAILED,
                    actor="system:skill-resolver",
                    action="skill_resolution_failed",
                    details={
                        "error_code": exc.code,
                        "reason": str(exc),
                    },
                )
                raise
        try:
            if skill_context is None:
                result = provider.analyze(event)
            else:
                analyze_with_skill = getattr(
                    provider,
                    "analyze_with_skill",
                    None,
                )
                if not callable(analyze_with_skill):
                    raise ProviderInputError(
                        "Provider does not accept explicit SkillContext.",
                        code="skill_context_unsupported",
                    )
                result = analyze_with_skill(event, skill_context)
            if (
                not isinstance(result, AnalysisResult)
                or result.requires_human_review is not True
            ):
                raise ProviderOutputError(
                    "Provider must return an AnalysisResult requiring human review.",
                    code="human_review_required",
                )
        except AnalysisProviderError as exc:
            model_metadata.update(
                self._provider_audit_metadata(provider)
            )
            failure_details: dict[str, Any] = {
                "failure_type": exc.failure_type,
                "error_code": exc.code,
                "provider_id": provider.provider_id,
            }
            if model_metadata:
                failure_details["model_metadata"] = model_metadata
            self._transition(
                event.event_id,
                EventStatus.FAILED,
                actor=provider_actor,
                action="provider_analysis_failed",
                details=failure_details,
            )
            raise

        model_metadata.update(self._provider_audit_metadata(provider))
        return self._apply_analysis_result(
            event,
            result,
            actor=provider_actor,
            model_metadata=model_metadata,
        )

    def create_notification_for_decision(
        self,
        decision_id: str,
        *,
        directory: ResponsibilityDirectory,
        actor: str = "system:responsibility-router",
    ) -> Notification:
        """Resolve a reviewed local owner and persist one outbox record."""

        decision = self.store.get_decision(decision_id)
        existing = self.store.find_notification_by_decision(decision_id)
        if existing is not None:
            return existing

        event = self.store.get_event(decision.event_id)
        allowed = {
            DecisionStatus.PENDING_HUMAN_REVIEW,
            DecisionStatus.NEEDS_MORE_EVIDENCE,
            DecisionStatus.ESCALATED,
        }
        if decision.status not in allowed:
            reason = (
                "create_notification_for_decision requires a Decision "
                "awaiting human attention, found "
                f"{decision.status.value}"
            )
            self._operation_rejected(
                event,
                actor,
                "create_notification_for_decision",
                reason,
            )
            raise InvalidStateTransition(reason)

        assignment = directory.resolve(event)
        return LocalNotificationOutbox(self.store).enqueue(
            event=event,
            decision=decision,
            assignment=assignment,
            actor=actor,
        )

    def _apply_analysis_result(
        self,
        event: Event,
        result: AnalysisResult,
        *,
        actor: str,
        model_metadata: dict[str, Any] | None = None,
    ) -> tuple[Decision, HookResult]:
        """Persist one validated result and route it through DecisionHook."""

        event.detected_issue = result.detected_issue
        event.confidence = result.confidence
        event.severity = result.severity
        self.store.update_event(event)

        decision = Decision(
            decision_id=new_id("decision"),
            event_id=event.event_id,
            decision_type=result.decision_type,
            reasoning_summary=result.reasoning_summary,
            evidence=result.evidence,
            model_or_rule=result.model_or_rule,
            confidence=result.confidence,
            requires_human_review=result.requires_human_review,
            status=DecisionStatus.PROPOSED,
            risk_level=result.severity,
        )
        self.store.save_decision(decision)
        decision_audit_details: dict[str, Any] = {
            "model_or_rule": decision.model_or_rule
        }
        if model_metadata:
            decision_audit_details["model_metadata"] = model_metadata
        self._record(
            actor=actor,
            action="decision_created",
            object_type="Decision",
            object_id=decision.decision_id,
            previous_state=None,
            new_state=decision.status.value,
            trace_id=event.trace_id,
            details=decision_audit_details,
        )
        self._transition(
            event.event_id,
            EventStatus.ANALYZED,
            actor=actor,
            action="event_analyzed",
        )

        hook_result = self.decision_hook.evaluate(decision)
        decision.status = self._decision_status_for_hook(hook_result.target_status)
        self.store.update_decision(decision)
        self._record(
            actor="system:decision-hook",
            action=hook_result.action.value.lower(),
            object_type="Decision",
            object_id=decision.decision_id,
            previous_state=DecisionStatus.PROPOSED.value,
            new_state=decision.status.value,
            trace_id=event.trace_id,
            details={"reason": hook_result.reason},
        )
        self._transition(
            event.event_id,
            hook_result.target_status,
            actor="system:decision-hook",
            action="decision_hook_routed",
            details={
                "hook_action": hook_result.action.value,
                "reason": hook_result.reason,
            },
        )
        return decision, hook_result

    def submit_human_review(
        self,
        decision_id: str,
        *,
        reviewer: str,
        outcome: HumanReviewOutcome,
        comment: str,
        revision_request: str = "",
    ) -> HumanReview:
        with self._human_review_lock:
            return self._submit_human_review(
                decision_id,
                reviewer=reviewer,
                outcome=outcome,
                comment=comment,
                revision_request=revision_request,
            )

    def _submit_human_review(
        self,
        decision_id: str,
        *,
        reviewer: str,
        outcome: HumanReviewOutcome,
        comment: str,
        revision_request: str,
    ) -> HumanReview:
        if not reviewer.startswith("human:") or len(reviewer) <= len("human:"):
            raise HumanActorRequired(
                "Human review actor must use a non-empty 'human:' identity."
            )
        decision = self.store.get_decision(decision_id)
        if outcome is HumanReviewOutcome.REVISED and not revision_request:
            raise ValueError("revision_request is required for REVISED outcomes")
        existing_reviews = self.store.list_human_reviews(decision_id)
        if existing_reviews:
            return self._existing_human_review(
                decision,
                existing_reviews,
                reviewer=reviewer,
                outcome=outcome,
            )
        event = self._require_event_status(
            decision.event_id,
            {EventStatus.PENDING_HUMAN_REVIEW},
            "submit_human_review",
        )

        review = HumanReview(
            human_review_id=new_id("human_review"),
            reviewer=reviewer,
            decision_id=decision_id,
            outcome=outcome,
            comment=comment,
            timestamp=utc_now(),
            revision_request=revision_request,
        )
        review, created = self.store.register_human_review(review)
        if not created:
            return self._existing_human_review(
                decision,
                [review],
                reviewer=reviewer,
                outcome=outcome,
            )
        self._record(
            actor=reviewer,
            action="human_review_submitted",
            object_type="HumanReview",
            object_id=review.human_review_id,
            previous_state=None,
            new_state=outcome.value,
            trace_id=event.trace_id,
            details={"decision_id": decision_id, "comment": comment},
        )

        hook_result = self.decision_hook.after_human_review(decision, outcome)
        previous_decision_status = decision.status
        decision.status = {
            HumanReviewOutcome.APPROVED: DecisionStatus.APPROVED,
            HumanReviewOutcome.REJECTED: DecisionStatus.REJECTED,
            HumanReviewOutcome.REVISED: DecisionStatus.REVISED,
        }[outcome]
        self.store.update_decision(decision)
        self._record(
            actor="system:decision-hook",
            action=hook_result.action.value.lower(),
            object_type="Decision",
            object_id=decision.decision_id,
            previous_state=previous_decision_status.value,
            new_state=decision.status.value,
            trace_id=event.trace_id,
            details={"human_review_id": review.human_review_id},
        )
        self._transition(
            event.event_id,
            hook_result.target_status,
            actor=reviewer,
            action="human_decision_applied",
            details={
                "human_review_id": review.human_review_id,
                "hook_action": hook_result.action.value,
            },
        )
        return review

    def _existing_human_review(
        self,
        decision: Decision,
        reviews: list[HumanReview],
        *,
        reviewer: str,
        outcome: HumanReviewOutcome,
    ) -> HumanReview:
        existing = reviews[0]
        if all(review.outcome is outcome for review in reviews):
            return existing

        event = self.store.get_event(decision.event_id)
        reason = (
            f"Decision {decision.decision_id} already has a terminal "
            f"Human Review outcome: {existing.outcome.value}."
        )
        self._operation_rejected(
            event,
            reviewer,
            "submit_human_review",
            reason,
        )
        raise InvalidStateTransition(reason)

    def create_task(
        self,
        decision_id: str,
        *,
        actor: str,
        deadline: str,
        assignee: str | None = None,
        task_template: Mapping[str, str] | None = None,
    ) -> Task:
        decision = self.store.get_decision(decision_id)
        event = self._require_event_status(
            decision.event_id, {EventStatus.APPROVED}, "create_task"
        )
        if decision.status is not DecisionStatus.APPROVED:
            self._operation_rejected(
                event,
                actor,
                "create_task",
                f"Decision is {decision.status.value}, not APPROVED.",
            )
            raise InvalidStateTransition(
                f"Decision {decision_id} is not APPROVED"
            )

        template = (
            self.skill.task_template
            if task_template is None
            else self._validated_task_template(task_template)
        )
        task = Task(
            task_id=new_id("task"),
            source_decision_id=decision_id,
            task_type=template["task_type"],
            assignee=assignee or template["assignee"],
            description=template["description"],
            expected_result=template["expected_result"],
            deadline=deadline,
            status=TaskStatus.CREATED,
        )
        self.store.save_task(task)
        self._record(
            actor=actor,
            action="task_created",
            object_type="Task",
            object_id=task.task_id,
            previous_state=None,
            new_state=task.status.value,
            trace_id=event.trace_id,
            details={"decision_id": decision_id},
        )
        self._transition(
            event.event_id,
            EventStatus.TASK_CREATED,
            actor=actor,
            action="task_linked_to_event",
            details={"task_id": task.task_id},
        )
        return task

    @staticmethod
    def _validated_task_template(
        task_template: Mapping[str, str],
    ) -> dict[str, str]:
        """Defensively validate an application-selected task template."""

        if not isinstance(task_template, Mapping):
            raise ValueError("task_template must be a mapping")
        required = {
            "task_type",
            "assignee",
            "description",
            "expected_result",
        }
        if set(task_template) != required:
            raise ValueError(
                "task_template must contain exactly: "
                + ", ".join(sorted(required))
            )
        validated: dict[str, str] = {}
        for key in sorted(required):
            value = task_template[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"task_template {key} must be non-empty text"
                )
            validated[key] = value.strip()
        return validated

    def start_task(self, task_id: str, *, actor: str) -> Task:
        task, event = self._task_context(task_id)
        self._require_event_status(
            event.event_id, {EventStatus.TASK_CREATED}, "start_task"
        )
        previous = task.status
        task.status = TaskStatus.IN_PROGRESS
        self.store.update_task(task)
        self._record_object_transition(
            event, actor, "task_started", task, previous.value, task.status.value
        )
        self._transition(
            event.event_id,
            EventStatus.IN_PROGRESS,
            actor=actor,
            action="task_work_started",
            details={"task_id": task.task_id},
        )
        return task

    def submit_evidence(
        self,
        task_id: str,
        *,
        evidence_type: str,
        file_or_data_ref: str,
        submitted_by: str,
        description: str,
        idempotency_key: str,
    ) -> Evidence:
        task, event = self._task_context(task_id)
        if self.store.has_idempotency_key(
            "submit_evidence", idempotency_key
        ):
            self._operation_rejected(
                event,
                submitted_by,
                "duplicate_evidence_submission",
                f"idempotency_key={idempotency_key}",
            )
            raise DuplicateSubmissionError(
                f"Evidence submission already accepted: {idempotency_key}"
            )
        self._require_event_status(
            event.event_id, {EventStatus.IN_PROGRESS}, "submit_evidence"
        )
        evidence = Evidence(
            evidence_id=new_id("evidence"),
            task_id=task_id,
            type=evidence_type,
            file_or_data_ref=file_or_data_ref,
            submitted_by=submitted_by,
            timestamp=utc_now(),
            validation_status=EvidenceValidationStatus.PENDING,
            description=description,
        )
        if not self.store.register_evidence(evidence, idempotency_key):
            raise DuplicateSubmissionError(
                f"Evidence submission already accepted: {idempotency_key}"
            )
        self._record(
            actor=submitted_by,
            action="evidence_submitted",
            object_type="Evidence",
            object_id=evidence.evidence_id,
            previous_state=None,
            new_state=evidence.validation_status.value,
            trace_id=event.trace_id,
            details={"task_id": task_id, "idempotency_key": idempotency_key},
        )

        previous = task.status
        task.status = TaskStatus.EVIDENCE_SUBMITTED
        self.store.update_task(task)
        self._record_object_transition(
            event,
            submitted_by,
            "task_evidence_received",
            task,
            previous.value,
            task.status.value,
        )
        self._transition(
            event.event_id,
            EventStatus.EVIDENCE_SUBMITTED,
            actor=submitted_by,
            action="event_evidence_received",
            details={"evidence_id": evidence.evidence_id},
        )
        return evidence

    def begin_review(self, task_id: str, *, actor: str) -> Task:
        task, event = self._task_context(task_id)
        self._require_event_status(
            event.event_id,
            {EventStatus.EVIDENCE_SUBMITTED},
            "begin_review",
        )
        previous = task.status
        task.status = TaskStatus.UNDER_REVIEW
        self.store.update_task(task)
        self._record_object_transition(
            event,
            actor,
            "post_task_review_started",
            task,
            previous.value,
            task.status.value,
        )
        self._transition(
            event.event_id,
            EventStatus.UNDER_REVIEW,
            actor=actor,
            action="event_under_review",
            details={"task_id": task_id},
        )
        return task

    def review_task(
        self,
        task_id: str,
        *,
        reviewer_or_model: str,
        result: PostReviewResult,
        comment: str,
        follow_up_required: bool = False,
    ) -> Review:
        task, event = self._task_context(task_id)
        self._require_event_status(
            event.event_id, {EventStatus.UNDER_REVIEW}, "review_task"
        )
        evidence_items = self.store.list_evidence(task_id)
        if not evidence_items:
            self._operation_rejected(
                event,
                reviewer_or_model,
                "review_task",
                "No evidence exists for the task.",
            )
            raise InvalidStateTransition("A task cannot be reviewed without evidence")

        if result is PostReviewResult.PASSED:
            pending_items = [
                item
                for item in evidence_items
                if item.validation_status is EvidenceValidationStatus.PENDING
            ]
            if not pending_items:
                self._operation_rejected(
                    event,
                    reviewer_or_model,
                    "review_task",
                    "No newly submitted evidence is pending validation.",
                )
                raise InvalidStateTransition(
                    "PASSED requires newly submitted pending evidence"
                )
            for item in pending_items:
                item.validation_status = EvidenceValidationStatus.ACCEPTED
                self.store.update_evidence(item)
            target_event = EventStatus.CLOSED
            target_task = TaskStatus.CLOSED
            closed = True
        elif result is PostReviewResult.NEEDS_MORE_EVIDENCE:
            for item in evidence_items:
                if item.validation_status is EvidenceValidationStatus.PENDING:
                    item.validation_status = EvidenceValidationStatus.REJECTED
                    self.store.update_evidence(item)
            target_event = EventStatus.NEEDS_MORE_EVIDENCE
            target_task = TaskStatus.NEEDS_MORE_EVIDENCE
            closed = False
            follow_up_required = True
        else:
            target_event = EventStatus.FAILED
            target_task = TaskStatus.FAILED
            closed = False
            follow_up_required = True

        review = Review(
            review_id=new_id("review"),
            event_id=event.event_id,
            task_id=task_id,
            evidence=[item.evidence_id for item in evidence_items],
            result=result,
            reviewer_or_model=reviewer_or_model,
            closed=closed,
            follow_up_required=follow_up_required,
            timestamp=utc_now(),
            comment=comment,
        )
        self.store.save_post_review(review)
        self._record(
            actor=reviewer_or_model,
            action="post_task_review_recorded",
            object_type="Review",
            object_id=review.review_id,
            previous_state=None,
            new_state=result.value,
            trace_id=event.trace_id,
            details={"task_id": task_id, "evidence": review.evidence},
        )

        previous = task.status
        task.status = target_task
        self.store.update_task(task)
        self._record_object_transition(
            event,
            reviewer_or_model,
            "task_review_completed",
            task,
            previous.value,
            task.status.value,
        )
        self._transition(
            event.event_id,
            target_event,
            actor=reviewer_or_model,
            action="event_review_completed",
            details={"review_id": review.review_id, "result": result.value},
        )
        return review

    def resume_task(self, task_id: str, *, actor: str) -> Task:
        task, event = self._task_context(task_id)
        self._require_event_status(
            event.event_id,
            {EventStatus.NEEDS_MORE_EVIDENCE},
            "resume_task",
        )
        previous = task.status
        task.status = TaskStatus.IN_PROGRESS
        self.store.update_task(task)
        self._record_object_transition(
            event,
            actor,
            "task_resumed_for_evidence",
            task,
            previous.value,
            task.status.value,
        )
        self._transition(
            event.event_id,
            EventStatus.IN_PROGRESS,
            actor=actor,
            action="event_resumed_for_evidence",
            details={"task_id": task_id},
        )
        return task

    def retry_failed_event(self, event_id: str, *, actor: str) -> Event:
        self._require_event_status(
            event_id, {EventStatus.FAILED}, "retry_failed_event"
        )
        return self._transition(
            event_id,
            EventStatus.NEW,
            actor=actor,
            action="failed_event_restarted",
        )

    def snapshot(self, event_id: str) -> dict[str, Any]:
        event = self.store.get_event(event_id)
        decisions = self.store.list_decisions(event_id)
        tasks = [
            task
            for decision in decisions
            for task in self.store.list_tasks(decision.decision_id)
        ]
        return {
            "event": event.to_dict(),
            "decisions": [decision.to_dict() for decision in decisions],
            "notifications": [
                notification.to_dict()
                for notification in self.store.list_notifications(event_id)
            ],
            "human_reviews": [
                review.to_dict()
                for decision in decisions
                for review in self.store.list_human_reviews(
                    decision.decision_id
                )
            ],
            "tasks": [task.to_dict() for task in tasks],
            "evidence": [
                evidence.to_dict()
                for task in tasks
                for evidence in self.store.list_evidence(task.task_id)
            ],
            "reviews": [
                review.to_dict()
                for task in tasks
                for review in self.store.list_post_reviews(task.task_id)
            ],
            "audit": [
                record.to_dict()
                for record in self.store.list_audit(event.trace_id)
            ],
        }

    def _transition(
        self,
        event_id: str,
        target: EventStatus,
        *,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> Event:
        event = self.store.get_event(event_id)
        try:
            ensure_transition(event.status, target)
        except InvalidStateTransition as exc:
            self._operation_rejected(event, actor, action, str(exc))
            raise
        audit = self._audit(
            actor=actor,
            action=action,
            object_type="Event",
            object_id=event.event_id,
            previous_state=event.status.value,
            new_state=target.value,
            trace_id=event.trace_id,
            details=details or {},
        )
        return self.store.transition_event(
            event.event_id, event.status, target, audit
        )

    def _require_event_status(
        self,
        event_id: str,
        allowed: set[EventStatus],
        operation: str,
    ) -> Event:
        event = self.store.get_event(event_id)
        if event.status not in allowed:
            reason = (
                f"{operation} requires "
                f"{sorted(status.value for status in allowed)}, "
                f"found {event.status.value}"
            )
            self._operation_rejected(
                event, "system:runtime", operation, reason
            )
            raise InvalidStateTransition(reason)
        return event

    def _task_context(self, task_id: str) -> tuple[Task, Event]:
        task = self.store.get_task(task_id)
        decision = self.store.get_decision(task.source_decision_id)
        return task, self.store.get_event(decision.event_id)

    def _operation_rejected(
        self, event: Event, actor: str, operation: str, reason: str
    ) -> None:
        self._record(
            actor=actor,
            action="operation_rejected",
            object_type="Event",
            object_id=event.event_id,
            previous_state=event.status.value,
            new_state=event.status.value,
            trace_id=event.trace_id,
            details={"operation": operation, "reason": reason},
        )

    def _record_object_transition(
        self,
        event: Event,
        actor: str,
        action: str,
        object_value: Any,
        previous_state: str,
        new_state: str,
    ) -> None:
        self._record(
            actor=actor,
            action=action,
            object_type=type(object_value).__name__,
            object_id=getattr(
                object_value,
                "task_id",
                getattr(object_value, "evidence_id", "unknown"),
            ),
            previous_state=previous_state,
            new_state=new_state,
            trace_id=event.trace_id,
        )

    def _record(
        self,
        *,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        previous_state: str | None,
        new_state: str | None,
        trace_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.store.record_audit(
            self._audit(
                actor=actor,
                action=action,
                object_type=object_type,
                object_id=object_id,
                previous_state=previous_state,
                new_state=new_state,
                trace_id=trace_id,
                details=details or {},
            )
        )

    @staticmethod
    def _provider_audit_metadata(
        provider: AnalysisProvider,
    ) -> dict[str, Any]:
        metadata_reader = getattr(provider, "get_audit_metadata", None)
        if not callable(metadata_reader):
            return {}
        try:
            metadata = metadata_reader()
            if not isinstance(metadata, Mapping):
                return {}
            allowed_fields = {
                "model_name",
                "provider_name",
                "analysis_timestamp",
                "validation_status",
                "attempt_count",
                "max_retry",
                "prompt_version",
                "skill_version",
                "skill_id",
                "skill_resolution",
                "model_digest",
                "model_failure_code",
                "source_error_codes",
                "knowledge_sources",
                "knowledge_version",
                "context_count",
                "knowledge_statuses",
            }
            copied = {
                key: value
                for key, value in metadata.items()
                if key in allowed_fields
            }
            encoded = json.dumps(
                copied,
                ensure_ascii=False,
                allow_nan=False,
            )
            decoded = json.loads(encoded)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _audit(
        *,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        previous_state: str | None,
        new_state: str | None,
        trace_id: str,
        details: dict[str, Any],
    ) -> AuditRecord:
        return AuditRecord(
            audit_id=new_id("audit"),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            previous_state=previous_state,
            new_state=new_state,
            timestamp=utc_now(),
            trace_id=trace_id,
            details=details,
        )

    @staticmethod
    def _decision_status_for_hook(
        target: EventStatus,
    ) -> DecisionStatus:
        return {
            EventStatus.PENDING_HUMAN_REVIEW: (
                DecisionStatus.PENDING_HUMAN_REVIEW
            ),
            EventStatus.APPROVED: DecisionStatus.APPROVED,
            EventStatus.CLOSED: DecisionStatus.APPROVED,
            EventStatus.REJECTED: DecisionStatus.REJECTED,
            EventStatus.NEEDS_MORE_EVIDENCE: (
                DecisionStatus.NEEDS_MORE_EVIDENCE
            ),
            EventStatus.ESCALATED: DecisionStatus.ESCALATED,
        }[target]
