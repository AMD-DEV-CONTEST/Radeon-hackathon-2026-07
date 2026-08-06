from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.scheduler_system.config import default_factory_scheduler_config, factory_scheduler_owner_id
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.scheduler_system.executor import SchedulerExecutor
from agent_factory.scheduler_system.feedback import summarize_scheduler_feedback
from agent_factory.scheduler_system.reports import SchedulerReportWriter
from agent_factory.scheduler_system.schema import (
    SchedulerContractConfig,
    SchedulerExecutionReport,
    SchedulerFeedbackSummaryDecision,
    SchedulerJob,
    SchedulerRun,
    utc_now,
)
from agent_factory.scheduler_system.store import SQLiteSchedulerStore


SchedulerEventSink = Callable[[SchedulerEventPayload], None]
SchedulerFeedbackSummarizer = Callable[..., SchedulerFeedbackSummaryDecision]


class SchedulerRuntime:
    def __init__(
        self,
        *,
        config: SchedulerContractConfig,
        owner_type: str,
        owner_id: str,
        store: SQLiteSchedulerStore | None = None,
        executor: SchedulerExecutor | None = None,
        report_root: str | Path | None = None,
        event_sink: SchedulerEventSink | None = None,
        feedback_summarizer: SchedulerFeedbackSummarizer | None = None,
    ) -> None:
        self.config = config
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.store = store or SQLiteSchedulerStore(config.store_path)
        self.executor = executor or SchedulerExecutor()
        self.report_writer = SchedulerReportWriter(report_root or Path(config.store_path).with_suffix("") / "reports")
        self.event_sink = event_sink
        self.feedback_summarizer = feedback_summarizer or summarize_scheduler_feedback
        self.worker = None
        self.holder_id = f"{owner_type}:{owner_id}:{uuid4().hex}"

    def create_job(self, payload: dict[str, Any]) -> SchedulerJob:
        job = self._job_from_payload(payload)
        created = self.store.create_job(job)
        self.emit("scheduler_job_created", job=created, status="created")
        self.reschedule()
        return created

    def upsert_job(self, payload: dict[str, Any]) -> SchedulerJob:
        job = self._job_from_payload(payload)
        saved = self.store.upsert_job(job)
        self.emit("scheduler_job_updated", job=saved, status="updated")
        self.reschedule()
        return saved

    def list_jobs(self) -> list[SchedulerJob]:
        return self.store.list_jobs(owner_type=self.owner_type, owner_id=self.owner_id)

    def describe_job(self, job_id: str) -> dict[str, Any]:
        job = self._required_job(job_id)
        runs = self.store.list_runs(job_id=job_id, limit=10)
        return {
            "job": job.model_dump(mode="json"),
            "recent_runs": [item.model_dump(mode="json") for item in runs],
        }

    def set_job_enabled(self, job_id: str, enabled: bool) -> SchedulerJob:
        job = self._required_job(job_id)
        if job.owner_type != self.owner_type or job.owner_id != self.owner_id:
            raise PermissionError("scheduler job does not belong to current owner")
        saved = self.store.set_job_enabled(job_id, enabled)
        self.emit("scheduler_job_updated", job=saved, status="enabled" if enabled else "paused")
        self.reschedule()
        return saved

    def delete_job(self, job_id: str) -> bool:
        job = self._required_job(job_id)
        if job.owner_type != self.owner_type or job.owner_id != self.owner_id:
            raise PermissionError("scheduler job does not belong to current owner")
        deleted = self.store.delete_job(job_id)
        if deleted:
            self.emit("scheduler_job_deleted", job=job, status="deleted")
        self.reschedule()
        return deleted

    def run_now(self, job_id: str) -> SchedulerExecutionReport:
        job = self._required_job(job_id)
        return self.execute_job(job, trigger_reason="manual")

    def execute_job(self, job: SchedulerJob | str, *, trigger_reason: str = "scheduled") -> SchedulerExecutionReport:
        job = self._required_job(job) if isinstance(job, str) else job
        scheduled_at = utc_now().isoformat()
        run = SchedulerRun(
            job_id=job.job_id,
            owner_type=job.owner_type,
            owner_id=job.owner_id,
            target_type=job.target.target_type,
            status="pending",
            scheduled_at=scheduled_at,
            trigger_reason=trigger_reason,
        )
        scheduler_request_id = f"scheduler-{run.run_id}"
        self.store.create_run(run)
        self.emit("scheduler_run_scheduled", job=job, run=run, payload={"request_id": scheduler_request_id})
        lease = self.store.acquire_lease(
            job_id=job.job_id,
            run_id=run.run_id,
            holder_id=self.holder_id,
            ttl_seconds=job.timeout_seconds,
        )
        if lease is None and job.concurrency_policy == "skip":
            skipped = run.model_copy(update={"status": "skipped", "completed_at": utc_now().isoformat()})
            self.store.update_run(skipped)
            report = SchedulerExecutionReport(
                run_id=run.run_id,
                job_id=job.job_id,
                owner_type=job.owner_type,
                owner_id=job.owner_id,
                target_type=job.target.target_type,
                status="skipped",
                started_at=scheduled_at,
                completed_at=skipped.completed_at or scheduled_at,
                duration_ms=0,
                error_summary="another run is already active",
            )
            report_path = self.report_writer.write(report)
            self.emit(
                "scheduler_run_skipped",
                job=job,
                run=skipped,
                report=report,
                report_path=report_path,
                payload={"request_id": scheduler_request_id},
            )
            return report
        if lease is None:
            raise RuntimeError(f"scheduler job is already leased: {job.job_id}")
        running = run.model_copy(update={"status": "running", "started_at": utc_now().isoformat()})
        self.store.update_run(running)
        self.emit("scheduler_run_started", job=job, run=running, payload={"request_id": scheduler_request_id})
        try:
            report = self.executor.execute(job=job, run=running)
            report_path = self.report_writer.write(report)
            status = "completed" if report.status == "completed" else "failed"
            completed = running.model_copy(
                update={
                    "status": status,
                    "completed_at": report.completed_at,
                    "output_summary": report.output_summary,
                    "error_summary": report.error_summary,
                    "report_path": report_path,
                }
            )
            self.store.update_run(completed)
            self.emit(
                "scheduler_run_completed" if status == "completed" else "scheduler_run_failed",
                job=job,
                run=completed,
                report=report,
                report_path=report_path,
                payload={"request_id": scheduler_request_id},
            )
            if status == "failed":
                self._auto_pause_after_failures(job=job, run=completed, report=report, report_path=report_path)
            report_with_path = report.model_copy(update={"evidence": {**report.evidence, "report_path": report_path}})
            self._emit_feedback(
                job=job,
                run=completed,
                report=report_with_path,
                report_path=report_path,
            )
            return report_with_path
        finally:
            self.store.release_lease(job_id=job.job_id, run_id=run.run_id)

    def reschedule(self) -> None:
        worker = self.worker
        if worker is not None:
            worker.reload_jobs()

    def emit(
        self,
        event_type: str,
        *,
        job: SchedulerJob | None = None,
        run: SchedulerRun | None = None,
        status: str | None = None,
        report: SchedulerExecutionReport | None = None,
        report_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.event_sink is None:
            return
        duration_ms = report.duration_ms if report is not None else None
        payload = SchedulerEventPayload(
            event_type=event_type,  # type: ignore[arg-type]
            job_id=job.job_id if job else run.job_id if run else None,
            run_id=run.run_id if run else report.run_id if report else None,
            owner_type=job.owner_type if job else run.owner_type if run else self.owner_type,
            owner_id=job.owner_id if job else run.owner_id if run else self.owner_id,
            target_type=job.target.target_type if job else run.target_type if run else None,
            status=status or (run.status if run else report.status if report else None),
            scheduled_at=run.scheduled_at if run else None,
            duration_ms=duration_ms,
            task_content=job.task_content if job else None,
            error_summary=report.error_summary if report else run.error_summary if run else None,
            report_path=report_path,
            payload=_scheduler_event_payload(payload=payload, report=report),
        )
        self.event_sink(payload)

    def _job_from_payload(self, payload: dict[str, Any]) -> SchedulerJob:
        payload = dict(payload)
        if not str(payload.get("task_content") or "").strip():
            payload["task_content"] = _derived_task_content(payload)
        job_payload = {
            "timezone": self.config.timezone,
            "concurrency_policy": self.config.default_concurrency_policy,
            "timeout_seconds": self.config.default_timeout_seconds,
            "failure_policy": self.config.default_failure_policy.model_dump(mode="json"),
            "unattended_policy": self.config.unattended_policy,
            **payload,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
        }
        return SchedulerJob.model_validate(job_payload)

    def _required_job(self, job_id: str) -> SchedulerJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(f"unknown scheduler job: {job_id}")
        return job

    def _auto_pause_after_failures(
        self,
        *,
        job: SchedulerJob,
        run: SchedulerRun,
        report: SchedulerExecutionReport,
        report_path: str,
    ) -> None:
        policy = job.failure_policy
        if not policy.enabled or policy.action != "pause" or not job.enabled:
            return
        consecutive_failures = self.store.count_consecutive_runs(job_id=job.job_id, status="failed")
        if consecutive_failures < policy.max_consecutive_failures:
            return
        paused = self.store.set_job_enabled(job.job_id, False)
        self.emit(
            "scheduler_job_auto_paused",
            job=paused,
            run=run,
            report=report,
            report_path=report_path,
            status="auto_paused",
            payload={
                "reason": "max_consecutive_failures",
                "consecutive_failures": consecutive_failures,
                "threshold": policy.max_consecutive_failures,
            },
        )
        self.reschedule()

    def _emit_feedback(
        self,
        *,
        job: SchedulerJob,
        run: SchedulerRun,
        report: SchedulerExecutionReport,
        report_path: str,
    ) -> None:
        if self.event_sink is None or not job.feedback.enabled:
            return
        completed_count = self.store.count_runs(job_id=job.job_id, status="completed")
        task_content = job.task_content or _derived_task_content(job.model_dump(mode="json"))
        try:
            decision = self.feedback_summarizer(
                job=job,
                run=run,
                report=report,
                completed_count=completed_count,
            )
            self.event_sink(
                SchedulerEventPayload(
                    event_type="scheduler_feedback_completed",
                    job_id=job.job_id,
                    run_id=run.run_id,
                    owner_type=job.owner_type,
                    owner_id=job.owner_id,
                    target_type=job.target.target_type,
                    status=report.status,
                    completed_at=report.completed_at,
                    completed_count=completed_count,
                    task_content=task_content,
                    summary=decision.summary,
                    report_path=report_path,
                )
            )
        except Exception as exc:
            self.event_sink(
                SchedulerEventPayload(
                    event_type="scheduler_feedback_failed",
                    job_id=job.job_id,
                    run_id=run.run_id,
                    owner_type=job.owner_type,
                    owner_id=job.owner_id,
                    target_type=job.target.target_type,
                    status=report.status,
                    completed_at=report.completed_at,
                    completed_count=completed_count,
                    task_content=task_content,
                    error_summary=f"{type(exc).__name__}: {exc}",
                    report_path=report_path,
                )
            )


def default_factory_scheduler_runtime(*, event_sink: SchedulerEventSink | None = None) -> SchedulerRuntime:
    return SchedulerRuntime(
        config=default_factory_scheduler_config(),
        owner_type="factory",
        owner_id=factory_scheduler_owner_id(),
        event_sink=event_sink,
    )


def _derived_task_content(payload: dict[str, Any]) -> str:
    target = payload.get("target")
    if not isinstance(target, dict):
        return str(payload.get("job_id") or "scheduler job")
    target_type = str(target.get("target_type") or "")
    target_payload = target.get("payload")
    target_payload = target_payload if isinstance(target_payload, dict) else {}
    if target_type == "graph_run":
        return str(target_payload.get("message") or payload.get("job_id") or "scheduled graph run")
    if target_type == "tool_call":
        return f"调用工具 {target_payload.get('tool_id') or payload.get('job_id') or 'tool'}"
    if target_type == "script_run":
        return str(payload.get("job_id") or "执行脚本定时任务")
    return str(payload.get("job_id") or "scheduler job")


def _scheduler_event_payload(
    *,
    payload: dict[str, Any] | None,
    report: SchedulerExecutionReport | None,
) -> dict[str, Any]:
    result = dict(payload or {})
    if report is None:
        return result
    evidence = report.evidence if isinstance(report.evidence, dict) else {}
    execution = evidence.get("execution") if isinstance(evidence.get("execution"), dict) else {}
    if execution:
        result["execution"] = {
            key: value
            for key, value in execution.items()
            if key
            in {
                "request_id",
                "target_scope",
                "package_id",
                "package_name",
                "agent_session",
                "conversation",
                "message",
                "error",
                "error_summary",
                "output_summary",
                "stdout_preview",
                "stderr_preview",
                "exit_code",
            }
        }
    return result
