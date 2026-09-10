"""REP-003 repair history contract tests."""

from dataclasses import FrozenInstanceError, fields, replace
from types import SimpleNamespace

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RepairStopReason, RuleStatus
from specstyle.domain.identifiers import ArtifactId, AttemptId, DecisionId, Sha256
from specstyle.errors import DomainError
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.protocols import GeneratedArtifact, run_generation
from specstyle.generation.requests import GenerationParameters
from specstyle.repair.history import (
    InitialAttempt,
    RepairAttempt,
    RepairHistory,
    start_repair_history,
)
from specstyle.verification.rule_models import RuleResult, VerificationReport
from tests.unit.repair.test_actions import _repair_request


class _HostileText(str):
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("hostile equality")


class _AlwaysEqualText(str):
    def __eq__(self, other: object) -> bool:
        return True


class _ExplodingText(str):
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("exploding equality")


class _AlwaysEqualFloat(float):
    def __eq__(self, other: object) -> bool:
        return True


def _initial(*, variation_index: int = 0) -> tuple[object, object, object]:
    request = _repair_request(variation_index=variation_index)
    artifact = run_generation(FakeBackend(), request)
    plan = request.compiled_spec.verification_plans[0]
    report = VerificationReport(
        (ArtifactRef(artifact.ref.artifact_id, artifact.ref.sha256),),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.FAIL, (artifact.ref.artifact_id,), None)
            for rule in plan.applicable_rule_definitions
        ),
    )
    return request, artifact, report


def test_history_starts_with_a_frozen_exact_initial_attempt() -> None:
    request, artifact, report = _initial()

    history = start_repair_history(request, artifact, report)

    assert type(history) is RepairHistory
    assert history.rounds == 0
    assert history.current_target_artifact_id == artifact.ref.artifact_id
    assert tuple(field.name for field in fields(InitialAttempt)) == (
        "request",
        "artifact",
        "report",
    )
    assert not hasattr(history, "__dict__")
    assert tuple(field.name for field in fields(RepairAttempt)) == (
        "parent_report",
        "decision",
        "request",
        "artifact",
        "report",
    )
    assert tuple(field.name for field in fields(RepairHistory)) == (
        "initial_attempt",
        "repair_attempts",
        "rounds",
        "consecutive_no_improvement",
        "seen_state_keys",
    )
    with pytest.raises(FrozenInstanceError):
        history.rounds = 2  # type: ignore[misc]


def test_history_accepts_a_nonzero_initial_variation_and_derived_seed() -> None:
    request, artifact, report = _initial(variation_index=7)

    history = start_repair_history(request, artifact, report)

    assert history.current_request.variation_index == 7
    assert history.current_request.seed == request.seed
    assert history.current_request.seed != _repair_request().seed


@pytest.mark.parametrize("replacement", (ArtifactId("other"), "forged"))
def test_initial_history_rejects_invalid_artifact_members(replacement: object) -> None:
    request, artifact, report = _initial()
    object.__setattr__(artifact.ref, "artifact_id", replacement)

    with pytest.raises(Exception, match="invalid repair history"):
        start_repair_history(request, artifact, report)


def test_history_normalizes_hostile_nested_primitives_to_a_fixed_error() -> None:
    request, artifact, report = _initial()
    object.__setattr__(artifact.ref.artifact_id, "value", _HostileText("artifact"))

    with pytest.raises(Exception, match="invalid repair history"):
        start_repair_history(request, artifact, report)


def test_initial_attempt_rejects_forged_nested_policy_text() -> None:
    request, artifact, report = _initial()
    object.__setattr__(
        request.compiled_spec.source_spec.repair,
        "policy_version",
        _AlwaysEqualText("1.0"),
    )

    with pytest.raises(Exception, match="invalid repair history"):
        start_repair_history(request, artifact, report)


def test_history_rejects_namespace_that_imitates_repair_attempt() -> None:
    from tests.unit.repair.test_repair_loop import _action_history, _report
    from specstyle.domain.identifiers import AttemptId, DecisionId
    from specstyle.domain.enums import RuleStatus
    from specstyle.repair.loop import next_repair_step
    from specstyle.generation.protocols import run_generation

    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    artifact = run_generation(backend, command.request)
    report = _report(artifact, command.request, RuleStatus.PASS)
    forged = SimpleNamespace(
        parent_report=history.current_report,
        decision=command.decision,
        request=command.request,
        artifact=artifact,
        report=report,
    )

    with pytest.raises(Exception, match="invalid repair history"):
        RepairHistory(history.initial_attempt, (forged,))  # type: ignore[arg-type]


def test_history_accepts_a_legal_item_result_permutation_in_parent_report() -> None:
    from specstyle.repair.loop import next_repair_step
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    sibling = ArtifactRef(ArtifactId("sibling"), Sha256("f" * 64))
    rule = history.current_report.rules[0]
    parent = VerificationReport(
        (history.current_artifact.ref, sibling),
        (rule,),
        (
            RuleResult(
                rule.rule_id,
                RuleStatus.FAIL,
                (history.current_target_artifact_id,),
                None,
            ),
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
        ),
    )
    history = start_repair_history(
        history.current_request, history.current_artifact, parent
    )
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    child = run_generation(backend, command.request)
    report = VerificationReport(
        (child.ref, sibling),
        (rule,),
        (
            RuleResult(rule.rule_id, RuleStatus.PASS, (child.ref.artifact_id,), None),
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
        ),
    )
    permuted_parent = VerificationReport(
        parent.artifacts, parent.rules, tuple(reversed(parent.results))
    )

    rebuilt = RepairHistory(
        history.initial_attempt,
        (
            RepairAttempt(
                permuted_parent, command.decision, command.request, child, report
            ),
        ),
    )

    assert rebuilt.current_report == report


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (
            lambda: InitialAttempt(object(), object(), object()),
            "invalid initial repair attempt",
        ),
        (
            lambda: RepairAttempt(object(), object(), object(), object(), object()),
            "invalid repair attempt",
        ),
    ),
)
def test_history_attempt_value_objects_have_fixed_errors_without_causes(
    factory: object, message: str
) -> None:
    with pytest.raises(DomainError, match=f"^{message}$") as error:
        factory()  # type: ignore[operator]
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda request: object.__setattr__(
            request.attempt_id, "value", _HostileText("attempt")
        ),
        lambda request: object.__setattr__(
            request.execution_parameters, "ip_adapter_scale", _AlwaysEqualText("0.8")
        ),
    ),
)
def test_initial_attempt_rejects_hostile_nested_request_primitives(
    mutate: object,
) -> None:
    request, artifact, report = _initial()
    mutate(request)  # type: ignore[operator]

    with pytest.raises(DomainError, match="^invalid initial repair attempt$") as error:
        InitialAttempt(request, artifact, report)

    assert error.value.__cause__ is None


def test_repair_attempt_rejects_a_hostile_nested_child_request() -> None:
    from specstyle.repair.loop import next_repair_step
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    artifact = run_generation(backend, command.request)
    report = VerificationReport(
        (artifact.ref,),
        history.current_report.rules,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.FAIL, (artifact.ref.artifact_id,), None)
            for rule in history.current_report.rules
        ),
    )
    object.__setattr__(command.request.attempt_id, "value", _AlwaysEqualText("child"))

    with pytest.raises(DomainError, match="^invalid repair attempt$") as error:
        RepairAttempt(
            history.current_report, command.decision, command.request, artifact, report
        )

    assert error.value.__cause__ is None


def test_start_history_has_its_fixed_public_error_without_a_cause() -> None:
    with pytest.raises(DomainError, match="^invalid repair history$") as error:
        start_repair_history(object(), object(), object())

    assert error.value.__cause__ is None


@pytest.mark.parametrize("identifier", ("decision", "attempt"))
def test_next_generation_rejects_each_supplied_identifier_reused_from_history(
    identifier: str,
) -> None:
    from specstyle.repair.loop import next_repair_step
    from tests.unit.repair.test_repair_loop import (
        _observe,
        _request_with_action,
        _with_policy,
    )

    request = _with_policy(_request_with_action(), 3, 2)
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    history = start_repair_history(
        request, artifact, _report_from_loop(artifact, request, RuleStatus.FAIL)
    )
    observed = _observe(
        history, backend, "decision1", "attempt2", {"STYLE_LOW": RuleStatus.FAIL}
    )
    decision = "decision1" if identifier == "decision" else "decision2"
    attempt = "attempt3" if identifier == "decision" else request.attempt_id.value

    with pytest.raises(DomainError, match="^invalid repair transition$") as error:
        next_repair_step(observed, DecisionId(decision), AttemptId(attempt))

    assert error.value.__cause__ is None


def _report_from_loop(artifact: object, request: object, status: RuleStatus) -> object:
    from tests.unit.repair.test_repair_loop import _report

    return _report(artifact, request, status)


def test_consume_rejects_each_reused_history_identifier_kind() -> None:
    from specstyle.repair.loop import (
        NextGeneration,
        consume_repair_result,
        next_repair_step,
    )
    from tests.unit.repair.test_repair_loop import _request_with_action, _with_policy

    request = _with_policy(_request_with_action(), 3, 2)
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    history = start_repair_history(
        request, artifact, _report_from_loop(artifact, request, RuleStatus.FAIL)
    )
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    child_report = _report_from_loop(child, command.request, RuleStatus.FAIL)
    duplicate_attempt = NextGeneration(
        command.decision, replace(command.request, attempt_id=request.attempt_id)
    )
    duplicate_artifact = GeneratedArtifact(
        ArtifactRef(artifact.ref.artifact_id, child.ref.sha256),
        child.content,
        child.request_hash,
        child.generation_fingerprint,
    )
    duplicate_artifact_report = _report_from_loop(
        duplicate_artifact, command.request, RuleStatus.FAIL
    )
    for forged_command, forged_artifact, forged_report in (
        (duplicate_attempt, child, child_report),
        (command, duplicate_artifact, duplicate_artifact_report),
    ):
        with pytest.raises(DomainError, match="^invalid repair observation$") as error:
            consume_repair_result(
                history, forged_command, forged_artifact, forged_report
            )
        assert error.value.__cause__ is None

    observed = consume_repair_result(history, command, child, child_report)
    with pytest.raises(DomainError, match="^invalid repair transition$"):
        next_repair_step(observed, command.decision.decision_id, AttemptId("attempt3"))


def test_terminal_ids_are_neither_checked_nor_consumed() -> None:
    from specstyle.repair.loop import (
        RepairTerminal,
        consume_repair_result,
        next_repair_step,
    )
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    child = run_generation(backend, command.request)
    observed = consume_repair_result(
        history,
        command,
        child,
        _report_from_loop(child, command.request, RuleStatus.PASS),
    )

    terminal = next_repair_step(
        observed, command.decision.decision_id, command.request.attempt_id
    )

    assert type(terminal) is RepairTerminal
    assert (
        terminal.artifact_decision.repair_stop_reason
        is RepairStopReason.PASS_ALL_REQUIRED
    )


def test_no_action_does_not_consume_supplied_identifiers() -> None:
    from specstyle.repair.loop import RepairTerminal, next_repair_step

    request = _repair_request()
    artifact = run_generation(FakeBackend(), request)
    history = start_repair_history(
        request, artifact, _report_from_loop(artifact, request, RuleStatus.FAIL)
    )

    first = next_repair_step(history, DecisionId("audit"), request.attempt_id)
    second = next_repair_step(history, DecisionId("audit"), request.attempt_id)

    assert type(first) is RepairTerminal
    assert type(second) is RepairTerminal
    assert first.artifact_decision.repair_stop_reason is RepairStopReason.NO_ACTION


def test_executed_decision_is_rejected_before_a_no_action_selection() -> None:
    from specstyle.repair.loop import (
        RepairTerminal,
        consume_repair_result,
        next_repair_step,
    )
    from tests.unit.repair.test_repair_loop import (
        _report_with_statuses,
        _two_rule_request,
    )

    request = _two_rule_request(3, 2)
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
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    child = run_generation(backend, command.request)
    observed = consume_repair_result(
        history,
        command,
        child,
        _report_with_statuses(
            child,
            command.request,
            {"STYLE_LOW": RuleStatus.PASS, "LATER": RuleStatus.FAIL},
        ),
    )

    with pytest.raises(DomainError, match="^invalid repair transition$"):
        next_repair_step(observed, command.decision.decision_id, AttemptId("attempt3"))

    terminal = next_repair_step(
        observed, DecisionId("fresh-audit"), AttemptId("attempt3")
    )
    assert type(terminal) is RepairTerminal
    assert terminal.artifact_decision.repair_stop_reason is RepairStopReason.NO_ACTION


@pytest.mark.parametrize(
    "mutation", ("insert", "delete", "wrong_slot", "sibling_id", "sibling_hash")
)
def test_consume_rejects_every_illegal_cohort_change(mutation: str) -> None:
    from specstyle.repair.loop import (
        NextGeneration,
        consume_repair_result,
        next_repair_step,
    )
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    sibling = ArtifactRef(ArtifactId("sibling"), Sha256("f" * 64))
    rule = history.current_report.rules[0]
    initial = VerificationReport(
        (history.current_artifact.ref, sibling),
        (rule,),
        (
            RuleResult(
                rule.rule_id,
                RuleStatus.FAIL,
                (history.current_target_artifact_id,),
                None,
            ),
            RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
        ),
    )
    history = start_repair_history(
        history.current_request, history.current_artifact, initial
    )
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    extra = ArtifactRef(ArtifactId("extra"), Sha256("e" * 64))
    artifacts = (child.ref, sibling)
    results = (
        RuleResult(rule.rule_id, RuleStatus.PASS, (child.ref.artifact_id,), None),
        RuleResult(rule.rule_id, RuleStatus.FAIL, (sibling.artifact_id,), None),
    )
    if mutation == "insert":
        artifacts = (child.ref, sibling, extra)
        results += (
            RuleResult(rule.rule_id, RuleStatus.FAIL, (extra.artifact_id,), None),
        )
    elif mutation == "delete":
        artifacts, results = (child.ref,), results[:1]
    elif mutation == "wrong_slot":
        artifacts = (sibling, child.ref)
        results = tuple(
            RuleResult(
                result.rule_id,
                result.status,
                result.affected_artifact_ids,
                result.score,
            )
            for result in reversed(results)
        )
    elif mutation == "sibling_id":
        changed = ArtifactRef(ArtifactId("other-sibling"), sibling.sha256)
        artifacts = (child.ref, changed)
        results = (
            results[0],
            RuleResult(rule.rule_id, RuleStatus.FAIL, (changed.artifact_id,), None),
        )
    else:
        artifacts = (child.ref, ArtifactRef(sibling.artifact_id, Sha256("d" * 64)))
    report = VerificationReport(artifacts, (rule,), results)

    with pytest.raises(DomainError, match="^invalid repair observation$"):
        consume_repair_result(history, command, child, report)


def test_consume_rejects_child_report_rules_that_do_not_match_the_plan() -> None:
    from specstyle.domain.identifiers import RuleId
    from specstyle.repair.loop import (
        NextGeneration,
        consume_repair_result,
        next_repair_step,
    )
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    rule = command.request.compiled_spec.verification_plans[
        0
    ].applicable_rule_definitions[0]
    changed = replace(rule, rule_id=RuleId("OTHER"))
    report = VerificationReport(
        (child.ref,),
        (changed,),
        (RuleResult(changed.rule_id, RuleStatus.PASS, (child.ref.artifact_id,), None),),
    )

    with pytest.raises(DomainError, match="^invalid repair observation$"):
        consume_repair_result(history, command, child, report)


def test_history_rejects_a_repair_attempt_with_a_different_parent_report() -> None:
    from specstyle.repair.loop import NextGeneration, next_repair_step
    from tests.unit.repair.test_repair_loop import _action_history

    history, backend = _action_history()
    command = next_repair_step(history, DecisionId("decision1"), AttemptId("attempt2"))
    assert type(command) is NextGeneration
    child = run_generation(backend, command.request)
    report = _report_from_loop(child, command.request, RuleStatus.PASS)
    attempt = RepairAttempt(report, command.decision, command.request, child, report)

    with pytest.raises(DomainError, match="^invalid repair history$"):
        RepairHistory(history.initial_attempt, (attempt,))


def _forged_seen(history: RepairHistory, value: object) -> tuple[object, ...]:
    parameters = history.current_request.execution_parameters
    forged = GenerationParameters(
        parameters.ip_adapter_scale,
        parameters.img2img_strength,
        parameters.controlnet_scale,
    )
    object.__setattr__(forged, "ip_adapter_scale", value)
    return ((forged, history.current_request.variation_index),)


@pytest.mark.parametrize(
    "seen",
    (
        lambda history: _forged_seen(history, _AlwaysEqualText("0.8")),
        lambda history: _forged_seen(history, _ExplodingText("0.8")),
        lambda history: _forged_seen(history, _AlwaysEqualFloat(0.8)),
    ),
)
def test_cached_seen_state_rejects_hostile_nested_primitives(seen: object) -> None:
    from specstyle.repair.loop import next_repair_step
    from tests.unit.repair.test_repair_loop import _action_history

    history, _ = _action_history()
    object.__setattr__(history, "seen_state_keys", seen(history))

    with pytest.raises(DomainError, match="^invalid repair transition$") as error:
        next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))

    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("field", "value"),
    (("rounds", 1), ("consecutive_no_improvement", 1)),
)
def test_cached_derived_counters_cannot_be_forged(field: str, value: int) -> None:
    from specstyle.repair.loop import next_repair_step
    from tests.unit.repair.test_repair_loop import _action_history

    history, _ = _action_history()
    object.__setattr__(history, field, value)

    with pytest.raises(DomainError, match="^invalid repair transition$"):
        next_repair_step(history, DecisionId("decision"), AttemptId("attempt2"))


def test_report_itself_rejects_duplicate_artifact_ids_before_history_replay() -> None:
    from tests.unit.repair.test_repair_loop import _action_history

    history, _ = _action_history()
    rule = history.current_report.rules[0]
    ref = history.current_artifact.ref

    with pytest.raises(DomainError, match="artifact ids must be unique"):
        VerificationReport(
            (ref, ref),
            (rule,),
            (
                RuleResult(rule.rule_id, RuleStatus.FAIL, (ref.artifact_id,), None),
                RuleResult(rule.rule_id, RuleStatus.FAIL, (ref.artifact_id,), None),
            ),
        )


def test_guardrail_appends_false_child_and_resets_after_true_improvement() -> None:
    from tests.unit.repair.test_repair_loop import (
        _observe,
        _report_with_statuses,
        _two_rule_request,
    )

    request = _two_rule_request(3, 2)
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
    false_child = _observe(
        history,
        backend,
        "decision1",
        "attempt2",
        {"STYLE_LOW": RuleStatus.FAIL, "LATER": RuleStatus.FAIL},
    )
    improved_child = _observe(
        false_child,
        backend,
        "decision2",
        "attempt3",
        {"STYLE_LOW": RuleStatus.PASS, "LATER": RuleStatus.FAIL},
    )

    assert false_child.rounds == 1
    assert false_child.consecutive_no_improvement == 1
    assert (
        improved_child.repair_attempts[-1].parent_report == false_child.current_report
    )
    assert improved_child.consecutive_no_improvement == 0
    assert len(improved_child.seen_state_keys) == 3
