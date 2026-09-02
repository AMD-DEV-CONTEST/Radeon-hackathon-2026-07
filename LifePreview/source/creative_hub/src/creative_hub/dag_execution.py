"""PostgreSQL-backed DAG execution over durable workflow/operation facts."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Iterable, Literal, Sequence
from uuid import UUID, uuid4

from sqlalchemy import (
    Integer,
    String,
    case,
    cast,
    func,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session, aliased

from .cost_budgets import (
    BudgetDecision,
    BudgetUsage,
    CostBudget,
    CostBudgetGuard,
    CostProposal,
)
from .dag_models import (
    PRIORITY_CLASSES,
    RESOURCE_POOLS,
    DagAdmissionReservationRecord,
    DagReadyQueueRecord,
    DagSchedulerEventRecord,
    OperationDependencyStateRecord,
    ResourcePoolQuotaRecord,
    SchedulerFairnessCounterRecord,
    WorkflowRunEdgeRecord,
)
from .db.canonical import canonical_json_digest
from .db.models import (
    BudgetAccountRecord,
    BudgetLedgerEntryRecord,
    BudgetReservationRecord,
    HumanReviewTaskRecord,
    OperationAttemptEventRecord,
    OperationAttemptRecord,
    OperationAttemptStateRecord,
    OperationRunRecord,
    ProviderInvocationRecord,
    WorkflowRunRecord,
)

if TYPE_CHECKING:
    from shared_contracts import OperationRequest


_PRIORITY_VALUES = {
    "batch": 0,
    "interactive": 100,
    "urgent": 200,
    "system": 300,
}
_SCOPE_ORDER = {"global": 0, "project": 1, "workflow": 2}
_TERMINAL_OPERATIONS = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


class DagExecutionError(RuntimeError):
    """Base error for durable DAG execution."""


class InvalidDag(DagExecutionError):
    pass


class DagConflict(DagExecutionError):
    pass


class DagLeaseLost(DagConflict):
    pass


class BudgetAdmissionDenied(DagExecutionError):
    def __init__(self, decision: BudgetDecision) -> None:
        super().__init__(decision.reason_code)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class DagNode:
    operation_run_id: UUID
    resource_pool: str
    priority_class: str = "batch"
    estimated_cost_micros: int | None = None
    not_before: datetime | None = None

    def __post_init__(self) -> None:
        if self.resource_pool not in RESOURCE_POOLS:
            raise InvalidDag("resource_pool is invalid")
        if self.priority_class not in PRIORITY_CLASSES:
            raise InvalidDag("priority_class is invalid")
        if (
            self.estimated_cost_micros is None
            or isinstance(self.estimated_cost_micros, bool)
            or self.estimated_cost_micros < 0
        ):
            raise InvalidDag(
                "estimated_cost_micros is required and must be non-negative"
            )


@dataclass(frozen=True, slots=True)
class DagEdge:
    upstream_operation_run_id: UUID
    downstream_operation_run_id: UUID
    required_status: Literal["SUCCEEDED", "TERMINAL"] = "SUCCEEDED"

    def __post_init__(self) -> None:
        if self.upstream_operation_run_id == self.downstream_operation_run_id:
            raise InvalidDag("self edges are forbidden")
        if self.required_status not in {"SUCCEEDED", "TERMINAL"}:
            raise InvalidDag("required_status is invalid")


@dataclass(frozen=True, slots=True)
class DagLease:
    queue_entry_id: UUID
    project_id: UUID
    workflow_run_id: UUID
    operation_run_id: UUID
    attempt_id: UUID
    worker_id: str
    fencing_token: int
    resource_pool: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DependencyProjection:
    dependency_count: int
    satisfied_count: int = 0
    failed_count: int = 0
    paused: bool = False
    dispatched: bool = False

    @property
    def state(self) -> str:
        if self.failed_count:
            return "BLOCKED"
        if self.dispatched:
            return "DISPATCHED"
        if self.paused and self.satisfied_count == self.dependency_count:
            return "PAUSED_HUMAN"
        if self.satisfied_count == self.dependency_count:
            return "READY"
        return "WAITING"

    def resolve(self, *, succeeded: bool, terminal_satisfies: bool = False):
        if self.satisfied_count + self.failed_count >= self.dependency_count:
            raise DagConflict("dependency projection is already complete")
        if succeeded or terminal_satisfies:
            return DependencyProjection(
                self.dependency_count,
                self.satisfied_count + 1,
                self.failed_count,
                self.paused,
                self.dispatched,
            )
        return DependencyProjection(
            self.dependency_count,
            self.satisfied_count,
            self.failed_count + 1,
            self.paused,
            self.dispatched,
        )


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def effective_priority(
    priority_class: str,
    enqueued_at: datetime,
    now: datetime,
    *,
    promotion_interval: timedelta = timedelta(minutes=2),
) -> int:
    """Return a deterministic, bounded aging score."""

    if priority_class not in _PRIORITY_VALUES:
        raise ValueError("priority_class is invalid")
    if promotion_interval <= timedelta(0):
        raise ValueError("promotion_interval must be positive")
    waited = max(0.0, (_utc(now) - _utc(enqueued_at)).total_seconds())
    promotions = int(waited // promotion_interval.total_seconds())
    return min(399, _PRIORITY_VALUES[priority_class] + promotions)


def topological_order(
    nodes: Iterable[UUID],
    edges: Iterable[DagEdge],
    *,
    max_fan_out: int = 64,
) -> tuple[UUID, ...]:
    """Validate a bounded DAG and return its stable topological order."""

    node_tuple = tuple(nodes)
    node_set = set(node_tuple)
    if len(node_tuple) != len(node_set):
        raise InvalidDag("operation nodes must be unique")
    if not node_tuple:
        raise InvalidDag("a DAG must contain at least one operation")
    if max_fan_out < 1:
        raise ValueError("max_fan_out must be positive")
    indegree = Counter({node: 0 for node in node_tuple})
    outgoing: dict[UUID, list[UUID]] = defaultdict(list)
    pairs: set[tuple[UUID, UUID]] = set()
    for edge in edges:
        pair = (
            edge.upstream_operation_run_id,
            edge.downstream_operation_run_id,
        )
        if pair in pairs:
            raise InvalidDag("duplicate workflow edge")
        pairs.add(pair)
        if pair[0] not in node_set or pair[1] not in node_set:
            raise InvalidDag("workflow edge references an unknown operation")
        outgoing[pair[0]].append(pair[1])
        if len(outgoing[pair[0]]) > max_fan_out:
            raise InvalidDag("operation fan-out exceeds the configured bound")
        indegree[pair[1]] += 1
    ready = deque(sorted((n for n, value in indegree.items() if value == 0), key=str))
    result: list[UUID] = []
    while ready:
        current = ready.popleft()
        result.append(current)
        for child in sorted(outgoing[current], key=str):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(result) != len(node_tuple):
        raise InvalidDag("workflow graph contains a cycle")
    return tuple(result)


class DurableDagScheduler:
    """Transactional DAG scheduler.

    Callers own transaction boundaries.  A successful ``claim`` writes its
    queue lease, fencing token, immutable attempt, initial attempt event,
    dependency projection, quota counter, fairness counters, and all budget
    reservations before returning.
    """

    def __init__(
        self,
        session: Session,
        *,
        budget_guard: CostBudgetGuard | None,
        observability=None,
        promotion_interval: timedelta = timedelta(minutes=2),
        max_candidate_scan: int = 64,
    ) -> None:
        if promotion_interval <= timedelta(0):
            raise ValueError("promotion_interval must be positive")
        if not 1 <= max_candidate_scan <= 256:
            raise ValueError("max_candidate_scan must be between 1 and 256")
        self.session = session
        self.budget_guard = budget_guard
        self.observability = observability
        self.promotion_interval = promotion_interval
        self.max_candidate_scan = max_candidate_scan

    def configure_quota(
        self, resource_pool: str, *, max_concurrent: int
    ) -> ResourcePoolQuotaRecord:
        if resource_pool not in RESOURCE_POOLS:
            raise ValueError("resource_pool is invalid")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        record = self.session.get(
            ResourcePoolQuotaRecord, resource_pool, with_for_update=True
        )
        if record is None:
            record = ResourcePoolQuotaRecord(
                resource_pool=resource_pool,
                max_concurrent=max_concurrent,
            )
            self.session.add(record)
        else:
            if record.in_use > max_concurrent:
                raise DagConflict("quota is below currently leased capacity")
            record.max_concurrent = max_concurrent
            record.state_version += 1
            record.updated_at = _utc()
        self.session.flush()
        return record

    def materialize(
        self,
        *,
        workflow_run_id: UUID,
        nodes: Sequence[DagNode],
        edges: Sequence[DagEdge],
        max_fan_out: int = 64,
        occurred_at: datetime | None = None,
    ) -> tuple[DagReadyQueueRecord, ...]:
        now = _utc(occurred_at)
        topological_order(
            (node.operation_run_id for node in nodes),
            edges,
            max_fan_out=max_fan_out,
        )
        workflow = self.session.scalar(
            select(WorkflowRunRecord)
            .where(WorkflowRunRecord.id == workflow_run_id)
            .with_for_update()
        )
        if workflow is None:
            raise DagConflict("workflow run not found")
        if workflow.status not in {"DRAFT", "RUNNING"}:
            raise DagConflict("workflow run cannot be materialized")
        operations = {
            item.id: item
            for item in self.session.scalars(
                select(OperationRunRecord)
                .where(
                    OperationRunRecord.workflow_run_id == workflow_run_id,
                    OperationRunRecord.id.in_(
                        [node.operation_run_id for node in nodes]
                    ),
                )
                .with_for_update()
            )
        }
        if len(operations) != len(nodes) or any(
            item.project_id != workflow.project_id
            for item in operations.values()
        ):
            raise InvalidDag("all operations must belong to the workflow")
        if self.session.scalar(
            select(func.count())
            .select_from(OperationDependencyStateRecord)
            .where(
                OperationDependencyStateRecord.workflow_run_id
                == workflow_run_id
            )
        ):
            raise DagConflict("workflow DAG is already materialized")

        indegree = Counter(
            edge.downstream_operation_run_id for edge in edges
        )
        for edge in edges:
            self.session.add(
                WorkflowRunEdgeRecord(
                    project_id=workflow.project_id,
                    workflow_run_id=workflow.id,
                    upstream_operation_run_id=edge.upstream_operation_run_id,
                    downstream_operation_run_id=edge.downstream_operation_run_id,
                    required_status=edge.required_status,
                )
            )
        queue_rows: list[DagReadyQueueRecord] = []
        for node in nodes:
            dependency_count = indegree[node.operation_run_id]
            ready = dependency_count == 0
            operation = operations[node.operation_run_id]
            operation.status = "QUEUED" if ready else "CREATED"
            operation.state_version += 1
            operation.updated_at = now
            self.session.add(
                OperationDependencyStateRecord(
                    operation_run_id=node.operation_run_id,
                    project_id=workflow.project_id,
                    workflow_run_id=workflow.id,
                    dependency_count=dependency_count,
                    status="READY" if ready else "WAITING",
                    updated_at=now,
                )
            )
            queue = DagReadyQueueRecord(
                project_id=workflow.project_id,
                workflow_run_id=workflow.id,
                operation_run_id=node.operation_run_id,
                resource_pool=node.resource_pool,
                priority_class=node.priority_class,
                priority_value=_PRIORITY_VALUES[node.priority_class],
                estimated_cost_micros=node.estimated_cost_micros,
                state="READY" if ready else "WAITING",
                not_before=_utc(node.not_before or now),
                enqueued_at=now,
            )
            self.session.add(queue)
            queue_rows.append(queue)
        workflow.status = "RUNNING"
        workflow.state_version += 1
        workflow.started_at = workflow.started_at or now
        workflow.updated_at = now
        self.session.flush()
        for queue in queue_rows:
            self._append_scheduler_event(
                queue,
                "OPERATION_READY" if queue.state == "READY" else "OPERATION_WAITING",
                {
                    "dependency_count": indegree[queue.operation_run_id],
                    "resource_pool": queue.resource_pool,
                },
                now,
            )
        return tuple(queue_rows)

    def extend(
        self,
        *,
        workflow_run_id: UUID,
        nodes: Sequence[DagNode],
        edges: Sequence[DagEdge],
        max_fan_out: int = 64,
        occurred_at: datetime | None = None,
    ) -> tuple[DagReadyQueueRecord, ...]:
        """Append a bounded derived sub-DAG to a running workflow.

        Quality repair is a new immutable ``OperationRun``.  It must not
        mutate or retry the generation attempt that produced the rejected
        candidate.  This append-only operation allows a gate worker to add a
        same-stage repair branch whose downstream nodes are all new.  Existing
        nodes may only be upstream anchors, which makes introducing a cycle
        impossible and keeps historical edges immutable.
        """

        if not nodes:
            raise InvalidDag("a DAG extension must contain at least one node")
        now = _utc(occurred_at)
        new_ids = tuple(node.operation_run_id for node in nodes)
        new_id_set = set(new_ids)
        if len(new_ids) != len(new_id_set):
            raise InvalidDag("operation nodes must be unique")
        if any(
            edge.downstream_operation_run_id not in new_id_set
            for edge in edges
        ):
            raise InvalidDag(
                "DAG extensions may not rewrite existing downstream nodes"
            )
        topological_order(
            new_ids,
            (
                edge
                for edge in edges
                if edge.upstream_operation_run_id in new_id_set
            ),
            max_fan_out=max_fan_out,
        )

        workflow = self.session.scalar(
            select(WorkflowRunRecord)
            .where(WorkflowRunRecord.id == workflow_run_id)
            .with_for_update()
        )
        if workflow is None:
            raise DagConflict("workflow run not found")
        if workflow.status != "RUNNING":
            raise DagConflict("only a running workflow can be extended")

        referenced_ids = new_id_set | {
            edge.upstream_operation_run_id for edge in edges
        }
        operations = {
            item.id: item
            for item in self.session.scalars(
                select(OperationRunRecord)
                .where(
                    OperationRunRecord.workflow_run_id == workflow_run_id,
                    OperationRunRecord.id.in_(referenced_ids),
                )
                .with_for_update()
            )
        }
        if set(operations) != referenced_ids or any(
            item.project_id != workflow.project_id
            for item in operations.values()
        ):
            raise InvalidDag(
                "all extension operations must belong to the workflow"
            )
        existing_projection_ids = set(
            self.session.scalars(
                select(
                    OperationDependencyStateRecord.operation_run_id
                ).where(
                    OperationDependencyStateRecord.operation_run_id.in_(
                        new_id_set
                    )
                )
            )
        )
        if existing_projection_ids:
            raise DagConflict("workflow DAG extension is already materialized")

        incoming: dict[UUID, list[DagEdge]] = defaultdict(list)
        outgoing_counts: Counter[UUID] = Counter()
        pairs: set[tuple[UUID, UUID]] = set()
        for edge in edges:
            pair = (
                edge.upstream_operation_run_id,
                edge.downstream_operation_run_id,
            )
            if pair in pairs:
                raise InvalidDag("duplicate workflow edge")
            pairs.add(pair)
            outgoing_counts[pair[0]] += 1
            if outgoing_counts[pair[0]] > max_fan_out:
                raise InvalidDag(
                    "operation fan-out exceeds the configured bound"
                )
            incoming[pair[1]].append(edge)
            self.session.add(
                WorkflowRunEdgeRecord(
                    project_id=workflow.project_id,
                    workflow_run_id=workflow.id,
                    upstream_operation_run_id=pair[0],
                    downstream_operation_run_id=pair[1],
                    required_status=edge.required_status,
                )
            )

        queue_rows: list[DagReadyQueueRecord] = []
        for node in nodes:
            dependencies = incoming[node.operation_run_id]
            satisfied = 0
            failed = 0
            for edge in dependencies:
                if edge.upstream_operation_run_id in new_id_set:
                    continue
                upstream_status = operations[
                    edge.upstream_operation_run_id
                ].status
                if upstream_status == "SUCCEEDED" or (
                    edge.required_status == "TERMINAL"
                    and upstream_status in _TERMINAL_OPERATIONS
                ):
                    satisfied += 1
                elif upstream_status in _TERMINAL_OPERATIONS:
                    failed += 1
            ready = not failed and satisfied == len(dependencies)
            blocked = failed > 0
            operation = operations[node.operation_run_id]
            if operation.status != "CREATED":
                raise DagConflict(
                    "new extension operations must be in CREATED state"
                )
            operation.status = (
                "CANCELLED" if blocked else ("QUEUED" if ready else "CREATED")
            )
            operation.state_version += 1
            operation.updated_at = now
            projection_status = (
                "BLOCKED" if blocked else ("READY" if ready else "WAITING")
            )
            self.session.add(
                OperationDependencyStateRecord(
                    operation_run_id=node.operation_run_id,
                    project_id=workflow.project_id,
                    workflow_run_id=workflow.id,
                    dependency_count=len(dependencies),
                    satisfied_count=satisfied,
                    failed_count=failed,
                    status=projection_status,
                    updated_at=now,
                )
            )
            queue = DagReadyQueueRecord(
                project_id=workflow.project_id,
                workflow_run_id=workflow.id,
                operation_run_id=node.operation_run_id,
                resource_pool=node.resource_pool,
                priority_class=node.priority_class,
                priority_value=_PRIORITY_VALUES[node.priority_class],
                estimated_cost_micros=node.estimated_cost_micros,
                state=(
                    "CANCELLED"
                    if blocked
                    else ("READY" if ready else "WAITING")
                ),
                blocked_reason="upstream_failed" if blocked else None,
                not_before=_utc(node.not_before or now),
                enqueued_at=now,
            )
            self.session.add(queue)
            queue_rows.append(queue)
        self.session.flush()
        for queue in queue_rows:
            self._append_scheduler_event(
                queue,
                {
                    "READY": "OPERATION_READY",
                    "WAITING": "OPERATION_WAITING",
                    "CANCELLED": "OPERATION_BLOCKED",
                }[queue.state],
                {
                    "dag_extension": True,
                    "resource_pool": queue.resource_pool,
                },
                now,
            )
        return tuple(queue_rows)

    def claim(
        self,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=2),
        resource_pools: Iterable[str] | None = None,
        operation_types: Iterable[str] | None = None,
        candidate_filter: (
            Callable[[OperationRunRecord], bool] | None
        ) = None,
        request_builder: (
            Callable[[OperationRunRecord, UUID], "OperationRequest"] | None
        ) = None,
        occurred_at: datetime | None = None,
    ) -> DagLease | None:
        if not worker_id or len(worker_id) > 160:
            raise ValueError("worker_id is invalid")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        pools = frozenset(resource_pools or RESOURCE_POOLS)
        if not pools or not pools.issubset(RESOURCE_POOLS):
            raise ValueError("resource_pools contains an invalid pool")
        types = (
            None
            if operation_types is None
            else frozenset(operation_types)
        )
        if types is not None and (
            not types
            or any(
                not isinstance(value, str) or not value.strip()
                for value in types
            )
        ):
            raise ValueError("operation_types contains an invalid type")
        now = _utc(occurred_at)
        candidates = self._locked_candidates(pools, now, types)
        if not candidates:
            return None
        counters = self._fairness_counts(candidates)
        candidates.sort(
            key=lambda row: (
                -effective_priority(
                    row.priority_class,
                    row.enqueued_at,
                    now,
                    promotion_interval=self.promotion_interval,
                ),
                counters[("RESOURCE_POOL", row.resource_pool, row.resource_pool)],
                counters[("PROJECT", str(row.project_id), row.resource_pool)],
                counters[("WORKFLOW", str(row.workflow_run_id), row.resource_pool)],
                _utc(row.enqueued_at),
                str(row.id),
            )
        )
        for queue in candidates:
            operation = self.session.scalar(
                select(OperationRunRecord)
                .where(OperationRunRecord.id == queue.operation_run_id)
                .with_for_update()
            )
            if operation is None:
                raise DagConflict("ready queue projection is inconsistent")
            if (
                candidate_filter is not None
                and not candidate_filter(operation)
            ):
                self._record_queue(
                    queue, "capability_mismatch", now, counters
                )
                continue
            quota = self.session.scalar(
                select(ResourcePoolQuotaRecord)
                .where(
                    ResourcePoolQuotaRecord.resource_pool
                    == queue.resource_pool
                )
                .with_for_update()
            )
            if quota is None or quota.in_use >= quota.max_concurrent:
                self._record_queue(queue, "quota_blocked", now, counters)
                continue
            budget = self._assess_budget(queue)
            if not budget.allowed:
                queue.state = "BUDGET_BLOCKED"
                queue.blocked_reason = budget.reason_code
                queue.updated_at = now
                self._append_scheduler_event(
                    queue,
                    "ADMISSION_BLOCKED",
                    {
                        "reason_code": budget.reason_code,
                        "scope": budget.scope,
                    },
                    now,
                )
                self._record_queue(queue, "deferred", now, counters)
                continue

            dependency = self.session.scalar(
                select(OperationDependencyStateRecord)
                .where(
                    OperationDependencyStateRecord.operation_run_id
                    == queue.operation_run_id
                )
                .with_for_update()
            )
            if (
                operation is None
                or dependency is None
                or operation.status != "QUEUED"
                or dependency.status != "READY"
            ):
                raise DagConflict("ready queue projection is inconsistent")
            generation = queue.lease_generation + 1
            attempt_number = (
                self.session.scalar(
                    select(func.max(OperationAttemptRecord.attempt_number)).where(
                        OperationAttemptRecord.operation_run_id == operation.id
                    )
                )
                or 0
            ) + 1
            attempt_id = uuid4()
            if request_builder is None:
                request_payload = dict(operation.request_payload)
                request_digest = canonical_json_digest(request_payload)
                implementation_digest = canonical_json_digest(
                    {
                        "op_type": operation.op_type,
                        "op_version": operation.op_version,
                    }
                )
            else:
                request = request_builder(operation, attempt_id)
                if (
                    request.project_id != operation.project_id
                    or request.workflow_run_id
                    != operation.workflow_run_id
                    or request.operation_run_id != operation.id
                    or request.operation_attempt_id != attempt_id
                    or request.op_type != operation.op_type
                ):
                    raise DagConflict(
                        "operation request binding does not match claimed scope"
                    )
                request_payload = request.model_dump(mode="json")
                request_digest = canonical_json_digest(request_payload)
                implementation_digest = request.implementation_digest
            attempt = OperationAttemptRecord(
                id=attempt_id,
                project_id=operation.project_id,
                operation_run_id=operation.id,
                attempt_number=attempt_number,
                fencing_token=generation,
                worker_id=worker_id,
                implementation_digest=implementation_digest,
                submission_nonce=uuid4(),
                request_payload=request_payload,
                request_digest=request_digest,
            )
            self.session.add(attempt)
            self.session.flush()
            state = OperationAttemptStateRecord(
                attempt_id=attempt.id,
                project_id=operation.project_id,
                operation_run_id=operation.id,
                status="PREPARED",
                stage="ADMITTED",
                provider_state={},
                metrics={},
                error={},
                started_at=now,
                updated_at=now,
            )
            self.session.add(state)
            self.session.add(
                OperationAttemptEventRecord(
                    project_id=operation.project_id,
                    operation_run_id=operation.id,
                    attempt_id=attempt.id,
                    sequence=1,
                    state_version=0,
                    event_type="ATTEMPT_ADMITTED",
                    from_status=None,
                    to_status="PREPARED",
                    data={
                        "resource_pool": queue.resource_pool,
                        "fencing_token": generation,
                    },
                    data_digest=canonical_json_digest(
                        {
                            "resource_pool": queue.resource_pool,
                            "fencing_token": generation,
                        }
                    ),
                    occurred_at=now,
                )
            )
            self._reserve_budget_accounts(
                queue, attempt.id, generation, budget, now
            )
            expires_at = now + lease_duration
            queue.state = "LEASED"
            queue.lease_owner = worker_id
            queue.lease_generation = generation
            queue.lease_expires_at = expires_at
            queue.attempt_id = attempt.id
            queue.dispatch_count += 1
            queue.blocked_reason = None
            queue.updated_at = now
            dependency.status = "DISPATCHED"
            dependency.state_version += 1
            dependency.updated_at = now
            operation.status = "LEASED"
            operation.state_version += 1
            operation.updated_at = now
            quota.in_use += 1
            quota.state_version += 1
            quota.updated_at = now
            self._increment_fairness(queue, now)
            self._append_scheduler_event(
                queue,
                "OPERATION_CLAIMED",
                {
                    "fencing_token": generation,
                    "resource_pool": queue.resource_pool,
                },
                now,
                attempt_id=attempt.id,
            )
            self.session.flush()
            self._record_queue(queue, "claimed", now, counters)
            self._record_attempt(queue.resource_pool, "accepted")
            return DagLease(
                queue.id,
                queue.project_id,
                queue.workflow_run_id,
                queue.operation_run_id,
                attempt.id,
                worker_id,
                generation,
                queue.resource_pool,
                expires_at,
            )
        self.session.flush()
        return None

    def renew(
        self,
        lease: DagLease,
        *,
        lease_duration: timedelta = timedelta(minutes=2),
        occurred_at: datetime | None = None,
    ) -> datetime:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        now = _utc(occurred_at)
        queue = self._locked_lease(lease, now)
        queue.lease_expires_at = now + lease_duration
        queue.updated_at = now
        self.session.flush()
        return queue.lease_expires_at

    def complete(
        self,
        lease: DagLease,
        *,
        outcome: Literal["SUCCEEDED", "FAILED", "CANCELLED"],
        actual_cost_micros: int = 0,
        metrics: dict | None = None,
        error: dict | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if outcome not in _TERMINAL_OPERATIONS:
            raise ValueError("outcome is invalid")
        if (
            isinstance(actual_cost_micros, bool)
            or actual_cost_micros < 0
        ):
            raise ValueError("actual_cost_micros must be non-negative")
        now = _utc(occurred_at)
        workflow = self._locked_workflow(
            project_id=lease.project_id,
            workflow_run_id=lease.workflow_run_id,
        )
        queue = self._locked_lease(lease, now)
        operation = self.session.scalar(
            select(OperationRunRecord)
            .where(OperationRunRecord.id == lease.operation_run_id)
            .with_for_update()
        )
        state = self.session.scalar(
            select(OperationAttemptStateRecord)
            .where(OperationAttemptStateRecord.attempt_id == lease.attempt_id)
            .with_for_update()
        )
        dependency = self.session.scalar(
            select(OperationDependencyStateRecord)
            .where(
                OperationDependencyStateRecord.operation_run_id
                == lease.operation_run_id
            )
            .with_for_update()
        )
        if operation is None or state is None or dependency is None:
            raise DagConflict("leased projections are incomplete")
        from_status = state.status
        state.status = outcome
        state.stage = "TERMINAL"
        state.state_version += 1
        state.metrics = metrics or {}
        state.error = error or {}
        state.cost_micros = actual_cost_micros
        state.completed_at = now
        state.updated_at = now
        event_data = {
            "resource_pool": queue.resource_pool,
            "fencing_token": lease.fencing_token,
            "actual_cost_micros": actual_cost_micros,
        }
        self.session.add(
            OperationAttemptEventRecord(
                project_id=lease.project_id,
                operation_run_id=lease.operation_run_id,
                attempt_id=lease.attempt_id,
                sequence=state.state_version + 1,
                state_version=state.state_version,
                event_type=f"ATTEMPT_{outcome}",
                from_status=from_status,
                to_status=outcome,
                data=event_data,
                data_digest=canonical_json_digest(event_data),
                occurred_at=now,
            )
        )
        operation.status = outcome
        operation.state_version += 1
        operation.updated_at = now
        if outcome == "SUCCEEDED":
            attempt = self.session.get(
                OperationAttemptRecord, lease.attempt_id
            )
            operation.accepted_attempt_id = lease.attempt_id
            operation.accepted_attempt_number = attempt.attempt_number
        dependency.status = "TERMINAL"
        dependency.state_version += 1
        dependency.updated_at = now
        queue.state = "DONE" if outcome != "CANCELLED" else "CANCELLED"
        queue.lease_owner = None
        queue.lease_expires_at = None
        queue.updated_at = now
        self._release_quota(queue.resource_pool, now)
        self._settle_budget_accounts(queue, actual_cost_micros, now)
        self._append_scheduler_event(
            queue,
            f"OPERATION_{outcome}",
            event_data,
            now,
            attempt_id=lease.attempt_id,
        )
        self._advance_downstream(
            queue, succeeded=outcome == "SUCCEEDED", now=now
        )
        self._finish_workflow_if_terminal(workflow, now)
        self.session.flush()
        self._record_attempt(
            queue.resource_pool,
            {
                "SUCCEEDED": "succeeded",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }[outcome],
        )

    def wait_for_human(
        self,
        lease: DagLease,
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> None:
        if not reason or len(reason) > 100:
            raise ValueError("reason is invalid")
        now = _utc(occurred_at)
        workflow = self._locked_workflow(
            project_id=lease.project_id,
            workflow_run_id=lease.workflow_run_id,
        )
        queue = self._locked_lease(lease, now)
        state = self.session.scalar(
            select(OperationAttemptStateRecord)
            .where(OperationAttemptStateRecord.attempt_id == lease.attempt_id)
            .with_for_update()
        )
        dependency = self.session.scalar(
            select(OperationDependencyStateRecord)
            .where(
                OperationDependencyStateRecord.operation_run_id
                == lease.operation_run_id
            )
            .with_for_update()
        )
        if workflow is None or state is None or dependency is None:
            raise DagConflict("human-wait projections are incomplete")
        from_status = state.status
        state.status = "OUTCOME_UNKNOWN"
        state.stage = "WAITING_HUMAN"
        state.state_version += 1
        state.error = {"reason": reason}
        state.updated_at = now
        payload = {"reason": reason, "fencing_token": lease.fencing_token}
        self.session.add(
            OperationAttemptEventRecord(
                project_id=lease.project_id,
                operation_run_id=lease.operation_run_id,
                attempt_id=lease.attempt_id,
                sequence=state.state_version + 1,
                state_version=state.state_version,
                event_type="ATTEMPT_WAITING_HUMAN",
                from_status=from_status,
                to_status="OUTCOME_UNKNOWN",
                data=payload,
                data_digest=canonical_json_digest(payload),
                occurred_at=now,
            )
        )
        workflow.status = "WAITING_HUMAN"
        workflow.state_version += 1
        workflow.updated_at = now
        queue.state = "PAUSED_HUMAN"
        queue.lease_owner = None
        queue.lease_expires_at = None
        queue.blocked_reason = reason
        queue.updated_at = now
        dependency.status = "PAUSED_HUMAN"
        dependency.state_version += 1
        dependency.updated_at = now
        paused = self.session.scalars(
            select(DagReadyQueueRecord)
            .where(
                DagReadyQueueRecord.workflow_run_id == lease.workflow_run_id,
                DagReadyQueueRecord.state == "READY",
            )
            .with_for_update()
        ).all()
        for item in paused:
            item.state = "PAUSED_HUMAN"
            item.blocked_reason = "workflow_waiting_human"
            item.updated_at = now
            projection = self.session.get(
                OperationDependencyStateRecord,
                item.operation_run_id,
                with_for_update=True,
            )
            projection.status = "PAUSED_HUMAN"
            projection.state_version += 1
            projection.updated_at = now
        self._release_quota(queue.resource_pool, now)
        self._append_scheduler_event(
            queue,
            "WORKFLOW_WAITING_HUMAN",
            payload,
            now,
            attempt_id=lease.attempt_id,
        )
        self.session.flush()
        self._record_queue(queue, "waiting_human", now, defaultdict(int))
        self._record_attempt(queue.resource_pool, "needs_human")

    def resume_after_human(
        self,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        decision: Literal["ACCEPT", "REWORK", "REJECT"],
        review_task_id: UUID | None = None,
        gate_operation_run_id: UUID | None = None,
        gate_operation_attempt_id: UUID | None = None,
        gate_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> int:
        """Settle the waiting gate and resume its project-scoped workflow.

        The workflow row is the serialization boundary shared with review
        creation. Callers own the transaction, so the review decision and all
        durable scheduler projections commit or roll back together.
        """

        if decision not in {"ACCEPT", "REWORK", "REJECT"}:
            raise ValueError("human review decision is invalid")
        if (gate_operation_run_id is None) != (
            gate_operation_attempt_id is None
        ):
            raise ValueError(
                "human review gate operation and attempt must be paired"
            )
        now = _utc(occurred_at)
        workflow = self.session.scalar(
            select(WorkflowRunRecord)
            .where(
                WorkflowRunRecord.id == workflow_run_id,
                WorkflowRunRecord.project_id == project_id,
            )
            .with_for_update()
        )
        if workflow is None:
            raise DagConflict("workflow run not found in project")
        if review_task_id is not None:
            review_task = self.session.scalar(
                select(HumanReviewTaskRecord)
                .where(
                    HumanReviewTaskRecord.id == review_task_id,
                    HumanReviewTaskRecord.project_id == project_id,
                    HumanReviewTaskRecord.workflow_run_id
                    == workflow_run_id,
                )
                .with_for_update()
            )
            if review_task is None:
                raise DagConflict("human review task not found in workflow")
            if (
                review_task.status != "DECIDED"
                or review_task.decision != decision
            ):
                raise DagConflict(
                    "human review task does not carry this decision"
                )
            if (
                gate_operation_run_id is not None
                and review_task.gate_operation_run_id
                != gate_operation_run_id
            ):
                raise DagConflict(
                    "human review task gate operation binding changed"
                )
            if (
                gate_operation_attempt_id is not None
                and review_task.gate_operation_attempt_id
                != gate_operation_attempt_id
            ):
                raise DagConflict(
                    "human review task gate attempt binding changed"
                )
            gate_operation_run_id = review_task.gate_operation_run_id
            gate_operation_attempt_id = (
                review_task.gate_operation_attempt_id
            )
            gate_key = review_task.gate_key
        if workflow.status != "WAITING_HUMAN":
            return 0

        queues = self.session.scalars(
            select(DagReadyQueueRecord)
            .where(
                DagReadyQueueRecord.project_id == project_id,
                DagReadyQueueRecord.workflow_run_id == workflow_run_id,
                DagReadyQueueRecord.state == "PAUSED_HUMAN",
            )
            .order_by(DagReadyQueueRecord.id)
            .with_for_update()
        ).all()
        projections: dict[UUID, OperationDependencyStateRecord] = {}
        operations: dict[UUID, OperationRunRecord] = {}
        attempt_states: dict[UUID, OperationAttemptStateRecord] = {}
        for queue in queues:
            projection = self.session.scalar(
                select(OperationDependencyStateRecord)
                .where(
                    OperationDependencyStateRecord.operation_run_id
                    == queue.operation_run_id,
                    OperationDependencyStateRecord.project_id == project_id,
                    OperationDependencyStateRecord.workflow_run_id
                    == workflow_run_id,
                )
                .with_for_update()
            )
            operation = self.session.scalar(
                select(OperationRunRecord)
                .where(
                    OperationRunRecord.id == queue.operation_run_id,
                    OperationRunRecord.project_id == project_id,
                    OperationRunRecord.workflow_run_id == workflow_run_id,
                )
                .with_for_update()
            )
            if projection is None or operation is None:
                raise DagConflict(
                    "human-resume scheduler projections are inconsistent"
                )
            projections[queue.operation_run_id] = projection
            operations[queue.operation_run_id] = operation
            if queue.attempt_id is not None:
                state = self.session.scalar(
                    select(OperationAttemptStateRecord)
                    .where(
                        OperationAttemptStateRecord.attempt_id
                        == queue.attempt_id,
                        OperationAttemptStateRecord.project_id == project_id,
                        OperationAttemptStateRecord.operation_run_id
                        == queue.operation_run_id,
                    )
                    .with_for_update()
                )
                if state is not None:
                    attempt_states[queue.operation_run_id] = state

        waiting_candidates = [
            queue
            for queue in queues
            if (
                queue.operation_run_id in attempt_states
                and attempt_states[queue.operation_run_id].stage
                == "WAITING_HUMAN"
            )
        ]
        if gate_operation_run_id is not None:
            waiting_queues = [
                queue
                for queue in waiting_candidates
                if queue.operation_run_id == gate_operation_run_id
                and queue.attempt_id == gate_operation_attempt_id
            ]
        elif gate_key is not None:
            waiting_queues = [
                queue
                for queue in waiting_candidates
                if (
                    operations[queue.operation_run_id]
                    .request_payload.get("gate_key")
                    == gate_key
                    or (
                        operations[queue.operation_run_id]
                        .request_payload.get("gate_key")
                        is None
                        and (
                            operations[
                                queue.operation_run_id
                            ].node_key
                            == gate_key
                            or gate_key.endswith(
                                ":"
                                + operations[
                                    queue.operation_run_id
                                ].node_key
                            )
                        )
                    )
                )
            ]
        else:
            waiting_queues = waiting_candidates
        if len(waiting_queues) > 1:
            raise DagConflict("review does not identify one waiting gate")

        settled = 0
        if waiting_queues:
            queue = waiting_queues[0]
            operation = operations[queue.operation_run_id]
            projection = projections[queue.operation_run_id]
            state = attempt_states[queue.operation_run_id]
            if (
                queue.attempt_id is None
                or projection.status != "PAUSED_HUMAN"
                or operation.status not in {"LEASED", "RUNNING"}
                or state.status != "OUTCOME_UNKNOWN"
            ):
                raise DagConflict(
                    "waiting human gate attempt is inconsistent"
                )
            outcome = {
                "ACCEPT": "SUCCEEDED",
                "REWORK": "FAILED",
                "REJECT": "CANCELLED",
            }[decision]
            from_status = state.status
            state.status = outcome
            state.stage = "TERMINAL"
            state.state_version += 1
            state.error = {
                **dict(state.error or {}),
                "human_review_decision": decision,
            }
            state.completed_at = now
            state.updated_at = now
            event_data = {
                "human_review_decision": decision,
                "review_task_id": (
                    None
                    if review_task_id is None
                    else str(review_task_id)
                ),
            }
            self.session.add(
                OperationAttemptEventRecord(
                    project_id=project_id,
                    operation_run_id=queue.operation_run_id,
                    attempt_id=queue.attempt_id,
                    sequence=state.state_version + 1,
                    state_version=state.state_version,
                    event_type=f"ATTEMPT_{outcome}",
                    from_status=from_status,
                    to_status=outcome,
                    data=event_data,
                    data_digest=canonical_json_digest(event_data),
                    occurred_at=now,
                )
            )
            operation.status = outcome
            operation.state_version += 1
            operation.updated_at = now
            if outcome == "SUCCEEDED":
                attempt = self.session.get(
                    OperationAttemptRecord,
                    queue.attempt_id,
                )
                if attempt is None:
                    raise DagConflict("waiting gate attempt is unavailable")
                operation.accepted_attempt_id = queue.attempt_id
                operation.accepted_attempt_number = attempt.attempt_number
            projection.status = "TERMINAL"
            projection.state_version += 1
            projection.updated_at = now
            queue.state = (
                "CANCELLED" if outcome == "CANCELLED" else "DONE"
            )
            queue.blocked_reason = None
            queue.updated_at = now
            self._settle_budget_accounts(
                queue,
                int(state.cost_micros or 0),
                now,
            )
            self._append_scheduler_event(
                queue,
                f"OPERATION_{outcome}_AFTER_HUMAN",
                event_data,
                now,
                attempt_id=queue.attempt_id,
            )
            self._advance_downstream(
                queue,
                succeeded=outcome == "SUCCEEDED",
                now=now,
            )
            self._record_attempt(
                queue.resource_pool,
                {
                    "SUCCEEDED": "succeeded",
                    "FAILED": "failed",
                    "CANCELLED": "cancelled",
                }[outcome],
            )
            settled = 1

        open_reviews = (
            self.session.scalar(
                select(func.count())
                .select_from(HumanReviewTaskRecord)
                .where(
                    HumanReviewTaskRecord.project_id == project_id,
                    HumanReviewTaskRecord.workflow_run_id == workflow_run_id,
                    HumanReviewTaskRecord.status == "OPEN",
                )
            )
            or 0
        )
        if open_reviews:
            self.session.flush()
            return settled

        blocking_decisions = set(
            self.session.scalars(
                select(HumanReviewTaskRecord.decision)
                .where(
                    HumanReviewTaskRecord.project_id == project_id,
                    HumanReviewTaskRecord.workflow_run_id == workflow_run_id,
                    HumanReviewTaskRecord.status == "DECIDED",
                    HumanReviewTaskRecord.decision.in_(
                        ("REWORK", "REJECT")
                    ),
                )
            ).all()
        )
        blocking_reviews = bool(blocking_decisions)
        workflow.status = "BLOCKED" if blocking_reviews else "RUNNING"
        workflow.state_version += 1
        workflow.updated_at = now

        remaining_queues = self.session.scalars(
            select(DagReadyQueueRecord)
            .where(
                DagReadyQueueRecord.project_id == project_id,
                DagReadyQueueRecord.workflow_run_id == workflow_run_id,
                DagReadyQueueRecord.state == "PAUSED_HUMAN",
            )
            .order_by(DagReadyQueueRecord.id)
            .with_for_update()
        ).all()
        resumed = settled
        for queue in remaining_queues:
            projection = self.session.scalar(
                select(OperationDependencyStateRecord)
                .where(
                    OperationDependencyStateRecord.operation_run_id
                    == queue.operation_run_id,
                    OperationDependencyStateRecord.project_id == project_id,
                    OperationDependencyStateRecord.workflow_run_id
                    == workflow_run_id,
                )
                .with_for_update()
            )
            operation = self.session.scalar(
                select(OperationRunRecord)
                .where(
                    OperationRunRecord.id == queue.operation_run_id,
                    OperationRunRecord.project_id == project_id,
                    OperationRunRecord.workflow_run_id == workflow_run_id,
                )
                .with_for_update()
            )
            if projection is None or operation is None:
                raise DagConflict(
                    "paused downstream projection is unavailable"
                )
            if blocking_reviews:
                projection.status = "BLOCKED"
                projection.state_version += 1
                projection.updated_at = now
                operation.status = "CANCELLED"
                operation.state_version += 1
                operation.updated_at = now
                queue.state = "CANCELLED"
                queue.blocked_reason = (
                    "human_rework_requires_repair"
                    if "REWORK" in blocking_decisions
                    else "human_review_rejected"
                )
                queue.updated_at = now
                self._append_scheduler_event(
                    queue,
                    "WORKFLOW_BLOCKED_AFTER_HUMAN",
                    {
                        "review_task_id": (
                            None
                            if review_task_id is None
                            else str(review_task_id)
                        ),
                        "decision": decision,
                    },
                    now,
                    attempt_id=queue.attempt_id,
                )
                continue
            if (
                projection.status != "PAUSED_HUMAN"
                or operation.status != "QUEUED"
            ):
                raise DagConflict(
                    "paused downstream projection is inconsistent"
                )
            projection.status = "READY"
            projection.state_version += 1
            projection.updated_at = now
            operation.status = "QUEUED"
            operation.state_version += 1
            operation.updated_at = now
            queue.state = "READY"
            queue.blocked_reason = None
            queue.enqueued_at = now
            queue.not_before = max(_utc(queue.not_before), now)
            queue.updated_at = now
            self._append_scheduler_event(
                queue,
                "WORKFLOW_RESUMED_AFTER_HUMAN",
                {
                    "project_id": str(project_id),
                    "workflow_run_id": str(workflow_run_id),
                    "review_task_id": (
                        None
                        if review_task_id is None
                        else str(review_task_id)
                    ),
                },
                now,
                attempt_id=queue.attempt_id,
            )
            resumed += 1

        self.session.flush()
        return resumed

    def requeue_budget_blocked(
        self,
        *,
        workflow_run_id: UUID | None = None,
        resource_pool: str | None = None,
        occurred_at: datetime | None = None,
        limit: int = 100,
    ) -> int:
        if resource_pool is not None and resource_pool not in RESOURCE_POOLS:
            raise ValueError("resource_pool is invalid")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        now = _utc(occurred_at)
        statement = (
            select(DagReadyQueueRecord)
            .where(DagReadyQueueRecord.state == "BUDGET_BLOCKED")
            .order_by(DagReadyQueueRecord.enqueued_at, DagReadyQueueRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if workflow_run_id is not None:
            statement = statement.where(
                DagReadyQueueRecord.workflow_run_id == workflow_run_id
            )
        if resource_pool is not None:
            statement = statement.where(
                DagReadyQueueRecord.resource_pool == resource_pool
            )
        rows = self.session.scalars(statement).all()
        for row in rows:
            row.state = "READY"
            row.blocked_reason = None
            row.updated_at = now
            self._append_scheduler_event(
                row, "ADMISSION_REQUEUED", {}, now
            )
        self.session.flush()
        return len(rows)

    def recover_expired(
        self,
        *,
        occurred_at: datetime | None = None,
        limit: int = 100,
    ) -> int:
        now = _utc(occurred_at)
        rows = self.session.scalars(
            select(DagReadyQueueRecord)
            .where(
                DagReadyQueueRecord.state == "LEASED",
                DagReadyQueueRecord.lease_expires_at <= now,
            )
            .order_by(
                DagReadyQueueRecord.lease_expires_at,
                DagReadyQueueRecord.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for queue in rows:
            state = self.session.get(
                OperationAttemptStateRecord,
                queue.attempt_id,
                with_for_update=True,
            )
            operation = self.session.get(
                OperationRunRecord,
                queue.operation_run_id,
                with_for_update=True,
            )
            dependency = self.session.get(
                OperationDependencyStateRecord,
                queue.operation_run_id,
                with_for_update=True,
            )
            provider = self.session.scalar(
                select(ProviderInvocationRecord)
                .where(
                    ProviderInvocationRecord.operation_attempt_id
                    == queue.attempt_id,
                    ProviderInvocationRecord.operation_run_id
                    == queue.operation_run_id,
                    ProviderInvocationRecord.project_id
                    == queue.project_id,
                    ProviderInvocationRecord.submit_started_at.is_not(None),
                )
                .with_for_update()
            )
            if provider is not None:
                workflow = self.session.get(
                    WorkflowRunRecord,
                    queue.workflow_run_id,
                    with_for_update=True,
                )
                if workflow is None:
                    raise DagConflict(
                        "provider recovery workflow is unavailable"
                    )
                previous = state.status
                reason = "provider_reconcile_required"
                state.status = "OUTCOME_UNKNOWN"
                state.stage = "WAITING_HUMAN"
                state.state_version += 1
                state.error = {
                    "reason": reason,
                    "provider_invocation_id": str(provider.id),
                    "provider_phase": provider.phase,
                }
                state.updated_at = now
                payload = {
                    "reason": reason,
                    "resource_pool": queue.resource_pool,
                    "fencing_token": queue.lease_generation,
                    "provider_invocation_id": str(provider.id),
                    "provider_phase": provider.phase,
                }
                self.session.add(
                    OperationAttemptEventRecord(
                        project_id=queue.project_id,
                        operation_run_id=queue.operation_run_id,
                        attempt_id=queue.attempt_id,
                        sequence=state.state_version + 1,
                        state_version=state.state_version,
                        event_type=(
                            "ATTEMPT_PROVIDER_RECONCILE_REQUIRED"
                        ),
                        from_status=previous,
                        to_status="OUTCOME_UNKNOWN",
                        data=payload,
                        data_digest=canonical_json_digest(payload),
                        occurred_at=now,
                    )
                )
                workflow.status = "WAITING_HUMAN"
                workflow.state_version += 1
                workflow.updated_at = now
                queue.state = "PAUSED_HUMAN"
                queue.lease_owner = None
                queue.lease_expires_at = None
                queue.blocked_reason = reason
                queue.updated_at = now
                dependency.status = "PAUSED_HUMAN"
                dependency.state_version += 1
                dependency.updated_at = now
                paused = self.session.scalars(
                    select(DagReadyQueueRecord)
                    .where(
                        DagReadyQueueRecord.workflow_run_id
                        == queue.workflow_run_id,
                        DagReadyQueueRecord.state == "READY",
                    )
                    .with_for_update()
                ).all()
                for item in paused:
                    item.state = "PAUSED_HUMAN"
                    item.blocked_reason = "workflow_waiting_human"
                    item.updated_at = now
                    projection = self.session.get(
                        OperationDependencyStateRecord,
                        item.operation_run_id,
                        with_for_update=True,
                    )
                    if projection is not None:
                        projection.status = "PAUSED_HUMAN"
                        projection.state_version += 1
                        projection.updated_at = now
                self._release_quota(queue.resource_pool, now)
                self._append_scheduler_event(
                    queue,
                    "PROVIDER_RECONCILE_REQUIRED",
                    payload,
                    now,
                    attempt_id=queue.attempt_id,
                )
                self._record_queue(
                    queue,
                    "waiting_human",
                    now,
                    defaultdict(int),
                )
                self._record_attempt(
                    queue.resource_pool,
                    "needs_human",
                )
                continue
            previous = state.status
            state.status = "STALE"
            state.stage = "LEASE_EXPIRED"
            state.state_version += 1
            state.completed_at = now
            state.updated_at = now
            payload = {
                "resource_pool": queue.resource_pool,
                "fencing_token": queue.lease_generation,
            }
            self.session.add(
                OperationAttemptEventRecord(
                    project_id=queue.project_id,
                    operation_run_id=queue.operation_run_id,
                    attempt_id=queue.attempt_id,
                    sequence=state.state_version + 1,
                    state_version=state.state_version,
                    event_type="ATTEMPT_LEASE_EXPIRED",
                    from_status=previous,
                    to_status="STALE",
                    data=payload,
                    data_digest=canonical_json_digest(payload),
                    occurred_at=now,
                )
            )
            operation.status = "QUEUED"
            operation.state_version += 1
            operation.updated_at = now
            dependency.status = "READY"
            dependency.state_version += 1
            dependency.updated_at = now
            queue.state = "READY"
            queue.lease_owner = None
            queue.lease_expires_at = None
            queue.blocked_reason = "lease_expired"
            queue.enqueued_at = now
            queue.updated_at = now
            self._release_quota(queue.resource_pool, now)
            self._release_budget_accounts(queue, now)
            self._append_scheduler_event(
                queue,
                "OPERATION_LEASE_EXPIRED",
                payload,
                now,
                attempt_id=queue.attempt_id,
            )
            self._record_attempt(queue.resource_pool, "lease_expired")
        self.session.flush()
        return len(rows)

    def _locked_candidates(
        self,
        pools: frozenset[str],
        now: datetime,
        operation_types: frozenset[str] | None = None,
    ) -> list[DagReadyQueueRecord]:
        if (
            self.session.bind is not None
            and self.session.bind.dialect.name == "postgresql"
        ):
            pool_counter = aliased(SchedulerFairnessCounterRecord)
            project_counter = aliased(SchedulerFairnessCounterRecord)
            workflow_counter = aliased(SchedulerFairnessCounterRecord)
            pool_count = (
                select(pool_counter.dispatch_count)
                .where(
                    pool_counter.scope_kind == "RESOURCE_POOL",
                    pool_counter.scope_key
                    == DagReadyQueueRecord.resource_pool,
                    pool_counter.resource_pool
                    == DagReadyQueueRecord.resource_pool,
                )
                .correlate(DagReadyQueueRecord)
                .scalar_subquery()
            )
            project_count = (
                select(project_counter.dispatch_count)
                .where(
                    project_counter.scope_kind == "PROJECT",
                    project_counter.scope_key
                    == cast(DagReadyQueueRecord.project_id, String),
                    project_counter.resource_pool
                    == DagReadyQueueRecord.resource_pool,
                )
                .correlate(DagReadyQueueRecord)
                .scalar_subquery()
            )
            workflow_count = (
                select(workflow_counter.dispatch_count)
                .where(
                    workflow_counter.scope_kind == "WORKFLOW",
                    workflow_counter.scope_key
                    == cast(DagReadyQueueRecord.workflow_run_id, String),
                    workflow_counter.resource_pool
                    == DagReadyQueueRecord.resource_pool,
                )
                .correlate(DagReadyQueueRecord)
                .scalar_subquery()
            )
            waited_seconds = func.extract(
                "epoch", literal(now) - DagReadyQueueRecord.enqueued_at
            )
            promoted_priority = func.least(
                399,
                DagReadyQueueRecord.priority_value
                + cast(
                    func.floor(
                        waited_seconds
                        / self.promotion_interval.total_seconds()
                    ),
                    Integer,
                ),
            )
            statement = (
                select(DagReadyQueueRecord)
                .join(
                    WorkflowRunRecord,
                    WorkflowRunRecord.id
                    == DagReadyQueueRecord.workflow_run_id,
                )
                .join(
                    OperationRunRecord,
                    OperationRunRecord.id
                    == DagReadyQueueRecord.operation_run_id,
                )
                .join(
                    ResourcePoolQuotaRecord,
                    ResourcePoolQuotaRecord.resource_pool
                    == DagReadyQueueRecord.resource_pool,
                )
                .where(
                    DagReadyQueueRecord.state == "READY",
                    DagReadyQueueRecord.resource_pool.in_(sorted(pools)),
                    DagReadyQueueRecord.not_before <= now,
                    WorkflowRunRecord.status == "RUNNING",
                    ResourcePoolQuotaRecord.in_use
                    < ResourcePoolQuotaRecord.max_concurrent,
                )
                .order_by(
                    promoted_priority.desc(),
                    func.coalesce(pool_count, 0),
                    func.coalesce(project_count, 0),
                    func.coalesce(workflow_count, 0),
                    DagReadyQueueRecord.enqueued_at,
                    DagReadyQueueRecord.id,
                )
                .limit(1)
                .with_for_update(
                    of=DagReadyQueueRecord, skip_locked=True
                )
            )
            if operation_types is not None:
                statement = statement.where(
                    OperationRunRecord.op_type.in_(
                        sorted(operation_types)
                    )
                )
            return list(self.session.scalars(statement).all())

        statement = (
            select(DagReadyQueueRecord)
            .join(
                WorkflowRunRecord,
                WorkflowRunRecord.id == DagReadyQueueRecord.workflow_run_id,
            )
            .join(
                OperationRunRecord,
                OperationRunRecord.id
                == DagReadyQueueRecord.operation_run_id,
            )
            .where(
                DagReadyQueueRecord.state == "READY",
                DagReadyQueueRecord.resource_pool.in_(sorted(pools)),
                DagReadyQueueRecord.not_before <= now,
                WorkflowRunRecord.status == "RUNNING",
            )
            .order_by(
                DagReadyQueueRecord.priority_value.desc(),
                DagReadyQueueRecord.enqueued_at,
                DagReadyQueueRecord.id,
            )
            .limit(self.max_candidate_scan)
        )
        if operation_types is not None:
            statement = statement.where(
                OperationRunRecord.op_type.in_(sorted(operation_types))
            )
        statement = statement.with_for_update()
        return list(self.session.scalars(statement).all())

    def _fairness_counts(
        self, candidates: Sequence[DagReadyQueueRecord]
    ) -> defaultdict[tuple[str, str, str], int]:
        result: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        if not candidates:
            return result
        pools = {item.resource_pool for item in candidates}
        keys = {
            item.resource_pool for item in candidates
        } | {str(item.project_id) for item in candidates} | {
            str(item.workflow_run_id) for item in candidates
        }
        rows = self.session.scalars(
            select(SchedulerFairnessCounterRecord).where(
                SchedulerFairnessCounterRecord.resource_pool.in_(pools),
                SchedulerFairnessCounterRecord.scope_key.in_(keys),
            )
        ).all()
        for row in rows:
            result[(row.scope_kind, row.scope_key, row.resource_pool)] = (
                row.dispatch_count
            )
        return result

    def _assess_budget(self, queue: DagReadyQueueRecord) -> BudgetDecision:
        proposal = CostProposal(
            resource_pool=queue.resource_pool,
            estimated_micros=queue.estimated_cost_micros,
            project_id=str(queue.project_id),
            workflow_id=str(queue.workflow_run_id),
        )
        if self.budget_guard is None:
            return BudgetDecision(
                verdict="block",
                reason_code="cost_policy_required",
                scope="unconfigured",
                limiting_budget_id=None,
                projected_micros=None,
                hard_limit_micros=None,
            )
        budgets = sorted(
            (
                item
                for item in self.budget_guard.policy.budgets
                if item.applies_to(proposal)
            ),
            key=lambda item: (_SCOPE_ORDER[item.scope], item.budget_id),
        )
        if not budgets:
            return BudgetDecision(
                verdict="block",
                reason_code="cost_policy_required",
                scope="unconfigured",
                limiting_budget_id=None,
                projected_micros=None,
                hard_limit_micros=None,
            )
        rows = self._locked_budget_accounts(queue, budgets)
        accounts = {row["account_key"]: row for row in rows}
        usage: dict[str, BudgetUsage] = {}
        for budget in budgets:
            account = accounts.get(budget.budget_id)
            if account is None:
                return BudgetDecision(
                    verdict="block",
                    reason_code="cost_usage_snapshot_required",
                    scope=budget.scope,
                    limiting_budget_id=budget.budget_id,
                    projected_micros=None,
                    hard_limit_micros=budget.hard_limit_micros,
                )
            if account["limit_micros"] != budget.hard_limit_micros:
                return BudgetDecision(
                    verdict="block",
                    reason_code="cost_policy_account_mismatch",
                    scope=budget.scope,
                    limiting_budget_id=budget.budget_id,
                    projected_micros=None,
                    hard_limit_micros=budget.hard_limit_micros,
                )
            usage[budget.budget_id] = BudgetUsage(
                spent_micros=account["settled_micros"],
                reserved_micros=account["reserved_micros"],
            )
        return self.budget_guard.assess(
            proposal, usage_by_budget=usage
        )

    def _locked_budget_accounts(
        self,
        queue: DagReadyQueueRecord,
        budgets: Sequence[CostBudget],
    ) -> list[dict]:
        keys = [item.budget_id for item in budgets]
        statement = (
            select(BudgetAccountRecord)
            .where(
                BudgetAccountRecord.resource_pool == queue.resource_pool,
                BudgetAccountRecord.account_key.in_(keys),
                (
                    (
                        (BudgetAccountRecord.scope_kind == "GLOBAL")
                        & BudgetAccountRecord.project_id.is_(None)
                        & BudgetAccountRecord.workflow_run_id.is_(None)
                    )
                    | (
                        (BudgetAccountRecord.scope_kind == "PROJECT")
                        & (
                            BudgetAccountRecord.project_id
                            == queue.project_id
                        )
                        & BudgetAccountRecord.workflow_run_id.is_(None)
                    )
                    | (
                        (BudgetAccountRecord.scope_kind == "WORKFLOW")
                        & (
                            BudgetAccountRecord.project_id
                            == queue.project_id
                        )
                        & (
                            BudgetAccountRecord.workflow_run_id
                            == queue.workflow_run_id
                        )
                    )
                ),
            )
            .order_by(
                case(
                    (BudgetAccountRecord.scope_kind == "GLOBAL", 0),
                    (BudgetAccountRecord.scope_kind == "PROJECT", 1),
                    else_=2,
                ),
                BudgetAccountRecord.id,
            )
            .with_for_update()
        )
        return [
            {
                "id": row.id,
                "account_key": row.account_key,
                "scope_kind": row.scope_kind,
                "project_id": row.project_id,
                "workflow_run_id": row.workflow_run_id,
                "resource_pool": row.resource_pool,
                "limit_micros": row.limit_micros,
                "reserved_micros": row.reserved_micros,
                "settled_micros": row.settled_micros,
                "state_version": row.state_version,
            }
            for row in self.session.scalars(statement)
        ]

    def _reserve_budget_accounts(
        self,
        queue: DagReadyQueueRecord,
        attempt_id: UUID,
        generation: int,
        decision: BudgetDecision,
        now: datetime,
    ) -> None:
        amount = queue.estimated_cost_micros
        if amount == 0:
            return
        proposal = CostProposal(
            resource_pool=queue.resource_pool,
            estimated_micros=amount,
            project_id=str(queue.project_id),
            workflow_id=str(queue.workflow_run_id),
        )
        budgets = sorted(
            (
                item
                for item in self.budget_guard.policy.budgets
                if item.applies_to(proposal)
            ),
            key=lambda item: (_SCOPE_ORDER[item.scope], item.budget_id),
        )
        accounts = {
            row["account_key"]: row
            for row in self._locked_budget_accounts(queue, budgets)
        }
        for budget in budgets:
            account = accounts[budget.budget_id]
            new_reserved = account["reserved_micros"] + amount
            changed = self.session.execute(
                text(
                    """
                    UPDATE orchestration.budget_accounts
                    SET reserved_micros = :reserved,
                        state_version = state_version + 1,
                        updated_at = :now
                    WHERE id = :account_id
                      AND state_version = :state_version
                    """
                ),
                {
                    "reserved": new_reserved,
                    "now": now,
                    "account_id": account["id"],
                    "state_version": account["state_version"],
                },
            )
            if changed.rowcount != 1:
                raise DagConflict("budget account changed during admission")
            reservation_id = uuid4()
            command = (
                f"dag:{queue.id}:{generation}:{budget.scope}:"
                f"{budget.budget_id}"
            )
            metadata = {
                "resource_pool": queue.resource_pool,
                "scope": budget.scope,
                "queue_entry_id": str(queue.id),
                "fencing_token": generation,
            }
            reservation = BudgetReservationRecord(
                id=reservation_id,
                project_id=queue.project_id,
                account_id=account["id"],
                operation_run_id=queue.operation_run_id,
                operation_attempt_id=attempt_id,
                command_idempotency_key=command,
                amount_micros=amount,
            )
            self.session.add(reservation)
            self.session.flush()
            self.session.add(
                BudgetLedgerEntryRecord(
                    id=uuid4(),
                    project_id=queue.project_id,
                    account_id=account["id"],
                    reservation_id=reservation_id,
                    sequence=1,
                    command_idempotency_key=command,
                    entry_type="RESERVE",
                    reserved_delta_micros=amount,
                    settled_delta_micros=0,
                    reserved_balance_micros=new_reserved,
                    settled_balance_micros=account["settled_micros"],
                    metadata_payload=metadata,
                    metadata_digest=canonical_json_digest(metadata),
                )
            )
            self.session.add(
                DagAdmissionReservationRecord(
                    queue_entry_id=queue.id,
                    lease_generation=generation,
                    project_id=queue.project_id,
                    attempt_id=attempt_id,
                    budget_account_id=account["id"],
                    budget_reservation_id=reservation_id,
                    amount_micros=amount,
                )
            )
            account["reserved_micros"] = new_reserved
            account["state_version"] += 1
        self.session.flush()

    def _settle_budget_accounts(
        self,
        queue: DagReadyQueueRecord,
        actual_micros: int,
        now: datetime,
    ) -> None:
        rows = self._locked_admission_rows(queue)
        for row in rows:
            new_reserved = row["reserved_micros"] - row["amount_micros"]
            new_settled = row["settled_micros"] + actual_micros
            if new_reserved < 0:
                raise DagConflict(
                    "budget reserved balance is inconsistent"
                )
            self._finalize_budget_row(
                row,
                status="SETTLED",
                actual_micros=actual_micros,
                new_reserved=new_reserved,
                new_settled=new_settled,
                now=now,
            )

    def _release_budget_accounts(
        self, queue: DagReadyQueueRecord, now: datetime
    ) -> None:
        for row in self._locked_admission_rows(queue):
            new_reserved = row["reserved_micros"] - row["amount_micros"]
            if new_reserved < 0:
                raise DagConflict("budget reserved balance is inconsistent")
            self._finalize_budget_row(
                row,
                status="RELEASED",
                actual_micros=0,
                new_reserved=new_reserved,
                new_settled=row["settled_micros"],
                now=now,
            )

    def _locked_admission_rows(
        self, queue: DagReadyQueueRecord
    ) -> list[dict]:
        reserved = self.session.scalar(
            select(DagAdmissionReservationRecord.id)
            .where(
                DagAdmissionReservationRecord.queue_entry_id == queue.id,
                DagAdmissionReservationRecord.lease_generation
                == queue.lease_generation,
                DagAdmissionReservationRecord.status == "RESERVED",
            )
            .limit(1)
        )
        if reserved is None:
            return []
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    """
                    SELECT d.id AS admission_id, d.amount_micros,
                           d.budget_reservation_id, d.budget_account_id,
                           a.account_key, a.scope_kind, a.limit_micros,
                           a.reserved_micros, a.settled_micros,
                           a.state_version
                    FROM orchestration.dag_admission_reservations d
                    JOIN orchestration.budget_accounts a
                      ON a.id = d.budget_account_id
                    WHERE d.queue_entry_id = :queue_id
                      AND d.lease_generation = :generation
                      AND d.status = 'RESERVED'
                    ORDER BY CASE a.scope_kind
                               WHEN 'GLOBAL' THEN 0
                               WHEN 'PROJECT' THEN 1
                               ELSE 2
                             END,
                             a.id
                    FOR UPDATE OF a, d
                    """
                ),
                {
                    "queue_id": queue.id,
                    "generation": queue.lease_generation,
                },
            ).mappings()
        ]

    def _finalize_budget_row(
        self,
        row: dict,
        *,
        status: str,
        actual_micros: int,
        new_reserved: int,
        new_settled: int,
        now: datetime,
    ) -> None:
        self.session.execute(
            text(
                """
                UPDATE orchestration.budget_accounts
                SET reserved_micros = :reserved,
                    settled_micros = :settled,
                    state_version = state_version + 1,
                    updated_at = :now
                WHERE id = :account_id AND state_version = :version
                """
            ),
            {
                "reserved": new_reserved,
                "settled": new_settled,
                "now": now,
                "account_id": row["budget_account_id"],
                "version": row["state_version"],
            },
        )
        self.session.execute(
            text(
                """
                UPDATE orchestration.budget_reservations
                SET status = :status,
                    settled_micros = :settled_micros,
                    state_version = state_version + 1,
                    updated_at = :now
                WHERE id = :reservation_id AND status = 'RESERVED'
                """
            ),
            {
                "status": status,
                "settled_micros": actual_micros
                if status == "SETTLED"
                else None,
                "now": now,
                "reservation_id": row["budget_reservation_id"],
            },
        )
        self.session.execute(
            update(DagAdmissionReservationRecord)
            .where(
                DagAdmissionReservationRecord.id == row["admission_id"],
                DagAdmissionReservationRecord.status == "RESERVED",
            )
            .values(status=status, updated_at=now)
        )
        overage_micros = (
            max(0, new_settled - row["limit_micros"])
            if status == "SETTLED"
            else 0
        )
        metadata = {
            "source": "dag_scheduler",
            "status": status,
            "budget_violation": overage_micros > 0,
            "overage_micros": overage_micros,
            "hard_limit_micros": row["limit_micros"],
        }
        self.session.add(
            BudgetLedgerEntryRecord(
                id=uuid4(),
                project_id=self.session.scalar(
                    select(BudgetReservationRecord.project_id).where(
                        BudgetReservationRecord.id
                        == row["budget_reservation_id"]
                    )
                ),
                account_id=row["budget_account_id"],
                reservation_id=row["budget_reservation_id"],
                sequence=2,
                command_idempotency_key=(
                    f"dag-finalize:{row['budget_reservation_id']}:{status}"
                ),
                entry_type="SETTLE" if status == "SETTLED" else "RELEASE",
                reserved_delta_micros=-row["amount_micros"],
                settled_delta_micros=(
                    actual_micros if status == "SETTLED" else 0
                ),
                reserved_balance_micros=new_reserved,
                settled_balance_micros=new_settled,
                metadata_payload=metadata,
                metadata_digest=canonical_json_digest(metadata),
            )
        )

    def _locked_lease(
        self, lease: DagLease, now: datetime
    ) -> DagReadyQueueRecord:
        queue = self.session.scalar(
            select(DagReadyQueueRecord)
            .where(
                DagReadyQueueRecord.id == lease.queue_entry_id,
                DagReadyQueueRecord.state == "LEASED",
                DagReadyQueueRecord.lease_owner == lease.worker_id,
                DagReadyQueueRecord.lease_generation == lease.fencing_token,
                DagReadyQueueRecord.attempt_id == lease.attempt_id,
                DagReadyQueueRecord.lease_expires_at > now,
            )
            .with_for_update()
        )
        if queue is None:
            raise DagLeaseLost(
                f"lease generation {lease.fencing_token} is no longer active"
            )
        return queue

    def _locked_workflow(
        self,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
    ) -> WorkflowRunRecord:
        """Acquire the shared workflow boundary before any child projection.

        Completing sibling operations touches a common quota, join
        dependencies and the workflow terminal projection.  Taking this row
        first gives every completion transaction one canonical lock order
        without serializing the long-running capability execution itself.
        """
        workflow = self.session.scalar(
            select(WorkflowRunRecord)
            .where(
                WorkflowRunRecord.id == workflow_run_id,
                WorkflowRunRecord.project_id == project_id,
            )
            .with_for_update()
        )
        if workflow is None:
            raise DagConflict("workflow run is unavailable")
        return workflow

    def _release_quota(
        self, resource_pool: str, occurred_at: datetime
    ) -> None:
        quota = self.session.get(
            ResourcePoolQuotaRecord,
            resource_pool,
            with_for_update=True,
        )
        if quota is None or quota.in_use < 1:
            raise DagConflict("resource quota projection is inconsistent")
        quota.in_use -= 1
        quota.state_version += 1
        quota.updated_at = occurred_at

    def _increment_fairness(
        self, queue: DagReadyQueueRecord, now: datetime
    ) -> None:
        for scope, key in (
            ("RESOURCE_POOL", queue.resource_pool),
            ("PROJECT", str(queue.project_id)),
            ("WORKFLOW", str(queue.workflow_run_id)),
        ):
            self.session.execute(
                text(
                    """
                    INSERT INTO orchestration.scheduler_fairness_counters
                        (id, scope_kind, scope_key, resource_pool,
                         dispatch_count, last_dispatched_at)
                    VALUES
                        (:id, :scope_kind, :scope_key, :resource_pool,
                         1, :now)
                    ON CONFLICT (scope_kind, scope_key, resource_pool)
                    DO UPDATE
                       SET dispatch_count =
                               scheduler_fairness_counters.dispatch_count + 1,
                           last_dispatched_at = EXCLUDED.last_dispatched_at
                    """
                ),
                {
                    "id": str(uuid4()),
                    "scope_kind": scope,
                    "scope_key": key,
                    "resource_pool": queue.resource_pool,
                    "now": now,
                },
            )

    def _advance_downstream(
        self,
        parent: DagReadyQueueRecord,
        *,
        succeeded: bool,
        now: datetime,
    ) -> None:
        pending: deque[tuple[UUID, bool]] = deque(
            [(parent.operation_run_id, succeeded)]
        )
        visited: set[UUID] = set()
        while pending:
            upstream_id, upstream_succeeded = pending.popleft()
            if upstream_id in visited:
                continue
            visited.add(upstream_id)
            edges = self.session.scalars(
                select(WorkflowRunEdgeRecord).where(
                    WorkflowRunEdgeRecord.upstream_operation_run_id
                    == upstream_id
                )
            ).all()
            for edge in edges:
                projection = self.session.get(
                    OperationDependencyStateRecord,
                    edge.downstream_operation_run_id,
                    with_for_update=True,
                )
                if projection.status in {
                    "BLOCKED",
                    "TERMINAL",
                    "DISPATCHED",
                }:
                    continue
                terminal_satisfies = edge.required_status == "TERMINAL"
                if upstream_succeeded or terminal_satisfies:
                    projection.satisfied_count += 1
                else:
                    projection.failed_count += 1
                child_queue = self.session.scalar(
                    select(DagReadyQueueRecord)
                    .where(
                        DagReadyQueueRecord.operation_run_id
                        == edge.downstream_operation_run_id
                    )
                    .with_for_update()
                )
                child_operation = self.session.get(
                    OperationRunRecord,
                    edge.downstream_operation_run_id,
                    with_for_update=True,
                )
                workflow = self.session.get(
                    WorkflowRunRecord, edge.workflow_run_id
                )
                if projection.failed_count:
                    projection.status = "BLOCKED"
                    child_queue.state = "CANCELLED"
                    child_queue.blocked_reason = "upstream_failed"
                    child_operation.status = "CANCELLED"
                    child_operation.state_version += 1
                    pending.append((child_operation.id, False))
                    event_type = "OPERATION_BLOCKED"
                elif (
                    projection.satisfied_count
                    == projection.dependency_count
                ):
                    paused = workflow.status == "WAITING_HUMAN"
                    projection.status = (
                        "PAUSED_HUMAN" if paused else "READY"
                    )
                    child_queue.state = (
                        "PAUSED_HUMAN" if paused else "READY"
                    )
                    child_queue.enqueued_at = now
                    child_queue.not_before = max(
                        _utc(child_queue.not_before), now
                    )
                    child_operation.status = "QUEUED"
                    child_operation.state_version += 1
                    event_type = (
                        "OPERATION_PAUSED_HUMAN"
                        if paused
                        else "OPERATION_READY"
                    )
                else:
                    event_type = "DEPENDENCY_RESOLVED"
                projection.state_version += 1
                projection.updated_at = now
                child_queue.updated_at = now
                child_operation.updated_at = now
                self._append_scheduler_event(
                    child_queue,
                    event_type,
                    {
                        "upstream_operation_run_id": str(upstream_id),
                        "satisfied_count": projection.satisfied_count,
                        "failed_count": projection.failed_count,
                    },
                    now,
                )

    def _finish_workflow_if_terminal(
        self, workflow: WorkflowRunRecord, now: datetime
    ) -> None:
        statuses = self.session.scalars(
            select(OperationRunRecord.status).where(
                OperationRunRecord.workflow_run_id == workflow.id
            )
        ).all()
        if not statuses or any(
            status not in _TERMINAL_OPERATIONS for status in statuses
        ):
            return
        workflow.status = (
            "FAILED"
            if any(status in {"FAILED", "CANCELLED"} for status in statuses)
            else "COMPLETED"
        )
        workflow.state_version += 1
        workflow.completed_at = now
        workflow.updated_at = now

    def _append_scheduler_event(
        self,
        queue: DagReadyQueueRecord,
        event_type: str,
        data: dict,
        occurred_at: datetime,
        *,
        attempt_id: UUID | None = None,
    ) -> None:
        self.session.flush()
        sequence = (
            self.session.scalar(
                select(func.max(DagSchedulerEventRecord.sequence)).where(
                    DagSchedulerEventRecord.queue_entry_id == queue.id
                )
            )
            or 0
        ) + 1
        self.session.add(
            DagSchedulerEventRecord(
                project_id=queue.project_id,
                workflow_run_id=queue.workflow_run_id,
                operation_run_id=queue.operation_run_id,
                queue_entry_id=queue.id,
                attempt_id=attempt_id,
                sequence=sequence,
                event_type=event_type,
                data=data,
                data_digest=canonical_json_digest(data),
                occurred_at=occurred_at,
            )
        )

    def _record_queue(
        self,
        queue: DagReadyQueueRecord,
        outcome: str,
        now: datetime,
        counters,
    ) -> None:
        if self.observability is None:
            return
        wait = max(0.0, (now - _utc(queue.enqueued_at)).total_seconds())
        project_count = counters[
            ("PROJECT", str(queue.project_id), queue.resource_pool)
        ]
        workflow_count = counters[
            ("WORKFLOW", str(queue.workflow_run_id), queue.resource_pool)
        ]
        fairness = (min(project_count, workflow_count) + 1) / (
            max(project_count, workflow_count) + 1
        )
        try:
            self.observability.record_queue_dispatch(
                resource_pool=queue.resource_pool,
                priority_class=queue.priority_class,
                outcome=outcome,
                wait_seconds=wait,
                oldest_wait_seconds=wait,
                fairness_ratio=fairness,
                starved=effective_priority(
                    queue.priority_class,
                    queue.enqueued_at,
                    now,
                    promotion_interval=self.promotion_interval,
                )
                > queue.priority_value,
            )
        except Exception:
            pass

    def _record_attempt(self, resource_pool: str, outcome: str) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_attempt(
                resource_pool=resource_pool, outcome=outcome
            )
        except Exception:
            pass


__all__ = [
    "BudgetAdmissionDenied",
    "DagConflict",
    "DagEdge",
    "DagExecutionError",
    "DagLease",
    "DagLeaseLost",
    "DagNode",
    "DependencyProjection",
    "DurableDagScheduler",
    "InvalidDag",
    "effective_priority",
    "topological_order",
]
