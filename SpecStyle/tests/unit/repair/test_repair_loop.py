"""REP-003 pure repair-loop contract tests."""

import inspect
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
import specstyle.repair.loop as repair_loop
import specstyle.repair.history as repair_history
import specstyle.generation.requests as generation_requests

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RepairStopReason, RuleLevel, RuleScope, RuleStatus
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    DecisionId,
    RuleId,
    Sha256,
)
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.protocols import run_generation
from specstyle.repair.actions import INCREASE_STYLE_SCALE
from specstyle.errors import DomainError
from specstyle.repair.history import (
    RepairHistory,
    start_repair_history,
)
from specstyle.repair.loop import (
    NextGeneration,
    RepairTerminal,
    consume_repair_result,
    next_repair_step,
)
from specstyle.verification.rule_models import RuleResult, VerificationReport
from tests.unit.repair.test_actions import _repair_request


class _AlwaysEqualText(str):
    def __eq__(self, other: object) -> bool:
        return True


class _ExplodingText(str):
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("exploding equality")


class _AlwaysEqualFloat(float):
    def __eq__(self, other: object) -> bool:
        return True


def _request_with_action() -> object:
    request = _repair_request()
    base_plan = request.compiled_spec.verification_plans[0]
    rule = replace(
        base_plan.rules[-1],
        definition=replace(
            base_plan.rules[-1].definition,
            rule_id=RuleId("STYLE_LOW"),
            level=RuleLevel.L2,
            scope=RuleScope.ITEM,
            required=True,
        ),
        priority=0,
        affected_by_actions=(INCREASE_STYLE_SCALE,),
    )
    plan = replace(base_plan, rules=(rule,))
    return replace(
        request,
        compiled_spec=replace(request.compiled_spec, verification_plans=(plan,)),
    )


def _report(
    artifact: object, request: object, status: RuleStatus
) -> VerificationReport:
    plan = request.compiled_spec.verification_plans[0]
    return VerificationReport(
        (ArtifactRef(artifact.ref.artifact_id, artifact.ref.sha256),),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(rule.rule_id, status, (artifact.ref.artifact_id,), None)
            for rule in plan.applicable_rule_definitions
        ),
    )


def _action_history() -> tuple[RepairHistory, FakeBackend]:
    request = _request_with_action()
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    report = _report(artifact, request, RuleStatus.FAIL)
    return start_repair_history(request, artifact, report), backend


def _with_policy(request: object, max_rounds: int, no_improvement_limit: int) -> object:
    repair = request.compiled_spec.source_spec.repair.model_copy(
        update={
            "max_rounds": max_rounds,
            "stop_after_no_improvement": no_improvement_limit,
        }
    )
    return replace(
        request,
        compiled_spec=replace(
            request.compiled_spec,
            source_spec=request.compiled_spec.source_spec.model_copy(
                update={"repair": repair}
            ),
        ),
    )


def _report_with_statuses(
    artifact: object, request: object, statuses: dict[str, RuleStatus]
) -> VerificationReport:
    plan = request.compiled_spec.verification_plans[0]
    return VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(
                rule.rule_id,
                statuses.get(rule.rule_id.value, RuleStatus.PASS),
                (artifact.ref.artifact_id,),
                None,
            )
            for rule in plan.applicable_rule_definitions
        ),
    )


def _two_rule_request(max_rounds: int, no_improvement_limit: int) -> object:
    request = _with_policy(_request_with_action(), max_rounds, no_improvement_limit)
    plan = request.compiled_spec.verification_plans[0]
    later = replace(
        plan.rules[0],
        definition=replace(plan.rules[0].definition, rule_id=RuleId("LATER")),
        priority=1,
        affected_by_actions=(),
    )
    return replace(
        request,
        compiled_spec=replace(
            request.compiled_spec,
            verification_plans=(replace(plan, rules=(plan.rules[0], later)),),
        ),
    )


def _observe(
    history: RepairHistory,
    backend: FakeBackend,
    decision: str,
    attempt: str,
    statuses: dict[str, RuleStatus],
) -> RepairHistory:
    command = next_repair_step(history, DecisionId(decision), AttemptId(attempt))
    assert type(command) is NextGeneration
    artifact = run_generation(backend, command.request)
    return consume_repair_result(
        history,
        command,
        artifact,
        _report_with_statuses(artifact, command.request, statuses),
    )


def test_loop_returns_a_terminal_for_an_approved_initial_observation() -> None:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, RuleStatus.PASS)
    )

    step = next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))

    assert type(step) is RepairTerminal
    assert (
        step.artifact_decision.repair_stop_reason is RepairStopReason.PASS_ALL_REQUIRED
    )
    assert step.no_action is None
    assert (
        tuple(inspect.signature(next_repair_step).parameters)[-1] == "next_attempt_id"
    )


def test_next_command_consumes_ids_and_observation_replays_provenance() -> None:
    history, backend = _action_history()

    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))

    assert type(command) is NextGeneration
    artifact = run_generation(backend, command.request)
    observed = consume_repair_result(
        history, command, artifact, _report(artifact, command.request, RuleStatus.PASS)
    )
    assert observed.rounds == 1
    assert observed.consecutive_no_improvement == 0
    assert len(observed.seen_state_keys) == 2
    terminal = next_repair_step(observed, DecisionId("unused"), AttemptId("unused2"))
    assert type(terminal) is RepairTerminal
    assert (
        terminal.artifact_decision.repair_stop_reason
        is RepairStopReason.PASS_ALL_REQUIRED
    )


def test_false_improvement_is_audited_before_no_improvement_terminal() -> None:
    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    artifact = run_generation(backend, command.request)
    observed = consume_repair_result(
        history, command, artifact, _report(artifact, command.request, RuleStatus.FAIL)
    )

    assert observed.rounds == 1
    assert observed.consecutive_no_improvement == 1
    terminal = next_repair_step(observed, DecisionId("unused"), AttemptId("unused2"))
    assert type(terminal) is RepairTerminal
    assert (
        terminal.artifact_decision.repair_stop_reason is RepairStopReason.NO_IMPROVEMENT
    )


def test_improved_but_still_failing_last_budget_round_stops_at_max_rounds() -> None:
    request = _request_with_action()
    plan = request.compiled_spec.verification_plans[0]
    later = replace(
        plan.rules[0],
        definition=replace(plan.rules[0].definition, rule_id=RuleId("LATER")),
        priority=1,
        affected_by_actions=(),
    )
    request = replace(
        request,
        compiled_spec=replace(
            request.compiled_spec,
            verification_plans=(replace(plan, rules=(plan.rules[0], later)),),
        ),
    )
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    rules = request.compiled_spec.verification_plans[0].applicable_rule_definitions
    report = VerificationReport(
        (artifact.ref,),
        rules,
        (
            RuleResult(
                RuleId("STYLE_LOW"), RuleStatus.FAIL, (artifact.ref.artifact_id,), None
            ),
            RuleResult(
                RuleId("LATER"), RuleStatus.FAIL, (artifact.ref.artifact_id,), None
            ),
        ),
    )
    history = start_repair_history(request, artifact, report)
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    child_report = VerificationReport(
        (child.ref,),
        rules,
        (
            RuleResult(
                RuleId("STYLE_LOW"), RuleStatus.PASS, (child.ref.artifact_id,), None
            ),
            RuleResult(
                RuleId("LATER"), RuleStatus.FAIL, (child.ref.artifact_id,), None
            ),
        ),
    )

    observed = consume_repair_result(history, command, child, child_report)
    terminal = next_repair_step(observed, DecisionId("unused"), AttemptId("unused2"))

    assert type(terminal) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is RepairStopReason.MAX_ROUNDS


def test_consume_preserves_cohort_order_except_for_the_target_slot() -> None:
    history, backend = _action_history()
    sibling = ArtifactRef(ArtifactId("sibling"), Sha256("f" * 64))
    request = history.current_request
    rule = request.compiled_spec.verification_plans[0].applicable_rule_definitions[0]
    initial_report = VerificationReport(
        (history.current_artifact.ref, sibling),
        (rule,),
        (
            RuleResult(
                rule.rule_id,
                RuleStatus.FAIL,
                (history.current_artifact.ref.artifact_id,),
                None,
            ),
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
        ),
    )
    history = start_repair_history(request, history.current_artifact, initial_report)
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    valid = VerificationReport(
        (child.ref, sibling),
        (rule,),
        (
            RuleResult(rule.rule_id, RuleStatus.PASS, (child.ref.artifact_id,), None),
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
        ),
    )

    observed = consume_repair_result(history, command, child, valid)

    assert observed.current_report.artifacts == (child.ref, sibling)
    reordered = VerificationReport(
        (sibling, child.ref),
        (rule,),
        (
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
            RuleResult(rule.rule_id, RuleStatus.PASS, (child.ref.artifact_id,), None),
        ),
    )
    with pytest.raises(Exception, match="invalid repair observation"):
        consume_repair_result(history, command, child, reordered)


def test_no_action_audits_only_decision_id_and_does_not_change_history() -> None:
    request = _repair_request()
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, RuleStatus.FAIL)
    )

    terminal = next_repair_step(
        history, DecisionId("audit"), history.initial_attempt.request.attempt_id
    )

    assert type(terminal) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is RepairStopReason.NO_ACTION
    assert terminal.no_action is not None
    assert terminal.no_action.decision_id == DecisionId("audit")
    assert history.rounds == 0


@pytest.mark.parametrize(
    ("status", "stop"),
    (
        (RuleStatus.UNVERIFIABLE, RepairStopReason.UNVERIFIABLE),
        (RuleStatus.WARNING, RepairStopReason.MANUAL_REQUEST),
    ),
)
def test_terminal_priority_routes_unverifiable_and_manual_before_repair(
    status: RuleStatus, stop: RepairStopReason
) -> None:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, status)
    )

    terminal = next_repair_step(history, DecisionId("unused"), AttemptId("unused2"))

    assert type(terminal) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is stop


def test_terminal_is_always_constructed_by_routing_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, RuleStatus.PASS)
    )
    calls: list[RepairStopReason | None] = []
    routed = repair_loop.decide_artifact

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(kwargs.get("repair_stop_reason"))
        return routed(*args, **kwargs)

    monkeypatch.setattr(repair_loop, "decide_artifact", spy)
    terminal = next_repair_step(history, DecisionId("unused"), AttemptId("unused2"))

    assert type(terminal) is RepairTerminal
    assert calls[-1] is RepairStopReason.PASS_ALL_REQUIRED


def test_forged_derived_state_is_rejected_at_the_next_public_boundary() -> None:
    history, _ = _action_history()
    object.__setattr__(history, "seen_state_keys", ())

    with pytest.raises(Exception, match="invalid repair transition"):
        next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))


@pytest.mark.parametrize(
    "seen",
    (
        lambda history: ([history.current_request.execution_parameters, 0],),
        lambda history: ((SimpleNamespace(), 0),),
        lambda history: ((history.current_request.execution_parameters, True),),
        lambda history: ((history.current_request.execution_parameters,),),
    ),
)
def test_cached_seen_state_requires_exact_state_key_shape(seen: object) -> None:
    history, _ = _action_history()
    object.__setattr__(history, "seen_state_keys", seen(history))

    with pytest.raises(Exception, match="invalid repair transition"):
        next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))


def test_consume_rejects_namespace_that_imitates_next_generation() -> None:
    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    artifact = run_generation(backend, command.request)
    forged = SimpleNamespace(decision=command.decision, request=command.request)

    with pytest.raises(Exception, match="invalid repair observation"):
        consume_repair_result(
            history,
            forged,  # type: ignore[arg-type]
            artifact,
            _report(artifact, command.request, RuleStatus.PASS),
        )


def test_consume_rejects_environment_change_even_when_request_digests_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = Sha256("0" * 64)
    monkeypatch.setattr(generation_requests, "_hash", lambda *_: fixed)
    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    changed_request = replace(command.request, environment_hash=Sha256("e" * 64))
    changed = NextGeneration(command.decision, changed_request)
    artifact = run_generation(backend, changed.request)

    with pytest.raises(Exception, match="invalid repair observation"):
        consume_repair_result(
            history,
            changed,
            artifact,
            _report(artifact, changed.request, RuleStatus.PASS),
        )


def test_terminal_rejects_namespace_that_imitates_no_action() -> None:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, RuleStatus.FAIL)
    )
    terminal = next_repair_step(history, DecisionId("audit"), AttemptId("unused"))
    assert type(terminal) is RepairTerminal and terminal.no_action is not None
    forged = SimpleNamespace(
        decision_id=terminal.no_action.decision_id,
        blocked_rule_ids=terminal.no_action.blocked_rule_ids,
        blocked_action_ids=terminal.no_action.blocked_action_ids,
    )

    with pytest.raises(Exception, match="invalid repair terminal"):
        RepairTerminal(terminal.artifact_decision, forged)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda no_action: object.__setattr__(
            no_action.decision_id, "value", _AlwaysEqualText("forged")
        ),
        lambda no_action: object.__setattr__(
            no_action, "blocked_rule_ids", (_ExplodingText("rule"),)
        ),
        lambda no_action: object.__setattr__(
            no_action, "blocked_action_ids", (SimpleNamespace(value="action"),)
        ),
        lambda no_action: object.__setattr__(no_action, "stop_reason", object()),
    ),
)
def test_terminal_rejects_forged_nested_no_action(mutate: object) -> None:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report(artifact, request, RuleStatus.FAIL)
    )
    terminal = next_repair_step(history, DecisionId("audit"), AttemptId("unused"))
    assert type(terminal) is RepairTerminal and terminal.no_action is not None
    mutate(terminal.no_action)  # type: ignore[operator]

    with pytest.raises(Exception, match="invalid repair terminal"):
        RepairTerminal(terminal.artifact_decision, terminal.no_action)


@pytest.mark.parametrize(
    ("function", "args", "message"),
    (
        (
            next_repair_step,
            (object(), DecisionId("d"), AttemptId("a")),
            "invalid repair transition",
        ),
        (
            consume_repair_result,
            (object(), object(), object(), object()),
            "invalid repair observation",
        ),
    ),
)
def test_public_loop_boundaries_normalize_invalid_observations(
    function: object, args: tuple[object, ...], message: str
) -> None:
    with pytest.raises(Exception, match=message):
        function(*args)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (lambda: RepairHistory(object()), "invalid repair history"),
        (lambda: NextGeneration(object(), object()), "invalid next generation"),
        (lambda: RepairTerminal(object(), None), "invalid repair terminal"),
    ),
)
def test_loop_value_objects_have_fixed_errors_without_causes(
    factory: object, message: str
) -> None:
    with pytest.raises(DomainError, match=f"^{message}$") as error:
        factory()  # type: ignore[operator]
    assert error.value.__cause__ is None


def test_loop_value_objects_are_slotted_frozen_and_have_exact_public_fields() -> None:
    history, _ = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    assert tuple(field.name for field in fields(NextGeneration)) == (
        "decision",
        "request",
    )
    assert tuple(field.name for field in fields(RepairTerminal)) == (
        "artifact_decision",
        "no_action",
    )
    assert not hasattr(command, "__dict__")
    with pytest.raises(Exception):
        command.decision = command.decision  # type: ignore[misc]


@pytest.mark.parametrize("exception", (KeyboardInterrupt, SystemExit))
def test_public_boundaries_do_not_normalize_base_exceptions(
    monkeypatch: pytest.MonkeyPatch, exception: type[BaseException]
) -> None:
    request, artifact, report = _initial_for_base_exception()
    history, backend = _action_history()

    def fail(*_: object) -> object:
        raise exception()

    monkeypatch.setattr(repair_history, "_trusted_request", fail)
    with pytest.raises(exception):
        start_repair_history(request, artifact, report)
    monkeypatch.undo()
    monkeypatch.setattr(repair_loop, "_trusted_history", fail)
    with pytest.raises(exception):
        next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))
    monkeypatch.undo()
    command = next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    monkeypatch.setattr(repair_loop, "_trusted_history", fail)
    with pytest.raises(exception):
        consume_repair_result(
            history, command, child, _report(child, command.request, RuleStatus.PASS)
        )


def _initial_for_base_exception() -> tuple[object, object, object]:
    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    return request, artifact, _report(artifact, request, RuleStatus.FAIL)


@pytest.mark.parametrize(
    "message", ("invalid repair transition", "invalid repair observation")
)
def test_public_loop_errors_have_no_cause(message: str) -> None:
    with pytest.raises(DomainError, match=f"^{message}$") as error:
        if message == "invalid repair transition":
            next_repair_step(object(), DecisionId("d"), AttemptId("a"))
        else:
            consume_repair_result(object(), object(), object(), object())
    assert error.value.__cause__ is None


def test_next_generation_rejects_hostile_nested_request_primitives() -> None:
    history, _ = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    object.__setattr__(command.request.attempt_id, "value", _ExplodingText("child"))

    with pytest.raises(DomainError, match="^invalid next generation$") as error:
        NextGeneration(command.decision, command.request)

    assert error.value.__cause__ is None


def _history_for_terminal(stop: RepairStopReason) -> RepairHistory:
    if stop is RepairStopReason.PASS_ALL_REQUIRED:
        request = _repair_request()
        artifact = run_generation(FakeBackend(), request)
        return start_repair_history(
            request, artifact, _report(artifact, request, RuleStatus.PASS)
        )
    if stop is RepairStopReason.UNVERIFIABLE:
        request = _repair_request()
        artifact = run_generation(FakeBackend(), request)
        return start_repair_history(
            request, artifact, _report(artifact, request, RuleStatus.UNVERIFIABLE)
        )
    if stop is RepairStopReason.MANUAL_REQUEST:
        request = _repair_request()
        artifact = run_generation(FakeBackend(), request)
        return start_repair_history(
            request, artifact, _report(artifact, request, RuleStatus.WARNING)
        )
    if stop is RepairStopReason.NO_ACTION:
        request = _repair_request()
        artifact = run_generation(FakeBackend(), request)
        return start_repair_history(
            request, artifact, _report(artifact, request, RuleStatus.FAIL)
        )
    if stop is RepairStopReason.NO_IMPROVEMENT:
        history, backend = _action_history()
        return _observe(
            history, backend, "decision1", "attempt2", {"STYLE_LOW": RuleStatus.FAIL}
        )
    request = _two_rule_request(1, 1)
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    history = start_repair_history(
        request,
        artifact,
        _report_with_statuses(
            artifact,
            request,
            {"STYLE_LOW": RuleStatus.FAIL, "LATER": RuleStatus.FAIL},
        ),
    )
    return _observe(
        history,
        backend,
        "decision1",
        "attempt2",
        {"STYLE_LOW": RuleStatus.PASS, "LATER": RuleStatus.FAIL},
    )


@pytest.mark.parametrize("stop", tuple(RepairStopReason))
def test_each_terminal_uses_routing_with_its_real_stop_reason(
    monkeypatch: pytest.MonkeyPatch, stop: RepairStopReason
) -> None:
    history = _history_for_terminal(stop)
    calls: list[RepairStopReason | None] = []
    routed = repair_loop.decide_artifact

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(kwargs.get("repair_stop_reason"))
        return routed(*args, **kwargs)

    monkeypatch.setattr(repair_loop, "decide_artifact", spy)
    terminal = next_repair_step(history, DecisionId("terminal"), AttemptId("attempt"))
    repeated = next_repair_step(history, DecisionId("terminal"), AttemptId("attempt"))

    assert type(terminal) is RepairTerminal
    assert type(repeated) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is stop
    assert calls[-1] is stop


@pytest.mark.parametrize(
    ("child_status", "expected"),
    (
        (RuleStatus.PASS, RepairStopReason.PASS_ALL_REQUIRED),
        (RuleStatus.UNVERIFIABLE, RepairStopReason.UNVERIFIABLE),
        (RuleStatus.WARNING, RepairStopReason.MANUAL_REQUEST),
        (RuleStatus.FAIL, RepairStopReason.NO_IMPROVEMENT),
    ),
)
def test_stop_priority_uses_real_reports_when_multiple_terminal_conditions_hold(
    child_status: RuleStatus, expected: RepairStopReason
) -> None:
    request = _two_rule_request(1, 1)
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    history = start_repair_history(
        request,
        artifact,
        _report_with_statuses(
            artifact,
            request,
            {"STYLE_LOW": RuleStatus.FAIL, "LATER": RuleStatus.FAIL},
        ),
    )
    observed = _observe(
        history,
        backend,
        "decision1",
        "attempt2",
        {"STYLE_LOW": child_status, "LATER": child_status},
    )

    terminal = next_repair_step(observed, DecisionId("terminal"), AttemptId("attempt3"))

    assert observed.rounds == 1
    assert type(terminal) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is expected


def test_public_functions_are_positional_only_and_keep_arity_type_errors() -> None:
    request, artifact, report = _initial_for_base_exception()
    history = start_repair_history(request, artifact, report)
    command = next_repair_step(history, DecisionId("audit"), AttemptId("attempt2"))

    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        for function in (start_repair_history, next_repair_step, consume_repair_result)
        for parameter in inspect.signature(function).parameters.values()
    )
    with pytest.raises(TypeError):
        start_repair_history(request=request, artifact=artifact, report=report)
    with pytest.raises(TypeError):
        next_repair_step(
            history=history, decision_id=DecisionId("d"), next_attempt_id=AttemptId("a")
        )
    with pytest.raises(TypeError):
        consume_repair_result(history, command, artifact)  # type: ignore[call-arg]
