"""Deterministic, bounded BFS over the real repair state machine."""

from dataclasses import replace
from functools import lru_cache
from collections import deque

import pytest

from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
)
from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    DecisionId,
    Identifier,
    RuleId,
)
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.actions import (
    DECREASE_STYLE_SCALE,
    INCREASE_STYLE_SCALE,
    RETRY_SAMPLING,
)
from specstyle.repair.history import RepairHistory, start_repair_history
from specstyle.repair.loop import (
    NextGeneration,
    RepairTerminal,
    consume_repair_result,
    next_repair_step,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from specstyle.verification.rule_models import RuleResult, VerificationReport
from tests.unit.generation.test_requests import _request as generation_request
from tests.unit.spec.test_compiler import context, raw_spec


@lru_cache
def _base_request():
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    return generation_request(
        compiled_spec=compile_style_spec(StyleSpecV1.model_validate(raw), context())
    )


def _request(max_rounds: int, no_improvement_limit: int, mode: str):
    base_request = _base_request()
    source = base_request.compiled_spec.source_spec.model_copy(
        update={
            "repair": base_request.compiled_spec.source_spec.repair.model_copy(
                update={
                    "max_rounds": max_rounds,
                    "stop_after_no_improvement": no_improvement_limit,
                }
            )
        }
    )
    request = replace(
        base_request,
        compiled_spec=replace(base_request.compiled_spec, source_spec=source),
    )
    base_plan = request.compiled_spec.verification_plans[0]
    base = base_plan.rules[-1]
    low = replace(
        base,
        definition=replace(
            base.definition,
            rule_id=RuleId("STYLE_LOW"),
            level=RuleLevel.L2,
            scope=RuleScope.ITEM,
            required=True,
        ),
        priority=0,
        affected_by_actions=(INCREASE_STYLE_SCALE,),
    )
    if mode == "new":
        sampling = replace(
            low,
            definition=replace(low.definition, rule_id=RuleId("SAMPLING_DEFECT")),
            affected_by_actions=(RETRY_SAMPLING,),
        )
        output = replace(
            sampling,
            definition=replace(
                sampling.definition, rule_id=RuleId("OUTPUT_PROFILE_INVALID")
            ),
            priority=1,
            affected_by_actions=(Identifier("RENDER_OUTPUT_PROFILE"),),
        )
        rules = (sampling, output)
    elif mode == "seen":
        over = replace(
            low,
            definition=replace(low.definition, rule_id=RuleId("STYLE_OVERPOWERED")),
            priority=1,
            affected_by_actions=(DECREASE_STYLE_SCALE,),
        )
        rules = (low, over)
    else:
        rules = (
            replace(
                low,
                definition=replace(
                    low.definition, rule_id=RuleId("OUTPUT_PROFILE_INVALID")
                ),
                affected_by_actions=(Identifier("RENDER_OUTPUT_PROFILE"),),
            ),
        )
    plan = replace(base_plan, rules=rules)
    return replace(
        request,
        compiled_spec=replace(request.compiled_spec, verification_plans=(plan,)),
    )


def _report(artifact: object, request: object, statuses: dict[str, RuleStatus]):
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


def _artifact(request: object) -> GeneratedArtifact:
    content = f"artifact:{request.attempt_id.value}".encode("ascii")
    return GeneratedArtifact(
        ArtifactRef(
            ArtifactId(f"artifact-{request.attempt_id.value}"), hash_bytes(content)
        ),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )


def _key(history: RepairHistory) -> tuple[object, ...]:
    report = history.current_report
    return (
        history.rounds,
        history.consecutive_no_improvement,
        tuple(
            (
                parameters.ip_adapter_scale.hex(),
                parameters.img2img_strength.hex(),
                parameters.controlnet_scale.hex(),
                variation,
            )
            for parameters, variation in history.seen_state_keys
        ),
        tuple((result.rule_id.value, result.status.value) for result in report.results),
    )


def _terminal(history: RepairHistory) -> RepairTerminal:
    step = next_repair_step(
        history, DecisionId("terminal"), AttemptId("terminal-attempt")
    )
    assert type(step) is RepairTerminal
    return step


def assert_terminal(
    history: RepairHistory,
    terminal: RepairTerminal,
    *,
    max_rounds: int,
) -> None:
    assert history.rounds <= max_rounds
    assert len(history.seen_state_keys) == history.rounds + 1
    assert len(history.seen_state_keys) == len(set(history.seen_state_keys))
    repeated = _terminal(history)
    assert (
        repeated.artifact_decision.repair_stop_reason
        is terminal.artifact_decision.repair_stop_reason
    )
    rules = {rule.rule_id: rule for rule in history.current_report.rules}
    required_nonpass = any(
        result.status is not RuleStatus.PASS and rules[result.rule_id].required
        for result in history.current_report.results
        if history.current_target_artifact_id in result.affected_artifact_ids
    )
    if (
        terminal.artifact_decision.repair_stop_reason
        in {
            RepairStopReason.NO_ACTION,
            RepairStopReason.NO_IMPROVEMENT,
            RepairStopReason.MAX_ROUNDS,
        }
        and required_nonpass
    ):
        assert terminal.artifact_decision.artifact_status is ArtifactStatus.REJECTED
        assert (
            terminal.artifact_decision.decision_reason
            is DecisionReason.REPAIR_EXHAUSTED
        )


@pytest.mark.parametrize("max_rounds", range(1, 11))
def test_real_repair_bfs_terminates_for_all_budget_and_threshold_pairs(
    max_rounds: int,
) -> None:
    for limit in range(1, max_rounds + 1):
        visited: set[tuple[object, ...]] = set()
        saw_repaired_history = False
        representative_terminals: dict[str, set[RepairStopReason]] = {}
        # Every budget/limit pair owns one real retry chain.  The representative
        # pair branches over the complete observation alphabet; separate starts
        # prove seen-state and no-action selection without multiplying all 55 runs.
        modes = ("new", "seen", "no_action") if max_rounds == limit == 2 else ("new",)
        for mode in modes:
            request = _request(max_rounds, limit, mode)
            artifact = _artifact(request)
            statuses = (
                {"OUTPUT_PROFILE_INVALID": RuleStatus.FAIL}
                if mode == "no_action"
                else {
                    "SAMPLING_DEFECT": RuleStatus.FAIL,
                    "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                }
                if mode == "new"
                else {
                    "STYLE_LOW": RuleStatus.FAIL,
                    "STYLE_OVERPOWERED": RuleStatus.PASS,
                }
            )
            initial = _report(artifact, request, statuses)
            history = start_repair_history(request, artifact, initial)
            visited.add(_key(history))
            if mode == "no_action":
                terminal = _terminal(history)
                assert_terminal(history, terminal, max_rounds=max_rounds)
                assert (
                    terminal.artifact_decision.repair_stop_reason
                    is RepairStopReason.NO_ACTION
                )
                continue
            queue = deque(((history, None),))
            while queue:
                history, label = queue.popleft()
                suffix = history.rounds + 1
                step = next_repair_step(
                    history,
                    DecisionId(f"decision{suffix}"),
                    AttemptId(f"attempt{suffix + 1}"),
                )
                if type(step) is RepairTerminal:
                    assert_terminal(history, step, max_rounds=max_rounds)
                    if label is not None:
                        representative_terminals.setdefault(label, set()).add(
                            step.artifact_decision.repair_stop_reason
                        )
                    continue
                assert type(step) is NextGeneration
                child = _artifact(step.request)
                observations = (
                    (
                        {
                            "SAMPLING_DEFECT": RuleStatus.PASS,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                        },
                        {
                            "SAMPLING_DEFECT": RuleStatus.UNVERIFIABLE,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                        },
                        {
                            "SAMPLING_DEFECT": RuleStatus.WARNING,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                        },
                        {
                            "SAMPLING_DEFECT": RuleStatus.PASS,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.FAIL,
                        },
                        {
                            "SAMPLING_DEFECT": RuleStatus.FAIL,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                        },
                    )
                    if mode == "new"
                    and history.rounds == 0
                    and max_rounds == 3
                    and limit == 2
                    else (
                        {
                            "STYLE_LOW": RuleStatus.PASS,
                            "STYLE_OVERPOWERED": RuleStatus.FAIL,
                        },
                    )
                    if mode == "seen" and history.rounds == 0
                    else (
                        {
                            "SAMPLING_DEFECT": RuleStatus.FAIL,
                            "OUTPUT_PROFILE_INVALID": RuleStatus.PASS,
                        },
                    )
                    if mode == "new"
                    else ({"STYLE_LOW": RuleStatus.FAIL},)
                )
                labels = (
                    (
                        "PASS",
                        "UNVERIFIABLE",
                        "MANUAL",
                        "FAIL_IMPROVED",
                        "FAIL_UNIMPROVED",
                    )
                    if mode == "new"
                    and history.rounds == 0
                    and max_rounds == 3
                    and limit == 2
                    else (None,) * len(observations)
                )
                for observed_label, statuses in zip(labels, observations, strict=True):
                    observed = consume_repair_result(
                        history, step, child, _report(child, step.request, statuses)
                    )
                    saw_repaired_history = True
                    key = _key(observed)
                    if key not in visited:
                        visited.add(key)
                        queue.append((observed, observed_label or label))
        assert saw_repaired_history
        if max_rounds == 3 and limit == 2:
            assert representative_terminals == {
                "PASS": {RepairStopReason.PASS_ALL_REQUIRED},
                "UNVERIFIABLE": {RepairStopReason.UNVERIFIABLE},
                "MANUAL": {RepairStopReason.MANUAL_REQUEST},
                "FAIL_IMPROVED": {RepairStopReason.NO_ACTION},
                "FAIL_UNIMPROVED": {RepairStopReason.NO_IMPROVEMENT},
            }
        assert visited
