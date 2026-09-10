"""WF-002 fake CPU end-to-end vertical-slice orchestrator.

The architect-frozen contract connects existing frozen functions from
contracts sections 3, 11.7, 12.9, and 13:
``load_style_spec_text``/``compile_style_spec``, ``run_generation``,
``run_verifier``, ``VerificationReport``, ``start_repair_history``/
``next_repair_step``/``consume_repair_result``, and ``export_bundle``. This
module assembles the planes without duplicating compiler, verifier, repair, or
gate business rules, and it does not import torch, diffusers, or gradio.

ID derivation is deterministic through ``_attempt_id`` and ``_decision_id``;
restarting with the same input produces the same IDs and enables stage
idempotency with the WF-001 JobStore. This module does not claim verified Spec
replay; same-seed repetition relies only on FakeBackend bit-exact behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import ArtifactStatus
from specstyle.domain.identifiers import (
    AttemptId,
    AssetId,
    DecisionId,
    JobId,
)
from specstyle.errors import DomainError, SpecStyleError
from specstyle.exporting.bundle import ExportBundle, export_bundle
from specstyle.exporting.manifest import (
    AssetCredit,
    ExportCohort,
    ExportItem,
    ExportRequest,
)
from specstyle.generation.preprocess import PreparedImage
from specstyle.generation.protocols import (
    GenerationBackend,
    build_control_input,
    run_generation,
)
from specstyle.generation.requests import GenerationRequest, RenderedPrompt
from specstyle.observability.environment import EnvironmentSnapshot, hash_environment
from specstyle.repair.history import RepairHistory, start_repair_history
from specstyle.repair.loop import (
    RepairTerminal,
    consume_repair_result,
    next_repair_step,
)
from specstyle.spec.compiled_models import (
    CompilerContext,
    CompiledExecutionGraph,
    CompiledStyleSpec,
    CompiledVerificationPlan,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.loader import load_style_spec_text
from specstyle.verification.protocols import Verifier, run_verifier
from specstyle.verification.rule_models import VerificationReport
from specstyle.workflow.job_models import (
    AttemptFinishedPayload,
    AttemptStartedPayload,
    Event,
    EventType,
    ExportPublishedPayload,
    ExportStartedPayload,
    FatalPayload,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    JobStatus,
    SpecCompiledPayload,
    VerifierFinishedPayload,
)
from specstyle.workflow.job_store import JobStore

_TIMESTAMP = "2026-07-31T00:00:00.000Z"
_SNAPSHOT_VERSION = "specstyle.workflow.snapshot.v1"


@dataclass(frozen=True, slots=True)
class FakeJobPlan:
    """Single-job plan producing ``item_count`` items per profile (P0=1).

    ``output_profiles`` is a non-empty, duplicate-free subset of ``xhs_grid``,
    ``talking_head_cover``, and ``background_sequence``.
    ``generation_profile`` is fixed at ``"production"`` and
    ``variation_index`` is the initial attempt variation (zero).
    """

    job_id: JobId
    output_profiles: tuple[str, ...]
    generation_profile: str
    variation_index: int
    item_count: int

    def __post_init__(self) -> None:
        allowed = ("xhs_grid", "talking_head_cover", "background_sequence")
        if (
            type(self.output_profiles) is not tuple
            or not self.output_profiles
            or type(self.generation_profile) is not str
            or self.generation_profile != "production"
            or type(self.variation_index) is not int
            or isinstance(self.variation_index, bool)
            or type(self.item_count) is not int
            or isinstance(self.item_count, bool)
        ):
            raise ValueError("invalid fake job plan")
        seen: set[str] = set()
        for profile in self.output_profiles:
            if type(profile) is not str or profile not in allowed or profile in seen:
                raise ValueError("invalid fake job plan")
            seen.add(profile)
        # P0 permits only EXPORTING after an item terminal, so require one profile/item.
        if (
            self.item_count != 1
            or len(self.output_profiles) != 1
            or self.variation_index < 0
        ):
            raise ValueError("invalid fake job plan")
        object.__setattr__(self, "job_id", JobId(self.job_id.value))
        object.__setattr__(self, "output_profiles", tuple(self.output_profiles))


@dataclass(frozen=True, slots=True)
class FakeJobResult:
    """Single-job terminal result.

    The bundle is non-empty only for a successful run with
    ``final_status == "COMPLETED"``. On restart of a completed job, the
    orchestrator returns ``bundle=None`` because the bundle was published
    previously, and it repeats neither generation nor export (INV-WF002-5).
    """

    bundle: ExportBundle | None
    cohorts: tuple[ExportCohort, ...]
    terminals: tuple[RepairTerminal, ...]
    histories: tuple[RepairHistory, ...]
    final_status: str


def _attempt_id(job: JobId, profile: str, item: int, rnd: int) -> AttemptId:
    """Deterministic attempt ID: ``{job}-a{round}-{profile}-{item}``."""
    return AttemptId(f"{job.value}-a{rnd}-{profile}-{item}")


def _decision_id(job: JobId, profile: str, item: int, rnd: int) -> DecisionId:
    """Deterministic decision ID: ``{job}-d{round}-{profile}-{item}``."""
    return DecisionId(f"{job.value}-d{rnd}-{profile}-{item}")


def _style_reference_refs(graph: CompiledExecutionGraph) -> tuple[AssetRef, ...]:
    """Style-reference AssetRefs aligned with ``graph.style_reference_hashes``."""
    return tuple(
        AssetRef(AssetId(f"style-{index}"), sha)
        for index, sha in enumerate(graph.style_reference_hashes)
    )


def _production_graph(
    compiled: CompiledStyleSpec, profile: str
) -> CompiledExecutionGraph:
    """Return the unique production graph matching the output profile."""
    matched = tuple(
        graph for graph in compiled.production_graphs if graph.output_profile == profile
    )
    if len(matched) != 1:
        raise DomainError("invalid fake job plan")
    return matched[0]


def _verification_plan(
    compiled: CompiledStyleSpec, profile: str
) -> CompiledVerificationPlan:
    """Return the unique verification plan matching the output profile."""
    matched = tuple(
        plan for plan in compiled.verification_plans if plan.output_profile == profile
    )
    if len(matched) != 1:
        raise DomainError("invalid fake job plan")
    return matched[0]


def _initial_request(
    compiled: CompiledStyleSpec,
    plan: FakeJobPlan,
    source: PreparedImage,
    prompt: RenderedPrompt,
    control_builder: object,
    env_hash: object,
    profile: str,
    item_index: int,
) -> GenerationRequest:
    """Build the root request from the plan variation and a round-zero attempt ID."""
    graph = _production_graph(compiled, profile)
    control = build_control_input(control_builder, source, graph)
    return GenerationRequest(
        plan.job_id,
        _attempt_id(plan.job_id, profile, item_index, 0),
        None,
        compiled,
        plan.generation_profile,
        profile,
        source,
        _style_reference_refs(graph),
        prompt,
        control,
        plan.variation_index,
        env_hash,
    )


def _expected_artifact_id(request: GenerationRequest) -> str:
    """Reuse FakeBackend section 11.7 derivation from request_hash to artifact_id."""
    return f"artifact-{request.request_hash.value}"


def _load_or_init(
    job_store: JobStore,
    job_id: JobId,
    compiled: CompiledStyleSpec,
    plan: FakeJobPlan,
) -> object:
    """Load for resume or create an initial job snapshot when none exists."""
    snapshot = job_store.get_snapshot(job_id)
    if snapshot is None:
        budget = JobBudget(1 + compiled.source_spec.repair.max_rounds)
        job = Job(
            job_id,
            compiled.compiled_spec_hash,
            plan.output_profiles,
            budget,
            JobStatus.CREATED,
            _TIMESTAMP,
            _TIMESTAMP,
        )
        job_store.save_snapshot(job_id, JobSnapshot(_SNAPSHOT_VERSION, job, 0, (), ()))
    return job_store.load(job_id)


def _append(
    cursor: SimpleNamespace,
    job_store: JobStore,
    job_id: JobId,
    event_type: EventType,
    to_state: JobStatus,
    payload: object,
) -> None:
    """Record an event and advance cursor.status from the current state."""
    event = Event(1, job_id, event_type, cursor.status, to_state, _TIMESTAMP, payload)
    job_store.append_event(job_id, event)
    cursor.status = to_state


def _terminal_to_state(terminal: RepairTerminal) -> JobStatus:
    """Map a terminal item status to an APPROVED/REJECTED/MANUAL_REVIEW job state."""
    status = terminal.artifact_decision.artifact_status
    if status is ArtifactStatus.APPROVED:
        return JobStatus.APPROVED
    if status is ArtifactStatus.REJECTED:
        return JobStatus.REJECTED
    return JobStatus.MANUAL_REVIEW


def _build_credits(
    compiled: CompiledStyleSpec,
    source: PreparedImage,
    graph: CompiledExecutionGraph,
) -> tuple[AssetCredit, ...]:
    """Build input, style_reference, and Spec-provenance credits."""
    spec_refs = compiled.source_spec.assets.style_references
    style_refs = _style_reference_refs(graph)
    credits: list[AssetCredit] = [
        AssetCredit(source.source, ("input",), None, None, None, None)
    ]
    for index, ref in enumerate(style_refs):
        spec_ref = spec_refs[index]
        credits.append(
            AssetCredit(
                ref,
                ("style_reference",),
                spec_ref.source_url,
                spec_ref.license,
                spec_ref.attribution,
                spec_ref.consent,
            )
        )
    credits.sort(key=lambda c: (c.asset.asset_id.value, c.asset.sha256.value))
    return tuple(credits)


def _try_fatal(job_store: JobStore, job_id: JobId, cursor: SimpleNamespace) -> None:
    """Best-effort sanitized FATAL append before failure; publish no partial bundle."""
    if cursor.status in (
        JobStatus.COMPLETED,
        JobStatus.JOB_FAILED,
        JobStatus.CANCELLED,
    ):
        return
    try:
        _append(
            cursor,
            job_store,
            job_id,
            EventType.FATAL,
            JobStatus.JOB_FAILED,
            FatalPayload("UNKNOWN", "job failed"),
        )
    except SpecStyleError:
        return


def _run_item(
    cursor: SimpleNamespace,
    job_store: JobStore,
    compiled: CompiledStyleSpec,
    plan: FakeJobPlan,
    source: PreparedImage,
    prompt: RenderedPrompt,
    control_builder: object,
    env_hash: object,
    profile: str,
    item_index: int,
    verifier: Verifier,
    backend: GenerationBackend,
) -> tuple[RepairHistory, RepairTerminal]:
    """Generate, verify, and repair FSM for a single item.

    Records ATTEMPT_STARTED/FINISHED and the final terminal VERIFIER_FINISHED
    with a non-None stop reason.
    Repair rounds advance in linear history without REPAIR_STEP events because
    WF-001 JobStore cannot serialize the ``repair_stop_reason=None``
    VERIFIER_FINISHED needed to enter REPAIR_SELECTING; ``RepairStopReason(None)``
    raises ``ValueError``. Only idempotent attempt, terminal, and export audit
    events are retained.
    """
    req0 = _initial_request(
        compiled, plan, source, prompt, control_builder, env_hash, profile, item_index
    )
    _append(
        cursor,
        job_store,
        plan.job_id,
        EventType.ATTEMPT_STARTED,
        JobStatus.GENERATING,
        AttemptStartedPayload(0, item_index, req0.attempt_id, None),
    )
    artifact = run_generation(backend, req0)
    _append(
        cursor,
        job_store,
        plan.job_id,
        EventType.ATTEMPT_FINISHED,
        JobStatus.VERIFYING,
        AttemptFinishedPayload(
            0, item_index, req0.attempt_id, artifact.ref.artifact_id, req0.request_hash
        ),
    )
    rules = _verification_plan(compiled, profile).applicable_rule_definitions
    report = VerificationReport(
        (artifact.ref,), rules, run_verifier(verifier, (artifact.ref,), rules)
    )
    history = start_repair_history(req0, artifact, report)
    while True:
        rnd = history.rounds + 1
        step = next_repair_step(
            history,
            _decision_id(plan.job_id, profile, item_index, rnd),
            _attempt_id(plan.job_id, profile, item_index, rnd),
        )
        if isinstance(step, RepairTerminal):
            _append(
                cursor,
                job_store,
                plan.job_id,
                EventType.VERIFIER_FINISHED,
                _terminal_to_state(step),
                VerifierFinishedPayload(
                    0,
                    item_index,
                    history.current_target_artifact_id,
                    step.artifact_decision.artifact_status,
                    step.artifact_decision.decision_reason,
                    step.artifact_decision.repair_stop_reason,
                ),
            )
            return history, step
        child = run_generation(backend, step.request)
        child_report = VerificationReport(
            (child.ref,), rules, run_verifier(verifier, (child.ref,), rules)
        )
        history = consume_repair_result(history, step, child, child_report)


def run_fake_job(
    spec_text: object,
    context: CompilerContext,
    source: PreparedImage,
    prompt: RenderedPrompt,
    control_builder: object,
    environment: EnvironmentSnapshot,
    plan: FakeJobPlan,
    job_store: JobStore,
    root_fd: int,
    bundle_name: str,
    /,
    *,
    verifier: Verifier,
    backend: GenerationBackend,
) -> FakeJobResult:
    """Four-chain vertical slice: compile, generate, verify, repair, and export."""
    compiled = compile_style_spec(load_style_spec_text(spec_text), context)
    env_hash = hash_environment(environment)
    state = _load_or_init(job_store, plan.job_id, compiled, plan)
    if state.job.terminal:  # type: ignore[attr-defined]
        job = state.job  # type: ignore[attr-defined]
        if (
            job.compiled_spec_hash != compiled.compiled_spec_hash
            or job.cohort_profiles != plan.output_profiles
        ):
            raise DomainError("job terminal but plan or spec hash mismatch") from None
        return FakeJobResult(None, (), (), (), job.status.value)
    cursor = SimpleNamespace(status=state.job.status)  # type: ignore[attr-defined]
    cohorts: list[ExportCohort] = []
    terminals: list[RepairTerminal] = []
    histories: list[RepairHistory] = []
    try:
        _append(
            cursor,
            job_store,
            plan.job_id,
            EventType.JOB_STARTED,
            JobStatus.SPEC_VALIDATED,
            JobStartedPayload(
                compiled.compiled_spec_hash, plan.output_profiles, _budget(compiled)
            ),
        )
        _append(
            cursor,
            job_store,
            plan.job_id,
            EventType.SPEC_COMPILED,
            JobStatus.SPEC_COMPILED,
            SpecCompiledPayload(compiled.compiled_spec_hash),
        )
        for profile in plan.output_profiles:
            for item_index in range(plan.item_count):
                history, terminal = _run_item(
                    cursor,
                    job_store,
                    compiled,
                    plan,
                    source,
                    prompt,
                    control_builder,
                    env_hash,
                    profile,
                    item_index,
                    verifier,
                    backend,
                )
                histories.append(history)
                terminals.append(terminal)
                seq = item_index if profile == "background_sequence" else None
                cohorts.append(
                    ExportCohort(
                        profile,
                        history.current_report,
                        (ExportItem(history, terminal, seq),),
                    )
                )
        export_request = ExportRequest(
            tuple(cohorts),
            environment,
            _build_credits(
                compiled, source, _production_graph(compiled, plan.output_profiles[0])
            ),
        )
        _append(
            cursor,
            job_store,
            plan.job_id,
            EventType.EXPORT_STARTED,
            JobStatus.EXPORTING,
            ExportStartedPayload(bundle_name),
        )
        bundle = export_bundle(export_request, root_fd, bundle_name)
        _append(
            cursor,
            job_store,
            plan.job_id,
            EventType.EXPORT_PUBLISHED,
            JobStatus.COMPLETED,
            ExportPublishedPayload(
                bundle.bundle_name,
                bundle.manifest_sha256,
                bundle.payload_sha256,
                bundle.bundle_sha256,
            ),
        )
        return FakeJobResult(
            bundle, tuple(cohorts), tuple(terminals), tuple(histories), "COMPLETED"
        )
    except SpecStyleError:
        _try_fatal(job_store, plan.job_id, cursor)
        return FakeJobResult(None, (), (), (), "JOB_FAILED")


def _budget(compiled: CompiledStyleSpec) -> JobBudget:
    return JobBudget(1 + compiled.source_spec.repair.max_rounds)
