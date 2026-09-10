"""Small-batch production runner — injected backend/verifier, export isolation."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.errors import DomainError
from specstyle.workflow.job_models import JobId
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.orchestrator import FakeJobPlan, FakeJobResult
from specstyle.workflow.real_pipeline import (
    CancelToken,
    PipelineServices,
    assert_export_isolation,
    run_production_job,
)


@dataclass(frozen=True, slots=True)
class BatchItem:
    job_id: JobId
    plan: FakeJobPlan
    bundle_name: str
    spec_text: object
    source: object
    prompt: object
    control_builder: object


@dataclass(frozen=True, slots=True)
class BatchResult:
    results: tuple[FakeJobResult, ...]
    completed: int
    failed: int
    cancelled: int


def run_small_batch(
    items: tuple[BatchItem, ...],
    *,
    context: object,
    environment: object,
    job_store: JobStore,
    root_fd: int,
    services: PipelineServices,
    cancel: CancelToken | None = None,
    max_items: int = 8,
) -> BatchResult:
    """Serial small batch (≤ max_items). Stops starting new work if cancelled."""
    if type(items) is not tuple:
        raise DomainError("invalid batch items")
    if type(max_items) is not int or isinstance(max_items, bool) or max_items < 1:
        raise DomainError("invalid max_items")
    if len(items) > max_items:
        raise DomainError("batch exceeds max_items")
    if not isinstance(services, PipelineServices):
        raise DomainError("invalid pipeline services")
    if not isinstance(job_store, JobStore):
        raise DomainError("invalid job store")
    results: list[FakeJobResult] = []
    completed = failed = cancelled = 0
    for item in items:
        if type(item) is not BatchItem:
            raise DomainError("invalid batch item")
        if cancel is not None and cancel.cancelled:
            cancelled += len(items) - len(results)
            break
        result = run_production_job(
            spec_text=item.spec_text,
            context=context,
            source=item.source,
            prompt=item.prompt,
            control_builder=item.control_builder,
            environment=environment,
            plan=item.plan,
            job_store=job_store,
            root_fd=root_fd,
            bundle_name=item.bundle_name,
            services=services,
            cancel=cancel,
        )
        assert_export_isolation(result)
        results.append(result)
        if result.final_status == "COMPLETED":
            completed += 1
        elif result.final_status == "CANCELLED":
            cancelled += 1
        else:
            failed += 1
    return BatchResult(tuple(results), completed, failed, cancelled)
