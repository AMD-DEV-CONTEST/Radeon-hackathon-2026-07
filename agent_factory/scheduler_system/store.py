from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Any

from agent_factory.scheduler_system.schema import SchedulerJob, SchedulerLease, SchedulerRun, utc_after, utc_now
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


SQLITE_BUSY_TIMEOUT_MS = 10000


class SchedulerStoreError(RuntimeError):
    pass


class SQLiteSchedulerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def create_job(self, job: SchedulerJob) -> SchedulerJob:
        now = utc_now().isoformat()
        job = job.model_copy(update={"created_at": job.created_at or now, "updated_at": now})
        with self._connect() as conn:
            conn.execute(
                """
                insert into scheduler_jobs (
                  job_id, owner_type, owner_id, enabled, schedule_type, schedule_expr,
                  timezone, target_type, concurrency_policy, max_concurrent_runs,
                  timeout_seconds, unattended_policy, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _job_row(job),
            )
        return job

    def upsert_job(self, job: SchedulerJob) -> SchedulerJob:
        now = utc_now().isoformat()
        existing = self.get_job(job.job_id)
        created_at = existing.created_at if existing else job.created_at
        job = job.model_copy(update={"created_at": created_at, "updated_at": now})
        with self._connect() as conn:
            conn.execute(
                """
                insert into scheduler_jobs (
                  job_id, owner_type, owner_id, enabled, schedule_type, schedule_expr,
                  timezone, target_type, concurrency_policy, max_concurrent_runs,
                  timeout_seconds, unattended_policy, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(job_id) do update set
                  owner_type=excluded.owner_type,
                  owner_id=excluded.owner_id,
                  enabled=excluded.enabled,
                  schedule_type=excluded.schedule_type,
                  schedule_expr=excluded.schedule_expr,
                  timezone=excluded.timezone,
                  target_type=excluded.target_type,
                  concurrency_policy=excluded.concurrency_policy,
                  max_concurrent_runs=excluded.max_concurrent_runs,
                  timeout_seconds=excluded.timeout_seconds,
                  unattended_policy=excluded.unattended_policy,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                _job_row(job),
            )
        return job

    def get_job(self, job_id: str) -> SchedulerJob | None:
        with self._connect() as conn:
            row = conn.execute("select payload_json from scheduler_jobs where job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return SchedulerJob.model_validate_json(str(row["payload_json"]))

    def list_jobs(self, *, owner_type: str | None = None, owner_id: str | None = None) -> list[SchedulerJob]:
        query = "select payload_json from scheduler_jobs"
        args: list[Any] = []
        clauses: list[str] = []
        if owner_type:
            clauses.append("owner_type = ?")
            args.append(owner_type)
        if owner_id:
            clauses.append("owner_id = ?")
            args.append(owner_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by updated_at desc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [SchedulerJob.model_validate_json(str(row["payload_json"])) for row in rows]

    def set_job_enabled(self, job_id: str, enabled: bool) -> SchedulerJob:
        job = self.get_job(job_id)
        if job is None:
            raise SchedulerStoreError(f"unknown scheduler job: {job_id}")
        return self.upsert_job(job.model_copy(update={"enabled": enabled}))

    def delete_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from scheduler_jobs where job_id = ?", (job_id,))
        return cursor.rowcount > 0

    def create_run(self, run: SchedulerRun) -> SchedulerRun:
        with self._connect() as conn:
            conn.execute(
                """
                insert into scheduler_runs (
                  run_id, job_id, owner_type, owner_id, target_type, status, scheduled_at,
                  started_at, completed_at, trigger_reason, output_summary, error_summary,
                  event_trace_id, report_path, payload_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _run_row(run),
            )
        return run

    def update_run(self, run: SchedulerRun) -> SchedulerRun:
        with self._connect() as conn:
            conn.execute(
                """
                update scheduler_runs set
                  status=?, started_at=?, completed_at=?, output_summary=?, error_summary=?,
                  event_trace_id=?, report_path=?, payload_json=?
                where run_id=?
                """,
                (
                    run.status,
                    run.started_at,
                    run.completed_at,
                    run.output_summary,
                    run.error_summary,
                    run.event_trace_id,
                    run.report_path,
                    run.model_dump_json(),
                    run.run_id,
                ),
            )
        return run

    def get_run(self, run_id: str) -> SchedulerRun | None:
        with self._connect() as conn:
            row = conn.execute("select payload_json from scheduler_runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return SchedulerRun.model_validate_json(str(row["payload_json"]))

    def list_runs(self, *, job_id: str | None = None, limit: int = 50) -> list[SchedulerRun]:
        args: list[Any] = []
        query = "select payload_json from scheduler_runs"
        if job_id:
            query += " where job_id = ?"
            args.append(job_id)
        query += " order by scheduled_at desc limit ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [SchedulerRun.model_validate_json(str(row["payload_json"])) for row in rows]

    def count_runs(self, *, job_id: str, status: str | None = None) -> int:
        query = "select count(*) from scheduler_runs where job_id = ?"
        args: list[Any] = [job_id]
        if status:
            query += " and status = ?"
            args.append(status)
        with self._connect() as conn:
            row = conn.execute(query, args).fetchone()
        return int(row[0]) if row is not None else 0

    def count_consecutive_runs(self, *, job_id: str, status: str) -> int:
        query = """
            select status from scheduler_runs
            where job_id = ? and status in ('completed', 'failed', 'skipped', 'cancelled')
            order by coalesce(completed_at, scheduled_at) desc
        """
        count = 0
        with self._connect() as conn:
            rows = conn.execute(query, (job_id,)).fetchall()
        for row in rows:
            if str(row["status"]) != status:
                break
            count += 1
        return count

    def acquire_lease(self, *, job_id: str, run_id: str, holder_id: str, ttl_seconds: int) -> SchedulerLease | None:
        now = utc_now().isoformat()
        lease = SchedulerLease(
            job_id=job_id,
            run_id=run_id,
            holder_id=holder_id,
            expires_at=utc_after(ttl_seconds).isoformat(),
        )
        with self._connect() as conn:
            conn.execute("delete from scheduler_leases where expires_at <= ?", (now,))
            existing = conn.execute(
                "select lease_id from scheduler_leases where job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None:
                return None
            conn.execute(
                """
                insert into scheduler_leases (lease_id, job_id, run_id, holder_id, expires_at, payload_json)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    lease.job_id,
                    lease.run_id,
                    lease.holder_id,
                    lease.expires_at,
                    lease.model_dump_json(),
                ),
            )
        return lease

    def release_lease(self, *, job_id: str, run_id: str | None = None) -> None:
        if run_id:
            args = (job_id, run_id)
            query = "delete from scheduler_leases where job_id = ? and run_id = ?"
        else:
            args = (job_id,)
            query = "delete from scheduler_leases where job_id = ?"
        with self._connect() as conn:
            conn.execute(query, args)

    def acquire_worker_lease(
        self,
        *,
        owner_type: str,
        owner_id: str,
        holder_id: str,
        ttl_seconds: int,
    ) -> bool:
        now = utc_now()
        expires_at = utc_after(ttl_seconds).isoformat()
        lease_key = _worker_lease_key(owner_type=owner_type, owner_id=owner_id)
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select holder_id,expires_at from scheduler_worker_leases where lease_key=?",
                (lease_key,),
            ).fetchone()
            if row is not None:
                current_holder = str(row["holder_id"] or "")
                current_expiry = str(row["expires_at"] or "")
                if current_holder != holder_id and current_expiry > now.isoformat():
                    return False
            conn.execute(
                """
                insert into scheduler_worker_leases(lease_key,holder_id,expires_at,updated_at)
                values(?,?,?,?)
                on conflict(lease_key) do update set
                  holder_id=excluded.holder_id,
                  expires_at=excluded.expires_at,
                  updated_at=excluded.updated_at
                """,
                (lease_key, holder_id, expires_at, now.isoformat()),
            )
        return True

    def release_worker_lease(
        self,
        *,
        owner_type: str,
        owner_id: str,
        holder_id: str,
    ) -> None:
        lease_key = _worker_lease_key(owner_type=owner_type, owner_id=owner_id)
        with self._connect() as conn:
            conn.execute(
                "delete from scheduler_worker_leases where lease_key=? and holder_id=?",
                (lease_key, holder_id),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = connect_sqlite(self.path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists scheduler_jobs (
                  job_id text primary key,
                  owner_type text not null,
                  owner_id text not null,
                  enabled integer not null,
                  schedule_type text not null,
                  schedule_expr text not null,
                  timezone text not null,
                  target_type text not null,
                  concurrency_policy text not null,
                  max_concurrent_runs integer not null,
                  timeout_seconds integer not null,
                  unattended_policy text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_scheduler_jobs_owner on scheduler_jobs(owner_type, owner_id);
                create index if not exists idx_scheduler_jobs_enabled on scheduler_jobs(enabled);
                create table if not exists scheduler_runs (
                  run_id text primary key,
                  job_id text not null,
                  owner_type text not null,
                  owner_id text not null,
                  target_type text not null,
                  status text not null,
                  scheduled_at text not null,
                  started_at text,
                  completed_at text,
                  trigger_reason text not null,
                  output_summary text,
                  error_summary text,
                  event_trace_id text,
                  report_path text,
                  payload_json text not null
                );
                create index if not exists idx_scheduler_runs_job on scheduler_runs(job_id);
                create index if not exists idx_scheduler_runs_status on scheduler_runs(status);
                create table if not exists scheduler_leases (
                  lease_id text primary key,
                  job_id text not null unique,
                  run_id text not null,
                  holder_id text not null,
                  expires_at text not null,
                  payload_json text not null
                );
                create table if not exists scheduler_worker_leases (
                  lease_key text primary key,
                  holder_id text not null,
                  expires_at text not null,
                  updated_at text not null
                );
                """
            )


def _worker_lease_key(*, owner_type: str, owner_id: str) -> str:
    normalized_type = str(owner_type or "").strip()
    normalized_id = str(owner_id or "").strip()
    if not normalized_type or not normalized_id:
        raise ValueError("scheduler worker lease requires owner_type and owner_id")
    return f"{normalized_type}:{normalized_id}"


def _job_row(job: SchedulerJob) -> tuple[Any, ...]:
    return (
        job.job_id,
        job.owner_type,
        job.owner_id,
        1 if job.enabled else 0,
        job.schedule_type,
        job.schedule_expr,
        job.timezone,
        job.target.target_type,
        job.concurrency_policy,
        job.max_concurrent_runs,
        job.timeout_seconds,
        job.unattended_policy,
        job.model_dump_json(),
        job.created_at,
        job.updated_at,
    )


def _run_row(run: SchedulerRun) -> tuple[Any, ...]:
    return (
        run.run_id,
        run.job_id,
        run.owner_type,
        run.owner_id,
        run.target_type,
        run.status,
        run.scheduled_at,
        run.started_at,
        run.completed_at,
        run.trigger_reason,
        run.output_summary,
        run.error_summary,
        run.event_trace_id,
        run.report_path,
        run.model_dump_json(),
    )
