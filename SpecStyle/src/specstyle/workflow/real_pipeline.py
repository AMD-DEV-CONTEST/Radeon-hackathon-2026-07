"""WF-003 production pipeline: serial stages, cancel, OOM/crash fail-closed.

Injected backends/verifiers only; no Gradio business truth. Wraps generation to
honour cancel between attempts and maps InfrastructureError (OOM/failure) to
JOB_FAILED without publishing partial approved bundles.
"""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.errors import DomainError, InfrastructureError, SpecStyleError
from specstyle.generation.protocols import GeneratedArtifact, GenerationBackend
from specstyle.generation.requests import GenerationRequest
from specstyle.verification.protocols import Verifier
from specstyle.workflow.job_models import JobId, JobStatus
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.orchestrator import FakeJobPlan, FakeJobResult, run_fake_job


@dataclass(slots=True)
class CancelToken:
    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@dataclass(frozen=True, slots=True)
class PipelineServices:
    backend: GenerationBackend
    verifier: Verifier


@dataclass(slots=True)
class _CancellableBackend:
    """GenerationBackend proxy: refuse work when cancel token is set."""

    inner: GenerationBackend
    cancel: CancelToken
    generate_calls: int = 0
    refused_after_cancel: int = 0

    def generate(self, request: GenerationRequest) -> GeneratedArtifact:
        if self.cancel.cancelled:
            self.refused_after_cancel += 1
            raise DomainError("job cancelled")
        self.generate_calls += 1
        return self.inner.generate(request)


@dataclass(slots=True)
class _FaultyBackend:
    """Test/prod helper: raise InfrastructureError after N successful calls."""

    inner: GenerationBackend
    fail_after: int
    error_message: str = "generation OOM"
    _calls: int = 0

    def generate(self, request: GenerationRequest) -> GeneratedArtifact:
        self._calls += 1
        if self._calls > self.fail_after:
            raise InfrastructureError(self.error_message)
        return self.inner.generate(request)


def run_production_job(
    *,
    spec_text: object,
    context: object,
    source: object,
    prompt: object,
    control_builder: object,
    environment: object,
    plan: FakeJobPlan,
    job_store: JobStore,
    root_fd: int,
    bundle_name: str,
    services: PipelineServices,
    cancel: CancelToken | None = None,
) -> FakeJobResult:
    """Serial production job with cancel and infrastructure fail-closed.

    - Pre-start cancel → DomainError, no store mutation beyond existing state.
    - Mid-run cancel (token set before next generate) → DomainError from backend
      proxy → orchestrator maps SpecStyleError to JOB_FAILED, no final bundle.
    - InfrastructureError (OOM/generation failed) → JOB_FAILED, bundle is None.
    - Terminal resume: delegates to run_fake_job short-circuit (no re-export).
    """
    if not isinstance(services, PipelineServices):
        raise DomainError("invalid pipeline services")
    if cancel is not None and cancel.cancelled:
        raise DomainError("job cancelled")

    backend: GenerationBackend = services.backend
    if cancel is not None:
        backend = _CancellableBackend(services.backend, cancel)

    try:
        result = run_fake_job(
            spec_text,
            context,  # type: ignore[arg-type]
            source,  # type: ignore[arg-type]
            prompt,  # type: ignore[arg-type]
            control_builder,
            environment,  # type: ignore[arg-type]
            plan,
            job_store,
            root_fd,
            bundle_name,
            verifier=services.verifier,
            backend=backend,
        )
    except InfrastructureError:
        # Fail closed: never return a partial COMPLETED bundle.
        return FakeJobResult(None, (), (), (), "JOB_FAILED")
    except SpecStyleError:
        return FakeJobResult(None, (), (), (), "JOB_FAILED")

    # Invariant: COMPLETED implies bundle published; failures never export.
    if result.final_status == "COMPLETED":
        if result.bundle is None and not _is_terminal_resume(job_store, plan.job_id):
            return FakeJobResult(None, (), (), (), "JOB_FAILED")
    if result.final_status == "JOB_FAILED":
        if result.bundle is not None:
            raise DomainError("export isolation violated")
    return result


def _is_terminal_resume(job_store: JobStore, job_id: JobId) -> bool:
    try:
        state = job_store.load(job_id)
    except DomainError:
        return False
    return bool(state.job.terminal)  # type: ignore[attr-defined]


def job_is_resumable(job_store: JobStore, job_id: JobId) -> bool:
    """True when job exists and is not in a terminal state (after event replay)."""
    try:
        state = job_store.load(job_id)
    except DomainError:
        return False
    status = state.job.status  # type: ignore[attr-defined]
    return status not in (
        JobStatus.COMPLETED,
        JobStatus.JOB_FAILED,
        JobStatus.CANCELLED,
    )


def assert_export_isolation(result: FakeJobResult) -> None:
    """Hard invariant: JOB_FAILED/FATAL never carries a published bundle."""
    if result.final_status in ("JOB_FAILED", "FATAL", "CANCELLED"):
        if result.bundle is not None:
            raise DomainError("export isolation violated")
