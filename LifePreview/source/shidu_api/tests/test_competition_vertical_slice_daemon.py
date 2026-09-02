from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from shidu_api.competition_vertical_slice_daemon import (
    AtomicPersistentCheckpointPort,
    CompetitionDaemonContext,
    CompetitionVerticalSliceDaemon,
    PostgresDeferredJobPort,
    ProductionStageFunctions,
    build_competition_vertical_slice_daemon,
)
from shidu_api.competition_vertical_slice_worker import (
    ClickedDeferredVideoJob,
    CoordinatorContractError,
    WorkerCheckpoint,
)


PROJECT_ID = UUID("50000000-0000-4000-8000-000000000001")
BOOK_ID = UUID("50000000-0000-4000-8000-000000000002")
SCRIPT_ID = UUID("50000000-0000-4000-8000-000000000003")
DIRECTION_ID = UUID("50000000-0000-4000-8000-000000000004")
RESEARCH_ID = UUID("50000000-0000-4000-8000-000000000005")
WORKFLOW_ID = UUID("50000000-0000-4000-8000-000000000006")


def _projection(
    *,
    external_job_id: str = "shidu_clicked_three_second",
    pipeline: str = "h3_deferred_vertical_slice",
    status: str = "queued",
    target: float = 3.0,
) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "bookId": str(BOOK_ID),
        "directionRevisionId": str(DIRECTION_ID),
        "trialScriptRevisionId": str(SCRIPT_ID),
        "contentMode": "source_grounded",
        "contentLabel": "AI-assisted historical adaptation",
        "contentNotice": "Adapted from cited historical sources.",
        "pipelineMode": pipeline,
        "targetDurationSeconds": target,
        "sequenceCount": 1,
        "frameCount": 73,
        "fps": 24,
        "nativeAudio": True,
        "subtitles": False,
        "requestDigest": "a" * 64,
        "researchJobId": str(RESEARCH_ID),
        "safetyDecisionDigest": "b" * 64,
        "competitionPreparedReference": {
            "requestId": "50000000-0000-4000-8000-000000000008",
            "artifactSha256": "d" * 64,
            "sourceMode": "preuploaded_imported",
            "importAuthoritySha256": "e" * 64,
        },
    }
    if pipeline == "h3_vertical_slice":
        payload["workflowRunId"] = str(WORKFLOW_ID)
    return SimpleNamespace(
        id=UUID("50000000-0000-4000-8000-000000000010"),
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        trial_script_revision_id=SCRIPT_ID,
        external_job_id=external_job_id,
        status=status,
        payload=payload,
        command_idempotency_key="user-click-command",
        created_at=1,
    )


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.flush_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def begin(self):
        return self

    def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.rows)

    def scalar(self, _statement: object) -> object | None:
        return self.rows[0] if self.rows else None

    def flush(self) -> None:
        self.flush_count += 1


class _SessionFactory:
    def __init__(self, rows: list[object]) -> None:
        self.session = _FakeSession(rows)

    def __call__(self) -> _FakeSession:
        return self.session


def test_postgres_port_claims_only_clicked_three_second_job_and_reports_safely() -> None:
    wrong = _projection(external_job_id="shidu_wrong", target=4.0)
    clicked = _projection()
    sessions = _SessionFactory([wrong, clicked])
    jobs = PostgresDeferredJobPort(
        session_factory=sessions,
        project_id=PROJECT_ID,
        worker_identity="amd-vertical-slice-1",
    )

    claimed = jobs.claim_next_clicked_deferred()

    assert claimed is not None
    job = ClickedDeferredVideoJob.from_projection_record(claimed)
    assert job.external_job_id == clicked.external_job_id
    assert clicked.status == "processing"
    worker = clicked.payload["competitionWorker"]
    assert worker == {
        "schemaVersion": "amd.vertical-slice-worker-state.v1",
        "ownerDigest": jobs.owner_digest,
        "status": "active",
        "attemptOrdinal": 1,
        "jobAuthorityDigest": job.authority_digest,
        "errorCode": None,
    }
    assert "amd-vertical-slice-1" not in json.dumps(worker)

    sessions.session.rows = [clicked]
    jobs.report(job, "retryable_failed", "SEARCH_PROVIDER_TIMEOUT")
    assert clicked.status == "processing"
    assert clicked.payload["competitionWorker"]["status"] == "retryable_failed"
    assert clicked.payload["competitionWorker"]["errorCode"] == "SEARCH_PROVIDER_TIMEOUT"
    assert "provider token" not in json.dumps(clicked.payload)

    claimed_again = jobs.claim_next_clicked_deferred()
    assert claimed_again is not None
    assert clicked.payload["competitionWorker"]["attemptOrdinal"] == 2

    jobs.report(job, "terminal_failed", "VISUAL_AUTHORITY_INVALID")
    assert clicked.status == "failed"
    assert clicked.payload["competitionWorker"]["status"] == "terminal_failed"


def test_postgres_port_accepts_materialized_job_but_skips_foreign_active_lease() -> None:
    materialized = _projection(pipeline="h3_vertical_slice", status="processing")
    authority = ClickedDeferredVideoJob.from_projection_record(materialized)
    materialized.payload["competitionWorker"] = {
        "schemaVersion": "amd.vertical-slice-worker-state.v1",
        "ownerDigest": "f" * 64,
        "status": "active",
        "attemptOrdinal": 1,
        "jobAuthorityDigest": authority.authority_digest,
        "errorCode": None,
    }
    jobs = PostgresDeferredJobPort(
        session_factory=_SessionFactory([materialized]),
        project_id=PROJECT_ID,
        worker_identity="another-stable-worker",
    )

    assert jobs.claim_next_clicked_deferred() is None


def test_postgres_report_accepts_delivery_publisher_already_marking_row_succeeded() -> None:
    materialized = _projection(pipeline="h3_vertical_slice", status="processing")
    sessions = _SessionFactory([materialized])
    jobs = PostgresDeferredJobPort(
        session_factory=sessions,
        project_id=PROJECT_ID,
        worker_identity="amd-vertical-slice-1",
    )
    claimed = jobs.claim_next_clicked_deferred()
    assert claimed is not None
    job = ClickedDeferredVideoJob.from_projection_record(claimed)
    # publish_competition_vertical_slice commits this public state first.
    materialized.status = "succeeded"
    materialized.payload["competitionVerticalSlice"] = {
        "envelopeDigest": "d" * 64
    }

    jobs.report(job, "delivered", None)

    assert materialized.status == "succeeded"
    assert materialized.payload["competitionWorker"]["status"] == "delivered"
    assert materialized.payload["competitionWorker"]["errorCode"] is None


def test_checkpoint_port_is_atomic_digest_bound_and_revision_cas(tmp_path: Path) -> None:
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    store = AtomicPersistentCheckpointPort(
        root=persistent / "douyin-amd" / "vertical-slice-checkpoints",
        persistent_root=persistent,
    )
    job = ClickedDeferredVideoJob.from_projection_record(_projection())

    first = store.save(job, WorkerCheckpoint.new(job), expected_revision=None)
    assert first.revision == 1
    assert store.load(job) == first
    target = store.path_for(job)
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["checkpointDigest"] == (
        first.checkpoint_digest
    )
    assert list(target.parent.glob("*.partial")) == []

    second = store.save(job, first, expected_revision=1)
    assert second.revision == 2
    with pytest.raises(CoordinatorContractError, match="revision"):
        store.save(job, second, expected_revision=1)

    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["status"] = "delivered"
    target.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(CoordinatorContractError):
        store.load(job)


def test_checkpoint_port_rejects_location_outside_persistent_root(tmp_path: Path) -> None:
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    with pytest.raises(ValueError, match="persistent"):
        AtomicPersistentCheckpointPort(
            root=tmp_path / "outside",
            persistent_root=persistent,
        )


@dataclass
class _IdleJobs:
    record: object | None
    reports: list[tuple[str, str | None]]

    def claim_next_clicked_deferred(self) -> object | None:
        return self.record

    def report(self, _job: object, status: str, code: str | None) -> None:
        self.reports.append((status, code))


def _stage_functions(calls: list[str]) -> ProductionStageFunctions:
    def function(invocation: object) -> dict[str, object]:
        stage = getattr(invocation, "stage")
        calls.append(stage)
        return {
            "outputDigest": sha256(stage.encode("ascii")).hexdigest(),
            "idempotencyKey": getattr(invocation, "idempotency_key"),
        }

    return ProductionStageFunctions(
        source_prepared=function,
        flux_generated=function,
        references_published=function,
        authority_finalized=function,
        workflow_materialized=function,
        h3_generated=function,
        delivered=function,
    )


def test_idle_daemon_does_not_construct_stage_bundle_or_start_gpu(tmp_path: Path) -> None:
    jobs = _IdleJobs(record=None, reports=[])
    constructed = 0

    def factory(_context: CompetitionDaemonContext) -> ProductionStageFunctions:
        nonlocal constructed
        constructed += 1
        raise AssertionError("idle daemon must not construct runtime/GPU adapters")

    daemon = build_competition_vertical_slice_daemon(
        jobs=jobs,
        checkpoints=AtomicPersistentCheckpointPort(
            root=tmp_path / "persistent" / "checkpoints",
            persistent_root=tmp_path / "persistent",
        ),
        context=CompetitionDaemonContext(
            project_id=PROJECT_ID,
            persistent_root=tmp_path / "persistent",
            session_factory=lambda: None,
        ),
        stage_factory=factory,
    )

    assert daemon.run_once() is None
    assert constructed == 0


def test_lazy_production_factory_invokes_all_seven_real_stage_boundaries_in_order(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    factory_calls = 0

    def factory(_context: CompetitionDaemonContext) -> ProductionStageFunctions:
        nonlocal factory_calls
        factory_calls += 1
        return _stage_functions(calls)

    jobs = _IdleJobs(record=_projection(), reports=[])
    persistent = tmp_path / "persistent"
    daemon = build_competition_vertical_slice_daemon(
        jobs=jobs,
        checkpoints=AtomicPersistentCheckpointPort(
            root=persistent / "checkpoints",
            persistent_root=persistent,
        ),
        context=CompetitionDaemonContext(
            project_id=PROJECT_ID,
            persistent_root=persistent,
            session_factory=lambda: None,
        ),
        stage_factory=factory,
    )

    result = daemon.run_once()

    assert result is not None and result.status == "delivered"
    assert factory_calls == 1
    assert calls == [
        "source_prepared",
        "flux_generated",
        "references_published",
        "authority_finalized",
        "workflow_materialized",
        "h3_generated",
        "delivered",
    ]
    assert jobs.reports == [("delivered", None)]


def test_daemon_run_loop_honors_stop_without_eager_stage_construction(
    tmp_path: Path,
) -> None:
    jobs = _IdleJobs(record=None, reports=[])
    sleeps: list[float] = []
    daemon = CompetitionVerticalSliceDaemon(
        coordinator=build_competition_vertical_slice_daemon(
            jobs=jobs,
            checkpoints=AtomicPersistentCheckpointPort(
                root=tmp_path / "persistent" / "checkpoints",
                persistent_root=tmp_path / "persistent",
            ),
            context=CompetitionDaemonContext(
                project_id=PROJECT_ID,
                persistent_root=tmp_path / "persistent",
                session_factory=lambda: None,
            ),
            stage_factory=lambda _context: (_ for _ in ()).throw(
                AssertionError("must remain idle")
            ),
        ).coordinator,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    checks = iter([False, False, True])

    daemon.serve(poll_seconds=0.25, should_stop=lambda: next(checks))

    assert sleeps == [0.25]
