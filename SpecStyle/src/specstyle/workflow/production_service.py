"""Private production composition for the initial generation attempt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import threading
from typing import Any, Callable

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.enums import ArtifactStatus, RuleScope, StaticApplicability
from specstyle.domain.identifiers import AttemptId, JobId
from specstyle.errors import DomainError, InfrastructureError, _GpuOutOfMemoryError
from specstyle.generation.diffusers_backend import DiffusersBackend, StyleAssetResolver
from specstyle.generation.diffusers_loader import (
    LoadedPipeline,
    _GPU_LEASE,
    load_production_pipeline,
)
from specstyle.generation.model_approval import VerifiedPipelineSupply
from specstyle.generation.output_profiles import render_production_output
from specstyle.generation.pipeline_factory import PipelineGraph
from specstyle.generation.preprocess import PreparedImage
from specstyle.generation.protocols import (
    ControlInputBuilder,
    GeneratedArtifact,
    build_control_input,
    run_generation,
)
from specstyle.generation.requests import GenerationRequest, RenderedPrompt
from specstyle.observability.environment import (
    EnvironmentSnapshot,
    hash_environment,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.history import RepairHistory
from specstyle.repair.loop import NextGeneration, RepairTerminal
from specstyle.spec.compiled_models import (
    CompiledExecutionGraph,
    CompiledStyleSpec,
    CompiledVerificationPlan,
    CompilerContext,
    OutputProfile,
    OutputProfileCapability,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.loader import load_style_spec_text
from specstyle.verification.l1.production_bindings import (
    ProductionL1RuleBinding,
    _rebuild_production_l1_rule_bindings,
    production_l1_rule_bindings,
)
from specstyle.verification.production import (
    _L1RuleMapping,
    _ProductionVerificationAllowlist,
    _create_production_verifier_factory,
)
from specstyle.verification.production_contracts import _clone_compiler_context
from specstyle.verification.protocols import Verifier, run_verifier
from specstyle.verification.rule_models import VerificationReport
from specstyle.workflow.job_models import (
    AttemptFinishedPayload,
    AttemptStartedPayload,
    CancelRequestedPayload,
    Event,
    EventType,
    FatalPayload,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    JobState,
    JobStatus,
    RepairStepPayload,
    SpecCompiledPayload,
    VerifierFinishedPayload,
    _bundle_name,
    _timestamp,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_artifacts import _open_production_artifact_store
from specstyle.workflow.production_export import (
    ProductionExportCommand,
    ProductionExportResult,
    ProductionRecoveryEntry,
    _prepare_production_export_command,
)
from specstyle.workflow.production_export_lifecycle import (
    _ExportPhase,
    _export_lock_holder,
    _prepare_publish_arguments,
    _publish_export,
    _recover_exports,
)
from specstyle.workflow.production_repair import (
    _compose_initial_repair,
    _compose_repair_result,
    _repair_ids,
    _validate_repair_contract,
)
from specstyle.workflow.production_reports import _open_production_report_store

__all__ = (
    "ProductionJobRequest",
    "ProductionJobResult",
    "ProductionL1RuleBinding",
    "production_l1_rule_bindings",
    "ProductionRuntime",
    "ProductionRuntimeReadiness",
    "ProductionRuntimeFailureKind",
    "load_production_compiler_context",
    "open_production_runtime",
)

_OUTPUT_PROFILES = {"xhs_grid", "talking_head_cover", "background_sequence"}
_PRODUCTION_BACKEND_TYPE = DiffusersBackend
_ACTIVE_RUNTIME = threading.local()
_CLOSE_GUARD = threading.Lock()
_CLOSE_DONE: dict[int, threading.Event] = {}
_SET_EVENT = threading.Event()
_SET_EVENT.set()
_CONTEXT_FACTORY_ACTIVE = threading.local()


class ProductionRuntimeReadiness(StrEnum):
    READY = "READY"
    BUSY = "BUSY"
    QUARANTINED = "QUARANTINED"
    CLOSED = "CLOSED"


class ProductionRuntimeFailureKind(StrEnum):
    GPU_OOM = "GPU_OOM"


_RuntimeReadiness = ProductionRuntimeReadiness
_RuntimeFailureKind = ProductionRuntimeFailureKind


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _NondecreasingAuditClock:
    __slots__ = ("_source", "_last")

    def __init__(self, source: Callable[[], str], /) -> None:
        self._source = source
        self._last: str | None = None

    def __call__(self) -> str:
        current = self._source()
        try:
            current = _timestamp(current)
        except DomainError:
            return current
        if self._last is None or current >= self._last:
            self._last = current
        return self._last


@dataclass(frozen=True, slots=True)
class ProductionJobRequest:
    """Validated input for one production generation attempt."""

    job_id: JobId
    spec_text: str
    source: PreparedImage
    style_references: tuple[AssetRef, ...]
    prompt: RenderedPrompt
    output_profile: OutputProfile
    variation_index: int
    bundle_name: str

    def __post_init__(self) -> None:
        if (
            type(self.job_id) is not JobId
            or type(self.spec_text) is not str
            or type(self.source) is not PreparedImage
            or type(self.style_references) is not tuple
            or not self.style_references
            or any(
                type(reference) is not AssetRef for reference in self.style_references
            )
            or type(self.prompt) is not RenderedPrompt
            or type(self.output_profile) is not str
            or self.output_profile not in _OUTPUT_PROFILES
            or type(self.variation_index) is not int
            or not 0 <= self.variation_index < 2**31
            or type(self.bundle_name) is not str
        ):
            raise DomainError("invalid production job request")
        _bundle_name(self.bundle_name)
        AttemptId(f"{self.job_id.value}-a0-{self.output_profile}-0")
        _repair_ids(self.job_id, self.output_profile)


@dataclass(frozen=True, slots=True)
class ProductionJobResult:
    compiled: CompiledStyleSpec
    graph: CompiledExecutionGraph
    verification_plan: CompiledVerificationPlan
    request: GenerationRequest
    artifact: GeneratedArtifact
    report: VerificationReport
    history: RepairHistory
    terminal: RepairTerminal
    job_state: JobState


def _rebuild_production_job_request(value: object) -> ProductionJobRequest:
    if type(value) is not ProductionJobRequest:
        raise DomainError("invalid production export") from None
    try:
        return ProductionJobRequest(
            value.job_id,
            value.spec_text,
            value.source,
            value.style_references,
            value.prompt,
            value.output_profile,
            value.variation_index,
            value.bundle_name,
        )
    except Exception:
        raise DomainError("invalid production export") from None


@dataclass(frozen=True, slots=True)
class _PreparedInitialAttempt:
    compiled: CompiledStyleSpec
    graph: CompiledExecutionGraph
    verification_plan: CompiledVerificationPlan
    request: GenerationRequest
    repository: Any
    report_repository: Any
    verifier: Verifier


def _select_initial_contract(
    request: ProductionJobRequest, compiler_context: CompilerContext
) -> tuple[CompiledStyleSpec, CompiledExecutionGraph, CompiledVerificationPlan]:
    compiled = compile_style_spec(
        load_style_spec_text(request.spec_text), compiler_context
    )
    graphs = tuple(
        graph
        for graph in compiled.production_graphs
        if graph.output_profile == request.output_profile
    )
    plans = tuple(
        plan
        for plan in compiled.verification_plans
        if plan.output_profile == request.output_profile
    )
    if len(graphs) != 1 or len(plans) != 1:
        raise DomainError("production selectors must resolve exactly once")
    _reject_required_batch_plan(plans[0])
    _validate_repair_contract(compiled, request.output_profile)
    return compiled, graphs[0], plans[0]


def _reject_required_batch_plan(plan: object) -> None:
    if any(
        rule.definition.scope is RuleScope.BATCH
        and rule.definition.required
        and rule.definition.applicability is StaticApplicability.APPLICABLE
        for rule in getattr(plan, "rules", ())
    ):
        raise DomainError("BATCH_CONTEXT_REQUIRED")


def _matches_descriptor(resolved: object, descriptor: object) -> bool:
    pin = getattr(resolved, "pin", None)
    return (
        getattr(pin, "id", None) == getattr(descriptor, "model_id", None)
        and getattr(pin, "revision", None) == getattr(descriptor, "revision", None)
        and getattr(pin, "sha256", None) == getattr(descriptor, "expected_sha256", None)
    )


def _preflight_bindings(
    request: ProductionJobRequest,
    graph: CompiledExecutionGraph,
    loaded: LoadedPipeline,
) -> None:
    loaded_graph = loaded._graph
    runtime = graph.runtime
    if (
        graph.generation_profile != "production"
        or graph.pipeline != "sdxl_base"
        or graph.scheduler != "euler"
        or graph.controlnet.controlnet_type != "canny"
        or runtime.backend != "rocm"
        or runtime.dtype != "float16"
        or (
            runtime.rocm_version,
            runtime.torch_version,
            runtime.diffusers_version,
            runtime.dtype,
        )
        != loaded._runtime
        or not _matches_descriptor(graph.base_model, loaded_graph.base)
        or not _matches_descriptor(graph.ip_adapter, loaded_graph.ip_adapter)
        or not _matches_descriptor(graph.controlnet, loaded_graph.controlnet)
        or tuple(reference.sha256 for reference in request.style_references)
        != graph.style_reference_hashes
    ):
        raise DomainError("production preflight binding mismatch")


def _initial_generation_request(
    request: ProductionJobRequest,
    compiled: CompiledStyleSpec,
    graph: CompiledExecutionGraph,
    control_builder: ControlInputBuilder,
    environment: EnvironmentSnapshot,
) -> GenerationRequest:
    control = build_control_input(control_builder, request.source, graph)
    return GenerationRequest(
        request.job_id,
        AttemptId(f"{request.job_id.value}-a0-{request.output_profile}-0"),
        None,
        compiled,
        "production",
        request.output_profile,
        request.source,
        request.style_references,
        request.prompt,
        control,
        request.variation_index,
        hash_environment(environment),
    )


def _append_event(
    store: JobStore,
    job_id: JobId,
    event_type: EventType,
    from_state: JobStatus,
    to_state: JobStatus,
    timestamp: str,
    payload: object,
) -> None:
    store.append_event(
        job_id,
        Event(1, job_id, event_type, from_state, to_state, timestamp, payload),
    )


def _create_initial_job(
    store: JobStore,
    request: ProductionJobRequest,
    compiled: CompiledStyleSpec,
    clock: Callable[[], str],
) -> JobBudget:
    timestamp = clock()
    budget = JobBudget(1 + compiled.source_spec.repair.max_rounds)
    job = Job(
        request.job_id,
        compiled.compiled_spec_hash,
        (request.output_profile,),
        budget,
        JobStatus.CREATED,
        timestamp,
        timestamp,
    )
    store.save_snapshot(
        request.job_id,
        JobSnapshot("specstyle.workflow.snapshot.v1", job, 0, (), ()),
    )
    return budget


def _reject_duplicate_job(store: JobStore, job_id: JobId) -> None:
    if store.get_snapshot(job_id) is not None:
        raise DomainError("duplicate production job id")


def _record_attempt_start(
    store: JobStore,
    request: ProductionJobRequest,
    compiled: CompiledStyleSpec,
    generation_request: GenerationRequest,
    budget: JobBudget,
    clock: Callable[[], str],
    checkpoint: Callable[[], None],
) -> None:
    transitions = (
        (
            EventType.JOB_STARTED,
            JobStatus.CREATED,
            JobStatus.SPEC_VALIDATED,
            JobStartedPayload(
                compiled.compiled_spec_hash, (request.output_profile,), budget
            ),
        ),
        (
            EventType.SPEC_COMPILED,
            JobStatus.SPEC_VALIDATED,
            JobStatus.SPEC_COMPILED,
            SpecCompiledPayload(compiled.compiled_spec_hash),
        ),
        (
            EventType.ATTEMPT_STARTED,
            JobStatus.SPEC_COMPILED,
            JobStatus.GENERATING,
            AttemptStartedPayload(0, 0, generation_request.attempt_id, None),
        ),
    )
    for event_type, from_state, to_state, payload in transitions:
        checkpoint()
        _append_event(
            store, request.job_id, event_type, from_state, to_state, clock(), payload
        )
        checkpoint()


def _run_initial_generation(
    loaded: LoadedPipeline,
    style_assets: StyleAssetResolver,
    store: JobStore,
    request: GenerationRequest,
    clock: Callable[[], str],
    from_state: JobStatus = JobStatus.GENERATING,
    cancel_event: threading.Event | None = None,
) -> GeneratedArtifact:
    del store, clock, from_state
    factory = DiffusersBackend
    if factory is _PRODUCTION_BACKEND_TYPE:
        backend = factory(loaded, style_assets, cancel_event=cancel_event)
    else:
        backend = factory(loaded, style_assets)
        if type(backend) is not _PRODUCTION_BACKEND_TYPE:
            raise InfrastructureError("invalid generation backend")
        if cancel_event is not None:
            backend._bind_cancel_event(cancel_event)
    artifact = run_generation(backend, request)
    contract = request.graph.render_contract
    if contract is None:
        return artifact
    capability = OutputProfileCapability(
        request.graph.output_profile_pin,
        request.output_profile,
        ("product_instance",),
        ("preview", "production"),
        contract,
    )
    content = render_production_output(artifact.content, capability)
    return GeneratedArtifact(
        ArtifactRef(artifact.ref.artifact_id, hash_bytes(content)),
        content,
        artifact.request_hash,
        artifact.generation_fingerprint,
    )


def _record_generation_fatal(
    store: JobStore,
    request: GenerationRequest,
    state: JobStatus,
    clock: Callable[[], str],
    *,
    oom: bool,
) -> None:
    try:
        _append_event(
            store,
            request.job_id,
            EventType.FATAL,
            state,
            JobStatus.JOB_FAILED,
            clock(),
            FatalPayload(
                "GENERATION_OOM" if oom else "GENERATION_FAILED",
                "generation OOM" if oom else "generation failed",
            ),
        )
    except Exception:
        pass


def _record_attempt_finish(
    store: JobStore,
    request: GenerationRequest,
    artifact: GeneratedArtifact,
    timestamp: str,
    from_state: JobStatus = JobStatus.GENERATING,
) -> None:
    _append_event(
        store,
        request.job_id,
        EventType.ATTEMPT_FINISHED,
        from_state,
        JobStatus.VERIFYING,
        timestamp,
        AttemptFinishedPayload(
            0,
            0,
            request.attempt_id,
            artifact.ref.artifact_id,
            request.request_hash,
        ),
    )


def _record_verifier_fatal(
    store: JobStore, job_id: JobId, clock: Callable[[], str]
) -> None:
    try:
        _append_event(
            store,
            job_id,
            EventType.FATAL,
            JobStatus.VERIFYING,
            JobStatus.JOB_FAILED,
            clock(),
            FatalPayload("VERIFIER_UNAVAILABLE", "verifier unavailable"),
        )
    except Exception:
        pass


def _run_initial_verification(
    verifier: Verifier,
    store: JobStore,
    request: GenerationRequest,
    artifact: GeneratedArtifact,
    plan: CompiledVerificationPlan,
    clock: Callable[[], str],
) -> VerificationReport:
    artifacts = (artifact.ref,)
    rules = plan.applicable_rule_definitions
    failed = False
    try:
        results = run_verifier(verifier, artifacts, rules)
        report = VerificationReport(artifacts, rules, results)
    except _GpuOutOfMemoryError:
        raise
    except Exception:
        failed = True
    if failed:
        _record_verifier_fatal(store, request.job_id, clock)
        raise InfrastructureError("verifier unavailable") from None
    return report


def _record_unknown_fatal(
    store: JobStore,
    job_id: JobId,
    from_state: JobStatus,
    clock: Callable[[], str],
    reason: str,
) -> None:
    try:
        _append_event(
            store,
            job_id,
            EventType.FATAL,
            from_state,
            JobStatus.JOB_FAILED,
            clock(),
            FatalPayload("UNKNOWN", reason),
        )
    except Exception:
        pass


def _persist_artifact(
    repository: Any,
    artifact: GeneratedArtifact,
    store: JobStore,
    request: GenerationRequest,
    state: JobStatus,
    clock: Callable[[], str],
    checkpoint: Callable[[], None],
) -> None:
    checkpoint()
    failed = False
    try:
        repository.put(artifact)
    except Exception:
        failed = True
    if failed:
        _record_unknown_fatal(
            store, request.job_id, state, clock, "artifact persistence failed"
        )
        raise InfrastructureError("artifact persistence failed") from None
    checkpoint()
    failed = False
    try:
        if repository(artifact.ref) != artifact:
            raise InfrastructureError("artifact readback mismatch")
    except Exception:
        failed = True
    if failed:
        _record_unknown_fatal(
            store, request.job_id, state, clock, "artifact persistence failed"
        )
        raise InfrastructureError("artifact persistence failed") from None
    checkpoint()


def _persist_report(
    repository: Any,
    request: GenerationRequest,
    report: VerificationReport,
    store: JobStore,
    clock: Callable[[], str],
    checkpoint: Callable[[], None],
) -> None:
    reason = "verification report persistence failed"
    checkpoint()
    failed = False
    try:
        repository.put(request, report)
    except Exception:
        failed = True
    if failed:
        _record_unknown_fatal(store, request.job_id, JobStatus.VERIFYING, clock, reason)
        raise InfrastructureError(reason) from None
    checkpoint()
    failed = False
    try:
        if repository() != report:
            raise InfrastructureError("report readback mismatch")
    except Exception:
        failed = True
    if failed:
        _record_unknown_fatal(store, request.job_id, JobStatus.VERIFYING, clock, reason)
        raise InfrastructureError(reason) from None
    checkpoint()


def _decision_state(status: ArtifactStatus) -> JobStatus:
    return JobStatus(status.value)


def _record_verifier_decision(
    store: JobStore,
    job_id: JobId,
    artifact: GeneratedArtifact,
    decision: Any,
    from_state: JobStatus,
    to_state: JobStatus,
    clock: Callable[[], str],
) -> None:
    _append_event(
        store,
        job_id,
        EventType.VERIFIER_FINISHED,
        from_state,
        to_state,
        clock(),
        VerifierFinishedPayload(
            0,
            0,
            artifact.ref.artifact_id,
            decision.artifact_status,
            decision.decision_reason,
            decision.repair_stop_reason,
        ),
    )


def _repair_call(
    operation: Callable[[], Any],
    store: JobStore,
    job_id: JobId,
    state: JobStatus,
    clock: Callable[[], str],
) -> Any:
    failed = False
    result: Any = None
    try:
        result = operation()
    except Exception:
        failed = True
    if failed:
        reason = "repair composition failed"
        _record_unknown_fatal(store, job_id, state, clock, reason)
        raise InfrastructureError(reason) from None
    return result


def _close_repositories(repositories: tuple[Any, ...], *, quiet: bool) -> None:
    first: Exception | None = None
    for repository in repositories:
        try:
            repository.close()
        except Exception as error:
            if first is None:
                first = error
    if first is not None and not quiet:
        raise first


def _close_all(
    resources: tuple[Any, ...], first: Exception | None = None
) -> Exception | None:
    for resource in resources:
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as error:
            if first is None:
                first = error
    return first


class ProductionRuntime:
    __slots__ = (
        "_loaded",
        "_load_pipeline",
        "_allowlist",
        "_verifier_factory",
        "_report_store",
        "_artifact_store",
        "_environment",
        "_compiler_context",
        "_style_assets",
        "_control_builder",
        "_job_store",
        "_clock",
        "_state_lock",
        "_run_lock",
        "_active_job_id",
        "_active_cancel",
        "_active_cancel_reason",
        "_readiness_value",
        "_failure_kind_value",
        "_closed",
    )

    def __init__(
        self,
        loaded: LoadedPipeline,
        load_pipeline: Callable[[], LoadedPipeline],
        allowlist: _ProductionVerificationAllowlist,
        verifier_factory: Any,
        report_store: Any,
        artifact_store: Any,
        environment: EnvironmentSnapshot,
        compiler_context: CompilerContext,
        style_assets: StyleAssetResolver,
        control_builder: ControlInputBuilder,
        job_store: JobStore,
        clock: Callable[[], str],
        /,
    ) -> None:
        self._loaded = loaded
        self._load_pipeline = load_pipeline
        self._allowlist = allowlist
        self._verifier_factory = verifier_factory
        self._report_store = report_store
        self._artifact_store = artifact_store
        self._environment = environment
        self._compiler_context = compiler_context
        self._style_assets = style_assets
        self._control_builder = control_builder
        self._job_store = job_store
        self._clock = _NondecreasingAuditClock(clock)
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._active_job_id: JobId | None = None
        self._active_cancel: threading.Event | None = None
        self._active_cancel_reason: str | None = None
        self._readiness_value = _RuntimeReadiness.READY
        self._failure_kind_value: _RuntimeFailureKind | None = None
        self._closed = False

    @property
    def readiness(self) -> _RuntimeReadiness:
        with self._state_lock:
            return self._readiness_value

    @property
    def failure_kind(self) -> _RuntimeFailureKind | None:
        with self._state_lock:
            return self._failure_kind_value

    @property
    def compiler_context(self) -> CompilerContext:
        with self._state_lock:
            context = self._compiler_context
        try:
            return _rebuild_compiler_context(context)
        except Exception:
            raise InfrastructureError("production runtime corrupted") from None

    def prepare_export(
        self,
        request: ProductionJobRequest,
        result: ProductionJobResult,
        asset_credits: tuple[Any, ...],
        /,
    ) -> ProductionExportCommand:
        if type(result) is not ProductionJobResult:
            raise DomainError("invalid production export") from None
        request = _rebuild_production_job_request(request)
        recompiled = _select_initial_contract(request, self._compiler_context)
        return _prepare_production_export_command(
            request, result, self._environment, asset_credits, recompiled
        )

    def publish_export(
        self, command: ProductionExportCommand, target_root_fd: int, /
    ) -> ProductionExportResult:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
        command, target_root_fd = _prepare_publish_arguments(command, target_root_fd)
        self._start_export(command.job_id)
        previous = getattr(_ACTIVE_RUNTIME, "current", None)
        _ACTIVE_RUNTIME.current = self
        try:
            return _publish_export(self, command, target_root_fd)
        finally:
            _ACTIVE_RUNTIME.current = previous
            self._finish_run()

    def _append_export_event(
        self,
        job_id: JobId,
        event_type: EventType,
        from_state: JobStatus,
        to_state: JobStatus,
        payload: object,
    ) -> None:
        _append_event(
            self._job_store,
            job_id,
            event_type,
            from_state,
            to_state,
            self._clock(),
            payload,
        )

    def recover_exports(
        self,
        commands: tuple[ProductionExportCommand, ...],
        target_root_fd: int,
        /,
    ) -> tuple[ProductionRecoveryEntry, ...]:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
        self._start_recovery()
        previous = getattr(_ACTIVE_RUNTIME, "current", None)
        _ACTIVE_RUNTIME.current = self
        try:
            return _recover_exports(self, commands, target_root_fd)
        finally:
            _ACTIVE_RUNTIME.current = previous
            self._finish_run()

    def _close_resources(self) -> None:
        with self._state_lock:
            factory, self._verifier_factory = self._verifier_factory, None
        first_error: Exception | None = None
        with _GPU_LEASE:
            first_error = _close_all((factory, self._loaded), first_error)
        first_error = _close_all(
            (self._report_store, self._artifact_store), first_error
        )
        if first_error is not None:
            raise first_error

    def close(self) -> None:
        if getattr(_ACTIVE_RUNTIME, "current", None) is self:
            raise InfrastructureError("production runtime close from active run")
        owner, done, job_id = self._begin_close()
        if not owner:
            done.wait()
            return
        first_error = self._request_close_cancel(job_id, signal_missing=True)
        try:
            with self._run_lock:
                error = self._request_close_cancel(job_id, signal_missing=False)
                if first_error is None:
                    first_error = error
                try:
                    self._close_resources()
                except Exception as error:
                    if first_error is None:
                        first_error = error
            if first_error is not None:
                raise first_error
        finally:
            with _CLOSE_GUARD:
                done.set()
                _CLOSE_DONE.pop(id(self), None)

    def _begin_close(self) -> tuple[bool, threading.Event, JobId | None]:
        with self._state_lock:
            if self._closed:
                with _CLOSE_GUARD:
                    done = _CLOSE_DONE.get(id(self))
                return False, done or _SET_EVENT, None
            done = threading.Event()
            with _CLOSE_GUARD:
                _CLOSE_DONE[id(self)] = done
            self._closed = True
            self._readiness_value = _RuntimeReadiness.CLOSED
            if self._active_cancel is not None:
                self._active_cancel_reason = "runtime closed"
            return True, done, self._active_job_id

    def _publish_close_signal(self, job_id: JobId | None) -> None:
        with self._state_lock:
            if self._active_job_id == job_id and self._active_cancel is not None:
                self._active_cancel_reason = "runtime closed"
                self._active_cancel.set()

    def _request_close_cancel(
        self, job_id: JobId | None, *, signal_missing: bool
    ) -> Exception | None:
        if job_id is None:
            if signal_missing:
                self._publish_close_signal(None)
            return None
        try:
            snapshot = self._job_store.get_snapshot(job_id)
        except Exception as error:
            return error
        if snapshot is None:
            if signal_missing:
                self._publish_close_signal(job_id)
            return None
        try:
            self._cancel_durable(job_id, CancelRequestedPayload("runtime closed"))
        except DomainError as error:
            if error.args in {("job not found",), ("job is terminal",)}:
                if signal_missing and error.args == ("job not found",):
                    self._publish_close_signal(job_id)
                return None
            return error
        except Exception as error:
            return error
        self._publish_close_signal(job_id)
        return None

    def _start_run(self, request: object) -> None:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
            if self._readiness_value is _RuntimeReadiness.QUARANTINED:
                raise InfrastructureError("production runtime quarantined")
            if self._readiness_value is _RuntimeReadiness.BUSY:
                raise InfrastructureError("production runtime busy")
            if not self._run_lock.acquire(blocking=False):
                raise InfrastructureError("production runtime busy")
            if type(request) is not ProductionJobRequest:
                self._run_lock.release()
                raise DomainError("invalid production job request")
            self._readiness_value = _RuntimeReadiness.BUSY
            self._active_job_id = request.job_id
            self._active_cancel = threading.Event()
            self._active_cancel_reason = None

    def _start_export(self, job_id: JobId) -> None:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
            if self._readiness_value is not _RuntimeReadiness.READY:
                raise InfrastructureError("production runtime busy")
            if not self._run_lock.acquire(blocking=False):
                raise InfrastructureError("production runtime busy")
            self._readiness_value = _RuntimeReadiness.BUSY
            self._active_job_id = job_id
            self._active_cancel = threading.Event()
            self._active_cancel_reason = None

    def _start_recovery(self) -> None:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
            if self._readiness_value is not _RuntimeReadiness.READY:
                raise InfrastructureError("production runtime busy")
            if not self._run_lock.acquire(blocking=False):
                raise InfrastructureError("production runtime busy")
            self._readiness_value = _RuntimeReadiness.BUSY
            self._active_job_id = None
            self._active_cancel = None
            self._active_cancel_reason = None

    def _finish_run(self) -> None:
        with self._state_lock:
            self._active_job_id = None
            self._active_cancel = None
            self._active_cancel_reason = None
            if not self._closed and self._readiness_value is _RuntimeReadiness.BUSY:
                self._readiness_value = _RuntimeReadiness.READY
        self._run_lock.release()

    @staticmethod
    def _cancel_terminal(state: JobState) -> JobState | None:
        status = state.job.status
        if status is JobStatus.CANCELLED:
            return state
        if status in {JobStatus.JOB_FAILED, JobStatus.COMPLETED}:
            raise DomainError("job is terminal")
        return None

    def _cancel_durable(
        self, job_id: JobId, payload: CancelRequestedPayload
    ) -> JobState:
        holder = _export_lock_holder(self._job_store, job_id)
        with holder.lock:
            stalled_status: JobStatus | None = None
            while True:
                state = self._job_store.load(job_id)
                terminal = self._cancel_terminal(state)
                if terminal is not None:
                    self._mark_durable_cancel(job_id, payload.reason)
                    return terminal
                if (
                    state.job.status is JobStatus.EXPORTING
                    and holder.phase is not _ExportPhase.STAGING
                ):
                    raise InfrastructureError(
                        "production export recovery required"
                    ) from None
                self._mark_durable_cancel(job_id, payload.reason)
                try:
                    _append_event(
                        self._job_store,
                        job_id,
                        EventType.CANCEL_REQUESTED,
                        state.job.status,
                        JobStatus.CANCELLED,
                        self._clock(),
                        payload,
                    )
                except DomainError:
                    if state.job.status is stalled_status:
                        raise
                    stalled_status = state.job.status
                    continue
                return self._job_store.load(job_id)

    def _mark_durable_cancel(self, job_id: JobId, reason: str) -> None:
        with self._state_lock:
            if self._active_job_id == job_id:
                self._active_cancel_reason = reason

    def cancel(
        self,
        job_id: JobId,
        /,
        *,
        reason: str = "user requested",
    ) -> JobState:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
        if type(job_id) is not JobId:
            raise DomainError("invalid production job id")
        payload = CancelRequestedPayload(reason)
        state = self._cancel_durable(job_id, payload)
        with self._state_lock:
            if self._active_job_id == job_id and self._active_cancel is not None:
                self._active_cancel_reason = payload.reason
                self._active_cancel.set()
        return state

    def _cancellation_won(self, job_id: JobId) -> bool:
        with self._state_lock:
            durable_hint = (
                self._active_job_id == job_id and self._active_cancel_reason is not None
            )
        if not durable_hint:
            return False
        snapshot = self._job_store.get_snapshot(job_id)
        if snapshot is None:
            return False
        return self._job_store.load(job_id).job.status is JobStatus.CANCELLED

    def _persist_close_cancel_at_checkpoint(self, job_id: JobId) -> None:
        with self._state_lock:
            requested = (
                self._closed
                and self._active_job_id == job_id
                and self._active_cancel is not None
                and self._active_cancel.is_set()
                and self._active_cancel_reason == "runtime closed"
            )
        if not requested or self._job_store.get_snapshot(job_id) is None:
            return
        try:
            self._cancel_durable(job_id, CancelRequestedPayload("runtime closed"))
        except DomainError as error:
            if error.args == ("job is terminal",):
                return
            raise

    def _checkpoint(self, job_id: JobId) -> None:
        self._persist_close_cancel_at_checkpoint(job_id)
        if self._cancellation_won(job_id):
            raise DomainError("production job cancelled")

    def reopen(self) -> None:
        with self._state_lock:
            if self._closed:
                raise InfrastructureError("production runtime closed")
            if self._readiness_value is not _RuntimeReadiness.QUARANTINED:
                raise InfrastructureError("production runtime is not quarantined")
            if not self._run_lock.acquire(blocking=False):
                raise InfrastructureError("production runtime busy")
        try:
            self._reopen_under_run_lock()
        finally:
            self._run_lock.release()

    def _reopen_under_run_lock(self) -> None:
        loaded = allowlist = factory = None
        failure: Exception | None = None
        with _GPU_LEASE:
            try:
                loaded = self._load_pipeline()
                if type(self._allowlist) is _ProductionVerificationAllowlist:
                    allowlist = _ProductionVerificationAllowlist(
                        self._allowlist.schema_version,
                        self._compiler_context,
                        loaded._processor_provenance,
                        self._allowlist.l1_rule_mappings,
                    )
                else:
                    allowlist = self._allowlist
                factory = _create_production_verifier_factory(loaded, allowlist)
            except Exception as error:
                failure = error
            if failure is None:
                with self._state_lock:
                    if self._closed:
                        failure = InfrastructureError("production runtime closed")
                    else:
                        self._loaded, self._allowlist, self._verifier_factory = (
                            loaded,
                            allowlist,
                            factory,
                        )
                        self._failure_kind_value = None
                        self._readiness_value = _RuntimeReadiness.READY
            if failure is not None:
                _close_all((factory, loaded))
        if failure is not None:
            raise failure

    def run(self, request: ProductionJobRequest, /) -> ProductionJobResult:
        self._start_run(request)
        previous = getattr(_ACTIVE_RUNTIME, "current", None)
        _ACTIVE_RUNTIME.current = self
        cancelled = False
        try:
            try:
                result = self._run_request(request)
                self._checkpoint(request.job_id)
                return result
            except _GpuOutOfMemoryError:
                raise
            except Exception:
                if self._cancellation_won(request.job_id):
                    cancelled = True
                else:
                    raise
            if cancelled:
                raise DomainError("production job cancelled")
            raise AssertionError("run failure must raise")
        finally:
            _ACTIVE_RUNTIME.current = previous
            self._finish_run()

    def _open_attempt(
        self, request: GenerationRequest, plan: CompiledVerificationPlan
    ) -> tuple[Any, Any, Verifier]:
        artifact_repository = self._artifact_store.for_job(request.job_id)
        try:
            report_repository = self._report_store.for_attempt(
                request.job_id, request.attempt_id
            )
        except Exception:
            _close_repositories((artifact_repository,), quiet=True)
            raise
        try:
            verifier = self._verifier_factory.create(
                request, plan, artifact_repository, self._style_assets
            )
        except Exception:
            _close_repositories((report_repository, artifact_repository), quiet=True)
            raise
        return artifact_repository, report_repository, verifier

    def _prepare_initial_attempt(
        self, request: ProductionJobRequest
    ) -> _PreparedInitialAttempt:
        compiled, graph, verification_plan = _select_initial_contract(
            request, self._compiler_context
        )
        _preflight_bindings(request, graph, self._loaded)
        _reject_duplicate_job(self._job_store, request.job_id)
        generation_request = _initial_generation_request(
            request,
            compiled,
            graph,
            self._control_builder,
            self._environment,
        )
        repository, report_repository, verifier = self._open_attempt(
            generation_request, verification_plan
        )
        return _PreparedInitialAttempt(
            compiled,
            graph,
            verification_plan,
            generation_request,
            repository,
            report_repository,
            verifier,
        )

    def _start_prepared_job(
        self, request: ProductionJobRequest, prepared: _PreparedInitialAttempt
    ) -> None:
        self._checkpoint(request.job_id)
        budget = _create_initial_job(
            self._job_store, request, prepared.compiled, self._clock
        )
        self._checkpoint(request.job_id)
        _record_attempt_start(
            self._job_store,
            request,
            prepared.compiled,
            prepared.request,
            budget,
            self._clock,
            lambda: self._checkpoint(request.job_id),
        )

    def _run_prepared_attempt(
        self, request: ProductionJobRequest, prepared: _PreparedInitialAttempt
    ) -> ProductionJobResult:
        self._start_prepared_job(request, prepared)
        artifact, report = self._run_attempt(
            prepared.request,
            prepared.verification_plan,
            prepared.repository,
            prepared.report_repository,
            prepared.verifier,
            JobStatus.GENERATING,
        )
        self._checkpoint(request.job_id)
        composed = _repair_call(
            lambda: _compose_initial_repair(prepared.request, artifact, report),
            self._job_store,
            request.job_id,
            JobStatus.VERIFYING,
            self._clock,
        )
        self._checkpoint(request.job_id)
        history, step = composed.history, composed.step
        if composed.selecting_decision is not None:
            self._checkpoint(request.job_id)
            _record_verifier_decision(
                self._job_store,
                request.job_id,
                artifact,
                composed.selecting_decision,
                JobStatus.VERIFYING,
                JobStatus.REPAIR_SELECTING,
                self._clock,
            )
            self._checkpoint(request.job_id)
            if type(step) is RepairTerminal:
                self._record_terminal(
                    request.job_id, artifact, step, JobStatus.REPAIR_SELECTING
                )
                return self._result(prepared, history, step)
            return self._run_repair(prepared, history, step)
        self._record_terminal(request.job_id, artifact, step, JobStatus.VERIFYING)
        return self._result(prepared, history, step)

    def _run_attempt(
        self, request, plan, artifact_repository, report_repository, verifier, state
    ) -> tuple[GeneratedArtifact, VerificationReport]:
        artifact = self._run_generation_phase(request, state)
        self._checkpoint(request.job_id)
        _persist_artifact(
            artifact_repository,
            artifact,
            self._job_store,
            request,
            state,
            self._clock,
            lambda: self._checkpoint(request.job_id),
        )
        self._checkpoint(request.job_id)
        _record_attempt_finish(self._job_store, request, artifact, self._clock(), state)
        self._checkpoint(request.job_id)
        report = self._run_verification_phase(verifier, request, artifact, plan)
        self._checkpoint(request.job_id)
        _persist_report(
            report_repository,
            request,
            report,
            self._job_store,
            self._clock,
            lambda: self._checkpoint(request.job_id),
        )
        self._checkpoint(request.job_id)
        return artifact, report

    def _quarantine_under_lease(self) -> None:
        with self._state_lock:
            factory, self._verifier_factory = self._verifier_factory, None
            self._failure_kind_value = _RuntimeFailureKind.GPU_OOM
            if not self._closed:
                self._readiness_value = _RuntimeReadiness.QUARANTINED
        _close_all((factory, self._loaded))

    def _run_generation_phase(
        self, request: GenerationRequest, state: JobStatus
    ) -> GeneratedArtifact:
        self._checkpoint(request.job_id)
        with self._state_lock:
            cancel_event = self._active_cancel
        artifact: GeneratedArtifact | None = None
        failure: DomainError | InfrastructureError | None = None
        self._checkpoint(request.job_id)
        with _GPU_LEASE:
            try:
                artifact = _run_initial_generation(
                    self._loaded,
                    self._style_assets,
                    self._job_store,
                    request,
                    self._clock,
                    state,
                    cancel_event,
                )
            except (DomainError, InfrastructureError) as error:
                failure = error
                if type(error) is _GpuOutOfMemoryError:
                    self._quarantine_under_lease()
        if failure is not None:
            cancelled = self._cancellation_won(request.job_id)
            oom = type(failure) is _GpuOutOfMemoryError
            if not cancelled:
                _record_generation_fatal(
                    self._job_store, request, state, self._clock, oom=oom
                )
            raise failure
        if artifact is None:
            raise AssertionError("generation must return or raise")
        self._checkpoint(request.job_id)
        return artifact

    def _run_verification_phase(
        self,
        verifier: Verifier,
        request: GenerationRequest,
        artifact: GeneratedArtifact,
        plan: CompiledVerificationPlan,
    ) -> VerificationReport:
        self._checkpoint(request.job_id)
        report: VerificationReport | None = None
        failure: _GpuOutOfMemoryError | None = None
        with _GPU_LEASE:
            try:
                report = _run_initial_verification(
                    verifier, self._job_store, request, artifact, plan, self._clock
                )
            except _GpuOutOfMemoryError as error:
                failure = error
                self._quarantine_under_lease()
        if failure is None:
            if report is None:
                raise AssertionError("verification must return or raise")
            self._checkpoint(request.job_id)
            return report
        if not self._cancellation_won(request.job_id):
            _record_generation_fatal(
                self._job_store,
                request,
                JobStatus.VERIFYING,
                self._clock,
                oom=True,
            )
        raise failure

    def _record_terminal(self, job_id, artifact, terminal, from_state) -> None:
        if type(terminal) is not RepairTerminal:
            _repair_call(
                lambda: (_ for _ in ()).throw(DomainError("invalid terminal")),
                self._job_store,
                job_id,
                from_state,
                self._clock,
            )
        decision = terminal.artifact_decision
        self._checkpoint(job_id)
        _record_verifier_decision(
            self._job_store,
            job_id,
            artifact,
            decision,
            from_state,
            _decision_state(decision.artifact_status),
            self._clock,
        )
        self._checkpoint(job_id)

    def _run_repair(self, prepared, history, command):
        self._checkpoint(command.request.job_id)
        resources = _repair_call(
            lambda: self._open_attempt(command.request, prepared.verification_plan),
            self._job_store,
            command.request.job_id,
            JobStatus.REPAIR_SELECTING,
            self._clock,
        )
        repository, report_repository, verifier = resources
        try:
            self._checkpoint(command.request.job_id)
            self._record_repair_step(command)
            self._checkpoint(command.request.job_id)
            artifact, report = self._run_attempt(
                command.request,
                prepared.verification_plan,
                repository,
                report_repository,
                verifier,
                JobStatus.REPAIRING,
            )
        except Exception:
            _close_repositories((report_repository, repository), quiet=True)
            raise
        _close_repositories((report_repository, repository), quiet=False)
        self._checkpoint(command.request.job_id)
        composed = _repair_call(
            lambda: _compose_repair_result(history, command, artifact, report),
            self._job_store,
            command.request.job_id,
            JobStatus.VERIFYING,
            self._clock,
        )
        self._checkpoint(command.request.job_id)
        history, terminal = composed.history, composed.terminal
        self._record_terminal(
            command.request.job_id, artifact, terminal, JobStatus.VERIFYING
        )
        return self._result(prepared, history, terminal)

    def _record_repair_step(self, command: NextGeneration) -> None:
        decision, request = command.decision, command.request
        _append_event(
            self._job_store,
            request.job_id,
            EventType.REPAIR_STEP,
            JobStatus.REPAIR_SELECTING,
            JobStatus.REPAIRING,
            self._clock(),
            RepairStepPayload(
                0,
                0,
                decision.decision_id,
                decision.action_id,
                decision.trigger_rule_id,
                request.parent_attempt_id,
                request.attempt_id,
            ),
        )

    def _result(self, prepared, history, terminal) -> ProductionJobResult:
        self._checkpoint(history.current_request.job_id)
        return ProductionJobResult(
            prepared.compiled,
            prepared.graph,
            prepared.verification_plan,
            history.current_request,
            history.current_artifact,
            history.current_report,
            history,
            terminal,
            self._job_store.load(history.current_request.job_id),
        )

    def _run_request(self, request: ProductionJobRequest, /) -> ProductionJobResult:
        self._checkpoint(request.job_id)
        prepared = self._prepare_initial_attempt(request)
        try:
            self._checkpoint(request.job_id)
            result = self._run_prepared_attempt(request, prepared)
        except Exception:
            _close_repositories(
                (prepared.report_repository, prepared.repository), quiet=True
            )
            raise
        _close_repositories(
            (prepared.report_repository, prepared.repository), quiet=False
        )
        return result

    def _execute_initial_attempt(
        self, request: ProductionJobRequest, /
    ) -> ProductionJobResult:
        return self.run(request)


def _cleanup_failed_open(
    loaded: LoadedPipeline,
    factory: Any | None,
    report_store: Any | None,
    artifact_store: Any | None,
) -> None:
    for resource in (report_store, artifact_store, factory, loaded):
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            pass


def _validate_runtime_dependencies(
    compiler_context_factory: object,
    style_assets: object,
    control_builder: object,
    l1_rule_bindings: object,
    job_store: object,
    clock: object,
) -> tuple[ProductionL1RuleBinding, ...]:
    _reject_context_factory_reentry()
    bindings = _rebuild_production_l1_rule_bindings(l1_rule_bindings)
    if (
        not callable(compiler_context_factory)
        or not callable(style_assets)
        or not callable(getattr(control_builder, "build", None))
        or type(job_store) is not JobStore
        or not callable(clock)
    ):
        raise DomainError("invalid production runtime dependency")
    return bindings


def _compiler_context_for_loaded(
    compiler_context_factory: Callable[[str], CompilerContext],
    loaded: LoadedPipeline,
    /,
) -> CompilerContext:
    evidence = loaded._borrow_image_evidence_encoder()
    preprocessing_version = evidence.preprocessing_version
    _reject_context_factory_reentry()
    _CONTEXT_FACTORY_ACTIVE.current = True
    try:
        candidate = compiler_context_factory(preprocessing_version)
    finally:
        _CONTEXT_FACTORY_ACTIVE.current = False
    try:
        context = _rebuild_compiler_context(candidate)
    except Exception:
        raise DomainError("invalid production runtime dependency") from None
    matching = tuple(
        capability
        for capability in context.encoder_capabilities
        if capability.pin == evidence.pin
    )
    if (
        len(matching) != 1
        or matching[0].preprocessing_version != preprocessing_version
        or matching[0].layer != evidence.layer
    ):
        raise DomainError("invalid production runtime dependency") from None
    return context


def _reject_context_factory_reentry() -> None:
    if getattr(_CONTEXT_FACTORY_ACTIVE, "current", False):
        raise DomainError("invalid production runtime dependency") from None


def _rebuild_compiler_context(value: object, /) -> CompilerContext:
    cloned = _clone_compiler_context(value)
    return CompilerContext(
        cloned.compiler_pin,
        cloned.runtime_capabilities,
        cloned.model_capabilities,
        cloned.encoder_capabilities,
        cloned.strength_mappings,
        cloned.output_profile_capabilities,
        cloned.rule_catalogs,
        cloned.threshold_profiles,
        cloned.l3_plugins,
    )


def _bind_pipeline_loader(
    supply: VerifiedPipelineSupply,
    pipeline_graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    torch_module: Any | None,
    diffusers_module: Any | None,
) -> Callable[[], LoadedPipeline]:
    def load_pipeline() -> LoadedPipeline:
        return load_production_pipeline(
            supply,
            pipeline_graph,
            environment,
            torch_module=torch_module,
            diffusers_module=diffusers_module,
        )

    return load_pipeline


def _open_runtime_owned_resources(
    loaded: LoadedPipeline,
    compiler_context: CompilerContext,
    l1_rule_bindings: tuple[ProductionL1RuleBinding, ...],
    artifact_root_fd: int,
) -> tuple[LoadedPipeline, _ProductionVerificationAllowlist, Any, Any, Any]:
    artifact_store = None
    report_store = None
    with _GPU_LEASE:
        try:
            allowlist = _ProductionVerificationAllowlist(
                "specstyle.production_verifier.v1",
                compiler_context,
                loaded._processor_provenance,
                tuple(
                    _L1RuleMapping(binding.rule_id, binding.implementation)
                    for binding in l1_rule_bindings
                ),
            )
            verifier_factory = _create_production_verifier_factory(loaded, allowlist)
        except Exception:
            _cleanup_failed_open(loaded, None, None, None)
            raise
    try:
        artifact_store = _open_production_artifact_store(artifact_root_fd)
        report_store = _open_production_report_store(artifact_root_fd)
    except Exception:
        _cleanup_failed_open(loaded, verifier_factory, report_store, artifact_store)
        raise
    return loaded, allowlist, verifier_factory, report_store, artifact_store


def _load_runtime_context(
    load_pipeline: Callable[[], LoadedPipeline],
    compiler_context_factory: Callable[[str], CompilerContext],
    /,
) -> tuple[LoadedPipeline, CompilerContext]:
    with _GPU_LEASE:
        loaded = load_pipeline()
    try:
        context = _compiler_context_for_loaded(compiler_context_factory, loaded)
    except Exception:
        _cleanup_failed_open(loaded, None, None, None)
        raise
    return loaded, context


def load_production_compiler_context(
    supply: VerifiedPipelineSupply,
    pipeline_graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    compiler_context_factory: Callable[[str], CompilerContext],
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
) -> CompilerContext:
    """Derive a detached compiler context while borrowing verified supply."""
    _reject_context_factory_reentry()
    if not callable(compiler_context_factory):
        raise DomainError("invalid production runtime dependency")
    load_pipeline = _bind_pipeline_loader(
        supply, pipeline_graph, environment, torch_module, diffusers_module
    )
    with _GPU_LEASE:
        loaded = load_pipeline()
        primary: BaseException | None = None
        try:
            return _compiler_context_for_loaded(compiler_context_factory, loaded)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                loaded.close()
            except Exception:
                if primary is None:
                    raise
                primary.add_note("production compiler context pipeline cleanup failed")


def open_production_runtime(
    supply: VerifiedPipelineSupply,
    pipeline_graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    compiler_context_factory: Callable[[str], CompilerContext],
    style_assets: StyleAssetResolver,
    control_builder: ControlInputBuilder,
    l1_rule_bindings: tuple[ProductionL1RuleBinding, ...],
    job_store: JobStore,
    artifact_root_fd: int,
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
    clock: Callable[[], str] = _utc_now,
) -> ProductionRuntime:
    l1_rule_bindings = _validate_runtime_dependencies(
        compiler_context_factory,
        style_assets,
        control_builder,
        l1_rule_bindings,
        job_store,
        clock,
    )
    load_pipeline = _bind_pipeline_loader(
        supply, pipeline_graph, environment, torch_module, diffusers_module
    )
    loaded, compiler_context = _load_runtime_context(
        load_pipeline, compiler_context_factory
    )
    loaded, allowlist, verifier_factory, report_store, artifact_store = (
        _open_runtime_owned_resources(
            loaded, compiler_context, l1_rule_bindings, artifact_root_fd
        )
    )
    return ProductionRuntime(
        loaded,
        load_pipeline,
        allowlist,
        verifier_factory,
        report_store,
        artifact_store,
        environment,
        compiler_context,
        style_assets,
        control_builder,
        job_store,
        clock,
    )


_ProductionGenerationRuntime = ProductionRuntime
_open_production_generation_runtime = open_production_runtime
