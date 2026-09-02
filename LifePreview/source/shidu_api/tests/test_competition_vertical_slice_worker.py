from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from shidu_api.competition_vertical_slice_worker import (
    ClickedDeferredVideoJob,
    CompetitionVerticalSliceCoordinator,
    CoordinatorContractError,
    RetryableWorkerStepError,
    StageReceipt,
    TerminalWorkerStepError,
    WorkerCheckpoint,
)


PROJECT_ID = UUID("40000000-0000-4000-8000-000000000001")
BOOK_ID = UUID("40000000-0000-4000-8000-000000000002")
SCRIPT_ID = UUID("40000000-0000-4000-8000-000000000003")
DIRECTION_ID = UUID("40000000-0000-4000-8000-000000000004")
WORKFLOW_ID = UUID("40000000-0000-4000-8000-000000000005")


def _projection(
    *,
    pipeline: str = "h3_deferred_vertical_slice",
    status: str = "queued",
    payload_updates: dict[str, Any] | None = None,
) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "bookId": str(BOOK_ID),
        "directionRevisionId": str(DIRECTION_ID),
        "trialScriptRevisionId": str(SCRIPT_ID),
        "contentMode": "source_grounded",
        "contentLabel": "AI-assisted historical adaptation",
        "contentNotice": "Adapted from cited sources.",
        "pipelineMode": pipeline,
        "targetDurationSeconds": 3.0,
        "sequenceCount": 1,
        "requestDigest": "a" * 64,
        "researchJobId": "40000000-0000-4000-8000-000000000006",
        "safetyDecisionDigest": "b" * 64,
        "competitionPreparedReference": {
            "requestId": "40000000-0000-4000-8000-000000000008",
            "artifactSha256": "d" * 64,
            "sourceMode": "preuploaded_imported",
            "importAuthoritySha256": "e" * 64,
        },
    }
    if pipeline == "h3_vertical_slice":
        payload.update(
            {
                "workflowRunId": str(WORKFLOW_ID),
                "visualIdentityResolutionId": (
                    "40000000-0000-4000-8000-000000000007"
                ),
                "inputAuthorityDigest": "c" * 64,
            }
        )
    if payload_updates:
        payload.update(payload_updates)
    return SimpleNamespace(
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        trial_script_revision_id=SCRIPT_ID,
        external_job_id="shidu_clicked_job",
        status=status,
        payload=payload,
        command_idempotency_key="user-click-key",
    )


class _Jobs:
    def __init__(self, record: object | None) -> None:
        self.record = record
        self.statuses: list[tuple[str, str | None]] = []

    def claim_next_clicked_deferred(self) -> object | None:
        return self.record

    def report(self, job: ClickedDeferredVideoJob, status: str, code: str | None) -> None:
        assert job.external_job_id == "shidu_clicked_job"
        self.statuses.append((status, code))


class _Checkpoints:
    def __init__(self) -> None:
        self.value: WorkerCheckpoint | None = None
        self.history: list[WorkerCheckpoint] = []
        self.fail_on_stage: str | None = None

    def load(self, job: ClickedDeferredVideoJob) -> WorkerCheckpoint | None:
        return self.value

    def save(
        self,
        job: ClickedDeferredVideoJob,
        checkpoint: WorkerCheckpoint,
        *,
        expected_revision: int | None,
    ) -> WorkerCheckpoint:
        if self.fail_on_stage == checkpoint.completed_stage:
            raise RuntimeError("checkpoint unavailable")
        current_revision = None if self.value is None else self.value.revision
        assert current_revision == expected_revision
        revision = 1 if expected_revision is None else expected_revision + 1
        self.value = checkpoint.with_revision(revision)
        self.history.append(self.value)
        return self.value


class _StagePort:
    def __init__(self, stage: str, calls: list[tuple[str, str]]) -> None:
        self.stage = stage
        self.calls = calls
        self.error: Exception | None = None

    def execute(
        self,
        *,
        job: ClickedDeferredVideoJob,
        prior_receipts: tuple[StageReceipt, ...],
        idempotency_key: str,
    ) -> StageReceipt:
        self.calls.append((self.stage, idempotency_key))
        if self.error is not None:
            raise self.error
        return StageReceipt.build(
            stage=self.stage,
            job_authority_digest=job.authority_digest,
            payload={
                "idempotencyKey": idempotency_key,
                "priorReceiptCount": len(prior_receipts),
                "outputDigest": self.stage[0] * 64,
            },
        )


def _coordinator(record: object | None = None) -> tuple[
    CompetitionVerticalSliceCoordinator,
    _Jobs,
    _Checkpoints,
    dict[str, _StagePort],
    list[tuple[str, str]],
]:
    jobs = _Jobs(_projection() if record is None else record)
    checkpoints = _Checkpoints()
    calls: list[tuple[str, str]] = []
    ports = {
        stage: _StagePort(stage, calls)
        for stage in (
            "source_prepared",
            "flux_generated",
            "references_published",
            "authority_finalized",
            "workflow_materialized",
            "h3_generated",
            "delivered",
        )
    }
    coordinator = CompetitionVerticalSliceCoordinator(
        jobs=jobs,
        checkpoints=checkpoints,
        source_preparer=ports["source_prepared"],
        flux_runner=ports["flux_generated"],
        reference_publisher=ports["references_published"],
        authority_finalizer=ports["authority_finalized"],
        workflow_materializer=ports["workflow_materialized"],
        h3_runner=ports["h3_generated"],
        delivery_publisher=ports["delivered"],
    )
    return coordinator, jobs, checkpoints, ports, calls


def test_process_one_runs_exact_restart_safe_clicked_pipeline() -> None:
    coordinator, jobs, checkpoints, _, calls = _coordinator()

    result = coordinator.process_one()

    assert result is not None
    assert result.status == "delivered"
    assert result.completed_stage == "delivered"
    assert [stage for stage, _ in calls] == [
        "source_prepared",
        "flux_generated",
        "references_published",
        "authority_finalized",
        "workflow_materialized",
        "h3_generated",
        "delivered",
    ]
    assert len({key for _, key in calls}) == 7
    assert all(key.startswith("amd-three-second:") for _, key in calls)
    assert [row.completed_stage for row in checkpoints.history] == [
        "clicked",
        "source_prepared",
        "flux_generated",
        "references_published",
        "authority_finalized",
        "workflow_materialized",
        "h3_generated",
        "delivered",
    ]
    assert jobs.statuses == [("delivered", None)]


@pytest.mark.parametrize(
    "updates",
    [
        {"pipelineMode": "legacy"},
        {"targetDurationSeconds": 4.0},
        {"sequenceCount": 2},
        {"nativeAudio": False},
        {"subtitles": True},
        {"frameCount": 72},
        {"requestDigest": "broken"},
    ],
)
def test_invalid_or_non_clicked_projection_fails_before_any_gpu_port(
    updates: dict[str, Any],
) -> None:
    coordinator, _, checkpoints, _, calls = _coordinator(
        _projection(payload_updates=updates)
    )

    with pytest.raises(CoordinatorContractError):
        coordinator.process_one()

    assert calls == []
    assert checkpoints.value is None


def test_no_clicked_job_is_idle_and_never_calls_gpu() -> None:
    coordinator, jobs, checkpoints, _, calls = _coordinator()
    jobs.record = None

    assert coordinator.process_one() is None
    assert calls == []
    assert checkpoints.value is None


def test_clicked_checkpoint_must_commit_before_any_stage_can_start() -> None:
    coordinator, _, checkpoints, _, calls = _coordinator()
    checkpoints.fail_on_stage = "clicked"

    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        coordinator.process_one()

    assert calls == []


def test_retryable_source_failure_is_durable_and_resume_skips_completed_stages() -> None:
    coordinator, jobs, checkpoints, ports, calls = _coordinator()
    ports["source_prepared"].error = RetryableWorkerStepError(
        "source_prepared", "SEARCH_TIMEOUT"
    )

    first = coordinator.process_one()

    assert first is not None
    assert first.status == "retryable_failed"
    assert first.completed_stage == "clicked"
    assert first.error_stage == "source_prepared"
    assert jobs.statuses == [("retryable_failed", "SEARCH_TIMEOUT")]
    assert [stage for stage, _ in calls] == ["source_prepared"]

    ports["source_prepared"].error = None
    second = coordinator.process_one()

    assert second is not None and second.status == "delivered"
    assert [stage for stage, _ in calls].count("source_prepared") == 2
    assert [stage for stage, _ in calls].count("flux_generated") == 1


def test_restart_after_flux_uses_receipts_and_does_not_repeat_flux() -> None:
    coordinator, _, checkpoints, ports, calls = _coordinator()
    job = ClickedDeferredVideoJob.from_projection_record(_projection())
    checkpoint = WorkerCheckpoint.new(job)
    checkpoint = checkpoint.advance(
        StageReceipt.build(
            stage="source_prepared",
            job_authority_digest=job.authority_digest,
            payload={"outputDigest": "1" * 64},
        )
    )
    checkpoint = checkpoint.advance(
        StageReceipt.build(
            stage="flux_generated",
            job_authority_digest=job.authority_digest,
            payload={"outputDigest": "2" * 64},
        )
    )
    checkpoints.value = checkpoint.with_revision(3)

    result = coordinator.process_one()

    assert result is not None and result.status == "delivered"
    assert ports["source_prepared"].calls == calls
    assert "source_prepared" not in [stage for stage, _ in calls]
    assert "flux_generated" not in [stage for stage, _ in calls]
    assert [stage for stage, _ in calls][0] == "references_published"


def test_terminal_step_failure_never_runs_later_gpu_and_is_not_retried() -> None:
    coordinator, jobs, _, ports, calls = _coordinator()
    ports["references_published"].error = TerminalWorkerStepError(
        "references_published", "CAS_LINEAGE_MISMATCH"
    )

    first = coordinator.process_one()
    second = coordinator.process_one()

    assert first is not None and first.status == "terminal_failed"
    assert second == first
    assert [stage for stage, _ in calls] == [
        "source_prepared",
        "flux_generated",
        "references_published",
    ]
    assert "h3_generated" not in [stage for stage, _ in calls]
    assert jobs.statuses == [("terminal_failed", "CAS_LINEAGE_MISMATCH")]


def test_unclassified_dependency_failure_is_retryable_without_leaking_message() -> None:
    coordinator, jobs, checkpoint_store, ports, _ = _coordinator()
    ports["workflow_materialized"].error = RuntimeError("secret provider token")

    result = coordinator.process_one()

    assert result is not None and result.status == "retryable_failed"
    assert result.error_code == "UNCLASSIFIED_DEPENDENCY_FAILURE"
    assert "secret" not in repr(checkpoint_store.value)
    assert jobs.statuses[-1] == (
        "retryable_failed",
        "UNCLASSIFIED_DEPENDENCY_FAILURE",
    )


def test_wrong_stage_receipt_is_durable_terminal_contract_failure() -> None:
    coordinator, jobs, _, ports, calls = _coordinator()

    def wrong_receipt(**kwargs: Any) -> StageReceipt:
        job = kwargs["job"]
        calls.append(("source_prepared", kwargs["idempotency_key"]))
        return StageReceipt.build(
            stage="flux_generated",
            job_authority_digest=job.authority_digest,
            payload={"outputDigest": "f" * 64},
        )

    ports["source_prepared"].execute = wrong_receipt  # type: ignore[method-assign]

    result = coordinator.process_one()

    assert result is not None and result.status == "terminal_failed"
    assert result.error_code == "STAGE_CONTRACT_VIOLATION"
    assert jobs.statuses[-1] == (
        "terminal_failed",
        "STAGE_CONTRACT_VIOLATION",
    )


def test_checkpoint_tamper_fails_closed_before_any_new_gpu_call() -> None:
    coordinator, _, checkpoints, _, calls = _coordinator()
    job = ClickedDeferredVideoJob.from_projection_record(_projection())
    valid = WorkerCheckpoint.new(job).with_revision(1)
    object.__setattr__(valid, "checkpoint_digest", "f" * 64)
    checkpoints.value = valid

    with pytest.raises(CoordinatorContractError):
        coordinator.process_one()

    assert calls == []


def test_checkpoint_standard_json_round_trip_and_tamper_detection() -> None:
    job = ClickedDeferredVideoJob.from_projection_record(_projection())
    checkpoint = WorkerCheckpoint.new(job).advance(
        StageReceipt.build(
            stage="source_prepared",
            job_authority_digest=job.authority_digest,
            payload={"outputDigest": "a" * 64},
        )
    ).with_revision(2)

    encoded = checkpoint.to_json_object()
    assert WorkerCheckpoint.from_json_object(encoded) == checkpoint

    encoded["receipts"][0]["payload"]["outputDigest"] = "b" * 64
    with pytest.raises(CoordinatorContractError):
        WorkerCheckpoint.from_json_object(encoded)


def test_materialized_projection_keeps_same_clicked_authority_identity() -> None:
    before = ClickedDeferredVideoJob.from_projection_record(_projection())
    after = ClickedDeferredVideoJob.from_projection_record(
        _projection(pipeline="h3_vertical_slice")
    )

    assert before.authority_digest == after.authority_digest
    assert before.workflow_run_id is None
    assert after.workflow_run_id == WORKFLOW_ID


def test_materialized_projection_without_clicked_checkpoint_fails_closed() -> None:
    coordinator, _, checkpoints, _, calls = _coordinator(
        _projection(pipeline="h3_vertical_slice")
    )

    with pytest.raises(
        CoordinatorContractError,
        match="no durable clicked checkpoint",
    ):
        coordinator.process_one()

    assert checkpoints.value is None
    assert calls == []
