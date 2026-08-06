from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path

from agent_factory.benchmarking.schema import (
    BenchmarkExperimentGroup,
    BenchmarkRun,
    utc_now_text,
)
from agent_factory.paths import factory_artifact_path
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


SQLITE_BUSY_TIMEOUT_MS = 10000


class BenchmarkStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else factory_artifact_path(
            "benchmark", "benchmark.sqlite"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def save(self, run: BenchmarkRun) -> BenchmarkRun:
        updated = run.model_copy(update={"updated_at": utc_now_text()}, deep=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into benchmark_runs (
                  run_id, status, profile_id, name, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                  status=excluded.status,
                  profile_id=excluded.profile_id,
                  name=excluded.name,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    updated.run_id,
                    updated.status,
                    updated.spec.profile_id,
                    updated.spec.name,
                    updated.model_dump_json(),
                    updated.created_at,
                    updated.updated_at,
                ),
            )
        return updated

    def get(self, run_id: str) -> BenchmarkRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from benchmark_runs where run_id = ?",
                (run_id,),
            ).fetchone()
        return BenchmarkRun.model_validate_json(str(row["payload_json"])) if row else None

    def require(self, run_id: str) -> BenchmarkRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"unknown benchmark run: {run_id}")
        return run

    def list(self, *, limit: int = 100) -> list[BenchmarkRun]:
        normalized_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from benchmark_runs order by created_at desc limit ?",
                (normalized_limit,),
            ).fetchall()
        return [BenchmarkRun.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from benchmark_runs where run_id = ?", (run_id,))
        return cursor.rowcount > 0

    def save_group(self, group: BenchmarkExperimentGroup) -> BenchmarkExperimentGroup:
        updated = group.model_copy(update={"updated_at": utc_now_text()}, deep=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into benchmark_experiment_groups (
                  group_id, status, profile_id, name, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(group_id) do update set
                  status=excluded.status,
                  profile_id=excluded.profile_id,
                  name=excluded.name,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    updated.group_id,
                    updated.status,
                    updated.spec.profile_id,
                    updated.spec.name,
                    updated.model_dump_json(),
                    updated.created_at,
                    updated.updated_at,
                ),
            )
        return updated

    def get_group(self, group_id: str) -> BenchmarkExperimentGroup | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from benchmark_experiment_groups where group_id = ?",
                (group_id,),
            ).fetchone()
        return (
            BenchmarkExperimentGroup.model_validate_json(str(row["payload_json"]))
            if row
            else None
        )

    def require_group(self, group_id: str) -> BenchmarkExperimentGroup:
        group = self.get_group(group_id)
        if group is None:
            raise ValueError(f"unknown benchmark experiment group: {group_id}")
        return group

    def list_groups(self, *, limit: int = 100) -> list[BenchmarkExperimentGroup]:
        normalized_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                select payload_json from benchmark_experiment_groups
                order by created_at desc limit ?
                """,
                (normalized_limit,),
            ).fetchall()
        return [
            BenchmarkExperimentGroup.model_validate_json(str(row["payload_json"]))
            for row in rows
        ]

    def delete_group(self, group_id: str) -> bool:
        group = self.require_group(group_id)
        run_ids = [item.run_id for item in group.runs]
        with self._connect() as conn:
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                conn.execute(
                    f"delete from benchmark_runs where run_id in ({placeholders})",
                    run_ids,
                )
            cursor = conn.execute(
                "delete from benchmark_experiment_groups where group_id = ?",
                (group_id,),
            )
        return cursor.rowcount > 0

    def interrupt_incomplete(self) -> int:
        updated_count = 0
        for run in self.list(limit=500):
            if run.status not in {"queued", "running"}:
                continue
            self.save(
                run.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "benchmark process stopped before the run completed",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
            updated_count += 1
        for group in self.list_groups(limit=500):
            if group.status not in {"queued", "running"}:
                continue
            self.save_group(
                group.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "benchmark process stopped before the experiment group completed",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
            updated_count += 1
        return updated_count

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
                create table if not exists benchmark_runs (
                  run_id text primary key,
                  status text not null,
                  profile_id text not null,
                  name text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_benchmark_runs_created_at
                  on benchmark_runs(created_at desc);
                create index if not exists idx_benchmark_runs_profile
                  on benchmark_runs(profile_id, created_at desc);
                create table if not exists benchmark_experiment_groups (
                  group_id text primary key,
                  status text not null,
                  profile_id text not null,
                  name text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_benchmark_groups_created_at
                  on benchmark_experiment_groups(created_at desc);
                create index if not exists idx_benchmark_groups_profile
                  on benchmark_experiment_groups(profile_id, created_at desc);
                """
            )
