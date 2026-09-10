"""APP-COMPOSE-001C pure production repair composition contracts."""

from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from specstyle.domain.enums import (
    DecisionReason,
    RepairStopReason,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import AttemptId, JobId, RuleId
from specstyle.errors import DomainError
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.protocols import run_generation
from specstyle.reliability.fixtures import sample_production_request
from specstyle.repair.actions import INCREASE_STYLE_SCALE
from specstyle.repair.loop import NextGeneration, RepairTerminal
from specstyle.verification.rule_models import RuleResult, VerificationReport


def _module():
    try:
        return importlib.import_module("specstyle.workflow.production_repair")
    except ModuleNotFoundError:
        pytest.fail("production repair composition module is missing")


def _request(*, actions=(INCREASE_STYLE_SCALE,)):
    base = sample_production_request()
    base_plan = base.compiled_spec.verification_plans[0]
    item = next(
        rule
        for rule in base_plan.rules
        if rule.definition.scope is RuleScope.ITEM and rule.affected_by_actions
    )
    item = replace(
        item,
        definition=replace(
            item.definition,
            rule_id=RuleId("STYLE_LOW"),
            required=True,
            applicability=StaticApplicability.APPLICABLE,
        ),
        affected_by_actions=actions,
    )
    plan = replace(base_plan, rules=(item,))
    compiled = replace(base.compiled_spec, verification_plans=(plan,))
    return replace(
        base,
        job_id=JobId("job"),
        attempt_id=AttemptId("job-a0-xhs_grid-0"),
        compiled_spec=compiled,
    )


def _report(request, artifact, status: RuleStatus) -> VerificationReport:
    rules = request.compiled_spec.verification_plans[0].applicable_rule_definitions
    return VerificationReport(
        (artifact.ref,),
        rules,
        tuple(
            RuleResult(rule.rule_id, status, (artifact.ref.artifact_id,), None)
            for rule in rules
        ),
    )


def _replace_source(compiled, **updates):
    source = compiled.source_spec.model_copy(update=updates)
    return replace(compiled, source_spec=source)


def test_private_module_has_exact_positional_interfaces_and_no_side_effect_imports() -> (
    None
):
    module = _module()

    assert module.__all__ == ()
    expected = {
        "_validate_repair_contract": ("compiled", "profile"),
        "_repair_ids": ("job_id", "profile"),
        "_compose_initial_repair": ("request", "artifact", "report"),
        "_compose_repair_result": (
            "history",
            "command",
            "artifact",
            "report",
        ),
    }
    for name, names in expected.items():
        parameters = tuple(inspect.signature(getattr(module, name)).parameters.values())
        assert tuple(item.name for item in parameters) == names
        assert all(
            item.kind is inspect.Parameter.POSITIONAL_ONLY for item in parameters
        )

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "os",
        "datetime",
        "threading",
        "specstyle.workflow",
        "specstyle.verification.production",
        "specstyle.generation.diffusers_backend",
        "specstyle.generation.diffusers_loader",
        "tests",
    )
    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden
    )


def test_validate_contract_accepts_only_exact_profile_policy_and_no_batch() -> None:
    module = _module()
    request = _request()

    assert (
        module._validate_repair_contract(request.compiled_spec, request.output_profile)
        is None
    )

    source = request.compiled_spec.source_spec
    cases = []
    cases.append(
        _replace_source(
            request.compiled_spec,
            outputs=source.outputs.model_copy(
                update={"profiles": ("xhs_grid", "talking_head_cover")}
            ),
        )
    )
    for update in (
        {"policy_version": "1.1"},
        {"max_rounds": 2},
        {"max_rounds": 2, "stop_after_no_improvement": 2},
    ):
        cases.append(
            _replace_source(
                request.compiled_spec,
                repair=source.repair.model_copy(update=update),
            )
        )
    for compiled in cases:
        with pytest.raises(
            DomainError, match="^production repair contract is unsupported$"
        ):
            module._validate_repair_contract(compiled, "xhs_grid")

    base = sample_production_request().compiled_spec.verification_plans[0]
    batch = next(
        rule for rule in base.rules if rule.definition.scope is RuleScope.BATCH
    )
    batch = replace(
        batch,
        definition=replace(
            batch.definition, applicability=StaticApplicability.APPLICABLE
        ),
    )
    plan = request.compiled_spec.verification_plans[0]
    compiled = replace(
        request.compiled_spec,
        verification_plans=(replace(plan, rules=plan.rules + (batch,)),),
    )
    with pytest.raises(
        DomainError, match="^applicable batch verification is unsupported$"
    ):
        module._validate_repair_contract(compiled, "xhs_grid")


def test_repair_ids_are_exact_and_fail_closed_for_noncanonical_inputs() -> None:
    module = _module()

    decision_id, attempt_id = module._repair_ids(JobId("job"), "xhs_grid")

    assert decision_id.value == "job-d1-xhs_grid-0"
    assert attempt_id.value == "job-a1-xhs_grid-0"
    with pytest.raises(DomainError):
        module._repair_ids(JobId("j" * 120), "xhs_grid")
    with pytest.raises(DomainError):
        module._repair_ids(object(), "xhs_grid")
    with pytest.raises(DomainError):
        module._repair_ids(JobId("job"), object())


@pytest.mark.parametrize(
    ("status", "stop"),
    (
        (RuleStatus.PASS, RepairStopReason.PASS_ALL_REQUIRED),
        (RuleStatus.UNVERIFIABLE, RepairStopReason.UNVERIFIABLE),
    ),
)
def test_initial_terminal_composition_is_frozen_and_skips_selecting_decision(
    status: RuleStatus, stop: RepairStopReason
) -> None:
    module = _module()
    request = _request()
    artifact = run_generation(FakeBackend(), request)
    report = _report(request, artifact, status)

    composed = module._compose_initial_repair(request, artifact, report)

    assert tuple(item.name for item in fields(composed)) == (
        "history",
        "step",
        "selecting_decision",
    )
    assert not hasattr(composed, "__dict__")
    assert type(composed.step) is RepairTerminal
    assert composed.step.artifact_decision.repair_stop_reason is stop
    assert composed.selecting_decision is None
    with pytest.raises(FrozenInstanceError):
        composed.history = object()


@pytest.mark.parametrize("actions", ((INCREASE_STYLE_SCALE,), ()))
def test_initial_repairable_or_no_action_composition_includes_selecting_decision(
    actions: tuple[object, ...],
) -> None:
    module = _module()
    request = _request(actions=actions)
    artifact = run_generation(FakeBackend(), request)
    report = _report(request, artifact, RuleStatus.FAIL)

    composed = module._compose_initial_repair(request, artifact, report)

    expected_type = NextGeneration if actions else RepairTerminal
    assert type(composed.step) is expected_type
    assert composed.selecting_decision.artifact_id == artifact.ref.artifact_id
    assert (
        composed.selecting_decision.decision_reason
        is DecisionReason.REQUIRED_GATE_FAILED
    )
    assert composed.selecting_decision.repair_stop_reason is None
    if not actions:
        assert composed.step.no_action is not None


def test_repair_result_consumes_exact_command_and_returns_terminal() -> None:
    module = _module()
    request = _request()
    backend = FakeBackend()
    artifact = run_generation(backend, request)
    initial = module._compose_initial_repair(
        request, artifact, _report(request, artifact, RuleStatus.FAIL)
    )
    assert type(initial.step) is NextGeneration
    child = run_generation(backend, initial.step.request)
    child_report = _report(initial.step.request, child, RuleStatus.PASS)

    composed = module._compose_repair_result(
        initial.history, initial.step, child, child_report
    )

    assert tuple(item.name for item in fields(composed)) == ("history", "terminal")
    assert not hasattr(composed, "__dict__")
    assert composed.history.rounds == 1
    assert type(composed.terminal) is RepairTerminal
    assert (
        composed.terminal.artifact_decision.repair_stop_reason
        is RepairStopReason.PASS_ALL_REQUIRED
    )
    with pytest.raises(FrozenInstanceError):
        composed.terminal = object()


def test_composition_propagates_repair_core_domain_errors_without_translation() -> None:
    module = _module()

    with pytest.raises(DomainError):
        module._compose_initial_repair(object(), object(), object())
    with pytest.raises(DomainError):
        module._compose_repair_result(object(), object(), object(), object())
