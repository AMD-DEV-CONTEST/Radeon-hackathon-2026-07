from __future__ import annotations

import logging
from threading import Event, RLock, Thread
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from agent_factory.scheduler_system.runtime import SchedulerRuntime
from agent_factory.scheduler_system.schema import SchedulerJob
from agent_factory.scheduler_system.triggers import build_trigger


LOGGER = logging.getLogger(__name__)
WORKER_LEASE_TTL_SECONDS = 5
WORKER_COORDINATION_INTERVAL_SECONDS = 1


class SchedulerWorker:
    """Coordinates one active scheduler per persistent store and owner.

    Package runtimes are scoped by workspace, while scheduler jobs are scoped by
    package owner and share one SQLite store.  Every runtime may therefore own a
    worker object, but only the worker holding the persistent owner lease is
    allowed to load and trigger jobs.
    """

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self.runtime = runtime
        self.runtime.worker = self
        self.scheduler: BackgroundScheduler | None = None
        self._started = False
        self._leader = False
        self._jobs_signature: tuple[tuple[Any, ...], ...] | None = None
        self._stop_event = Event()
        self._refresh_event = Event()
        self._state_lock = RLock()
        self._coordinator: Thread | None = None

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._refresh_event.clear()
        try:
            self._coordinate_once(force_refresh=True)
        except Exception:
            with self._state_lock:
                self._started = False
            self._release_leadership()
            raise
        coordinator = Thread(
            target=self._coordination_loop,
            name=f"scheduler-coordinator-{self.runtime.owner_type}-{self.runtime.owner_id}",
            daemon=True,
        )
        self._coordinator = coordinator
        coordinator.start()

    def reload_jobs(self) -> None:
        """Request reconciliation without assuming this worker is the leader."""
        self._refresh_event.set()

    def shutdown(self) -> None:
        with self._state_lock:
            if not self._started:
                return
            self._started = False
            self._stop_event.set()
            self._refresh_event.set()
        coordinator = self._coordinator
        if coordinator is not None and coordinator.is_alive():
            coordinator.join(timeout=WORKER_COORDINATION_INTERVAL_SECONDS + 1)
        self._coordinator = None
        self._release_leadership()

    def _coordination_loop(self) -> None:
        while not self._stop_event.is_set():
            refresh_requested = self._refresh_event.wait(WORKER_COORDINATION_INTERVAL_SECONDS)
            self._refresh_event.clear()
            if self._stop_event.is_set():
                return
            try:
                self._coordinate_once(force_refresh=refresh_requested)
            except Exception:
                LOGGER.exception(
                    "scheduler worker coordination failed for %s:%s",
                    self.runtime.owner_type,
                    self.runtime.owner_id,
                )
                try:
                    self._release_leadership()
                except Exception:
                    LOGGER.exception(
                        "scheduler worker leadership release failed for %s:%s",
                        self.runtime.owner_type,
                        self.runtime.owner_id,
                    )

    def _coordinate_once(self, *, force_refresh: bool = False) -> None:
        acquired = self.runtime.store.acquire_worker_lease(
            owner_type=self.runtime.owner_type,
            owner_id=self.runtime.owner_id,
            holder_id=self.runtime.holder_id,
            ttl_seconds=WORKER_LEASE_TTL_SECONDS,
        )
        if not acquired:
            self._demote()
            return
        with self._state_lock:
            if not self._started:
                self.runtime.store.release_worker_lease(
                    owner_type=self.runtime.owner_type,
                    owner_id=self.runtime.owner_id,
                    holder_id=self.runtime.holder_id,
                )
                return
            if not self._leader:
                self._promote()
            jobs = self.runtime.list_jobs()
            signature = _job_signature(jobs)
            if force_refresh or signature != self._jobs_signature:
                self._synchronize_jobs(jobs)
                self._jobs_signature = signature

    def _promote(self) -> None:
        scheduler = BackgroundScheduler(timezone=self.runtime.config.timezone)
        scheduler.start(paused=False)
        self.scheduler = scheduler
        self._leader = True
        self._jobs_signature = None

    def _demote(self) -> None:
        with self._state_lock:
            if not self._leader:
                return
            scheduler = self.scheduler
            self.scheduler = None
            self._leader = False
            self._jobs_signature = None
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    def _release_leadership(self) -> None:
        self._demote()
        self.runtime.store.release_worker_lease(
            owner_type=self.runtime.owner_type,
            owner_id=self.runtime.owner_id,
            holder_id=self.runtime.holder_id,
        )

    def _synchronize_jobs(self, jobs: list[SchedulerJob]) -> None:
        scheduler = self.scheduler
        if scheduler is None:
            return
        desired_ids = {job.job_id for job in jobs if job.enabled}
        existing_ids = {job.id for job in scheduler.get_jobs()}
        for job_id in existing_ids - desired_ids:
            scheduler.remove_job(job_id)
        for job in jobs:
            if not job.enabled:
                continue
            scheduler.add_job(
                self._execute_job,
                trigger=build_trigger(
                    schedule_type=job.schedule_type,
                    schedule_expr=job.schedule_expr,
                    timezone=job.timezone,
                    anchor_at=job.created_at,
                ),
                id=job.job_id,
                args=[job.job_id],
                replace_existing=True,
                coalesce=True,
                max_instances=job.max_concurrent_runs,
                misfire_grace_time=job.timeout_seconds,
            )

    def _execute_job(self, job_id: str) -> None:
        self.runtime.execute_job(job_id, trigger_reason="scheduled")


def _job_signature(jobs: list[SchedulerJob]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        sorted(
            (
                job.job_id,
                job.updated_at,
                job.enabled,
                job.schedule_type,
                job.schedule_expr,
                job.timezone,
            )
            for job in jobs
        )
    )
