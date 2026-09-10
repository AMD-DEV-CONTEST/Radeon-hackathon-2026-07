"""Production export commands and restart result contracts.

This module composes already-final generation, verification and repair values into the
existing export manifest model.  It performs no filesystem, JobStore, GPU or model work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from specstyle.domain.identifiers import JobId, Sha256
from specstyle.errors import DomainError
from specstyle.exporting import qa_report as _qa
from specstyle.exporting.bundle import ExportBundle, ExportedFile
from specstyle.exporting.manifest import (
    AssetCredit,
    ExportCohort,
    ExportItem,
    ExportRequest,
)
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.environment import EnvironmentSnapshot, hash_environment
from specstyle.repair.history import RepairHistory
from specstyle.repair.loop import RepairTerminal
from specstyle.spec.compiled_models import (
    CompiledExecutionGraph,
    CompiledStyleSpec,
    CompiledVerificationPlan,
    OutputProfile,
)
from specstyle.verification.rule_models import VerificationReport
from specstyle.workflow.job_models import (
    Job,
    JobBudget,
    JobState,
    JobStatus,
    _bundle_name,
)

__all__ = (
    "ProductionRecoveryDisposition",
    "ProductionExportCommand",
    "ProductionExportResult",
    "ProductionRecoveryEntry",
)

_EXPORTABLE_STATUSES = {
    JobStatus.APPROVED,
    JobStatus.MANUAL_REVIEW,
    JobStatus.REJECTED,
}
_SUCCESS_DISPOSITIONS: frozenset[ProductionRecoveryDisposition]


def _invalid() -> None:
    raise DomainError("invalid production export") from None


def _same(left: object, right: object) -> bool:
    return _qa.canonical_material(left) == _qa.canonical_material(right)


def _rebuild_job_id(value: object) -> JobId:
    if type(value) is not JobId or type(value.value) is not str:
        _invalid()
    return JobId(str.__str__(value.value))


def _rebuild_sha(value: object) -> Sha256:
    if type(value) is not Sha256 or type(value.value) is not str:
        _invalid()
    return Sha256(str.__str__(value.value))


def _rebuild_export_request(value: object) -> ExportRequest:
    if type(value) is not ExportRequest:
        _invalid()
    try:
        rebuilt = ExportRequest(value.cohorts, value.environment, value.asset_credits)
        if not _same(value, rebuilt):
            _invalid()
        return rebuilt
    except Exception:
        _invalid()


def _export_job_id(request: ExportRequest) -> JobId:
    generation = request.cohorts[0].items[0].history.current_request
    return _rebuild_job_id(generation.job_id)


class ProductionRecoveryDisposition(StrEnum):
    RECOVERED = "RECOVERED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    SKIPPED_MISSING_COMMAND = "SKIPPED_MISSING_COMMAND"
    SKIPPED_NOT_EXPORTABLE = "SKIPPED_NOT_EXPORTABLE"
    SKIPPED_TERMINAL = "SKIPPED_TERMINAL"


_SUCCESS_DISPOSITIONS = frozenset(
    {
        ProductionRecoveryDisposition.RECOVERED,
        ProductionRecoveryDisposition.ALREADY_COMPLETED,
    }
)


@dataclass(frozen=True, slots=True)
class ProductionExportCommand:
    job_id: JobId
    bundle_name: str
    export_request: ExportRequest

    def __post_init__(self) -> None:
        try:
            job_id = _rebuild_job_id(self.job_id)
            bundle_name = _bundle_name(self.bundle_name)
            export_request = _rebuild_export_request(self.export_request)
            if _export_job_id(export_request).value != job_id.value:
                _invalid()
        except Exception:
            _invalid()
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "bundle_name", bundle_name)
        object.__setattr__(self, "export_request", export_request)


def _rebuild_production_export_command(value: object) -> ProductionExportCommand:
    if type(value) is not ProductionExportCommand:
        _invalid()
    try:
        rebuilt = ProductionExportCommand(
            value.job_id,
            value.bundle_name,
            value.export_request,
        )
        if not _same(value, rebuilt):
            _invalid()
        return rebuilt
    except Exception:
        _invalid()


def _safe_relative_path(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or value.startswith("/")
        or "\\" in value
        or any(ord(character) <= 31 or ord(character) == 127 for character in value)
    ):
        _invalid()
    components = value.split("/")
    if any(not item or item in {".", ".."} for item in components):
        _invalid()
    return value


def _rebuild_exported_file(value: object) -> ExportedFile:
    if (
        type(value) is not ExportedFile
        or type(value.size_bytes) is not int
        or isinstance(value.size_bytes, bool)
        or value.size_bytes < 0
    ):
        _invalid()
    return ExportedFile(
        _safe_relative_path(value.relative_path),
        _rebuild_sha(value.sha256),
        value.size_bytes,
    )


def _rebuild_bundle(value: object) -> ExportBundle:
    if (
        type(value) is not ExportBundle
        or type(value.root_device) is not int
        or isinstance(value.root_device, bool)
        or value.root_device < 0
        or type(value.root_inode) is not int
        or isinstance(value.root_inode, bool)
        or value.root_inode < 0
        or type(value.files) is not tuple
        or not value.files
    ):
        _invalid()
    files = tuple(_rebuild_exported_file(item) for item in value.files)
    paths = tuple(item.relative_path for item in files)
    manifest = tuple(item for item in files if item.relative_path == "manifest.json")
    if (
        paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or len(manifest) != 1
    ):
        _invalid()
    rebuilt = ExportBundle(
        _bundle_name(value.bundle_name),
        value.root_device,
        value.root_inode,
        _rebuild_sha(value.manifest_sha256),
        _rebuild_sha(value.payload_sha256),
        _rebuild_sha(value.bundle_sha256),
        files,
    )
    if manifest[0].sha256 != rebuilt.manifest_sha256 or not _same(value, rebuilt):
        _invalid()
    return rebuilt


def _rebuild_job_state(value: object) -> JobState:
    if type(value) is not JobState or type(value.job) is not Job:
        _invalid()
    job = value.job
    if type(job.budget) is not JobBudget:
        _invalid()
    try:
        rebuilt_job = Job(
            job.job_id,
            job.compiled_spec_hash,
            job.cohort_profiles,
            JobBudget(job.budget.max_attempts_per_item),
            job.status,
            job.created_at,
            job.updated_at,
        )
        rebuilt = JobState(
            rebuilt_job,
            value.last_sequence,
            value.attempt_ids,
            value.bundle_names,
        )
        if not _same(value, rebuilt):
            _invalid()
        return rebuilt
    except Exception:
        _invalid()


@dataclass(frozen=True, slots=True)
class ProductionExportResult:
    bundle: ExportBundle
    job_state: JobState

    def __post_init__(self) -> None:
        try:
            bundle = _rebuild_bundle(self.bundle)
            job_state = _rebuild_job_state(self.job_state)
            if (
                job_state.job.status is not JobStatus.COMPLETED
                or job_state.bundle_names != (bundle.bundle_name,)
            ):
                _invalid()
        except Exception:
            _invalid()
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(self, "job_state", job_state)


@dataclass(frozen=True, slots=True)
class ProductionRecoveryEntry:
    job_id: JobId
    disposition: ProductionRecoveryDisposition
    result: ProductionExportResult | None

    def __post_init__(self) -> None:
        try:
            job_id = _rebuild_job_id(self.job_id)
            if type(self.disposition) is not ProductionRecoveryDisposition:
                _invalid()
            result = self._rebuild_result(job_id)
        except Exception:
            _invalid()
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "result", result)

    def _rebuild_result(self, job_id: JobId) -> ProductionExportResult | None:
        if self.disposition in _SUCCESS_DISPOSITIONS:
            if type(self.result) is not ProductionExportResult:
                _invalid()
            result = ProductionExportResult(self.result.bundle, self.result.job_state)
            if result.job_state.job.job_id.value != job_id.value:
                _invalid()
            return result
        if self.result is not None:
            _invalid()
        return None


@dataclass(frozen=True, slots=True)
class _ValidatedResult:
    compiled: CompiledStyleSpec
    graph: CompiledExecutionGraph
    plan: CompiledVerificationPlan
    request: GenerationRequest
    artifact: GeneratedArtifact
    report: VerificationReport
    history: RepairHistory
    terminal: RepairTerminal
    job_state: JobState


def _rebuild_request(value: object) -> GenerationRequest:
    if type(value) is not GenerationRequest:
        _invalid()
    try:
        rebuilt = GenerationRequest(
            value.job_id,
            value.attempt_id,
            value.parent_attempt_id,
            value.compiled_spec,
            value.generation_profile,
            value.output_profile,
            value.source,
            value.style_references,
            value.prompt,
            value.control_input,
            value.variation_index,
            value.environment_hash,
            value.execution_parameters,
        )
        if not _same(value, rebuilt):
            _invalid()
        return rebuilt
    except Exception:
        _invalid()


def _rebuild_artifact(value: object) -> GeneratedArtifact:
    if type(value) is not GeneratedArtifact:
        _invalid()
    try:
        rebuilt = GeneratedArtifact(
            value.ref,
            value.content,
            value.request_hash,
            value.generation_fingerprint,
        )
        if not _same(value, rebuilt):
            _invalid()
        return rebuilt
    except Exception:
        _invalid()


def _select_contract(compiled: CompiledStyleSpec, profile: str):
    graphs = tuple(
        item for item in compiled.production_graphs if item.output_profile == profile
    )
    plans = tuple(
        item for item in compiled.verification_plans if item.output_profile == profile
    )
    if len(graphs) != 1 or len(plans) != 1:
        _invalid()
    return graphs[0], plans[0]


def _validate_result_fields(result: object) -> _ValidatedResult:
    expected = (
        ("compiled", CompiledStyleSpec),
        ("graph", CompiledExecutionGraph),
        ("verification_plan", CompiledVerificationPlan),
        ("request", GenerationRequest),
        ("artifact", GeneratedArtifact),
        ("report", VerificationReport),
        ("history", RepairHistory),
        ("terminal", RepairTerminal),
        ("job_state", JobState),
    )
    if any(type(getattr(result, name, None)) is not kind for name, kind in expected):
        _invalid()
    history = _qa.rebuild_repair_history(result.history)
    return _ValidatedResult(
        _qa.rebuild_compiled_spec(result.compiled),
        result.graph,
        result.verification_plan,
        _rebuild_request(result.request),
        _rebuild_artifact(result.artifact),
        _qa.rebuild_verification_report(result.report),
        history,
        _qa.rebuild_repair_terminal(result.terminal),
        _rebuild_job_state(result.job_state),
    )


def _validate_result_bindings(value: _ValidatedResult) -> None:
    current_request = value.history.current_request
    expected_graph, expected_plan = _select_contract(
        value.compiled, current_request.output_profile
    )
    pairs = (
        (value.compiled, current_request.compiled_spec),
        (value.graph, expected_graph),
        (value.plan, expected_plan),
        (value.request, current_request),
        (value.artifact, value.history.current_artifact),
        (value.report, value.history.current_report),
    )
    if any(not _same(actual, expected) for actual, expected in pairs):
        _invalid()


def _validate_recompiled_contract(
    value: _ValidatedResult,
    compiled: object,
    graph: object,
    plan: object,
) -> None:
    if (
        type(compiled) is not CompiledStyleSpec
        or type(graph) is not CompiledExecutionGraph
        or type(plan) is not CompiledVerificationPlan
    ):
        _invalid()
    rebuilt = _qa.rebuild_compiled_spec(compiled)
    if any(
        not _same(actual, expected)
        for actual, expected in (
            (value.compiled, rebuilt),
            (value.graph, graph),
            (value.plan, plan),
        )
    ):
        _invalid()


def _validate_job_request(request: object, value: _ValidatedResult) -> None:
    initial = value.history.initial_attempt.request
    pairs = (
        (request.source, initial.source),
        (request.style_references, initial.style_references),
        (request.prompt, initial.prompt),
    )
    if (
        request.job_id.value != initial.job_id.value
        or request.output_profile != initial.output_profile
        or request.variation_index != initial.variation_index
        or any(not _same(actual, expected) for actual, expected in pairs)
    ):
        _invalid()


def _history_attempt_ids(history: RepairHistory) -> tuple[str, ...]:
    requests = (
        history.initial_attempt.request,
        *(attempt.request for attempt in history.repair_attempts),
    )
    return tuple(item.attempt_id.value for item in requests)


def _sequence_index(profile: OutputProfile) -> int | None:
    return 0 if profile == "background_sequence" else None


def _validate_job_state(value: _ValidatedResult) -> None:
    state, current = value.job_state, value.request
    job, decision = state.job, value.terminal.artifact_decision
    attempt_ids = tuple(item.value for item in state.attempt_ids)
    expected_budget = 1 + value.compiled.source_spec.repair.max_rounds
    if (
        job.status not in _EXPORTABLE_STATUSES
        or decision.artifact_status.value != job.status.value
        or job.job_id.value != current.job_id.value
        or job.compiled_spec_hash != value.compiled.compiled_spec_hash
        or job.cohort_profiles != (current.output_profile,)
        or job.budget.max_attempts_per_item != expected_budget
        or attempt_ids != _history_attempt_ids(value.history)
        or state.bundle_names
    ):
        _invalid()


def _prepare_production_export_command(
    request: object,
    result: object,
    environment: object,
    asset_credits: object,
    recompiled: tuple[object, object, object],
) -> ProductionExportCommand:
    try:
        value = _validate_result_fields(result)
        _validate_result_bindings(value)
        if type(recompiled) is not tuple or len(recompiled) != 3:
            _invalid()
        _validate_recompiled_contract(value, *recompiled)
        _validate_job_request(request, value)
        _validate_job_state(value)
        if type(environment) is not EnvironmentSnapshot:
            _invalid()
        rebuilt_environment = _qa.rebuild_environment(environment)
        if value.request.environment_hash != hash_environment(rebuilt_environment):
            _invalid()
        if type(asset_credits) is not tuple or any(
            type(item) is not AssetCredit for item in asset_credits
        ):
            _invalid()
        sequence = _sequence_index(value.request.output_profile)
        export_request = ExportRequest(
            (
                ExportCohort(
                    value.request.output_profile,
                    value.report,
                    (ExportItem(value.history, value.terminal, sequence),),
                ),
            ),
            rebuilt_environment,
            asset_credits,
        )
        return ProductionExportCommand(
            value.request.job_id, request.bundle_name, export_request
        )
    except Exception:
        _invalid()
