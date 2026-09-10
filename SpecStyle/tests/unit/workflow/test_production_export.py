"""APP-COMPOSE-001E production export command contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, fields, replace
import importlib
import os
from pathlib import Path
import threading

import pytest

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.enums import (
    ArtifactStatus,
    RepairStopReason,
    RuleScope,
    RuleStatus,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    DecisionId,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.bundle import ExportBundle, ExportedFile
from specstyle.exporting.manifest import (
    AssetCredit,
    ExportCohort,
    ExportItem,
    ExportRequest,
    _prepare_export,
)
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import (
    GenerationRequest,
    PreparedControlInput,
    RenderedPrompt,
)
from specstyle.observability.environment import TextObservation, hash_environment
from specstyle.observability.hashing import hash_bytes
from specstyle.reliability.fixtures import (
    sample_approved_export_request,
    sample_compiler_context,
    sample_environment,
    sample_source,
    sample_style_spec,
)
from specstyle.repair.actions import RETRY_SAMPLING
from specstyle.repair.history import start_repair_history
from specstyle.repair.loop import (
    NextGeneration,
    RepairTerminal,
    consume_repair_result,
    next_repair_step,
)
from specstyle.spec.compiled_models import ResourcePin
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import RuleResult, VerificationReport
from specstyle.workflow.job_models import Job, JobBudget, JobState, JobStatus
from specstyle.workflow.job_models import (
    AttemptFinishedPayload,
    AttemptStartedPayload,
    Event,
    EventType,
    ExportStartedPayload,
    JobSnapshot,
    JobStartedPayload,
    SpecCompiledPayload,
    VerifierFinishedPayload,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_artifacts import _open_production_artifact_store
from specstyle.workflow.production_reports import _open_production_report_store
from specstyle.workflow.production_service import (
    ProductionJobRequest,
    ProductionJobResult,
    _ProductionGenerationRuntime,
)


_PROFILES = ("xhs_grid", "talking_head_cover", "background_sequence")
_DECISIONS = (
    (ArtifactStatus.APPROVED, RuleStatus.PASS, RepairStopReason.PASS_ALL_REQUIRED),
    (ArtifactStatus.MANUAL_REVIEW, RuleStatus.WARNING, RepairStopReason.MANUAL_REQUEST),
    (ArtifactStatus.REJECTED, RuleStatus.FAIL, RepairStopReason.NO_IMPROVEMENT),
)


class _HostileStr(str):
    pass


class _HostileInt(int):
    pass


class _HostileJobId(JobId):
    pass


def _export_module():
    return importlib.import_module("specstyle.workflow.production_export")


@dataclass(frozen=True)
class _Case:
    request: ProductionJobRequest
    result: ProductionJobResult
    environment: object
    compiler_context: object
    credits: tuple[AssetCredit, ...]


def _compiled(profile: str, *, retry_l1: bool = False):
    raw = sample_style_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    raw["outputs"]["profiles"] = (profile,)
    context = sample_compiler_context()
    output = replace(context.output_profile_capabilities[0], profile=profile)
    alternate = next(item for item in _PROFILES if item != profile)
    rules = tuple(
        replace(
            rule,
            rule_id=(
                RuleId("l1_bundle")
                if retry_l1 and rule.level.value == "L1"
                else rule.rule_id
            ),
            supported_output_profiles=(
                (alternate,) if rule.scope is RuleScope.BATCH else (profile,)
            ),
            affected_by_actions=(
                (RETRY_SAMPLING,)
                if retry_l1 and rule.level.value == "L1"
                else rule.affected_by_actions
            ),
        )
        for rule in context.rule_catalogs[0].rules
    )
    context = replace(
        context,
        output_profile_capabilities=(output,),
        rule_catalogs=(replace(context.rule_catalogs[0], rules=rules),),
        threshold_profiles=(
            replace(
                context.threshold_profiles[0],
                metrics=tuple(
                    metric
                    for metric in context.threshold_profiles[0].metrics
                    if metric.metric_id.value != "batch-metric"
                ),
            ),
        ),
    )
    spec = StyleSpecV1.model_validate(raw)
    return compile_style_spec(spec, context), spec.model_dump_json(), context


def _case(
    profile: str = "xhs_grid",
    status: ArtifactStatus = ArtifactStatus.APPROVED,
    *,
    job_id: str = "job",
) -> _Case:
    compiled, spec_text, compiler_context = _compiled(profile)
    graph = compiled.production_graphs[0]
    plan = compiled.verification_plans[0]
    environment = sample_environment()
    source = sample_source()
    prompt = RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)),
        graph.preset_id,
        "a prompt",
        "",
    )
    generation_request = GenerationRequest(
        JobId(job_id),
        AttemptId(f"{job_id}-a0-{profile}-0"),
        None,
        compiled,
        "production",
        profile,
        source,
        (AssetRef(AssetId("style"), graph.style_reference_hashes[0]),),
        prompt,
        PreparedControlInput("canny", source),
        0,
        hash_environment(environment),
    )
    artifact = GeneratedArtifact(
        ArtifactRef(ArtifactId(f"artifact-{profile}"), hash_bytes(source.content)),
        source.content,
        generation_request.request_hash,
        generation_request.generation_fingerprint,
    )
    rule_status, stop = next(
        (rule_status, stop)
        for artifact_status, rule_status, stop in _DECISIONS
        if artifact_status is status
    )
    report = VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(
                rule.rule_id,
                rule_status,
                (artifact.ref.artifact_id,),
                None,
            )
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(generation_request, artifact, report)
    terminal = RepairTerminal(
        decide_artifact(
            report,
            artifact.ref.artifact_id,
            repair_stop_reason=stop,
        ),
        None,
    )
    job = Job(
        generation_request.job_id,
        compiled.compiled_spec_hash,
        (profile,),
        JobBudget(2),
        JobStatus(status.value),
        "2026-08-02T00:00:00.000Z",
        "2026-08-02T00:00:01.000Z",
    )
    result = ProductionJobResult(
        compiled,
        graph,
        plan,
        generation_request,
        artifact,
        report,
        history,
        terminal,
        JobState(job, 5, (generation_request.attempt_id,), ()),
    )
    style = compiled.source_spec.assets.style_references[0]
    credits = tuple(
        sorted(
            (
                AssetCredit(source.source, ("input",), None, None, None, None),
                AssetCredit(
                    generation_request.style_references[0],
                    ("style_reference",),
                    style.source_url,
                    style.license,
                    style.attribution,
                    style.consent,
                ),
            ),
            key=lambda credit: credit.identity,
        )
    )
    request = ProductionJobRequest(
        generation_request.job_id,
        spec_text,
        source,
        generation_request.style_references,
        prompt,
        profile,
        0,
        "bundle",
    )
    return _Case(request, result, environment, compiler_context, credits)


def _initial_retry_history(compiled, environment):
    graph = compiled.production_graphs[0]
    plan = compiled.verification_plans[0]
    source = sample_source()
    prompt = RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)),
        graph.preset_id,
        "a prompt",
        "",
    )
    initial_request = GenerationRequest(
        JobId("repair-job"),
        AttemptId("repair-job-a0-xhs_grid-0"),
        None,
        compiled,
        "production",
        graph.output_profile,
        source,
        (AssetRef(AssetId("style"), graph.style_reference_hashes[0]),),
        prompt,
        PreparedControlInput("canny", source),
        0,
        hash_environment(environment),
    )
    initial_artifact = GeneratedArtifact(
        ArtifactRef(ArtifactId("artifact-initial"), hash_bytes(source.content)),
        source.content,
        initial_request.request_hash,
        initial_request.generation_fingerprint,
    )
    initial_report = VerificationReport(
        (initial_artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(
                rule.rule_id,
                RuleStatus.FAIL
                if rule.rule_id.value == "l1_bundle"
                else RuleStatus.PASS,
                (initial_artifact.ref.artifact_id,),
                None,
            )
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(initial_request, initial_artifact, initial_report)
    return history, source, prompt


def _successful_retry(history):
    command = next_repair_step(
        history,
        DecisionId("repair-decision"),
        AttemptId("repair-job-a1-xhs_grid-0"),
    )
    assert type(command) is NextGeneration
    source = history.initial_attempt.request.source
    plan = history.initial_attempt.request.compiled_spec.verification_plans[0]
    child_artifact = GeneratedArtifact(
        ArtifactRef(ArtifactId("artifact-child"), hash_bytes(source.content)),
        source.content,
        command.request.request_hash,
        command.request.generation_fingerprint,
    )
    child_report = VerificationReport(
        (child_artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(
                rule.rule_id,
                RuleStatus.PASS,
                (child_artifact.ref.artifact_id,),
                None,
            )
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = consume_repair_result(history, command, child_artifact, child_report)
    terminal = next_repair_step(
        history,
        DecisionId("unused-decision"),
        AttemptId("unused-attempt"),
    )
    assert type(terminal) is RepairTerminal
    return history, terminal


def _repaired_result(history, terminal):
    initial_request = history.initial_attempt.request
    compiled = initial_request.compiled_spec
    job = Job(
        initial_request.job_id,
        compiled.compiled_spec_hash,
        (initial_request.output_profile,),
        JobBudget(2),
        JobStatus.APPROVED,
        "2026-08-02T00:00:00.000Z",
        "2026-08-02T00:00:01.000Z",
    )
    return ProductionJobResult(
        compiled,
        initial_request.graph,
        compiled.verification_plans[0],
        history.current_request,
        history.current_artifact,
        history.current_report,
        history,
        terminal,
        JobState(
            job,
            8,
            tuple(
                attempt.request.attempt_id
                for attempt in (history.initial_attempt, *history.repair_attempts)
            ),
            (),
        ),
    )


def _asset_credits(compiled, request):
    style = compiled.source_spec.assets.style_references[0]
    return tuple(
        sorted(
            (
                AssetCredit(request.source.source, ("input",), None, None, None, None),
                AssetCredit(
                    request.style_references[0],
                    ("style_reference",),
                    style.source_url,
                    style.license,
                    style.attribution,
                    style.consent,
                ),
            ),
            key=lambda credit: credit.identity,
        )
    )


def _repaired_case() -> _Case:
    profile = "xhs_grid"
    compiled, spec_text, compiler_context = _compiled(profile, retry_l1=True)
    environment = sample_environment()
    history, source, prompt = _initial_retry_history(compiled, environment)
    history, terminal = _successful_retry(history)
    result = _repaired_result(history, terminal)
    initial_request = history.initial_attempt.request
    request = ProductionJobRequest(
        initial_request.job_id,
        spec_text,
        source,
        initial_request.style_references,
        prompt,
        profile,
        0,
        "bundle-repaired",
    )
    return _Case(
        request,
        result,
        environment,
        compiler_context,
        _asset_credits(compiled, initial_request),
    )


def _runtime(case: _Case) -> _ProductionGenerationRuntime:
    runtime = object.__new__(_ProductionGenerationRuntime)
    runtime._environment = case.environment
    runtime._compiler_context = case.compiler_context
    return runtime


def _append_case_event(
    store: JobStore,
    case: _Case,
    event_type: EventType,
    from_state: JobStatus,
    to_state: JobStatus,
    payload: object,
) -> None:
    store.append_event(
        case.request.job_id,
        Event(
            1,
            case.request.job_id,
            event_type,
            from_state,
            to_state,
            "2026-08-02T00:00:01.000Z",
            payload,
        ),
    )


def _persist_case(store: JobStore, case: _Case) -> None:
    result = case.result
    request = result.history.initial_attempt.request
    decision = result.terminal.artifact_decision
    terminal_status = JobStatus(decision.artifact_status.value)
    genesis = Job(
        request.job_id,
        result.compiled.compiled_spec_hash,
        (request.output_profile,),
        JobBudget(2),
        JobStatus.CREATED,
        "2026-08-02T00:00:00.000Z",
        "2026-08-02T00:00:00.000Z",
    )
    store.save_snapshot(
        request.job_id,
        JobSnapshot("specstyle.workflow.snapshot.v1", genesis, 0, (), ()),
    )
    events = (
        (
            EventType.JOB_STARTED,
            JobStatus.CREATED,
            JobStatus.SPEC_VALIDATED,
            JobStartedPayload(
                result.compiled.compiled_spec_hash,
                (request.output_profile,),
                JobBudget(2),
            ),
        ),
        (
            EventType.SPEC_COMPILED,
            JobStatus.SPEC_VALIDATED,
            JobStatus.SPEC_COMPILED,
            SpecCompiledPayload(result.compiled.compiled_spec_hash),
        ),
        (
            EventType.ATTEMPT_STARTED,
            JobStatus.SPEC_COMPILED,
            JobStatus.GENERATING,
            AttemptStartedPayload(0, 0, request.attempt_id, None),
        ),
        (
            EventType.ATTEMPT_FINISHED,
            JobStatus.GENERATING,
            JobStatus.VERIFYING,
            AttemptFinishedPayload(
                0,
                0,
                request.attempt_id,
                result.artifact.ref.artifact_id,
                request.request_hash,
            ),
        ),
        (
            EventType.VERIFIER_FINISHED,
            JobStatus.VERIFYING,
            terminal_status,
            VerifierFinishedPayload(
                0,
                0,
                result.artifact.ref.artifact_id,
                decision.artifact_status,
                decision.decision_reason,
                decision.repair_stop_reason,
            ),
        ),
    )
    for event_type, from_state, to_state, payload in events:
        _append_case_event(store, case, event_type, from_state, to_state, payload)


def _export_runtime(case: _Case, root: Path):
    from specstyle.workflow import production_service

    store = JobStore(root)
    _persist_case(store, case)
    persistence_root = root.parent / f"{root.name}-persistence"
    persistence_root.mkdir()
    root_fd = os.open(persistence_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        artifact_store = _open_production_artifact_store(root_fd)
        report_store = _open_production_report_store(root_fd)
    finally:
        os.close(root_fd)
    artifact_repository = artifact_store.for_job(case.request.job_id)
    report_repository = report_store.for_attempt(
        case.request.job_id, case.result.request.attempt_id
    )
    artifact_repository.put(case.result.artifact)
    report_repository.put(case.result.request, case.result.report)
    artifact_repository.close()
    report_repository.close()
    runtime = object.__new__(production_service.ProductionRuntime)
    values = {
        "_loaded": object(),
        "_load_pipeline": lambda: None,
        "_allowlist": object(),
        "_verifier_factory": object(),
        "_report_store": report_store,
        "_artifact_store": artifact_store,
        "_environment": case.environment,
        "_compiler_context": case.compiler_context,
        "_style_assets": object(),
        "_control_builder": object(),
        "_job_store": store,
        "_clock": production_service._NondecreasingAuditClock(
            lambda: "2026-08-02T00:00:02.000Z"
        ),
        "_state_lock": threading.RLock(),
        "_run_lock": threading.Lock(),
        "_active_job_id": None,
        "_active_cancel": None,
        "_active_cancel_reason": None,
        "_readiness_value": production_service.ProductionRuntimeReadiness.READY,
        "_failure_kind_value": None,
        "_closed": False,
    }
    for name, value in values.items():
        setattr(runtime, name, value)
    return runtime, store, artifact_store, report_store


def _completed_state(bundle_name: str = "bundle") -> JobState:
    export_request = sample_approved_export_request()
    item = export_request.cohorts[0].items[0]
    request = item.history.current_request
    job = Job(
        request.job_id,
        request.compiled_spec.compiled_spec_hash,
        (request.output_profile,),
        JobBudget(2),
        JobStatus.COMPLETED,
        "2026-08-02T00:00:00.000Z",
        "2026-08-02T00:00:01.000Z",
    )
    return JobState(job, 6, (request.attempt_id,), (bundle_name,))


def _bundle(bundle_name: str = "bundle") -> ExportBundle:
    return ExportBundle(
        bundle_name,
        1,
        2,
        Sha256("1" * 64),
        Sha256("2" * 64),
        Sha256("3" * 64),
        (ExportedFile("manifest.json", Sha256("1" * 64), 1),),
    )


def test_public_export_contracts_are_frozen_slotted_and_exactly_exported() -> None:
    module = _export_module()
    export_request = sample_approved_export_request()
    command = module.ProductionExportCommand(JobId("job"), "bundle", export_request)
    result = module.ProductionExportResult(_bundle(), _completed_state())
    entry = module.ProductionRecoveryEntry(
        JobId("job"), module.ProductionRecoveryDisposition.RECOVERED, result
    )

    assert module.__all__ == (
        "ProductionRecoveryDisposition",
        "ProductionExportCommand",
        "ProductionExportResult",
        "ProductionRecoveryEntry",
    )
    assert tuple(module.ProductionRecoveryDisposition) == tuple(
        module.ProductionRecoveryDisposition(value)
        for value in (
            "RECOVERED",
            "ALREADY_COMPLETED",
            "SKIPPED_MISSING_COMMAND",
            "SKIPPED_NOT_EXPORTABLE",
            "SKIPPED_TERMINAL",
        )
    )
    assert tuple(field.name for field in fields(command)) == (
        "job_id",
        "bundle_name",
        "export_request",
    )
    assert tuple(field.name for field in fields(result)) == ("bundle", "job_state")
    assert tuple(field.name for field in fields(entry)) == (
        "job_id",
        "disposition",
        "result",
    )
    assert not hasattr(command, "__dict__")
    with pytest.raises(FrozenInstanceError):
        command.bundle_name = "other"
    with pytest.raises(ValueError):
        module.ProductionRecoveryDisposition("recovered")


@pytest.mark.parametrize("disposition_name", ("RECOVERED", "ALREADY_COMPLETED"))
def test_recovery_success_entries_require_a_job_bound_result(
    disposition_name: str,
) -> None:
    module = _export_module()
    result = module.ProductionExportResult(_bundle(), _completed_state())
    disposition = module.ProductionRecoveryDisposition[disposition_name]

    assert (
        module.ProductionRecoveryEntry(JobId("job"), disposition, result).result
        is not result
    )
    with pytest.raises(DomainError):
        module.ProductionRecoveryEntry(JobId("other"), disposition, result)
    with pytest.raises(DomainError):
        module.ProductionRecoveryEntry(JobId("job"), disposition, None)


@pytest.mark.parametrize(
    "disposition_name",
    (
        "SKIPPED_MISSING_COMMAND",
        "SKIPPED_NOT_EXPORTABLE",
        "SKIPPED_TERMINAL",
    ),
)
def test_recovery_skips_forbid_results(disposition_name: str) -> None:
    module = _export_module()
    disposition = module.ProductionRecoveryDisposition[disposition_name]

    assert (
        module.ProductionRecoveryEntry(JobId("job"), disposition, None).result is None
    )
    with pytest.raises(DomainError):
        module.ProductionRecoveryEntry(
            JobId("job"),
            disposition,
            module.ProductionExportResult(_bundle(), _completed_state()),
        )


def test_export_command_and_result_rebuild_values_and_reject_bad_bindings() -> None:
    module = _export_module()
    case = _case()
    export_request = ExportRequest(
        (
            ExportCohort(
                "xhs_grid",
                case.result.report,
                (ExportItem(case.result.history, case.result.terminal, None),),
            ),
        ),
        case.environment,
        case.credits,
    )

    command = module.ProductionExportCommand(JobId("job"), "bundle", export_request)
    bundle = _bundle()
    completed = module.ProductionExportResult(bundle, _completed_state())

    assert command.export_request is not export_request
    assert completed.bundle is not bundle
    with pytest.raises(DomainError):
        module.ProductionExportCommand(JobId("other"), "bundle", export_request)
    with pytest.raises(DomainError):
        module.ProductionExportCommand(JobId("job"), "../bundle", export_request)
    with pytest.raises(DomainError):
        module.ProductionExportResult(_bundle("other"), _completed_state("bundle"))
    with pytest.raises(DomainError):
        module.ProductionExportResult(_bundle(), _case().result.job_state)


@pytest.mark.parametrize("profile", _PROFILES)
@pytest.mark.parametrize("status", tuple(case[0] for case in _DECISIONS))
def test_prepare_export_supports_every_profile_and_terminal_route(
    profile: str, status: ArtifactStatus
) -> None:
    case = _case(profile, status)

    command = _runtime(case).prepare_export(case.request, case.result, case.credits)
    prepared = _prepare_export(command.export_request)

    assert type(command) is _export_module().ProductionExportCommand
    assert command.job_id == case.request.job_id
    assert command.bundle_name == case.request.bundle_name
    assert len(command.export_request.cohorts) == 1
    cohort = command.export_request.cohorts[0]
    assert cohort.output_profile == profile
    assert len(cohort.items) == 1
    assert cohort.items[0].sequence_index == (
        0 if profile == "background_sequence" else None
    )
    routed = tuple(
        item.relative_path
        for item in prepared.payload_files
        if item.relative_path.endswith(".png")
    )
    assert len(routed) == 1
    assert routed[0].startswith(
        {
            ArtifactStatus.APPROVED: f"approved/{profile}/",
            ArtifactStatus.MANUAL_REVIEW: "manual_review/",
            ArtifactStatus.REJECTED: "rejected/",
        }[status]
    )
    if profile == "background_sequence":
        assert routed[0].rsplit("/", 1)[-1].startswith("000000_")


@pytest.mark.parametrize(
    ("profile", "status"),
    tuple(
        zip(
            _PROFILES,
            (
                ArtifactStatus.APPROVED,
                ArtifactStatus.MANUAL_REVIEW,
                ArtifactStatus.REJECTED,
            ),
            strict=True,
        )
    ),
)
def test_publish_export_persists_started_then_atomically_published(
    tmp_path: Path,
    profile: str,
    status: ArtifactStatus,
) -> None:
    case = _case(profile, status)
    root = tmp_path / "state"
    target = tmp_path / "exports"
    root.mkdir()
    target.mkdir()
    runtime, store, artifact_store, report_store = _export_runtime(case, root)
    command = _runtime(case).prepare_export(case.request, case.result, case.credits)
    target_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        result = runtime.publish_export(command, target_fd)
    finally:
        os.close(target_fd)
        report_store.close()
        artifact_store.close()

    assert type(result) is _export_module().ProductionExportResult
    assert result.job_state.job.status is JobStatus.COMPLETED
    assert result.job_state.bundle_names == ("bundle",)
    assert (target / "bundle" / "manifest.json").is_file()
    assert [event.event_type for event in store.list_events(case.request.job_id)][
        -2:
    ] == [EventType.EXPORT_STARTED, EventType.EXPORT_PUBLISHED]


def test_cancel_rejects_restarted_export_with_unknown_commit_point(
    tmp_path: Path,
) -> None:
    case = _case()
    root = tmp_path / "state"
    root.mkdir()
    runtime, store, artifact_store, report_store = _export_runtime(case, root)
    _append_case_event(
        store,
        case,
        EventType.EXPORT_STARTED,
        JobStatus.APPROVED,
        JobStatus.EXPORTING,
        ExportStartedPayload("bundle"),
    )

    try:
        with pytest.raises(
            InfrastructureError,
            match="^production export recovery required$",
        ):
            runtime.cancel(case.request.job_id)
    finally:
        report_store.close()
        artifact_store.close()

    assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
    assert (
        store.list_events(case.request.job_id)[-1].event_type
        is EventType.EXPORT_STARTED
    )


def test_recover_exports_restages_missing_final_and_completes_job(
    tmp_path: Path,
) -> None:
    module = _export_module()
    case = _case()
    root = tmp_path / "state"
    target = tmp_path / "exports"
    root.mkdir()
    target.mkdir()
    runtime, store, artifact_store, report_store = _export_runtime(case, root)
    command = _runtime(case).prepare_export(case.request, case.result, case.credits)
    _append_case_event(
        store,
        case,
        EventType.EXPORT_STARTED,
        JobStatus.APPROVED,
        JobStatus.EXPORTING,
        ExportStartedPayload("bundle"),
    )
    target_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        entries = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        report_store.close()
        artifact_store.close()

    assert len(entries) == 1
    assert entries[0].job_id == case.request.job_id
    assert entries[0].disposition is module.ProductionRecoveryDisposition.RECOVERED
    assert entries[0].result is not None
    assert entries[0].result.job_state.job.status is JobStatus.COMPLETED
    assert (target / "bundle" / "manifest.json").is_file()
    assert [event.event_type for event in store.list_events(case.request.job_id)][
        -2:
    ] == [EventType.EXPORT_STARTED, EventType.EXPORT_PUBLISHED]


def test_close_cancels_staging_export_and_waits_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specstyle.workflow import production_export_lifecycle

    case = _case()
    root = tmp_path / "state"
    target = tmp_path / "exports"
    root.mkdir()
    target.mkdir()
    runtime, store, _artifact_store, _report_store = _export_runtime(case, root)
    command = _runtime(case).prepare_export(case.request, case.result, case.credits)
    entered, release, close_done = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_stage = production_export_lifecycle._stage_bundle

    def blocked_stage(*args):
        entered.set()
        assert release.wait(2)
        return original_stage(*args)

    monkeypatch.setattr(production_export_lifecycle, "_stage_bundle", blocked_stage)
    target_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    export_errors: list[Exception] = []
    close_errors: list[Exception] = []

    def publish() -> None:
        try:
            runtime.publish_export(command, target_fd)
        except Exception as error:
            export_errors.append(error)

    def close() -> None:
        try:
            runtime.close()
        except Exception as error:
            close_errors.append(error)
        finally:
            close_done.set()

    publisher = threading.Thread(target=publish)
    closer = threading.Thread(target=close)
    publisher.start()
    assert entered.wait(2)
    closer.start()
    close_waited = not close_done.wait(0.1)
    release.set()
    publisher.join(2)
    closer.join(2)
    os.close(target_fd)

    assert not publisher.is_alive() and not closer.is_alive()
    assert close_waited
    assert close_errors == []
    assert len(export_errors) == 1
    assert isinstance(export_errors[0], DomainError)
    assert store.load(case.request.job_id).job.status is JobStatus.CANCELLED
    assert not (target / "bundle").exists()


def test_publish_export_closes_staged_owner_when_commit_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specstyle.workflow import production_export_lifecycle

    case = _case()
    root = tmp_path / "state"
    target = tmp_path / "exports"
    root.mkdir()
    target.mkdir()
    runtime, store, artifact_store, report_store = _export_runtime(case, root)
    command = _runtime(case).prepare_export(case.request, case.result, case.credits)

    class Staged:
        closes = 0

        def close(self) -> None:
            self.closes += 1

    staged = Staged()
    failure = InfrastructureError("commit failed")
    monkeypatch.setattr(
        production_export_lifecycle, "_stage_bundle", lambda *_args: staged
    )
    monkeypatch.setattr(
        production_export_lifecycle,
        "_commit_staged_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    target_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.publish_export(command, target_fd)
    finally:
        os.close(target_fd)
        report_store.close()
        artifact_store.close()

    assert raised.value is failure
    assert staged.closes == 1
    assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
    assert EventType.EXPORT_PUBLISHED not in {
        event.event_type for event in store.list_events(case.request.job_id)
    }


def test_prepare_export_rejects_non_exact_arguments_and_credit_contracts() -> None:
    case = _case()
    runtime = _runtime(case)

    with pytest.raises(DomainError):
        runtime.prepare_export(object(), case.result, case.credits)
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, object(), case.credits)
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, case.result, list(case.credits))
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, case.result, tuple(reversed(case.credits)))
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, case.result, case.credits[:-1])
    style = case.credits[-1]
    incomplete = AssetCredit(
        style.asset,
        style.roles,
        style.source_url,
        None,
        style.attribution,
        style.consent,
    )
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, case.result, (case.credits[0], incomplete))


def test_prepare_export_rejects_cross_job_profile_and_environment() -> None:
    case = _case()
    other_job = _case(job_id="other")
    other_profile = _case("talking_head_cover")

    with pytest.raises(DomainError):
        _runtime(case).prepare_export(other_job.request, case.result, case.credits)
    with pytest.raises(DomainError):
        _runtime(case).prepare_export(other_profile.request, case.result, case.credits)
    runtime = _runtime(case)
    runtime._environment = replace(
        case.environment,
        os_name=TextObservation("AVAILABLE", "SpecOS", None),
    )
    with pytest.raises(DomainError):
        runtime.prepare_export(case.request, case.result, case.credits)


def test_prepare_export_recompiles_and_rejects_forged_outer_spec_text() -> None:
    case = _case()
    forged = replace(
        case.request, spec_text=_case("talking_head_cover").request.spec_text
    )

    with pytest.raises(DomainError):
        _runtime(case).prepare_export(forged, case.result, case.credits)


def test_prepare_export_accepts_repaired_result_bound_to_initial_outer_request() -> (
    None
):
    case = _repaired_case()

    command = _runtime(case).prepare_export(case.request, case.result, case.credits)

    item = command.export_request.cohorts[0].items[0]
    assert case.request.variation_index == 0
    assert item.history.initial_attempt.request.variation_index == 0
    assert item.history.current_request.variation_index == 1
    assert len(item.history.repair_attempts) == 1
    assert item.history.current_artifact.ref == case.result.artifact.ref
    assert (
        item.terminal.artifact_decision.artifact_id
        == item.history.current_artifact.ref.artifact_id
    )


def test_prepare_export_rejects_outer_request_bound_to_repair_child_variation() -> None:
    case = _repaired_case()
    forged = replace(case.request, variation_index=1)

    with pytest.raises(DomainError, match="^invalid production export$"):
        _runtime(case).prepare_export(forged, case.result, case.credits)


@pytest.mark.parametrize(
    ("field", "mutate"),
    (
        ("job_id", lambda case: _HostileJobId(case.request.job_id.value)),
        ("spec_text", lambda case: _HostileStr(case.request.spec_text)),
        ("source", lambda _case: object()),
        ("style_references", lambda case: list(case.request.style_references)),
        ("prompt", lambda _case: object()),
        ("output_profile", lambda case: _HostileStr(case.request.output_profile)),
        ("variation_index", lambda _case: False),
        ("variation_index", lambda _case: True),
        ("variation_index", lambda _case: _HostileInt(0)),
        ("bundle_name", lambda case: _HostileStr(case.request.bundle_name)),
    ),
)
def test_prepare_export_rejects_hostile_outer_request_field_mutations(
    field: str, mutate: object
) -> None:
    case = _case()
    object.__setattr__(case.request, field, mutate(case))  # type: ignore[operator]

    with pytest.raises(DomainError):
        _runtime(case).prepare_export(case.request, case.result, case.credits)


def test_prepare_export_rejects_every_forged_result_binding() -> None:
    case = _case()
    profile = _case("talking_head_cover")
    rejected = _case(status=ArtifactStatus.REJECTED)
    other_job = _case(job_id="other")
    forged = (
        replace(case.result, compiled=profile.result.compiled),
        replace(case.result, graph=profile.result.graph),
        replace(case.result, verification_plan=profile.result.verification_plan),
        replace(case.result, request=other_job.result.request),
        replace(case.result, artifact=other_job.result.artifact),
        replace(case.result, report=rejected.result.report),
        replace(case.result, history=other_job.result.history),
        replace(case.result, terminal=rejected.result.terminal),
        replace(case.result, job_state=other_job.result.job_state),
    )

    for result in forged:
        with pytest.raises(DomainError):
            _runtime(case).prepare_export(case.request, result, case.credits)


def test_prepare_export_does_not_touch_store_gpu_or_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specstyle.workflow import production_service

    case = _case()
    runtime = _runtime(case)

    class Trap:
        def __getattribute__(self, name: str) -> object:
            if name == "__class__":
                return object.__getattribute__(self, name)
            raise AssertionError("side effect dependency was touched")

        def __enter__(self) -> None:
            raise AssertionError("GPU lease was touched")

        def __exit__(self, *_args: object) -> None:
            raise AssertionError("GPU lease was touched")

    trap = Trap()
    runtime._job_store = trap
    monkeypatch.setattr(production_service, "_GPU_LEASE", trap)

    command = runtime.prepare_export(case.request, case.result, case.credits)

    assert command.export_request.environment == case.environment
    assert runtime._job_store is trap
