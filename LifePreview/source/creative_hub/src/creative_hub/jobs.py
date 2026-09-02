from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from collections.abc import Iterator
from uuid import UUID, uuid4

from shared_contracts import ContractVersion, JobEvent, JobEventType
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import HubJobRecord, JobEventRecord


TERMINAL_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "needs_human"}
)


class HubJobError(RuntimeError):
    pass


class HubJobNotFound(HubJobError):
    pass


class HubJobConflict(HubJobError):
    pass


class HubJobAuthorizationError(HubJobError):
    pass


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job: HubJobRecord
    created: bool


@dataclass(frozen=True, slots=True)
class HubJobLease:
    job_id: UUID
    worker_id: str
    generation: int


class HubLeaseLost(HubJobConflict):
    pass


class HubLeaseGuard:
    def __init__(self) -> None:
        self._lock = Lock()
        self._error: BaseException | None = None
        self._cancel_requested = False

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def mark_cancel_requested(self) -> None:
        with self._lock:
            self._cancel_requested = True

    def mark_lost(self, error: BaseException) -> None:
        with self._lock:
            if self._error is None:
                self._error = error

    def raise_if_lost(self) -> None:
        with self._lock:
            error = self._error
        if error is not None:
            raise HubLeaseLost("Hub job lease was lost") from error


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _restore_event(record: JobEventRecord) -> JobEvent:
    return JobEvent(
        contract_version=ContractVersion(
            major=record.contract_major,
            minor=record.contract_minor,
        ),
        event_id=record.id,
        job_id=record.job_id,
        request_id=record.request_id,
        sequence=record.sequence,
        event_type=JobEventType(record.event_type),
        occurred_at=_aware(record.occurred_at),
        data=record.data,
    )


class HubJobRepository:
    """Durable Hub orchestration jobs and ordered append-only events."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, job_id: UUID, *, for_update: bool = False) -> HubJobRecord:
        statement = select(HubJobRecord).where(HubJobRecord.id == job_id)
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            raise HubJobNotFound(str(job_id))
        return record

    def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        request_id: UUID,
        actor_id: str,
        payload: dict,
        max_attempts: int = 3,
        occurred_at: datetime | None = None,
    ) -> EnqueueResult:
        if not job_type or len(job_type) > 100:
            raise ValueError("invalid job type")
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("invalid idempotency key")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        existing = self._session.scalar(
            select(HubJobRecord).where(
                HubJobRecord.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if (
                existing.job_type != job_type
                or existing.payload != payload
                or existing.actor_id != actor_id
            ):
                raise HubJobConflict(
                    "idempotency key conflicts with stored job"
                )
            return EnqueueResult(job=existing, created=False)

        job = HubJobRecord(
            job_type=job_type,
            idempotency_key=idempotency_key,
            request_id=request_id,
            actor_id=actor_id,
            payload=payload,
            checkpoint={},
            result={},
            error={},
            max_attempts=max_attempts,
        )
        self._session.add(job)
        self._session.flush()
        self.append_event(
            job.id,
            event_type=JobEventType.QUEUED,
            request_id=request_id,
            data={"job_type": job_type},
            occurred_at=occurred_at,
        )
        return EnqueueResult(job=job, created=True)

    def claim(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        request_id: UUID,
        lease_duration: timedelta = timedelta(minutes=2),
        occurred_at: datetime | None = None,
    ) -> HubJobLease:
        if not worker_id or len(worker_id) > 100:
            raise ValueError("invalid worker id")
        if lease_duration <= timedelta(0):
            raise ValueError("lease duration must be positive")
        job = self.get(job_id, for_update=True)
        if job.status != "queued" or job.cancel_requested:
            raise HubJobConflict("Hub job is not claimable")
        now = _aware(occurred_at or datetime.now(timezone.utc))
        job.status = "running"
        job.lock_owner = worker_id
        job.lease_generation += 1
        job.attempts += 1
        job.heartbeat_at = now
        job.lease_expires_at = now + lease_duration
        self.append_event(
            job.id,
            event_type=JobEventType.STARTED,
            request_id=request_id,
            data={
                "worker_id": worker_id,
                "lease_generation": job.lease_generation,
                "attempt": job.attempts,
            },
            occurred_at=now,
        )
        self._session.flush()
        return HubJobLease(job.id, worker_id, job.lease_generation)

    def _leased_job(
        self,
        lease: HubJobLease,
        *,
        occurred_at: datetime | None = None,
    ) -> tuple[HubJobRecord, datetime]:
        now = _aware(occurred_at or datetime.now(timezone.utc))
        job = self._session.scalar(
            select(HubJobRecord)
            .where(
                HubJobRecord.id == lease.job_id,
                HubJobRecord.status == "running",
                HubJobRecord.lock_owner == lease.worker_id,
                HubJobRecord.lease_generation == lease.generation,
                HubJobRecord.lease_expires_at > now,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if job is None:
            raise HubLeaseLost(
                f"lease lost for Hub job {lease.job_id} "
                f"generation {lease.generation}"
            )
        return job, now

    def renew(
        self,
        lease: HubJobLease,
        *,
        lease_duration: timedelta = timedelta(minutes=2),
        occurred_at: datetime | None = None,
    ) -> HubJobRecord:
        if lease_duration <= timedelta(0):
            raise ValueError("lease duration must be positive")
        job, now = self._leased_job(lease, occurred_at=occurred_at)
        job.heartbeat_at = now
        job.lease_expires_at = now + lease_duration
        self._session.flush()
        return job

    def save_checkpoint(
        self,
        lease: HubJobLease,
        checkpoint: dict,
        *,
        request_id: UUID,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job, now = self._leased_job(lease, occurred_at=occurred_at)
        return self.append_event(
            job.id,
            event_type=JobEventType.CHECKPOINT,
            request_id=request_id,
            data=checkpoint,
            occurred_at=now,
        )

    def complete(
        self,
        lease: HubJobLease,
        result: dict,
        *,
        request_id: UUID,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job, now = self._leased_job(lease, occurred_at=occurred_at)
        if job.cancel_requested:
            return self.acknowledge_cancel(
                lease,
                request_id=request_id,
                occurred_at=now,
            )
        return self.append_event(
            job.id,
            event_type=JobEventType.SUCCEEDED,
            request_id=request_id,
            data=result,
            occurred_at=now,
        )

    def fail(
        self,
        lease: HubJobLease,
        error: dict,
        *,
        request_id: UUID,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job, now = self._leased_job(lease, occurred_at=occurred_at)
        if job.cancel_requested:
            return self.acknowledge_cancel(
                lease,
                request_id=request_id,
                occurred_at=now,
            )
        return self.append_event(
            job.id,
            event_type=JobEventType.FAILED,
            request_id=request_id,
            data=error,
            occurred_at=now,
        )

    def acknowledge_cancel(
        self,
        lease: HubJobLease,
        *,
        request_id: UUID,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job, now = self._leased_job(lease, occurred_at=occurred_at)
        if not job.cancel_requested:
            raise HubJobConflict("Hub job cancellation was not requested")
        return self.append_event(
            job.id,
            event_type=JobEventType.CANCELLED,
            request_id=request_id,
            data={"reason": "worker acknowledged cancellation"},
            occurred_at=now,
        )

    def recover_expired(
        self,
        *,
        request_id: UUID,
        occurred_at: datetime | None = None,
        limit: int = 100,
    ) -> int:
        now = _aware(occurred_at or datetime.now(timezone.utc))
        jobs = self._session.scalars(
            select(HubJobRecord)
            .where(
                HubJobRecord.status == "running",
                HubJobRecord.lease_expires_at <= now,
            )
            .order_by(HubJobRecord.lease_expires_at, HubJobRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            job.lock_owner = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            if job.cancel_requested:
                self.append_event(
                    job.id,
                    event_type=JobEventType.CANCELLED,
                    request_id=request_id,
                    data={"reason": "cancelled after lease expiry"},
                    occurred_at=now,
                )
            elif job.attempts < job.max_attempts:
                job.status = "queued"
                self.append_event(
                    job.id,
                    event_type=JobEventType.PROGRESS,
                    request_id=request_id,
                    data={
                        "recovery": "lease_expired",
                        "next_attempt": job.attempts + 1,
                    },
                    occurred_at=now,
                )
            else:
                self.append_event(
                    job.id,
                    event_type=JobEventType.PROGRESS,
                    request_id=request_id,
                    data={
                        "recovery": "lease_expired",
                        "outcome": "needs_human",
                    },
                    occurred_at=now,
                )
                job.status = "needs_human"
                job.error = {
                    "error_code": "hub_job_lease_exhausted",
                    "safe_message": "任务多次中断，需要人工确认后继续。",
                }
        self._session.flush()
        return len(jobs)

    def append_event(
        self,
        job_id: UUID,
        *,
        event_type: JobEventType,
        request_id: UUID,
        data: dict,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job = self.get(job_id, for_update=True)
        if job.status in TERMINAL_JOB_STATUSES:
            raise HubJobConflict("cannot append to a terminal job")
        if event_type is JobEventType.STARTED:
            job.status = "running"
        elif event_type is JobEventType.SUCCEEDED:
            job.status = "succeeded"
            job.result = data
        elif event_type is JobEventType.FAILED:
            job.status = "failed"
            job.error = data
        elif event_type is JobEventType.CANCELLED:
            job.status = "cancelled"
        elif event_type is JobEventType.CHECKPOINT:
            job.checkpoint = data
        if event_type in {
            JobEventType.SUCCEEDED,
            JobEventType.FAILED,
            JobEventType.CANCELLED,
        }:
            job.lock_owner = None
            job.heartbeat_at = None
            job.lease_expires_at = None

        sequence = (
            self._session.scalar(
                select(func.max(JobEventRecord.sequence)).where(
                    JobEventRecord.job_id == job_id
                )
            )
            or 0
        ) + 1
        now = _aware(occurred_at or datetime.now(timezone.utc))
        event = JobEvent(
            event_id=uuid4(),
            job_id=job_id,
            request_id=request_id,
            sequence=sequence,
            event_type=event_type,
            occurred_at=now,
            data=data,
        )
        self._session.add(
            JobEventRecord(
                id=event.event_id,
                job_id=event.job_id,
                sequence=event.sequence,
                event_type=event.event_type.value,
                contract_major=event.contract_version.major,
                contract_minor=event.contract_version.minor,
                request_id=event.request_id,
                data=event.data,
                occurred_at=event.occurred_at,
            )
        )
        self._session.flush()
        return event

    def list_events(
        self,
        job_id: UUID,
        *,
        after_event_id: UUID | None = None,
        limit: int = 500,
    ) -> tuple[JobEvent, ...]:
        self.get(job_id)
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        after_sequence = 0
        if after_event_id is not None:
            cursor = self._session.get(JobEventRecord, after_event_id)
            if cursor is None or cursor.job_id != job_id:
                raise HubJobConflict("job event cursor is invalid")
            after_sequence = cursor.sequence
        records = self._session.scalars(
            select(JobEventRecord)
            .where(
                JobEventRecord.job_id == job_id,
                JobEventRecord.sequence > after_sequence,
            )
            .order_by(JobEventRecord.sequence)
            .limit(limit)
        ).all()
        return tuple(_restore_event(record) for record in records)

    def request_cancel(
        self,
        job_id: UUID,
        *,
        actor_id: str,
        request_id: UUID,
        occurred_at: datetime | None = None,
    ) -> HubJobRecord:
        job = self.get(job_id, for_update=True)
        if job.actor_id != actor_id:
            raise HubJobAuthorizationError(
                "only the owning Hub session can cancel this job"
            )
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        job.cancel_requested = True
        if job.status == "queued":
            self.append_event(
                job.id,
                event_type=JobEventType.CANCELLED,
                request_id=request_id,
                data={"reason": "cancelled before worker claim"},
                occurred_at=occurred_at,
            )
        else:
            self.append_event(
                job.id,
                event_type=JobEventType.PROGRESS,
                request_id=request_id,
                data={"cancel_requested": True},
                occurred_at=occurred_at,
            )
        self._session.flush()
        return job


@contextmanager
def managed_hub_heartbeat(
    session_factory,
    lease: HubJobLease,
    *,
    interval_seconds: float = 30.0,
    lease_duration: timedelta = timedelta(minutes=2),
) -> Iterator[HubLeaseGuard]:
    if interval_seconds <= 0:
        raise ValueError("heartbeat interval must be positive")
    if interval_seconds >= lease_duration.total_seconds() / 2:
        raise ValueError("heartbeat interval must be less than half the lease")
    stop = Event()
    guard = HubLeaseGuard()

    def heartbeat() -> None:
        while not stop.wait(interval_seconds):
            try:
                with session_factory() as session:
                    job = HubJobRepository(session).renew(
                        lease,
                        lease_duration=lease_duration,
                    )
                    cancel_requested = job.cancel_requested
                    session.commit()
                if cancel_requested:
                    guard.mark_cancel_requested()
                    stop.set()
                    return
            except BaseException as error:
                guard.mark_lost(error)
                stop.set()
                return

    thread = Thread(
        target=heartbeat,
        name=f"hub-job-heartbeat-{lease.job_id}",
        daemon=False,
    )
    thread.start()
    try:
        yield guard
        guard.raise_if_lost()
    finally:
        stop.set()
        thread.join(10.0)
        if thread.is_alive():
            guard.mark_lost(RuntimeError("Hub heartbeat thread did not stop"))
        guard.raise_if_lost()
