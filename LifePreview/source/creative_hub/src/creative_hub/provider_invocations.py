from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    BudgetReservationRecord,
    OperationAttemptRecord,
    ProviderCallbackReceiptRecord,
    ProviderInvocationGrantRecord,
    ProviderInvocationRecord,
)
from creative_hub.db.repositories import (
    BudgetRepository,
    ConcurrentStateConflict,
    IdempotencyConflict,
    InvalidState,
    PersistenceError,
    Stored,
)


PROVIDER_PHASES = frozenset(
    {
        "PREPARED",
        "SUBMITTED",
        "OUTCOME_UNKNOWN",
        "OBSERVED_TERMINAL",
        "MATERIALIZING",
        "COMMITTED",
    }
)
TERMINAL_OUTCOMES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
GRANT_ACTIONS = frozenset({"SUBMIT", "RECONCILE", "MATERIALIZE"})


class ProviderInvocationObserver(Protocol):
    def record_provider(self, *, provider: str, outcome: str) -> None: ...

    def record_provider_cost_actualized(
        self,
        *,
        provider: str,
        outcome: str,
        cost_micros: int,
    ) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _metric_provider(provider: str) -> str:
    normalized = provider.casefold()
    if normalized in {"comfy", "comfyui"}:
        return "comfyui"
    if normalized.startswith("qwen"):
        return "qwen"
    if normalized.startswith(("glm", "zhipu")):
        return "glm"
    if normalized in {"local", "other"}:
        return normalized
    return "other"


class ProviderInvocationRepository:
    """Transactional authority for durable provider invocation state."""

    def __init__(
        self,
        session: Session,
        *,
        observer: ProviderInvocationObserver | None = None,
    ) -> None:
        self.session = session
        self.observer = observer

    def prepare(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        operation_attempt_id: UUID,
        provider: str,
        client_token: str,
        request_payload: Mapping[str, Any],
        supports_idempotent_submit: bool,
        supports_query_by_client_token: bool,
        supports_query_by_task_id: bool = True,
        reservation_id: UUID | None = None,
        invocation_id: UUID | None = None,
    ) -> Stored:
        provider_name = provider.strip()
        if not provider_name or len(provider_name) > 100:
            raise ValueError("provider identity is invalid")
        if len(client_token) < 16 or len(client_token) > 255:
            raise ValueError("provider client token is invalid")
        payload = dict(request_payload)
        request_digest = canonical_json_digest(payload)
        existing = self.session.scalar(
            select(ProviderInvocationRecord).where(
                ProviderInvocationRecord.operation_attempt_id
                == operation_attempt_id,
                ProviderInvocationRecord.provider == provider_name,
            )
        )
        attempt = self.session.scalar(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.id == operation_attempt_id,
                OperationAttemptRecord.operation_run_id == operation_run_id,
                OperationAttemptRecord.project_id == project_id,
            )
        )
        if attempt is None:
            raise PersistenceError("provider invocation attempt was not found")
        if existing is not None:
            if not (
                existing.project_id == project_id
                and existing.operation_run_id == operation_run_id
                and existing.client_token == client_token
                and existing.submission_nonce == attempt.submission_nonce
                and existing.request_digest == request_digest
                and existing.supports_idempotent_submit
                is supports_idempotent_submit
                and existing.supports_query_by_client_token
                is supports_query_by_client_token
                and existing.supports_query_by_task_id
                is supports_query_by_task_id
                and existing.reservation_id == reservation_id
                and (invocation_id is None or existing.id == invocation_id)
            ):
                raise IdempotencyConflict(
                    "attempt/provider invocation identity conflicts"
                )
            return Stored(existing, False)
        if reservation_id is not None:
            reservation = self.session.scalar(
                select(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.id == reservation_id,
                    BudgetReservationRecord.project_id == project_id,
                )
                .with_for_update()
            )
            if reservation is None:
                raise PersistenceError(
                    "provider budget reservation was not found for project"
                )
            if reservation.status != "RESERVED":
                raise InvalidState(
                    "provider budget reservation is not active"
                )
            if (
                reservation.operation_attempt_id is not None
                and (
                    reservation.operation_attempt_id
                    != operation_attempt_id
                    or reservation.operation_run_id != operation_run_id
                )
            ):
                raise PersistenceError(
                    "provider budget reservation belongs to another attempt"
                )
        record = ProviderInvocationRecord(
            id=invocation_id or uuid4(),
            project_id=project_id,
            operation_run_id=operation_run_id,
            operation_attempt_id=operation_attempt_id,
            provider=provider_name,
            client_token=client_token,
            submission_nonce=attempt.submission_nonce,
            request_payload=payload,
            request_digest=request_digest,
            supports_idempotent_submit=supports_idempotent_submit,
            supports_query_by_client_token=supports_query_by_client_token,
            supports_query_by_task_id=supports_query_by_task_id,
            phase="PREPARED",
            result_payload={},
            reservation_id=reservation_id,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(record, True)

    def grant(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        action: str,
        granted_by_actor: str,
        reason: str,
        grant_id: UUID | None = None,
    ) -> ProviderInvocationGrantRecord:
        checked_action = action.upper()
        if checked_action not in GRANT_ACTIONS:
            raise ValueError("provider grant action is invalid")
        if not granted_by_actor.strip() or not reason.strip():
            raise ValueError("provider grant requires actor and reason")
        invocation = self._locked(invocation_id, project_id)
        grant = ProviderInvocationGrantRecord(
            id=grant_id or uuid4(),
            invocation_id=invocation.id,
            project_id=invocation.project_id,
            operation_run_id=invocation.operation_run_id,
            operation_attempt_id=invocation.operation_attempt_id,
            action=checked_action,
            granted_by_actor=granted_by_actor,
            reason=reason,
        )
        self.session.add(grant)
        self.session.flush()
        return grant

    def mark_submission_started(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        grant_id: UUID,
        expected_state_version: int,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        moment = occurred_at or _utcnow()
        invocation = self._locked(invocation_id, project_id)
        if invocation.phase != "PREPARED":
            raise InvalidState("only prepared provider invocation can submit")
        if invocation.submit_started_at is not None:
            raise InvalidState(
                "provider submission already started; reconcile instead"
            )
        if invocation.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        self._consume_grant(invocation, grant_id, "SUBMIT", moment)
        return self._cas(
            invocation,
            expected_state_version=expected_state_version,
            submit_started_at=moment,
        )

    def record_submitted(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        provider_task_id: str,
        expected_state_version: int,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        if not provider_task_id.strip():
            raise ValueError("provider task id is invalid")
        invocation = self._locked(invocation_id, project_id)
        if invocation.phase == "SUBMITTED":
            if invocation.provider_task_id == provider_task_id:
                return invocation
            raise InvalidState("invocation already has another provider task")
        if invocation.phase not in {"PREPARED", "OUTCOME_UNKNOWN"}:
            raise InvalidState("provider invocation is already terminal")
        updated = self._cas(
            invocation,
            expected_state_version=expected_state_version,
            phase="SUBMITTED",
            provider_task_id=provider_task_id,
            submitted_at=invocation.submitted_at or occurred_at or _utcnow(),
            human_required=False,
            safe_reason_code=None,
        )
        self._observe(updated.provider, "submitted")
        return updated

    def record_outcome_unknown(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        expected_state_version: int,
        human_required: bool = False,
        safe_reason_code: str | None = None,
    ) -> ProviderInvocationRecord:
        invocation = self._locked(invocation_id, project_id)
        if invocation.phase == "OUTCOME_UNKNOWN":
            if (
                invocation.human_required == human_required
                and invocation.safe_reason_code == safe_reason_code
            ):
                return invocation
        elif invocation.phase not in {"PREPARED", "SUBMITTED"}:
            raise InvalidState(
                "terminal provider invocation cannot become unknown"
            )
        if human_required and not safe_reason_code:
            raise ValueError("human-required invocation needs a safe reason")
        updated = self._cas(
            invocation,
            expected_state_version=expected_state_version,
            phase="OUTCOME_UNKNOWN",
            human_required=human_required,
            safe_reason_code=safe_reason_code,
        )
        self._observe(updated.provider, "outcome_unknown")
        return updated

    def record_observation(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        observed_state: str,
        provider_task_id: str | None,
        result_payload: Mapping[str, Any] | None,
        cost_micros: int | None,
        expected_state_version: int,
        callback_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        state = observed_state.upper()
        if state not in {
            "PENDING",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "UNKNOWN",
            "ABSENT",
        }:
            raise ValueError("provider observation state is invalid")
        if cost_micros is not None and cost_micros < 0:
            raise ValueError("provider cost must be nonnegative")
        moment = occurred_at or _utcnow()
        invocation = self._locked(invocation_id, project_id)
        payload = dict(result_payload or {})
        callback_digest = canonical_json_digest(
            {
                "observed_state": state,
                "provider_task_id": provider_task_id,
                "result": payload,
                "cost_micros": cost_micros,
            }
        )
        if callback_id is not None:
            receipt = self.session.scalar(
                select(ProviderCallbackReceiptRecord).where(
                    ProviderCallbackReceiptRecord.invocation_id
                    == invocation_id,
                    ProviderCallbackReceiptRecord.callback_id == callback_id,
                )
            )
            if receipt is not None:
                if receipt.payload_digest != callback_digest:
                    raise IdempotencyConflict(
                        "provider callback id was reused with different data"
                    )
                return invocation
        if (
            provider_task_id is not None
            and invocation.provider_task_id is not None
            and provider_task_id != invocation.provider_task_id
        ):
            raise InvalidState(
                "provider observation belongs to another provider task"
            )
        terminal = state if state in TERMINAL_OUTCOMES else None
        result_digest = canonical_json_digest(payload) if terminal else None
        if invocation.phase in {
            "OBSERVED_TERMINAL",
            "MATERIALIZING",
            "COMMITTED",
        }:
            if (
                invocation.terminal_outcome == terminal
                and invocation.result_digest == result_digest
                and (
                    provider_task_id is None
                    or provider_task_id == invocation.provider_task_id
                )
                and cost_micros == invocation.cost_micros
            ):
                self._record_callback(
                    invocation, callback_id, callback_digest, moment
                )
                return invocation
            raise InvalidState(
                "late provider result conflicts with terminal authority"
            )
        if invocation.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        task_id = provider_task_id or invocation.provider_task_id
        if terminal:
            if result_payload is None:
                raise ValueError("terminal observation requires result payload")
            updated = self._cas(
                invocation,
                expected_state_version=expected_state_version,
                phase="OBSERVED_TERMINAL",
                provider_task_id=task_id,
                terminal_outcome=terminal,
                result_payload=payload,
                result_digest=result_digest,
                cost_micros=cost_micros,
                terminal_observed_at=moment,
                human_required=False,
                safe_reason_code=None,
            )
            metric_outcome = {
                "SUCCEEDED": "completed_pending_collection",
                "FAILED": "failed",
                "CANCELLED": "failed",
            }[terminal]
            if cost_micros is not None:
                self._settle_actual_cost(updated, cost_micros)
                self._observe_cost(
                    updated.provider,
                    metric_outcome,
                    cost_micros,
                )
        elif state in {"PENDING", "RUNNING"}:
            if not task_id:
                raise ValueError(
                    "nonterminal observation requires provider task id"
                )
            updated = self._cas(
                invocation,
                expected_state_version=expected_state_version,
                phase="SUBMITTED",
                provider_task_id=task_id,
                submitted_at=invocation.submitted_at or moment,
                human_required=False,
                safe_reason_code=None,
            )
            metric_outcome = "running"
        else:
            updated = self._cas(
                invocation,
                expected_state_version=expected_state_version,
                phase="OUTCOME_UNKNOWN",
            )
            metric_outcome = "outcome_unknown"
        self._record_callback(updated, callback_id, callback_digest, moment)
        self._observe(updated.provider, metric_outcome)
        return updated

    def begin_materialization(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        grant_id: UUID,
        expected_state_version: int,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        moment = occurred_at or _utcnow()
        invocation = self._locked(invocation_id, project_id)
        if (
            invocation.phase != "OBSERVED_TERMINAL"
            or invocation.terminal_outcome != "SUCCEEDED"
        ):
            raise InvalidState(
                "only observed successful provider result can materialize"
            )
        if invocation.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        self._consume_grant(invocation, grant_id, "MATERIALIZE", moment)
        return self._cas(
            invocation,
            expected_state_version=expected_state_version,
            phase="MATERIALIZING",
            materializing_at=moment,
        )

    def commit(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        committed_result: Mapping[str, Any],
        actual_cost_micros: int,
        expected_state_version: int,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        if actual_cost_micros < 0:
            raise ValueError("actual provider cost must be nonnegative")
        result = dict(committed_result)
        result_digest = canonical_json_digest(result)
        invocation = self._locked(invocation_id, project_id)
        if invocation.phase == "COMMITTED":
            if (
                invocation.materialized_digest == result_digest
                and invocation.cost_micros == actual_cost_micros
            ):
                return invocation
            raise InvalidState("provider invocation already committed")
        if invocation.phase != "MATERIALIZING":
            raise InvalidState("provider invocation is not materializing")
        if (
            invocation.cost_micros is not None
            and invocation.cost_micros != actual_cost_micros
        ):
            raise InvalidState(
                "actual cost conflicts with observed provider cost"
            )
        if invocation.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        self._settle_actual_cost(invocation, actual_cost_micros)
        cost_was_actualized = invocation.cost_micros is not None
        updated = self._cas(
            invocation,
            expected_state_version=expected_state_version,
            phase="COMMITTED",
            materialized_payload=result,
            materialized_digest=result_digest,
            cost_micros=actual_cost_micros,
            committed_at=occurred_at or _utcnow(),
        )
        self._observe(updated.provider, "succeeded")
        if not cost_was_actualized:
            self._observe_cost(
                updated.provider,
                "succeeded",
                actual_cost_micros,
            )
        return updated

    def consume_reconcile_grant(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        grant_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ProviderInvocationRecord:
        invocation = self._locked(invocation_id, project_id)
        self._consume_grant(
            invocation,
            grant_id,
            "RECONCILE",
            occurred_at or _utcnow(),
        )
        return invocation

    def _locked(
        self,
        invocation_id: UUID,
        project_id: UUID,
    ) -> ProviderInvocationRecord:
        invocation = self.session.scalar(
            select(ProviderInvocationRecord)
            .where(
                ProviderInvocationRecord.id == invocation_id,
                ProviderInvocationRecord.project_id == project_id,
            )
            .with_for_update()
        )
        if invocation is None:
            raise PersistenceError("provider invocation was not found")
        return invocation

    def _consume_grant(
        self,
        invocation: ProviderInvocationRecord,
        grant_id: UUID,
        action: str,
        moment: datetime,
    ) -> None:
        grant = self.session.scalar(
            select(ProviderInvocationGrantRecord)
            .where(
                ProviderInvocationGrantRecord.id == grant_id,
                ProviderInvocationGrantRecord.invocation_id == invocation.id,
                ProviderInvocationGrantRecord.project_id
                == invocation.project_id,
            )
            .with_for_update()
        )
        if grant is None or grant.action != action:
            raise InvalidState("provider action grant is invalid")
        if grant.consumed_at is not None:
            raise InvalidState("provider action grant was already consumed")
        grant.consumed_at = moment
        self.session.flush()

    def _cas(
        self,
        invocation: ProviderInvocationRecord,
        *,
        expected_state_version: int,
        **values: Any,
    ) -> ProviderInvocationRecord:
        if expected_state_version != invocation.state_version:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        changed = self.session.execute(
            update(ProviderInvocationRecord)
            .where(
                ProviderInvocationRecord.id == invocation.id,
                ProviderInvocationRecord.project_id == invocation.project_id,
                ProviderInvocationRecord.state_version
                == expected_state_version,
            )
            .values(
                **values,
                state_version=expected_state_version + 1,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "provider invocation changed concurrently"
            )
        self.session.flush()
        self.session.refresh(invocation)
        return invocation

    def _record_callback(
        self,
        invocation: ProviderInvocationRecord,
        callback_id: str | None,
        payload_digest: str,
        moment: datetime,
    ) -> None:
        if callback_id is None:
            return
        self.session.add(
            ProviderCallbackReceiptRecord(
                invocation_id=invocation.id,
                project_id=invocation.project_id,
                operation_run_id=invocation.operation_run_id,
                operation_attempt_id=invocation.operation_attempt_id,
                callback_id=callback_id,
                payload_digest=payload_digest,
                received_at=moment,
            )
        )
        self.session.flush()

    def _observe(self, provider: str, outcome: str) -> None:
        if self.observer is None:
            return
        try:
            self.observer.record_provider(
                provider=_metric_provider(provider),
                outcome=outcome,
            )
        except Exception:
            pass

    def _settle_actual_cost(
        self,
        invocation: ProviderInvocationRecord,
        actual_cost_micros: int,
    ) -> None:
        if invocation.reservation_id is None:
            return
        BudgetRepository(self.session).settle(
            reservation_id=invocation.reservation_id,
            project_id=invocation.project_id,
            actual_micros=actual_cost_micros,
            command_idempotency_key=f"provider-settle:{invocation.id}",
            metadata={
                "provider": invocation.provider,
                "provider_invocation_id": str(invocation.id),
            },
        )

    def _observe_cost(
        self,
        provider: str,
        outcome: str,
        cost_micros: int,
    ) -> None:
        if self.observer is None:
            return
        try:
            self.observer.record_provider_cost_actualized(
                provider=_metric_provider(provider),
                outcome=outcome,
                cost_micros=cost_micros,
            )
        except Exception:
            pass


__all__ = [
    "GRANT_ACTIONS",
    "PROVIDER_PHASES",
    "ProviderInvocationObserver",
    "ProviderInvocationRepository",
    "TERMINAL_OUTCOMES",
]
