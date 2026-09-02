from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from colorgraph.domain.jobs import JobRecord, JobStatus


class JobNotFoundError(KeyError):
    pass


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._listeners: dict[str, list[asyncio.Queue[JobRecord]]] = defaultdict(list)
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    def spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def create(self, *, kind: str, project_id: str) -> JobRecord:
        record = JobRecord(
            id=f"job_{uuid4().hex}",
            kind=kind,
            project_id=project_id,
        )
        async with self._lock:
            self._jobs[record.id] = record
        return record.model_copy(deep=True)

    async def create_unique(
        self,
        *,
        kind: str,
        project_id: str,
    ) -> tuple[JobRecord, bool]:
        async with self._lock:
            active = [
                record
                for record in self._jobs.values()
                if record.kind == kind
                and record.project_id == project_id
                and record.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]
            if active:
                newest = max(active, key=lambda record: record.created_at)
                return newest.model_copy(deep=True), False
            record = JobRecord(
                id=f"job_{uuid4().hex}",
                kind=kind,
                project_id=project_id,
            )
            self._jobs[record.id] = record
        return record.model_copy(deep=True), True

    async def find_active(
        self,
        *,
        kind: str,
        project_id: str,
    ) -> JobRecord | None:
        async with self._lock:
            active = [
                record
                for record in self._jobs.values()
                if record.kind == kind
                and record.project_id == project_id
                and record.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]
            if not active:
                return None
            newest = max(active, key=lambda record: record.created_at)
            return newest.model_copy(deep=True)

    async def get(self, job_id: str) -> JobRecord:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise JobNotFoundError(job_id)
            return record.model_copy(deep=True)

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        stage: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        device: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> JobRecord:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise JobNotFoundError(job_id)
            updated = record.model_copy(
                update={
                    key: value
                    for key, value in {
                        "status": status,
                        "stage": stage,
                        "progress": progress,
                        "message": message,
                        "device": device,
                        "result": result,
                        "error": error,
                        "updated_at": datetime.now(UTC),
                    }.items()
                    if value is not None
                }
            )
            self._jobs[job_id] = updated
            listeners = list(self._listeners.get(job_id, []))
        for queue in listeners:
            queue.put_nowait(updated.model_copy(deep=True))
        return updated.model_copy(deep=True)

    async def complete(self, job_id: str, result: dict) -> JobRecord:
        return await self.update(
            job_id,
            status=JobStatus.COMPLETED,
            stage="completed",
            progress=100,
            message="Task completed",
            result=result,
        )

    async def fail(self, job_id: str, error: Exception | str) -> JobRecord:
        return await self.update(
            job_id,
            status=JobStatus.FAILED,
            stage="failed",
            progress=100,
            message="Task failed",
            error=str(error),
        )

    async def events(self, job_id: str) -> AsyncIterator[JobRecord]:
        queue: asyncio.Queue[JobRecord] = asyncio.Queue()
        current = await self.get(job_id)
        async with self._lock:
            self._listeners[job_id].append(queue)
        try:
            yield current
            if current.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                return
            while True:
                event = await queue.get()
                yield event
                if event.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                    return
        finally:
            async with self._lock:
                listeners = self._listeners.get(job_id, [])
                if queue in listeners:
                    listeners.remove(queue)
                if not listeners:
                    self._listeners.pop(job_id, None)


job_manager = JobManager()
