"""APP-COMPOSE-001C production generation→verification→repair vertical slice."""

from __future__ import annotations

import os
import importlib
import inspect
from dataclasses import dataclass, replace
from pathlib import Path
import threading

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, AttemptId, JobId, RuleId
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes
from specstyle.reliability.fixtures import sample_production_request
from specstyle.repair.actions import (
    DECREASE_STYLE_SCALE,
    INCREASE_STRUCTURE,
    INCREASE_STYLE_SCALE,
    REDUCE_DENOISE,
    RENDER_OUTPUT_PROFILE,
    RETRY_SAMPLING,
)
from specstyle.verification.rule_models import GatePolicy, RuleResult
from specstyle.workflow import production_service
from specstyle.workflow.job_models import Event, EventType, JobStatus
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_artifacts import _open_production_artifact_store
from specstyle.workflow.production_reports import _open_production_report_store

_TS = "2026-08-02T00:00:00.000Z"


@dataclass(frozen=True)
class _RuleSpec:
    rule_id: str
    actions: tuple[object, ...]
    priority: int = 1
    policy: GatePolicy = GatePolicy("reject", "reject", "reject")


def _contract(rule_specs: tuple[_RuleSpec, ...]):
    base = sample_production_request()
    template = next(
        rule
        for rule in base.compiled_spec.verification_plans[0].rules
        if rule.definition.scope is RuleScope.ITEM and rule.metric_id is not None
    )
    rules = tuple(
        replace(
            template,
            definition=replace(
                template.definition,
                rule_id=RuleId(spec.rule_id),
                required=True,
                applicability=StaticApplicability.APPLICABLE,
                gate_policy=spec.policy,
            ),
            priority=spec.priority,
            affected_by_actions=spec.actions,
        )
        for spec in rule_specs
    )
    plan = replace(base.compiled_spec.verification_plans[0], rules=rules)
    compiled = replace(base.compiled_spec, verification_plans=(plan,))
    request = GenerationRequest(
        JobId("job"),
        AttemptId("job-a0-xhs_grid-0"),
        None,
        compiled,
        "production",
        "xhs_grid",
        base.source,
        base.style_references,
        base.prompt,
        base.control_input,
        0,
        base.environment_hash,
    )
    return compiled, compiled.production_graphs[0], plan, request


class _Verifier:
    def __init__(self, statuses: dict[str, RuleStatus]) -> None:
        self.statuses = statuses
        self.calls = 0

    def verify(self, artifacts, rules, /):
        self.calls += 1
        artifact_id = artifacts[0].artifact_id
        return tuple(
            RuleResult(
                rule.rule_id,
                self.statuses[rule.rule_id.value],
                (artifact_id,),
                None,
            )
            for rule in rules
        )


class _Factory:
    def __init__(self, outcomes: dict[str, dict[str, RuleStatus]]) -> None:
        self.outcomes = outcomes
        self.created: list[tuple[GenerationRequest, object, _Verifier]] = []
        self.closed = False

    def create(self, request, _plan, repository, _style_assets):
        verifier = _Verifier(self.outcomes[request.attempt_id.value])
        self.created.append((request, repository, verifier))
        return verifier

    def close(self) -> None:
        self.closed = True


class _TrackingRepository:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.puts = 0
        self.reads = 0
        self.closed = False

    def put(self, *args) -> None:
        self.puts += 1
        self.inner.put(*args)

    def __call__(self, *args):
        self.reads += 1
        return self.inner(*args)

    def close(self) -> None:
        self.closed = True
        self.inner.close()


class _TrackingStore:
    def __init__(self, inner, method: str) -> None:
        self.inner = inner
        self.method = method
        self.repositories: list[_TrackingRepository] = []

    def for_job(self, job_id):
        assert self.method == "for_job"
        repository = _TrackingRepository(self.inner.for_job(job_id))
        self.repositories.append(repository)
        return repository

    def for_attempt(self, job_id, attempt_id):
        assert self.method == "for_attempt"
        repository = _TrackingRepository(self.inner.for_attempt(job_id, attempt_id))
        self.repositories.append(repository)
        return repository

    def close(self) -> None:
        self.inner.close()


class _Loaded:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _DurabilityCheckingJobStore(JobStore):
    def __init__(self, state_root: Path, persistence_root: Path) -> None:
        super().__init__(state_root)
        self.persistence_root = persistence_root

    def append_event(self, job_id: JobId, event: Event, /) -> Event:
        if event.event_type is EventType.ATTEMPT_FINISHED:
            artifact = event.payload.artifact_id.value
            directory = (
                self.persistence_root / "jobs" / job_id.value / "artifacts" / artifact
            )
            assert (directory / "artifact.png").is_file()
            assert (directory / "metadata.json").is_file()
        if event.event_type is EventType.VERIFIER_FINISHED:
            attempt = self.load(job_id).attempt_ids[-1].value
            directory = (
                self.persistence_root / "jobs" / job_id.value / "reports" / attempt
            )
            assert (directory / "report.json").is_file()
            assert (directory / "metadata.json").is_file()
        return super().append_event(job_id, event)


def _artifact(request: GenerationRequest) -> GeneratedArtifact:
    suffix = "a0" if request.parent_attempt_id is None else "a1"
    content = f"artifact-{suffix}".encode()
    return GeneratedArtifact(
        ArtifactRef(ArtifactId(f"artifact-{suffix}"), hash_bytes(content)),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )


def _runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_specs: tuple[_RuleSpec, ...],
    outcomes: dict[str, dict[str, RuleStatus]],
):
    compiled, graph, plan, initial = _contract(rule_specs)
    state_root = tmp_path / "state"
    persistence_root = tmp_path / "persistence"
    state_root.mkdir()
    persistence_root.mkdir()
    root_fd = os.open(persistence_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        artifacts = _TrackingStore(_open_production_artifact_store(root_fd), "for_job")
        reports = _TrackingStore(_open_production_report_store(root_fd), "for_attempt")
    finally:
        os.close(root_fd)
    factory, loaded = _Factory(outcomes), _Loaded()
    runtime = object.__new__(production_service._ProductionGenerationRuntime)
    values = {
        "_loaded": loaded,
        "_load_pipeline": lambda: loaded,
        "_allowlist": object(),
        "_verifier_factory": factory,
        "_report_store": reports,
        "_artifact_store": artifacts,
        "_environment": object(),
        "_compiler_context": object(),
        "_style_assets": lambda _reference: b"",
        "_control_builder": object(),
        "_job_store": _DurabilityCheckingJobStore(state_root, persistence_root),
        "_clock": production_service._NondecreasingAuditClock(lambda: _TS),
        "_state_lock": threading.RLock(),
        "_run_lock": threading.Lock(),
        "_active_job_id": None,
        "_active_cancel": None,
        "_active_cancel_reason": None,
        "_readiness_value": production_service._RuntimeReadiness.READY,
        "_failure_kind_value": None,
        "_closed": False,
    }
    for name, value in values.items():
        setattr(runtime, name, value)
    monkeypatch.setattr(
        production_service,
        "_select_initial_contract",
        lambda *_args: (compiled, graph, plan),
    )
    monkeypatch.setattr(production_service, "_preflight_bindings", lambda *_args: None)
    monkeypatch.setattr(
        production_service, "_initial_generation_request", lambda *_args: initial
    )
    monkeypatch.setattr(
        production_service,
        "_run_initial_generation",
        lambda *args: _artifact(
            next(item for item in args if type(item) is GenerationRequest)
        ),
    )
    request = production_service.ProductionJobRequest(
        initial.job_id,
        "spec",
        initial.source,
        initial.style_references,
        initial.prompt,
        initial.output_profile,
        initial.variation_index,
        "bundle",
    )
    return runtime, request, factory, artifacts, reports


def _event_summary(store: JobStore) -> list[tuple[str, str, str]]:
    return [
        (event.event_type.value, event.from_state.value, event.to_state.value)
        for event in store.list_events(JobId("job"))
    ]


@pytest.mark.parametrize(
    ("status", "policy", "expected_state", "reason", "stop"),
    [
        (
            RuleStatus.PASS,
            GatePolicy("reject", "reject", "reject"),
            JobStatus.APPROVED,
            DecisionReason.ALL_REQUIRED_PASS,
            RepairStopReason.PASS_ALL_REQUIRED,
        ),
        (
            RuleStatus.UNVERIFIABLE,
            GatePolicy("reject", "reject", "reject"),
            JobStatus.REJECTED,
            DecisionReason.REQUIRED_GATE_UNVERIFIABLE,
            RepairStopReason.UNVERIFIABLE,
        ),
        (
            RuleStatus.WARNING,
            GatePolicy("reject", "reject", "manual_review"),
            JobStatus.MANUAL_REVIEW,
            DecisionReason.MANUAL_POLICY,
            RepairStopReason.MANUAL_REQUEST,
        ),
    ],
)
def test_initial_terminal_routes_are_durable_before_exact_final_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: RuleStatus,
    policy: GatePolicy,
    expected_state: JobStatus,
    reason: DecisionReason,
    stop: RepairStopReason,
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,), policy=policy),),
        {attempt: {"STYLE_LOW": status}},
    )
    try:
        result = runtime._execute_initial_attempt(request)
        events = runtime._job_store.list_events(JobId("job"))
        assert _event_summary(runtime._job_store) == [
            ("JOB_STARTED", "CREATED", "SPEC_VALIDATED"),
            ("SPEC_COMPILED", "SPEC_VALIDATED", "SPEC_COMPILED"),
            ("ATTEMPT_STARTED", "SPEC_COMPILED", "GENERATING"),
            ("ATTEMPT_FINISHED", "GENERATING", "VERIFYING"),
            ("VERIFIER_FINISHED", "VERIFYING", expected_state.value),
        ]
        payload = events[-1].payload
        assert (payload.artifact_status, payload.decision_reason) == (
            ArtifactStatus(expected_state.value),
            reason,
        )
        assert payload.repair_stop_reason is stop
        assert result.request.attempt_id.value == attempt
        assert result.terminal.artifact_decision.repair_stop_reason is stop
        assert result.job_state.job.status is expected_state
        assert len(factory.created) == 1
        assert artifacts.repositories[0].reads >= 1
        assert reports.repositories[0].reads >= 1
        assert all(
            repo.closed for repo in artifacts.repositories + reports.repositories
        )
    finally:
        runtime.close()


def test_no_action_records_selecting_then_repair_exhausted(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.FAIL}},
    )
    try:
        result = runtime._execute_initial_attempt(request)
        events = runtime._job_store.list_events(JobId("job"))
        assert _event_summary(runtime._job_store)[-2:] == [
            ("VERIFIER_FINISHED", "VERIFYING", "REPAIR_SELECTING"),
            ("VERIFIER_FINISHED", "REPAIR_SELECTING", "REJECTED"),
        ]
        assert events[-2].payload.repair_stop_reason is None
        assert events[-1].payload.decision_reason is DecisionReason.REPAIR_EXHAUSTED
        assert events[-1].payload.repair_stop_reason is RepairStopReason.NO_ACTION
        assert result.terminal.no_action is not None
        assert result.job_state.job.status is JobStatus.REJECTED
        assert len(factory.created) == 1
        assert all(
            repo.closed for repo in artifacts.repositories + reports.repositories
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("child", "stop"),
    [
        ((RuleStatus.PASS,), RepairStopReason.PASS_ALL_REQUIRED),
        ((RuleStatus.FAIL,), RepairStopReason.NO_IMPROVEMENT),
    ],
)
def test_repair_round_pass_or_no_improvement_has_exact_events(
    tmp_path, monkeypatch, child: tuple[RuleStatus, ...], stop: RepairStopReason
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    runtime, request, factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,)),),
        {
            a0: {"STYLE_LOW": RuleStatus.FAIL},
            a1: {"STYLE_LOW": child[0]},
        },
    )
    try:
        result = runtime._execute_initial_attempt(request)
        summaries = _event_summary(runtime._job_store)
        assert summaries[4:] == [
            ("VERIFIER_FINISHED", "VERIFYING", "REPAIR_SELECTING"),
            ("REPAIR_STEP", "REPAIR_SELECTING", "REPAIRING"),
            ("ATTEMPT_FINISHED", "REPAIRING", "VERIFYING"),
            (
                "VERIFIER_FINISHED",
                "VERIFYING",
                "APPROVED"
                if stop is RepairStopReason.PASS_ALL_REQUIRED
                else "REJECTED",
            ),
        ]
        repair_payload = runtime._job_store.list_events(JobId("job"))[5].payload
        assert (
            repair_payload.decision_id.value,
            repair_payload.action_id,
            repair_payload.parent_attempt_id.value,
            repair_payload.child_attempt_id.value,
        ) == (
            "job-d1-xhs_grid-0",
            INCREASE_STYLE_SCALE,
            a0,
            a1,
        )
        assert result.request.attempt_id.value == a1
        assert result.history.rounds == 1
        assert result.terminal.artifact_decision.repair_stop_reason is stop
        assert len(factory.created) == 2
        assert factory.created[0][2] is not factory.created[1][2]
        assert all(
            repo.closed for repo in artifacts.repositories + reports.repositories
        )
    finally:
        runtime.close()


def test_improved_but_still_failing_round_stops_at_max_rounds(
    tmp_path, monkeypatch
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    rules = (
        _RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,), 1),
        _RuleSpec("CONTENT_DRIFT", (REDUCE_DENOISE,), 2),
    )
    runtime, request, _factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        rules,
        {
            a0: {"STYLE_LOW": RuleStatus.FAIL, "CONTENT_DRIFT": RuleStatus.FAIL},
            a1: {"STYLE_LOW": RuleStatus.PASS, "CONTENT_DRIFT": RuleStatus.FAIL},
        },
    )
    try:
        result = runtime._execute_initial_attempt(request)
        payload = runtime._job_store.list_events(JobId("job"))[-1].payload
        assert payload.decision_reason is DecisionReason.REPAIR_EXHAUSTED
        assert payload.repair_stop_reason is RepairStopReason.MAX_ROUNDS
        assert result.history.consecutive_no_improvement == 0
        assert result.terminal.artifact_decision.repair_stop_reason is (
            RepairStopReason.MAX_ROUNDS
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("rule_id", "actions", "expected"),
    [
        ("STYLE_LOW", (INCREASE_STYLE_SCALE,), INCREASE_STYLE_SCALE),
        (
            "STYLE_OVERPOWERED",
            (DECREASE_STYLE_SCALE, REDUCE_DENOISE),
            DECREASE_STYLE_SCALE,
        ),
        ("STYLE_OVERPOWERED", (REDUCE_DENOISE,), REDUCE_DENOISE),
        ("CONTENT_DRIFT", (REDUCE_DENOISE, INCREASE_STRUCTURE), REDUCE_DENOISE),
        ("CONTENT_DRIFT", (INCREASE_STRUCTURE,), INCREASE_STRUCTURE),
        ("FACE_ID_LOW", (REDUCE_DENOISE,), REDUCE_DENOISE),
        ("SAMPLING_DEFECT", (RETRY_SAMPLING,), RETRY_SAMPLING),
        ("OUTPUT_PROFILE_INVALID", (RENDER_OUTPUT_PROFILE,), None),
        ("UNKNOWN_BLOCKER", (INCREASE_STYLE_SCALE,), None),
        ("STYLE_LOW", (REDUCE_DENOISE,), None),
    ],
)
def test_repair_action_uses_core_policy_and_compiled_intersection(
    tmp_path, monkeypatch, rule_id: str, actions: tuple[object, ...], expected
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    outcomes = {a0: {rule_id: RuleStatus.FAIL}}
    if expected is not None:
        outcomes[a1] = {rule_id: RuleStatus.PASS}
    runtime, request, _factory, artifacts, reports = _runtime(
        tmp_path, monkeypatch, (_RuleSpec(rule_id, actions),), outcomes
    )
    try:
        runtime._execute_initial_attempt(request)
        events = runtime._job_store.list_events(JobId("job"))
        repair = next(
            (event for event in events if event.event_type is EventType.REPAIR_STEP),
            None,
        )
        if expected is None:
            assert repair is None
            assert events[-1].payload.repair_stop_reason is RepairStopReason.NO_ACTION
        else:
            assert repair.payload.action_id == expected
    finally:
        runtime.close()


def _capture_call(call, results, errors) -> None:
    try:
        results.append(call())
    except BaseException as error:
        errors.append(error)


def _close_at_barrier(runtime, request, entered, release, *, close_count=1):
    run_results: list[object] = []
    run_errors: list[BaseException] = []
    close_results: list[object] = []
    close_errors: list[BaseException] = []
    runner = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.run(request), run_results, run_errors
        )
    )
    runner.start()
    assert entered.wait(2)
    closers = [
        threading.Thread(
            target=lambda: _capture_call(runtime.close, close_results, close_errors)
        )
        for _index in range(close_count)
    ]
    for closer in closers:
        closer.start()
    assert runtime._active_cancel is not None
    assert runtime._active_cancel.wait(2)
    release.set()
    runner.join(2)
    for closer in closers:
        closer.join(2)
    assert not runner.is_alive()
    assert all(not closer.is_alive() for closer in closers)
    return run_results, run_errors, close_results, close_errors


def _assert_durable_close_cancel(runtime, run_errors, close_results, close_errors):
    assert len(run_errors) == 1
    assert type(run_errors[0]) is DomainError
    assert str(run_errors[0]) == "production job cancelled"
    assert run_errors[0].__cause__ is None
    assert run_errors[0].__context__ is None
    assert close_errors == []
    assert all(result is None for result in close_results)
    events = runtime._job_store.list_events(JobId("job"))
    assert sum(event.event_type is EventType.CANCEL_REQUESTED for event in events) == 1
    assert events[-1].event_type is EventType.CANCEL_REQUESTED
    assert all(event.event_type is not EventType.FATAL for event in events)
    assert runtime._job_store.load(JobId("job")).job.status is JobStatus.CANCELLED


def _cancel_running_job(runtime, request, entered, release, *, after_cancel=None):
    errors: list[BaseException] = []

    def run() -> None:
        try:
            runtime.run(request)
        except BaseException as error:
            errors.append(error)

    runner = threading.Thread(target=run)
    runner.start()
    assert entered.wait(2)
    cancel_error: BaseException | None = None
    state = None
    try:
        state = runtime.cancel(JobId("job"), reason="operator stop")
        if after_cancel is not None:
            after_cancel()
    except BaseException as error:
        cancel_error = error
    finally:
        release.set()
        runner.join(2)
    assert not runner.is_alive()
    if cancel_error is not None:
        raise cancel_error
    return state, errors


def _install_startup_barrier(
    runtime, monkeypatch, boundary, entered, release, cancelled, later_calls
) -> None:
    store = runtime._job_store
    original_append = store.append_event

    def tracked_append(job_id, event):
        if cancelled.is_set() and event.event_type is not EventType.CANCEL_REQUESTED:
            later_calls.append(event.event_type)
        result = original_append(job_id, event)
        if event.event_type.value == boundary:
            entered.set()
            assert release.wait(2)
        return result

    monkeypatch.setattr(store, "append_event", tracked_append)
    if boundary != "GENESIS":
        return
    original_save = store.save_snapshot

    def blocked_save(job_id, snapshot):
        original_save(job_id, snapshot)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(store, "save_snapshot", blocked_save)


def _assert_cancelled(runtime, state, errors, *, allow_verifier: bool = False) -> None:
    assert state.job.status is JobStatus.CANCELLED
    assert len(errors) == 1
    assert type(errors[0]) is production_service.DomainError
    assert str(errors[0]) == "production job cancelled"
    assert errors[0].__cause__ is None
    assert errors[0].__context__ is None
    assert _event_summary(runtime._job_store)[-1][0] == "CANCEL_REQUESTED"
    events = runtime._job_store.list_events(JobId("job"))
    assert all(event.event_type is not EventType.FATAL for event in events)
    if not allow_verifier:
        assert all(
            event.event_type is not EventType.VERIFIER_FINISHED for event in events
        )


def test_cancel_before_genesis_not_found_does_not_signal_or_fail_active_run(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = production_service._ProductionGenerationRuntime._prepare_initial_attempt
    results: list[object] = []
    errors: list[BaseException] = []

    def blocked_prepare(active_runtime, active_request):
        entered.set()
        assert release.wait(2)
        return original(active_runtime, active_request)

    monkeypatch.setattr(
        production_service._ProductionGenerationRuntime,
        "_prepare_initial_attempt",
        blocked_prepare,
    )
    runner = threading.Thread(
        target=lambda: _capture_call(lambda: runtime.run(request), results, errors)
    )
    runner.start()
    assert entered.wait(2)
    try:
        with pytest.raises(DomainError, match="^job not found$"):
            runtime.cancel(JobId("job"), reason="too early")
        assert runtime._active_cancel is not None
        signal_was_published = runtime._active_cancel.is_set()
    finally:
        release.set()
        runner.join(2)
    try:
        assert not signal_was_published
        assert not runner.is_alive()
        assert errors == []
        assert len(results) == 1
        assert runtime._job_store.load(JobId("job")).job.status is JobStatus.APPROVED
        assert all(
            event.event_type is not EventType.FATAL
            for event in runtime._job_store.list_events(JobId("job"))
        )
    finally:
        runtime.close()


def test_external_close_before_genesis_is_durable_and_wakes_all_waiters(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = production_service._ProductionGenerationRuntime._prepare_initial_attempt

    def blocked_prepare(active_runtime, active_request):
        entered.set()
        assert release.wait(2)
        return original(active_runtime, active_request)

    monkeypatch.setattr(
        production_service._ProductionGenerationRuntime,
        "_prepare_initial_attempt",
        blocked_prepare,
    )
    run_results, run_errors, close_results, close_errors = _close_at_barrier(
        runtime, request, entered, release, close_count=2
    )

    assert run_results == []
    assert len(close_results) == 2
    _assert_durable_close_cancel(runtime, run_errors, close_results, close_errors)
    assert factory.closed and runtime._loaded.closed


def test_external_close_racing_genesis_persists_one_cancel(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original_save = runtime._job_store.save_snapshot

    def blocked_save(job_id, snapshot):
        original_save(job_id, snapshot)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(runtime._job_store, "save_snapshot", blocked_save)
    run_results, run_errors, close_results, close_errors = _close_at_barrier(
        runtime, request, entered, release
    )

    assert run_results == []
    _assert_durable_close_cancel(runtime, run_errors, close_results, close_errors)


@pytest.mark.parametrize(
    "boundary",
    ("GENESIS", "JOB_STARTED", "SPEC_COMPILED", "ATTEMPT_STARTED"),
)
def test_cancel_at_startup_boundary_prevents_every_later_event_or_phase(
    tmp_path, monkeypatch, boundary
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    cancelled = threading.Event()
    later_calls: list[EventType] = []
    _install_startup_barrier(
        runtime,
        monkeypatch,
        boundary,
        entered,
        release,
        cancelled,
        later_calls,
    )
    try:
        state, errors = _cancel_running_job(
            runtime,
            request,
            entered,
            release,
            after_cancel=cancelled.set,
        )
        _assert_cancelled(runtime, state, errors)
        assert later_calls == []
    finally:
        release.set()
        runtime.close()


@pytest.mark.parametrize("phase", ("generation", "verification", "repair"))
def test_external_close_durably_cancels_each_active_phase(
    tmp_path, monkeypatch, phase
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    actions = (INCREASE_STYLE_SCALE,) if phase == "repair" else ()
    outcomes = {
        a0: {"STYLE_LOW": RuleStatus.FAIL if phase == "repair" else RuleStatus.PASS},
        a1: {"STYLE_LOW": RuleStatus.PASS},
    }
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path, monkeypatch, (_RuleSpec("STYLE_LOW", actions),), outcomes
    )
    entered, release = threading.Event(), threading.Event()
    generation_calls = 0
    original_verify = production_service._run_initial_verification

    def generation(*args):
        nonlocal generation_calls
        generation_calls += 1
        generation_request = next(
            item for item in args if type(item) is GenerationRequest
        )
        if phase == "generation" or (phase == "repair" and generation_calls == 2):
            entered.set()
            assert release.wait(2)
        return _artifact(generation_request)

    def verification(*args):
        report = original_verify(*args)
        if phase == "verification":
            entered.set()
            assert release.wait(2)
        return report

    monkeypatch.setattr(production_service, "_run_initial_generation", generation)
    monkeypatch.setattr(production_service, "_run_initial_verification", verification)
    run_results, run_errors, close_results, close_errors = _close_at_barrier(
        runtime, request, entered, release
    )

    assert run_results == []
    _assert_durable_close_cancel(runtime, run_errors, close_results, close_errors)


def test_external_close_after_final_checkpoint_finishes_durable_cancel(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    runtime_type = production_service._ProductionGenerationRuntime
    original_checkpoint = runtime_type._checkpoint
    original_begin = runtime_type._begin_close
    entered, release, close_started = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def blocked_checkpoint(active_runtime, job_id):
        original_checkpoint(active_runtime, job_id)
        caller = inspect.currentframe().f_back
        if caller is not None and caller.f_code.co_name == "run":
            entered.set()
            assert release.wait(2)

    def tracked_begin(active_runtime):
        result = original_begin(active_runtime)
        close_started.set()
        return result

    monkeypatch.setattr(runtime_type, "_checkpoint", blocked_checkpoint)
    monkeypatch.setattr(runtime_type, "_begin_close", tracked_begin)
    run_results: list[object] = []
    run_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    runner = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.run(request), run_results, run_errors
        )
    )
    closer = threading.Thread(
        target=lambda: _capture_call(runtime.close, [], close_errors)
    )
    runner.start()
    assert entered.wait(2)
    closer.start()
    assert close_started.wait(2)
    release.set()
    runner.join(2)
    closer.join(2)

    assert not runner.is_alive() and not closer.is_alive()
    assert len(run_results) == 1 and run_errors == [] and close_errors == []
    events = runtime._job_store.list_events(JobId("job"))
    assert sum(event.event_type is EventType.CANCEL_REQUESTED for event in events) == 1
    assert events[-1].event_type is EventType.CANCEL_REQUESTED
    assert runtime._job_store.load(JobId("job")).job.status is JobStatus.CANCELLED


def test_cancel_during_generation_is_durable_without_fatal(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()

    def blocked_generation(*args):
        generation_request = next(
            item for item in args if type(item) is GenerationRequest
        )
        entered.set()
        assert release.wait(2)
        return _artifact(generation_request)

    monkeypatch.setattr(
        production_service, "_run_initial_generation", blocked_generation
    )
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors)
        assert _event_summary(runtime._job_store)[-2:] == [
            ("ATTEMPT_STARTED", "SPEC_COMPILED", "GENERATING"),
            ("CANCEL_REQUESTED", "GENERATING", "CANCELLED"),
        ]
    finally:
        release.set()
        runtime.close()


def test_durable_cancel_wins_before_execution_event_is_published(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    generation_entered, release_generation = threading.Event(), threading.Event()
    signal_entered, release_signal = threading.Event(), threading.Event()
    run_results: list[object] = []
    run_errors: list[BaseException] = []
    cancel_results: list[object] = []
    cancel_errors: list[BaseException] = []

    def blocked_generation(*args):
        generation_request = next(
            item for item in args if type(item) is GenerationRequest
        )
        generation_entered.set()
        assert release_generation.wait(2)
        return _artifact(generation_request)

    monkeypatch.setattr(
        production_service, "_run_initial_generation", blocked_generation
    )
    runner = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.run(request), run_results, run_errors
        )
    )
    runner.start()
    assert generation_entered.wait(2)
    runtime_type = production_service._ProductionGenerationRuntime
    original_cancel_durable = runtime_type._cancel_durable

    def blocked_cancel_durable(active_runtime, *args):
        state = original_cancel_durable(active_runtime, *args)
        signal_entered.set()
        assert release_signal.wait(2)
        return state

    monkeypatch.setattr(runtime_type, "_cancel_durable", blocked_cancel_durable)
    canceller = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.cancel(JobId("job")), cancel_results, cancel_errors
        )
    )
    canceller.start()
    assert signal_entered.wait(2)
    checkpoint_results: list[object] = []
    checkpoint_errors: list[BaseException] = []
    _capture_call(
        lambda: runtime._checkpoint(JobId("job")),
        checkpoint_results,
        checkpoint_errors,
    )
    release_generation.set()
    runner.join(2)
    release_signal.set()
    canceller.join(2)
    try:
        assert not runner.is_alive() and not canceller.is_alive()
        assert checkpoint_results == []
        assert len(checkpoint_errors) == 1
        assert type(checkpoint_errors[0]) is DomainError
        assert str(checkpoint_errors[0]) == "production job cancelled"
        assert run_results == [] and len(run_errors) == 1
        assert str(run_errors[0]) == "production job cancelled"
        assert cancel_errors == []
        assert cancel_results[0].job.status is JobStatus.CANCELLED
        assert artifacts.repositories[0].puts == 0
        assert artifacts.repositories[0].reads == 0
    finally:
        release_generation.set()
        release_signal.set()
        runtime.close()


def test_cancel_hint_precedes_durable_append_without_claiming_early_win(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    generation_entered, release_generation = threading.Event(), threading.Event()
    append_entered, release_append = threading.Event(), threading.Event()
    run_results: list[object] = []
    run_errors: list[BaseException] = []
    cancel_results: list[object] = []
    cancel_errors: list[BaseException] = []

    def blocked_generation(*args):
        generation_request = next(
            item for item in args if type(item) is GenerationRequest
        )
        generation_entered.set()
        assert release_generation.wait(2)
        return _artifact(generation_request)

    monkeypatch.setattr(
        production_service, "_run_initial_generation", blocked_generation
    )
    runner = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.run(request), run_results, run_errors
        )
    )
    runner.start()
    assert generation_entered.wait(2)
    active_event = runtime._active_cancel
    assert active_event is not None
    original_append = runtime._job_store.append_event

    def blocked_append(job_id, event):
        if event.event_type is EventType.CANCEL_REQUESTED:
            append_entered.set()
            assert release_append.wait(2)
        return original_append(job_id, event)

    monkeypatch.setattr(runtime._job_store, "append_event", blocked_append)
    canceller = threading.Thread(
        target=lambda: _capture_call(
            lambda: runtime.cancel(JobId("job")), cancel_results, cancel_errors
        )
    )
    canceller.start()
    assert append_entered.wait(2)
    checkpoint_results: list[object] = []
    checkpoint_errors: list[BaseException] = []
    checkpoint_done = threading.Event()
    checkpoint = threading.Thread(
        target=lambda: (
            _capture_call(
                lambda: runtime._checkpoint(JobId("job")),
                checkpoint_results,
                checkpoint_errors,
            ),
            checkpoint_done.set(),
        )
    )
    checkpoint.start()
    assert not checkpoint_done.wait(0.1)
    hint_before_append = runtime._active_cancel_reason
    event_before_append = active_event.is_set()
    release_append.set()
    canceller.join(2)
    release_generation.set()
    runner.join(2)
    checkpoint.join(2)
    try:
        assert hint_before_append == "user requested"
        assert event_before_append is False
        assert checkpoint_results == [] and len(checkpoint_errors) == 1
        assert str(checkpoint_errors[0]) == "production job cancelled"
        assert not runner.is_alive() and not canceller.is_alive()
        assert not checkpoint.is_alive()
        assert run_results == [] and len(run_errors) == 1
        assert str(run_errors[0]) == "production job cancelled"
        assert cancel_errors == []
        assert cancel_results[0].job.status is JobStatus.CANCELLED
        assert artifacts.repositories[0].puts == 0
    finally:
        release_append.set()
        release_generation.set()
        runtime.close()


def test_cancel_after_artifact_put_prevents_attempt_finish(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = _TrackingRepository.put

    def blocked_put(repository, *args):
        original(repository, *args)
        if len(args) == 1:
            entered.set()
            assert release.wait(2)

    monkeypatch.setattr(_TrackingRepository, "put", blocked_put)
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors)
        assert artifacts.repositories[0].puts == 1
        assert artifacts.repositories[0].reads == 0
        assert all(
            event.event_type is not EventType.ATTEMPT_FINISHED
            for event in runtime._job_store.list_events(JobId("job"))
        )
    finally:
        release.set()
        runtime.close()


def test_cancel_before_verifier_lease_prevents_verification(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = production_service._record_attempt_finish

    def blocked_finish(*args):
        original(*args)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(production_service, "_record_attempt_finish", blocked_finish)
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors)
        assert factory.created[0][2].calls == 0
    finally:
        release.set()
        runtime.close()


def test_cancel_after_verify_prevents_report_and_repair(tmp_path, monkeypatch) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = production_service._run_initial_verification

    def blocked_verification(*args):
        report = original(*args)
        entered.set()
        assert release.wait(2)
        return report

    monkeypatch.setattr(
        production_service, "_run_initial_verification", blocked_verification
    )
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors)
        assert reports.repositories[0].puts == 0
        assert _event_summary(runtime._job_store)[-2:] == [
            ("ATTEMPT_FINISHED", "GENERATING", "VERIFYING"),
            ("CANCEL_REQUESTED", "VERIFYING", "CANCELLED"),
        ]
    finally:
        release.set()
        runtime.close()


def test_cancel_after_report_put_prevents_readback_and_initial_composition(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original_put = _TrackingRepository.put
    original_compose = production_service._compose_initial_repair
    compose_calls: list[object] = []

    def blocked_put(repository, *args):
        original_put(repository, *args)
        if len(args) == 2:
            entered.set()
            assert release.wait(2)

    def tracked_compose(*args):
        compose_calls.append(args)
        return original_compose(*args)

    monkeypatch.setattr(_TrackingRepository, "put", blocked_put)
    monkeypatch.setattr(production_service, "_compose_initial_repair", tracked_compose)
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors)
        assert reports.repositories[0].puts == 1
        assert reports.repositories[0].reads == 0
        assert compose_calls == []
    finally:
        release.set()
        runtime.close()


def test_cancel_in_repair_selecting_prevents_repair_step(tmp_path, monkeypatch) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    runtime, request, _factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,)),),
        {a0: {"STYLE_LOW": RuleStatus.FAIL}, a1: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original = production_service._ProductionGenerationRuntime._open_attempt
    original_step = production_service._ProductionGenerationRuntime._record_repair_step
    calls = 0
    step_calls: list[object] = []

    def blocked_open(active_runtime, *args):
        nonlocal calls
        resources = original(active_runtime, *args)
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(2)
        return resources

    monkeypatch.setattr(
        production_service._ProductionGenerationRuntime, "_open_attempt", blocked_open
    )

    def tracked_step(active_runtime, command):
        step_calls.append(command)
        return original_step(active_runtime, command)

    monkeypatch.setattr(
        production_service._ProductionGenerationRuntime,
        "_record_repair_step",
        tracked_step,
    )
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors, allow_verifier=True)
        assert all(
            event.event_type is not EventType.REPAIR_STEP
            for event in runtime._job_store.list_events(JobId("job"))
        )
        assert step_calls == []
        assert [repository.puts for repository in artifacts.repositories] == [1, 0]
        assert [repository.puts for repository in reports.repositories] == [1, 0]
    finally:
        release.set()
        runtime.close()


def test_cancel_after_selecting_append_prevents_child_open(
    tmp_path, monkeypatch
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,)),),
        {a0: {"STYLE_LOW": RuleStatus.FAIL}, a1: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    runtime_type = production_service._ProductionGenerationRuntime
    original_open = runtime_type._open_attempt
    original_decision = production_service._record_verifier_decision
    open_calls: list[object] = []

    def tracked_open(active_runtime, *args):
        open_calls.append(args)
        return original_open(active_runtime, *args)

    def blocked_decision(*args):
        result = original_decision(*args)
        if args[5] is JobStatus.REPAIR_SELECTING:
            entered.set()
            assert release.wait(2)
        return result

    monkeypatch.setattr(runtime_type, "_open_attempt", tracked_open)
    monkeypatch.setattr(
        production_service, "_record_verifier_decision", blocked_decision
    )
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors, allow_verifier=True)
        assert len(open_calls) == 1
    finally:
        release.set()
        runtime.close()


def test_cancel_in_repairing_prevents_child_artifact(tmp_path, monkeypatch) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    runtime, request, _factory, artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,)),),
        {a0: {"STYLE_LOW": RuleStatus.FAIL}, a1: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def blocked_child_generation(*args):
        nonlocal calls
        generation_request = next(
            item for item in args if type(item) is GenerationRequest
        )
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(2)
        return _artifact(generation_request)

    monkeypatch.setattr(
        production_service, "_run_initial_generation", blocked_child_generation
    )
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors, allow_verifier=True)
        assert len(artifacts.repositories) == 2
        assert artifacts.repositories[1].puts == 0
        assert [repository.puts for repository in reports.repositories] == [1, 0]
        assert _event_summary(runtime._job_store)[-2:] == [
            ("REPAIR_STEP", "REPAIR_SELECTING", "REPAIRING"),
            ("CANCEL_REQUESTED", "REPAIRING", "CANCELLED"),
        ]
    finally:
        release.set()
        runtime.close()


def test_cancel_after_child_composition_prevents_terminal_append(
    tmp_path, monkeypatch
) -> None:
    a0, a1 = "job-a0-xhs_grid-0", "job-a1-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", (INCREASE_STYLE_SCALE,)),),
        {a0: {"STYLE_LOW": RuleStatus.FAIL}, a1: {"STYLE_LOW": RuleStatus.PASS}},
    )
    entered, release = threading.Event(), threading.Event()
    original_compose = production_service._compose_repair_result
    runtime_type = production_service._ProductionGenerationRuntime
    original_terminal = runtime_type._record_terminal
    terminal_calls: list[object] = []

    def blocked_compose(*args):
        result = original_compose(*args)
        entered.set()
        assert release.wait(2)
        return result

    def tracked_terminal(active_runtime, *args):
        terminal_calls.append(args)
        return original_terminal(active_runtime, *args)

    monkeypatch.setattr(production_service, "_compose_repair_result", blocked_compose)
    monkeypatch.setattr(runtime_type, "_record_terminal", tracked_terminal)
    try:
        state, errors = _cancel_running_job(runtime, request, entered, release)
        _assert_cancelled(runtime, state, errors, allow_verifier=True)
        assert terminal_calls == []
    finally:
        release.set()
        runtime.close()


@pytest.mark.parametrize("structured", (True, False))
def test_only_structured_gpu_oom_quarantines_runtime(
    tmp_path, monkeypatch, structured: bool
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    loaded = runtime._loaded
    oom_type = getattr(
        importlib.import_module("specstyle.errors"), "_GpuOutOfMemoryError"
    )
    failure = (
        oom_type("generation OOM")
        if structured
        else production_service.InfrastructureError("generation OOM")
    )
    calls = 0

    def fail_generation(*_args):
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(production_service, "_run_initial_generation", fail_generation)
    try:
        with pytest.raises(type(failure)) as raised:
            runtime.run(request)
        assert raised.value is failure
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        event = runtime._job_store.list_events(JobId("job"))[-1]
        assert event.event_type is EventType.FATAL
        assert event.payload.error_family == (
            "GENERATION_OOM" if structured else "GENERATION_FAILED"
        )
        if structured:
            assert runtime.readiness.value == "QUARANTINED"
            assert runtime.failure_kind.value == "GPU_OOM"
            assert factory.closed and loaded.closed
            before = runtime._job_store.list_events(JobId("job"))
            with pytest.raises(
                production_service.InfrastructureError,
                match="^production runtime quarantined$",
            ):
                runtime.run(request)
            assert runtime._job_store.list_events(JobId("job")) == before
            assert calls == 1
        else:
            assert runtime.readiness.value == "READY"
            assert runtime.failure_kind is None
            assert not factory.closed and not loaded.closed
    finally:
        runtime.close()


def test_durable_cancelled_job_keeps_cancelled_state_but_oom_wins_caller(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    oom_type = getattr(
        importlib.import_module("specstyle.errors"), "_GpuOutOfMemoryError"
    )
    failure = oom_type("generation OOM")
    entered, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def fail_generation(*_args):
        entered.set()
        assert release.wait(2)
        raise failure

    monkeypatch.setattr(production_service, "_run_initial_generation", fail_generation)

    def run() -> None:
        try:
            runtime.run(request)
        except BaseException as error:
            errors.append(error)

    runner = threading.Thread(target=run)
    runner.start()
    assert entered.wait(2)
    try:
        state = runtime.cancel(JobId("job"), reason="operator stop")
        release.set()
        runner.join(2)
        assert not runner.is_alive()
        assert state.job.status is JobStatus.CANCELLED
        assert errors == [failure]
        assert runtime.readiness.value == "QUARANTINED"
        assert runtime.failure_kind.value == "GPU_OOM"
        events = runtime._job_store.list_events(JobId("job"))
        assert events[-1].event_type is EventType.CANCEL_REQUESTED
        assert all(event.event_type is not EventType.FATAL for event in events)
    finally:
        release.set()
        runtime.close()


def test_verification_oom_quarantines_with_generation_oom_family(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, _factory, _artifacts, reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )
    oom_type = getattr(
        importlib.import_module("specstyle.errors"), "_GpuOutOfMemoryError"
    )
    failure = oom_type("verification OOM")
    monkeypatch.setattr(
        production_service,
        "_run_initial_verification",
        lambda *_args: (_ for _ in ()).throw(failure),
    )
    try:
        with pytest.raises(oom_type) as raised:
            runtime.run(request)
        assert raised.value is failure
        assert runtime.readiness.value == "QUARANTINED"
        assert runtime.failure_kind.value == "GPU_OOM"
        assert reports.repositories[0].puts == 0
        event = runtime._job_store.list_events(JobId("job"))[-1]
        assert (event.event_type, event.from_state, event.to_state) == (
            EventType.FATAL,
            JobStatus.VERIFYING,
            JobStatus.JOB_FAILED,
        )
        assert event.payload.error_family == "GENERATION_OOM"
    finally:
        runtime.close()


@pytest.mark.parametrize("real_oom", (True, False))
def test_end_to_end_runtime_quarantines_only_registered_torch_oom(
    tmp_path, monkeypatch, real_oom: bool
) -> None:
    from tests.integration.test_production_generation_slice import (
        _Pipeline,
        _open_clock_case,
    )

    runtime, supply, store, request, observed = _open_clock_case(
        tmp_path,
        monkeypatch,
        tuple(f"2026-08-02T00:00:00.{index:03d}Z" for index in range(10)),
        failure="oom" if real_oom else None,
    )
    if not real_oom:

        class OutOfMemoryError(Exception):
            pass

        monkeypatch.setattr(
            _Pipeline,
            "__call__",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OutOfMemoryError("same fake class name")
            ),
        )
    errors = importlib.import_module("specstyle.errors")
    oom_type = getattr(errors, "_GpuOutOfMemoryError")
    expected_type = oom_type if real_oom else production_service.InfrastructureError
    try:
        with pytest.raises(expected_type) as raised:
            runtime.run(request)
        assert raised.value is observed["error"]
        assert type(raised.value) is expected_type
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        event = store.list_events(request.job_id)[-1]
        assert event.event_type is EventType.FATAL
        assert event.payload.error_family == (
            "GENERATION_OOM" if real_oom else "GENERATION_FAILED"
        )
        assert runtime.readiness.value == ("QUARANTINED" if real_oom else "READY")
        assert (
            runtime.failure_kind.value if runtime.failure_kind is not None else None
        ) == ("GPU_OOM" if real_oom else None)
    finally:
        runtime.close()
        supply.close()


def test_oom_quarantine_cleanup_failures_never_replace_primary_oom(
    tmp_path, monkeypatch
) -> None:
    attempt = "job-a0-xhs_grid-0"
    runtime, request, original_factory, _artifacts, _reports = _runtime(
        tmp_path,
        monkeypatch,
        (_RuleSpec("STYLE_LOW", ()),),
        {attempt: {"STYLE_LOW": RuleStatus.PASS}},
    )

    class FailingFactory(_Factory):
        def close(self) -> None:
            if self.closed:
                return
            self.closed = True
            raise production_service.InfrastructureError("factory cleanup failed")

    class FailingLoaded(_Loaded):
        def close(self) -> None:
            if self.closed:
                return
            self.closed = True
            raise production_service.InfrastructureError("loaded cleanup failed")

    factory = FailingFactory(original_factory.outcomes)
    loaded = FailingLoaded()
    runtime._verifier_factory = factory
    runtime._loaded = loaded
    oom_type = getattr(
        importlib.import_module("specstyle.errors"), "_GpuOutOfMemoryError"
    )
    primary = oom_type("generation OOM")
    monkeypatch.setattr(
        production_service,
        "_run_initial_generation",
        lambda *_args: (_ for _ in ()).throw(primary),
    )
    try:
        with pytest.raises(oom_type) as raised:
            runtime.run(request)
        assert raised.value is primary
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert factory.closed and loaded.closed
        assert runtime.readiness.value == "QUARANTINED"
    finally:
        try:
            runtime.close()
        except production_service.InfrastructureError:
            pass
