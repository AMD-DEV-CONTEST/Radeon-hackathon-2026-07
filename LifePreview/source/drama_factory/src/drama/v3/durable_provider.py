from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

from shared_contracts import (
    ImplementationManifest,
    ReplayClass,
    SchemaRevision,
    build_implementation_digest,
    stable_json_sha256,
)


class DurableProviderError(RuntimeError):
    """Base error for the provider side-effect protocol."""


class ProviderResponseLost(DurableProviderError):
    """The request may have reached the provider but no response was observed."""


class ProviderRejected(DurableProviderError):
    """The provider definitively rejected a request before accepting work."""


class ProviderStateConflict(DurableProviderError):
    """A stale or contradictory durable-provider mutation was requested."""


class ProviderHumanRequired(DurableProviderError):
    """The provider cannot be reconciled safely without an operator."""


class ProviderInvocationPhase(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    OBSERVED_TERMINAL = "OBSERVED_TERMINAL"
    MATERIALIZING = "MATERIALIZING"
    COMMITTED = "COMMITTED"


class ProviderTerminalOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProviderObservationState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"


class ProviderGrantAction(StrEnum):
    SUBMIT = "SUBMIT"
    RECONCILE = "RECONCILE"
    MATERIALIZE = "MATERIALIZE"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    idempotent_submit: bool
    query_by_client_token: bool
    query_by_task_id: bool = True

    @property
    def safely_reconcilable(self) -> bool:
        return (
            self.idempotent_submit
            or self.query_by_client_token
            or self.query_by_task_id
        )


@dataclass(frozen=True, slots=True)
class ProviderActionGrant:
    grant_id: UUID
    invocation_id: UUID
    action: ProviderGrantAction
    granted_by_actor: str
    reason: str
    granted_at: datetime

    def __post_init__(self) -> None:
        if not self.granted_by_actor.strip() or not self.reason.strip():
            raise ValueError("provider grant requires actor and reason")
        if self.granted_at.tzinfo is None:
            raise ValueError("provider grant timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    state: ProviderObservationState
    provider_task_id: str | None = None
    result: Mapping[str, Any] | None = None
    cost_micros: int | None = None

    def __post_init__(self) -> None:
        if self.cost_micros is not None and self.cost_micros < 0:
            raise ValueError("provider cost must be non-negative")
        if self.state in {
            ProviderObservationState.SUCCEEDED,
            ProviderObservationState.FAILED,
            ProviderObservationState.CANCELLED,
        } and self.result is None:
            raise ValueError("terminal provider observation requires a result")


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    invocation_id: UUID
    project_id: UUID
    operation_run_id: UUID
    operation_attempt_id: UUID
    provider: str
    client_token: str
    submission_nonce: UUID
    request_payload: Mapping[str, Any]
    request_digest: str
    capabilities: ProviderCapabilities
    phase: ProviderInvocationPhase
    state_version: int
    provider_task_id: str | None = None
    terminal_outcome: ProviderTerminalOutcome | None = None
    result: Mapping[str, Any] | None = None
    result_digest: str | None = None
    committed_result: Mapping[str, Any] | None = None
    committed_result_digest: str | None = None
    cost_micros: int | None = None
    submit_started_at: datetime | None = None
    submitted_at: datetime | None = None
    terminal_observed_at: datetime | None = None
    materializing_at: datetime | None = None
    committed_at: datetime | None = None
    human_required: bool = False
    safe_reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider identity must not be empty")
        if len(self.client_token) < 16:
            raise ValueError("provider client token is too short")
        if self.request_digest != stable_json_sha256(self.request_payload):
            raise ValueError("provider request digest does not match payload")
        if self.state_version < 0:
            raise ValueError("provider state version must be non-negative")
        if self.cost_micros is not None and self.cost_micros < 0:
            raise ValueError("provider cost must be non-negative")
        if self.phase in {
            ProviderInvocationPhase.OBSERVED_TERMINAL,
            ProviderInvocationPhase.MATERIALIZING,
            ProviderInvocationPhase.COMMITTED,
        } and (
            self.terminal_outcome is None
            or self.result is None
            or self.result_digest != stable_json_sha256(self.result)
        ):
            raise ValueError("terminal provider phase requires digest-bound result")
        if self.phase is ProviderInvocationPhase.COMMITTED:
            if self.terminal_outcome is not ProviderTerminalOutcome.SUCCEEDED:
                raise ValueError("only successful provider work can be committed")
            if self.committed_at is None:
                raise ValueError("committed provider work requires commit time")
            if (
                self.committed_result is None
                or self.committed_result_digest
                != stable_json_sha256(self.committed_result)
            ):
                raise ValueError(
                    "committed provider work requires digest-bound materialization"
                )
        if self.human_required and not self.safe_reason_code:
            raise ValueError("human-required provider state needs a safe reason")


class DurableProviderTransport(Protocol):
    provider_name: str
    capabilities: ProviderCapabilities

    def submit(
        self,
        request: Mapping[str, Any],
        *,
        client_token: str,
    ) -> str: ...

    def query(
        self,
        *,
        client_token: str,
        provider_task_id: str | None,
    ) -> ProviderObservation: ...


class DurableProviderStore(Protocol):
    def prepare(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        operation_run_id: UUID,
        operation_attempt_id: UUID,
        provider: str,
        client_token: str,
        submission_nonce: UUID,
        request_payload: Mapping[str, Any],
        capabilities: ProviderCapabilities,
    ) -> ProviderInvocation: ...

    def get(self, invocation_id: UUID) -> ProviderInvocation: ...

    def mark_submission_started(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def record_submitted(
        self,
        invocation_id: UUID,
        *,
        provider_task_id: str,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def record_outcome_unknown(
        self,
        invocation_id: UUID,
        *,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def record_observation(
        self,
        invocation_id: UUID,
        *,
        observation: ProviderObservation,
        callback_id: str | None,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def consume_reconcile_grant(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
    ) -> ProviderInvocation: ...

    def require_human(
        self,
        invocation_id: UUID,
        *,
        safe_reason_code: str,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def begin_materialization(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...

    def commit(
        self,
        invocation_id: UUID,
        *,
        committed_result: Mapping[str, Any],
        actual_cost_micros: int | None,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation: ...


def _terminal_outcome(
    state: ProviderObservationState,
) -> ProviderTerminalOutcome | None:
    return {
        ProviderObservationState.SUCCEEDED: ProviderTerminalOutcome.SUCCEEDED,
        ProviderObservationState.FAILED: ProviderTerminalOutcome.FAILED,
        ProviderObservationState.CANCELLED: ProviderTerminalOutcome.CANCELLED,
    }.get(state)


class InMemoryDurableProviderStore:
    """Reference store used by property tests and provider adapter fixtures.

    Production authority lives in Creative Hub PostgreSQL.  This implementation
    intentionally applies the same CAS and uniqueness rules so transport tests
    do not need a database.
    """

    def __init__(self) -> None:
        self._records: dict[UUID, ProviderInvocation] = {}
        self._attempt_provider: dict[tuple[UUID, str], UUID] = {}
        self._provider_task: dict[tuple[str, str], UUID] = {}
        self._used_grants: set[UUID] = set()
        self._callbacks: dict[tuple[UUID, str], str] = {}
        self._lock = RLock()

    def prepare(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        operation_run_id: UUID,
        operation_attempt_id: UUID,
        provider: str,
        client_token: str,
        submission_nonce: UUID,
        request_payload: Mapping[str, Any],
        capabilities: ProviderCapabilities,
    ) -> ProviderInvocation:
        payload = dict(request_payload)
        digest = stable_json_sha256(payload)
        key = (operation_attempt_id, provider)
        with self._lock:
            existing_id = self._attempt_provider.get(key)
            if existing_id is not None:
                existing = self._records[existing_id]
                if (
                    existing.invocation_id != invocation_id
                    or existing.project_id != project_id
                    or existing.operation_run_id != operation_run_id
                    or existing.client_token != client_token
                    or existing.submission_nonce != submission_nonce
                    or existing.request_digest != digest
                    or existing.capabilities != capabilities
                ):
                    raise ProviderStateConflict(
                        "attempt/provider invocation identity conflicts"
                    )
                return existing
            record = ProviderInvocation(
                invocation_id=invocation_id,
                project_id=project_id,
                operation_run_id=operation_run_id,
                operation_attempt_id=operation_attempt_id,
                provider=provider,
                client_token=client_token,
                submission_nonce=submission_nonce,
                request_payload=payload,
                request_digest=digest,
                capabilities=capabilities,
                phase=ProviderInvocationPhase.PREPARED,
                state_version=0,
            )
            self._records[invocation_id] = record
            self._attempt_provider[key] = invocation_id
            return record

    def get(self, invocation_id: UUID) -> ProviderInvocation:
        with self._lock:
            try:
                return self._records[invocation_id]
            except KeyError:
                raise ProviderStateConflict(
                    "provider invocation does not exist"
                ) from None

    @staticmethod
    def _check_version(record: ProviderInvocation, expected: int) -> None:
        if record.state_version != expected:
            raise ProviderStateConflict("provider invocation version changed")

    def _consume_grant(
        self,
        record: ProviderInvocation,
        grant: ProviderActionGrant,
        action: ProviderGrantAction,
    ) -> None:
        if (
            grant.invocation_id != record.invocation_id
            or grant.action is not action
            or grant.grant_id in self._used_grants
        ):
            raise ProviderStateConflict("provider action grant is invalid or used")
        self._used_grants.add(grant.grant_id)

    def mark_submission_started(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            if record.phase is not ProviderInvocationPhase.PREPARED:
                raise ProviderStateConflict("only prepared invocation can submit")
            if record.submit_started_at is not None:
                raise ProviderStateConflict(
                    "submission was already started; reconcile instead"
                )
            self._consume_grant(record, grant, ProviderGrantAction.SUBMIT)
            updated = replace(
                record,
                submit_started_at=occurred_at,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated

    def consume_reconcile_grant(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
    ) -> ProviderInvocation:
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            self._consume_grant(
                record,
                grant,
                ProviderGrantAction.RECONCILE,
            )
            return record

    def record_submitted(
        self,
        invocation_id: UUID,
        *,
        provider_task_id: str,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        if not provider_task_id.strip():
            raise ValueError("provider task id must not be empty")
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            if record.phase not in {
                ProviderInvocationPhase.PREPARED,
                ProviderInvocationPhase.OUTCOME_UNKNOWN,
                ProviderInvocationPhase.SUBMITTED,
            }:
                raise ProviderStateConflict("provider submission is already terminal")
            task_key = (record.provider, provider_task_id)
            owner = self._provider_task.get(task_key)
            if owner not in {None, invocation_id}:
                raise ProviderStateConflict(
                    "provider task already belongs to another invocation"
                )
            if (
                record.phase is ProviderInvocationPhase.SUBMITTED
                and record.provider_task_id == provider_task_id
            ):
                return record
            if (
                record.provider_task_id is not None
                and record.provider_task_id != provider_task_id
            ):
                raise ProviderStateConflict(
                    "provider task does not match invocation"
                )
            self._provider_task[task_key] = invocation_id
            updated = replace(
                record,
                phase=ProviderInvocationPhase.SUBMITTED,
                provider_task_id=provider_task_id,
                submitted_at=record.submitted_at or occurred_at,
                human_required=False,
                safe_reason_code=None,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated

    def record_outcome_unknown(
        self,
        invocation_id: UUID,
        *,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        del occurred_at
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            if record.phase is ProviderInvocationPhase.OUTCOME_UNKNOWN:
                return record
            if record.phase not in {
                ProviderInvocationPhase.PREPARED,
                ProviderInvocationPhase.SUBMITTED,
            }:
                raise ProviderStateConflict(
                    "terminal provider invocation cannot become unknown"
                )
            updated = replace(
                record,
                phase=ProviderInvocationPhase.OUTCOME_UNKNOWN,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated

    def record_observation(
        self,
        invocation_id: UUID,
        *,
        observation: ProviderObservation,
        callback_id: str | None,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        with self._lock:
            record = self.get(invocation_id)
            if (
                record.provider_task_id is not None
                and observation.provider_task_id is not None
                and observation.provider_task_id
                != record.provider_task_id
            ):
                raise ProviderStateConflict(
                    "provider task does not match invocation"
                )
            terminal = _terminal_outcome(observation.state)
            result = dict(observation.result or {})
            result_digest = (
                stable_json_sha256(result) if terminal is not None else None
            )
            callback_key: tuple[UUID, str] | None = None
            callback_digest: str | None = None
            if callback_id is not None:
                callback_key = (invocation_id, callback_id)
                prior = self._callbacks.get(callback_key)
                callback_digest = stable_json_sha256(
                    {
                        "state": observation.state.value,
                        "provider_task_id": observation.provider_task_id,
                        "result": result,
                        "cost_micros": observation.cost_micros,
                    }
                )
                if prior is not None:
                    if prior != callback_digest:
                        raise ProviderStateConflict(
                            "callback id was reused with different provider data"
                        )
                    return record
            if record.phase in {
                ProviderInvocationPhase.OBSERVED_TERMINAL,
                ProviderInvocationPhase.MATERIALIZING,
                ProviderInvocationPhase.COMMITTED,
            }:
                if (
                    terminal == record.terminal_outcome
                    and result_digest == record.result_digest
                    and (
                        observation.provider_task_id is None
                        or observation.provider_task_id
                        == record.provider_task_id
                    )
                    and observation.cost_micros == record.cost_micros
                ):
                    if callback_key is not None and callback_digest is not None:
                        self._callbacks[callback_key] = callback_digest
                    return record
                raise ProviderStateConflict(
                    "late provider result conflicts with terminal authority"
                )
            self._check_version(record, expected_state_version)
            provider_task_id = (
                observation.provider_task_id or record.provider_task_id
            )
            if provider_task_id:
                task_key = (record.provider, provider_task_id)
                owner = self._provider_task.get(task_key)
                if owner not in {None, invocation_id}:
                    raise ProviderStateConflict(
                        "provider task already belongs to another invocation"
                    )
                self._provider_task[task_key] = invocation_id
            if terminal is not None:
                updated = replace(
                    record,
                    phase=ProviderInvocationPhase.OBSERVED_TERMINAL,
                    provider_task_id=provider_task_id,
                    terminal_outcome=terminal,
                    result=result,
                    result_digest=result_digest,
                    cost_micros=observation.cost_micros,
                    terminal_observed_at=occurred_at,
                    human_required=False,
                    safe_reason_code=None,
                    state_version=record.state_version + 1,
                )
            elif observation.state in {
                ProviderObservationState.PENDING,
                ProviderObservationState.RUNNING,
            }:
                if not provider_task_id:
                    raise ProviderStateConflict(
                        "nonterminal observation requires provider task id"
                    )
                updated = replace(
                    record,
                    phase=ProviderInvocationPhase.SUBMITTED,
                    provider_task_id=provider_task_id,
                    submitted_at=record.submitted_at or occurred_at,
                    human_required=False,
                    safe_reason_code=None,
                    state_version=record.state_version + 1,
                )
            else:
                updated = replace(
                    record,
                    phase=ProviderInvocationPhase.OUTCOME_UNKNOWN,
                    state_version=record.state_version + 1,
                )
            self._records[invocation_id] = updated
            if callback_key is not None and callback_digest is not None:
                self._callbacks[callback_key] = callback_digest
            return updated

    def require_human(
        self,
        invocation_id: UUID,
        *,
        safe_reason_code: str,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        del occurred_at
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            if record.phase in {
                ProviderInvocationPhase.OBSERVED_TERMINAL,
                ProviderInvocationPhase.MATERIALIZING,
                ProviderInvocationPhase.COMMITTED,
            }:
                raise ProviderStateConflict(
                    "terminal invocation cannot require reconciliation"
                )
            updated = replace(
                record,
                phase=ProviderInvocationPhase.OUTCOME_UNKNOWN,
                human_required=True,
                safe_reason_code=safe_reason_code,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated

    def begin_materialization(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        with self._lock:
            record = self.get(invocation_id)
            self._check_version(record, expected_state_version)
            if (
                record.phase is not ProviderInvocationPhase.OBSERVED_TERMINAL
                or record.terminal_outcome is not ProviderTerminalOutcome.SUCCEEDED
            ):
                raise ProviderStateConflict(
                    "only observed successful result can materialize"
                )
            self._consume_grant(
                record,
                grant,
                ProviderGrantAction.MATERIALIZE,
            )
            updated = replace(
                record,
                phase=ProviderInvocationPhase.MATERIALIZING,
                materializing_at=occurred_at,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated

    def commit(
        self,
        invocation_id: UUID,
        *,
        committed_result: Mapping[str, Any],
        actual_cost_micros: int | None,
        expected_state_version: int,
        occurred_at: datetime,
    ) -> ProviderInvocation:
        if actual_cost_micros is not None and actual_cost_micros < 0:
            raise ValueError("actual provider cost must be non-negative")
        with self._lock:
            record = self.get(invocation_id)
            if record.phase is ProviderInvocationPhase.COMMITTED:
                if (
                    stable_json_sha256(record.committed_result or {})
                    == stable_json_sha256(committed_result)
                    and record.cost_micros == actual_cost_micros
                ):
                    return record
                raise ProviderStateConflict(
                    "provider invocation already committed another result"
                )
            self._check_version(record, expected_state_version)
            if record.phase is not ProviderInvocationPhase.MATERIALIZING:
                raise ProviderStateConflict(
                    "provider invocation is not materializing"
                )
            if (
                record.cost_micros is not None
                and actual_cost_micros != record.cost_micros
            ):
                raise ProviderStateConflict(
                    "actual cost conflicts with observed provider cost"
                )
            result = dict(committed_result)
            updated = replace(
                record,
                phase=ProviderInvocationPhase.COMMITTED,
                committed_result=result,
                committed_result_digest=stable_json_sha256(result),
                cost_micros=actual_cost_micros,
                committed_at=occurred_at,
                state_version=record.state_version + 1,
            )
            self._records[invocation_id] = updated
            return updated


class DurableProviderCoordinator:
    """Provider-agnostic durable side-effect coordinator.

    A submission-start fact is committed before network I/O.  A restarted
    coordinator therefore reconciles a prepared-but-started invocation and
    never mistakes it for a fresh submission.
    """

    def __init__(
        self,
        *,
        store: DurableProviderStore,
        transport: DurableProviderTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def prepare(
        self,
        *,
        invocation_id: UUID,
        project_id: UUID,
        operation_run_id: UUID,
        operation_attempt_id: UUID,
        client_token: str,
        submission_nonce: UUID,
        request_payload: Mapping[str, Any],
    ) -> ProviderInvocation:
        request_nonce = request_payload.get("submission_nonce")
        transport_nonce = getattr(self.transport, "submission_nonce", None)
        if transport_nonce is not None:
            nonce_matches = (
                type(transport_nonce) is str
                and type(request_nonce) is str
                and request_nonce == submission_nonce.hex
                and request_nonce == transport_nonce
            )
        else:
            nonce_matches = request_nonce is None or (
                type(request_nonce) is str
                and request_nonce == submission_nonce.hex
            )
        if not nonce_matches:
            raise ProviderStateConflict(
                "provider request submission nonce does not match persisted nonce"
            )
        transport_workflow_digest = getattr(self.transport, "workflow_digest", None)
        if (
            transport_workflow_digest is not None
            and request_payload.get("workflow_digest") != transport_workflow_digest
        ):
            raise ProviderStateConflict(
                "provider request workflow digest does not match transport"
            )
        return self.store.prepare(
            invocation_id=invocation_id,
            project_id=project_id,
            operation_run_id=operation_run_id,
            operation_attempt_id=operation_attempt_id,
            provider=self.transport.provider_name,
            client_token=client_token,
            submission_nonce=submission_nonce,
            request_payload=request_payload,
            capabilities=self.transport.capabilities,
        )

    def _require_transport_match(
        self,
        record: ProviderInvocation,
    ) -> ProviderInvocation:
        if record.provider != self.transport.provider_name:
            raise ProviderStateConflict(
                "persisted provider does not match transport provider"
            )
        missing = object()
        for field_name, label in (
            ("workflow_digest", "workflow digest"),
            ("submission_nonce", "submission nonce"),
        ):
            transport_value = getattr(self.transport, field_name, missing)
            if transport_value is missing:
                continue
            persisted_value = record.request_payload.get(field_name, missing)
            if (
                persisted_value is missing
                or type(persisted_value) is not type(transport_value)
                or persisted_value != transport_value
            ):
                raise ProviderStateConflict(
                    f"persisted provider request {label} does not match transport"
                )
        return record

    def submit(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
    ) -> ProviderInvocation:
        record = self._require_transport_match(self.store.get(invocation_id))
        if record.phase is not ProviderInvocationPhase.PREPARED:
            return record
        if record.submit_started_at is not None:
            return self._reconcile_without_grant(record)
        record = self._require_transport_match(
            self.store.mark_submission_started(
                invocation_id,
                grant=grant,
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        )
        try:
            provider_task_id = self.transport.submit(
                record.request_payload,
                client_token=record.client_token,
            )
        except ProviderResponseLost:
            return self.store.record_outcome_unknown(
                invocation_id,
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        except ProviderRejected as exc:
            return self.store.record_observation(
                invocation_id,
                observation=ProviderObservation(
                    state=ProviderObservationState.FAILED,
                    result={"safe_error_code": "provider_submit_rejected"},
                ),
                callback_id=None,
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        return self.store.record_submitted(
            invocation_id,
            provider_task_id=provider_task_id,
            expected_state_version=record.state_version,
            occurred_at=self.clock(),
        )

    def reconcile(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        allow_idempotent_replay_after_absence: bool = False,
    ) -> ProviderInvocation:
        record = self._require_transport_match(self.store.get(invocation_id))
        if grant.invocation_id != invocation_id:
            raise ProviderStateConflict("reconcile grant belongs to another invocation")
        if grant.action is not ProviderGrantAction.RECONCILE:
            raise ProviderStateConflict("provider grant does not authorize reconcile")
        if record.phase in {
            ProviderInvocationPhase.OBSERVED_TERMINAL,
            ProviderInvocationPhase.MATERIALIZING,
            ProviderInvocationPhase.COMMITTED,
        }:
            return record
        record = self._require_transport_match(
            self.store.consume_reconcile_grant(
                invocation_id,
                grant=grant,
                expected_state_version=record.state_version,
            )
        )
        if not record.capabilities.safely_reconcilable:
            return self.store.require_human(
                invocation_id,
                safe_reason_code="provider_reconciliation_unsupported",
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        observation = self.transport.query(
            client_token=record.client_token,
            provider_task_id=record.provider_task_id,
        )
        if (
            observation.state is ProviderObservationState.ABSENT
            and allow_idempotent_replay_after_absence
            and record.capabilities.idempotent_submit
        ):
            # This reuses the already-persisted token.  It cannot create a
            # second logical task at an idempotent provider.
            try:
                provider_task_id = self.transport.submit(
                    record.request_payload,
                    client_token=record.client_token,
                )
            except ProviderResponseLost:
                return self.store.record_outcome_unknown(
                    invocation_id,
                    expected_state_version=record.state_version,
                    occurred_at=self.clock(),
                )
            return self.store.record_submitted(
                invocation_id,
                provider_task_id=provider_task_id,
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        return self.store.record_observation(
            invocation_id,
            observation=observation,
            callback_id=None,
            expected_state_version=record.state_version,
            occurred_at=self.clock(),
        )

    def _reconcile_without_grant(
        self,
        record: ProviderInvocation,
    ) -> ProviderInvocation:
        record = self._require_transport_match(record)
        if not record.capabilities.safely_reconcilable:
            return self.store.require_human(
                record.invocation_id,
                safe_reason_code="provider_reconciliation_unsupported",
                expected_state_version=record.state_version,
                occurred_at=self.clock(),
            )
        observation = self.transport.query(
            client_token=record.client_token,
            provider_task_id=record.provider_task_id,
        )
        return self.store.record_observation(
            record.invocation_id,
            observation=observation,
            callback_id=None,
            expected_state_version=record.state_version,
            occurred_at=self.clock(),
        )

    def callback(
        self,
        invocation_id: UUID,
        *,
        callback_id: str,
        observation: ProviderObservation,
    ) -> ProviderInvocation:
        if not callback_id.strip():
            raise ValueError("provider callback id must not be empty")
        record = self._require_transport_match(self.store.get(invocation_id))
        return self.store.record_observation(
            invocation_id,
            observation=observation,
            callback_id=callback_id,
            expected_state_version=record.state_version,
            occurred_at=self.clock(),
        )

    def materialize(
        self,
        invocation_id: UUID,
        *,
        grant: ProviderActionGrant,
        materializer: Callable[
            [ProviderInvocation], Mapping[str, Any]
        ],
        actual_cost_micros: int | None = None,
    ) -> ProviderInvocation:
        record = self._require_transport_match(self.store.get(invocation_id))
        if record.phase is ProviderInvocationPhase.COMMITTED:
            return record
        if record.phase is ProviderInvocationPhase.OBSERVED_TERMINAL:
            record = self._require_transport_match(
                self.store.begin_materialization(
                    invocation_id,
                    grant=grant,
                    expected_state_version=record.state_version,
                    occurred_at=self.clock(),
                )
            )
        if record.phase is not ProviderInvocationPhase.MATERIALIZING:
            raise ProviderStateConflict("provider result is not materializable")
        committed = materializer(record)
        return self.store.commit(
            invocation_id,
            committed_result=committed,
            actual_cost_micros=(
                actual_cost_micros
                if actual_cost_micros is not None
                else record.cost_micros
            ),
            expected_state_version=record.state_version,
            occurred_at=self.clock(),
        )


def new_grant(
    invocation_id: UUID,
    action: ProviderGrantAction,
    *,
    granted_by_actor: str,
    reason: str,
    granted_at: datetime | None = None,
) -> ProviderActionGrant:
    return ProviderActionGrant(
        grant_id=uuid4(),
        invocation_id=invocation_id,
        action=action,
        granted_by_actor=granted_by_actor,
        reason=reason,
        granted_at=granted_at or datetime.now(timezone.utc),
    )


def reproducible_implementation_manifest(
    *,
    code_image_digest: str,
    adapter_digest: str,
    upcaster_digest: str,
    comfy_workflow_digest: str,
    custom_node_set_digest: str,
    model_weight_digests: tuple[str, ...],
) -> ImplementationManifest:
    """Build a replayable manifest exclusively from content-addressed inputs."""

    values = {
        "manifest_schema_version": SchemaRevision(major=1, minor=0),
        "replay_class": ReplayClass.REPLAYABLE,
        "code_image_digest": code_image_digest,
        "adapter_digest": adapter_digest,
        "comfy_workflow_digest": comfy_workflow_digest,
        "custom_node_set_digest": custom_node_set_digest,
        "model_weight_digests": tuple(sorted(set(model_weight_digests))),
        "upcaster_digest": upcaster_digest,
    }
    if len(values["model_weight_digests"]) != len(model_weight_digests):
        raise ValueError("model weight digest evidence must be unique")
    return ImplementationManifest(
        **values,
        implementation_digest=build_implementation_digest(**values),
    )


__all__ = [
    "DurableProviderCoordinator",
    "DurableProviderError",
    "DurableProviderStore",
    "DurableProviderTransport",
    "InMemoryDurableProviderStore",
    "ProviderActionGrant",
    "ProviderCapabilities",
    "ProviderGrantAction",
    "ProviderHumanRequired",
    "ProviderInvocation",
    "ProviderInvocationPhase",
    "ProviderObservation",
    "ProviderObservationState",
    "ProviderRejected",
    "ProviderResponseLost",
    "ProviderStateConflict",
    "ProviderTerminalOutcome",
    "new_grant",
    "reproducible_implementation_manifest",
]
