from dataclasses import replace

import pytest
import specstyle.repair.policies as policies_module

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import (
    ArtifactId,
    DecisionId,
    Identifier,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError
from specstyle.generation.requests import GenerationParameters, GenerationRequest
from specstyle.repair.actions import (
    DECREASE_STYLE_SCALE,
    INCREASE_STRUCTURE,
    INCREASE_STYLE_SCALE,
    REDUCE_DENOISE,
    RENDER_OUTPUT_PROFILE,
    RETRY_SAMPLING,
    plan_repair_action,
)
from specstyle.repair.models import NoAction, RepairDecision
from specstyle.repair.policies import repair_state_key, select_repair
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.compiled_models import CompiledVerificationPlan
from specstyle.spec.models import StyleSpecV1
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)
from tests.unit.repair.test_actions import _repair_request
from tests.unit.generation.test_requests import _request as _generation_request
from tests.unit.spec.test_compiler import context, raw_spec


class SelfSafeCrossExplodingText(str):
    """A str subclass safe only for self-comparison, proving boundary normalization."""

    def __hash__(self) -> int:
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        raise RuntimeError("cross-object equality exploded")

    def __ne__(self, other: object) -> bool:
        if self is other:
            return False
        raise RuntimeError("cross-object equality exploded")


def _request_and_plan(
    entries: tuple[tuple[str, RuleLevel, RuleScope, int, tuple[Identifier, ...]], ...],
    request: GenerationRequest | None = None,
) -> tuple[GenerationRequest, CompiledVerificationPlan]:
    request = _repair_request() if request is None else request
    base_plan = request.compiled_spec.verification_plans[0]
    base_rule = next(
        rule for rule in base_plan.rules if rule.definition.rule_id == RuleId("l1")
    )
    rules = tuple(
        replace(
            base_rule,
            definition=RuleDefinition(
                RuleId(rule_id),
                level,
                scope,
                True,
                StaticApplicability.APPLICABLE,
                GatePolicy("reject", "reject", "reject"),
            ),
            priority=priority,
            affected_by_actions=actions,
        )
        for rule_id, level, scope, priority, actions in entries
    )
    plan_changes: dict[str, object] = {"rules": rules}
    if any(level is RuleLevel.L3 for _, level, _, _, _ in entries):
        plan_changes.update(
            l3_status="APPLICABLE",
            l3_reason=None,
            l3_plugin_pin=base_plan.output_profile_pin,
            l3_threshold_profile_pin=base_plan.output_profile_pin,
        )
    plan = replace(base_plan, **plan_changes)
    compiled = replace(request.compiled_spec, verification_plans=(plan,))
    return replace(request, compiled_spec=compiled), plan


def _report(
    plan: CompiledVerificationPlan,
    statuses: dict[str, RuleStatus],
) -> VerificationReport:
    artifact = ArtifactRef(ArtifactId("target"), Sha256("b" * 64))
    results = tuple(
        RuleResult(
            rule.rule_id,
            statuses[rule.rule_id.value],
            (ArtifactId("target"),),
            None,
        )
        for rule in plan.applicable_rule_definitions
    )
    return VerificationReport((artifact,), plan.applicable_rule_definitions, results)


def _cohort_report(
    plan: CompiledVerificationPlan,
    statuses: dict[tuple[str, str], RuleStatus],
) -> VerificationReport:
    artifacts = (
        ArtifactRef(ArtifactId("target"), Sha256("b" * 64)),
        ArtifactRef(ArtifactId("sibling"), Sha256("c" * 64)),
    )
    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
    results = tuple(
        RuleResult(
            rule.rule_id,
            statuses[(rule.rule_id.value, artifact_id.value)],
            (artifact_id,),
            None,
        )
        for rule in plan.applicable_rule_definitions
        if rule.scope is RuleScope.ITEM
        for artifact_id in artifact_ids
    ) + tuple(
        RuleResult(
            rule.rule_id,
            statuses[(rule.rule_id.value, "target")],
            artifact_ids,
            None,
        )
        for rule in plan.applicable_rule_definitions
        if rule.scope is RuleScope.BATCH
    )
    return VerificationReport(artifacts, plan.applicable_rule_definitions, results)


def _unknown_policy_request() -> GenerationRequest:
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "2.0"
    return _generation_request(
        compiled_spec=compile_style_spec(StyleSpecV1.model_validate(raw), context())
    )


@pytest.mark.parametrize(
    ("rule_id", "actions", "expected"),
    (
        ("STYLE_LOW", (INCREASE_STYLE_SCALE,), INCREASE_STYLE_SCALE),
        (
            "STYLE_OVERPOWERED",
            (DECREASE_STYLE_SCALE, REDUCE_DENOISE),
            DECREASE_STYLE_SCALE,
        ),
        ("CONTENT_DRIFT", (REDUCE_DENOISE, INCREASE_STRUCTURE), REDUCE_DENOISE),
        ("FACE_ID_LOW", (REDUCE_DENOISE,), REDUCE_DENOISE),
        ("SAMPLING_DEFECT", (RETRY_SAMPLING,), RETRY_SAMPLING),
    ),
)
def test_selects_first_policy_action_in_compiled_intersection(
    rule_id: str, actions: tuple[Identifier, ...], expected: Identifier
) -> None:
    request, plan = _request_and_plan(
        ((rule_id, RuleLevel.L2, RuleScope.ITEM, 1, actions),)
    )
    report = _report(plan, {rule_id: RuleStatus.FAIL})

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert selection.action_id == expected


def test_select_returns_no_action_for_render_unknown_and_highest_blocker_only() -> None:
    entries = (
        (
            "OUTPUT_PROFILE_INVALID",
            RuleLevel.L1,
            RuleScope.ITEM,
            1,
            (RENDER_OUTPUT_PROFILE,),
        ),
        ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 0, (INCREASE_STYLE_SCALE,)),
    )
    request, plan = _request_and_plan(entries)
    report = _report(
        plan, {"OUTPUT_PROFILE_INVALID": RuleStatus.FAIL, "STYLE_LOW": RuleStatus.FAIL}
    )

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert selection == NoAction(
        DecisionId("decision"),
        (RuleId("OUTPUT_PROFILE_INVALID"),),
        (RENDER_OUTPUT_PROFILE,),
    )


def test_production_bundle_failure_discloses_retry_but_requires_compiled_whitelist() -> (
    None
):
    request, plan = _request_and_plan(
        (("l1_bundle", RuleLevel.L1, RuleScope.ITEM, 1, ()),)
    )
    report = _report(plan, {"l1_bundle": RuleStatus.FAIL})

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert selection == NoAction(
        DecisionId("decision"),
        (RuleId("l1_bundle"),),
        (RETRY_SAMPLING,),
    )


def test_select_orders_l1_l3_l2_then_priority_and_rule_id() -> None:
    entries = (
        ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 0, (INCREASE_STYLE_SCALE,)),
        ("SAMPLING_DEFECT", RuleLevel.L3, RuleScope.ITEM, 0, (RETRY_SAMPLING,)),
        ("FACE_ID_LOW", RuleLevel.L1, RuleScope.ITEM, 3, (REDUCE_DENOISE,)),
        ("CONTENT_DRIFT", RuleLevel.L1, RuleScope.ITEM, 2, (REDUCE_DENOISE,)),
    )
    request, plan = _request_and_plan(entries)
    report = _report(plan, {entry[0]: RuleStatus.FAIL for entry in entries})

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert selection.trigger_rule_id == RuleId("CONTENT_DRIFT")


def test_select_skips_seen_after_state_and_stops_when_all_candidates_seen() -> None:
    entries = (
        (
            "STYLE_OVERPOWERED",
            RuleLevel.L2,
            RuleScope.ITEM,
            1,
            (DECREASE_STYLE_SCALE, REDUCE_DENOISE),
        ),
    )
    request, plan = _request_and_plan(entries)
    report = _report(plan, {"STYLE_OVERPOWERED": RuleStatus.FAIL})
    first = plan_repair_action(
        request, DecisionId("first"), RuleId("STYLE_OVERPOWERED"), DECREASE_STYLE_SCALE
    )
    second = plan_repair_action(
        request, DecisionId("second"), RuleId("STYLE_OVERPOWERED"), REDUCE_DENOISE
    )
    first_key = (first.patch.after_parameters, first.patch.after_variation_index)
    second_key = (second.patch.after_parameters, second.patch.after_variation_index)

    selected = select_repair(
        request,
        plan,
        report,
        ArtifactId("target"),
        DecisionId("decision"),
        (first_key,),
    )
    exhausted = select_repair(
        request,
        plan,
        report,
        ArtifactId("target"),
        DecisionId("decision"),
        (first_key, second_key),
    )

    assert type(selected) is RepairDecision
    assert selected.action_id == REDUCE_DENOISE
    assert type(exhausted) is NoAction


def test_state_key_and_selection_reject_invalid_terminal_or_seen_contracts() -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    failed = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    approved = _report(plan, {"STYLE_LOW": RuleStatus.PASS})

    assert repair_state_key(request) == (
        request.execution_parameters,
        request.variation_index,
    )
    with pytest.raises(DomainError):
        select_repair(
            request, plan, approved, ArtifactId("target"), DecisionId("decision")
        )
    with pytest.raises(DomainError):
        select_repair(
            request,
            plan,
            failed,
            ArtifactId("target"),
            DecisionId("decision"),
            ((GenerationParameters(0.5, 0.5, 0.5), True),),
        )


def test_policy_table_is_immutable_and_public_callables_are_frozen() -> None:
    with pytest.raises(TypeError):
        policies_module._POLICY_ACTIONS[0] = ("OTHER", ())  # type: ignore[index]
    public = {
        name
        for name, value in vars(policies_module).items()
        if not name.startswith("_") and callable(value)
    }
    assert public == {"repair_state_key", "select_repair"}


def test_compiled_intersection_can_select_second_policy_candidate() -> None:
    request, plan = _request_and_plan(
        (("STYLE_OVERPOWERED", RuleLevel.L2, RuleScope.ITEM, 1, (REDUCE_DENOISE,)),)
    )
    report = _report(plan, {"STYLE_OVERPOWERED": RuleStatus.FAIL})

    selected = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selected) is RepairDecision
    assert selected.action_id == REDUCE_DENOISE


def test_selection_accepts_multi_target_item_and_batch_cohort() -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("BATCH_STYLE_INCONSISTENT", RuleLevel.L2, RuleScope.BATCH, 2, ()),
        )
    )
    report = _cohort_report(
        plan,
        {
            ("STYLE_LOW", "target"): RuleStatus.FAIL,
            ("STYLE_LOW", "sibling"): RuleStatus.PASS,
            ("BATCH_STYLE_INCONSISTENT", "target"): RuleStatus.PASS,
        },
    )

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert selection.trigger_rule_id == RuleId("STYLE_LOW")


def test_selection_normalizes_legal_report_result_permutation() -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("FACE_ID_LOW", RuleLevel.L2, RuleScope.ITEM, 2, (REDUCE_DENOISE,)),
        )
    )
    report = _report(
        plan, {"STYLE_LOW": RuleStatus.FAIL, "FACE_ID_LOW": RuleStatus.PASS}
    )
    permuted = replace(report, results=report.results[::-1])

    selection = select_repair(
        request, plan, permuted, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert selection.trigger_rule_id == RuleId("STYLE_LOW")


@pytest.mark.parametrize(
    ("results"),
    (
        pytest.param("duplicate", id="duplicate"),
        pytest.param("missing", id="missing"),
        pytest.param("extra", id="extra"),
    ),
)
def test_selection_rejects_non_permutation_report_results(results: str) -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("FACE_ID_LOW", RuleLevel.L2, RuleScope.ITEM, 2, (REDUCE_DENOISE,)),
        )
    )
    report = _report(
        plan, {"STYLE_LOW": RuleStatus.FAIL, "FACE_ID_LOW": RuleStatus.PASS}
    )
    changed = {
        "duplicate": (report.results[0], report.results[0]),
        "missing": (report.results[0],),
        "extra": report.results + (report.results[0],),
    }[results]
    object.__setattr__(report, "results", changed)

    with pytest.raises(DomainError):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


@pytest.mark.parametrize(
    ("entries", "statuses", "seen"),
    (
        pytest.param(
            (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),),
            {"STYLE_LOW": RuleStatus.PASS},
            (),
            id="no-failure-approved",
        ),
        pytest.param(
            (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),),
            {"STYLE_LOW": RuleStatus.UNVERIFIABLE},
            (),
            id="terminal-unverifiable",
        ),
        pytest.param(
            (("UNKNOWN", RuleLevel.L2, RuleScope.ITEM, 1, ()),),
            {"UNKNOWN": RuleStatus.FAIL},
            (),
            id="unknown-rule-no-candidate",
        ),
        pytest.param(
            (
                (
                    "STYLE_OVERPOWERED",
                    RuleLevel.L2,
                    RuleScope.ITEM,
                    1,
                    (DECREASE_STYLE_SCALE,),
                ),
            ),
            {"STYLE_OVERPOWERED": RuleStatus.FAIL},
            ((GenerationParameters(0.4, 0.45, 0.7), 0),),
            id="seen-exhaustion",
        ),
    ),
)
def test_unknown_policy_fails_closed_before_every_no_action_path(
    entries: tuple[tuple[str, RuleLevel, RuleScope, int, tuple[Identifier, ...]], ...],
    statuses: dict[str, RuleStatus],
    seen: tuple[tuple[GenerationParameters, int], ...],
) -> None:
    request, plan = _request_and_plan(entries, _unknown_policy_request())
    report = _report(plan, statuses)

    with pytest.raises(DomainError, match="unsupported repair policy"):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision"), seen
        )


@pytest.mark.parametrize("status", (RuleStatus.PASS, RuleStatus.UNVERIFIABLE))
def test_terminal_routes_are_rejected_before_selection(status: RuleStatus) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": status})

    with pytest.raises(DomainError):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


def test_selection_rejects_wrong_plan_and_report_order() -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("FACE_ID_LOW", RuleLevel.L2, RuleScope.ITEM, 2, (REDUCE_DENOISE,)),
        )
    )
    report = _report(
        plan, {"STYLE_LOW": RuleStatus.FAIL, "FACE_ID_LOW": RuleStatus.FAIL}
    )

    with pytest.raises(DomainError):
        select_repair(
            request,
            replace(plan, rules=plan.rules[::-1]),
            report,
            ArtifactId("target"),
            DecisionId("decision"),
        )


@pytest.mark.parametrize("field_name", ("status", "score", "affected_artifact_ids"))
def test_selection_rejects_forged_nested_report_results(field_name: str) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    forged = {"status": "FAIL", "score": "bad", "affected_artifact_ids": []}[field_name]
    object.__setattr__(report.results[0], field_name, forged)

    with pytest.raises(DomainError):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


def test_selection_rejects_forged_compiled_priority() -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    object.__setattr__(plan.rules[0], "priority", "bad")

    with pytest.raises(DomainError):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )
    with pytest.raises(DomainError):
        select_repair(
            request,
            plan,
            replace(report, rules=report.rules[::-1]),
            ArtifactId("target"),
            DecisionId("decision"),
        )


def test_select_normalizes_hostile_decision_trigger_action_and_target_ids() -> None:
    action = Identifier("INCREASE_STYLE_SCALE")
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (action,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    decision_id = DecisionId("decision")
    target_id = ArtifactId("target")
    object.__setattr__(decision_id, "value", SelfSafeCrossExplodingText("decision"))
    object.__setattr__(target_id, "value", SelfSafeCrossExplodingText("target"))
    object.__setattr__(
        plan.rules[0].definition.rule_id,
        "value",
        SelfSafeCrossExplodingText("STYLE_LOW"),
    )
    object.__setattr__(
        action, "value", SelfSafeCrossExplodingText("INCREASE_STYLE_SCALE")
    )

    selection = select_repair(request, plan, report, target_id, decision_id)

    assert type(selection) is RepairDecision
    assert type(selection.decision_id.value) is str
    assert type(selection.trigger_rule_id.value) is str
    assert type(selection.action_id.value) is str


def test_select_normalizes_hostile_report_and_plan_ids() -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    object.__setattr__(
        plan.rules[0].definition.rule_id,
        "value",
        SelfSafeCrossExplodingText("STYLE_LOW"),
    )
    object.__setattr__(
        report.rules[0].rule_id, "value", SelfSafeCrossExplodingText("STYLE_LOW")
    )
    object.__setattr__(
        report.results[0].rule_id, "value", SelfSafeCrossExplodingText("STYLE_LOW")
    )
    object.__setattr__(
        report.artifacts[0].artifact_id, "value", SelfSafeCrossExplodingText("target")
    )
    object.__setattr__(
        report.results[0].affected_artifact_ids[0],
        "value",
        SelfSafeCrossExplodingText("target"),
    )

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert type(selection.trigger_rule_id.value) is str


def test_select_rejects_duplicate_or_forged_seen_parameters() -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    seen = (GenerationParameters(0.5, 0.5, 0.5), 0)
    forged = GenerationParameters(0.5, 0.5, 0.5)
    object.__setattr__(forged, "ip_adapter_scale", "bad")

    with pytest.raises(DomainError):
        select_repair(
            request,
            plan,
            report,
            ArtifactId("target"),
            DecisionId("decision"),
            (seen, seen),
        )
    with pytest.raises(DomainError):
        select_repair(
            request,
            plan,
            report,
            ArtifactId("target"),
            DecisionId("decision"),
            ((forged, 0),),
        )


def test_select_uses_rule_id_for_same_tier_and_priority_tie() -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("FACE_ID_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (REDUCE_DENOISE,)),
        )
    )
    report = _report(
        plan, {"STYLE_LOW": RuleStatus.FAIL, "FACE_ID_LOW": RuleStatus.FAIL}
    )

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert type(selection) is RepairDecision
    assert selection.trigger_rule_id == RuleId("FACE_ID_LOW")


@pytest.mark.parametrize(
    ("rule_id", "scope"),
    (("UNKNOWN", RuleScope.ITEM), ("BATCH_STYLE_INCONSISTENT", RuleScope.BATCH)),
)
def test_supported_policy_returns_no_action_for_unknown_or_batch_blocker(
    rule_id: str, scope: RuleScope
) -> None:
    request, plan = _request_and_plan(((rule_id, RuleLevel.L2, scope, 1, ()),))
    report = _report(plan, {rule_id: RuleStatus.FAIL})

    selection = select_repair(
        request, plan, report, ArtifactId("target"), DecisionId("decision")
    )

    assert selection == NoAction(DecisionId("decision"), (RuleId(rule_id),), ())


@pytest.mark.parametrize(
    ("status", "on_unverifiable", "on_warning"),
    (
        (RuleStatus.WARNING, "reject", "manual_review"),
        (RuleStatus.UNVERIFIABLE, "manual_review", "reject"),
    ),
)
def test_select_rejects_manual_terminal_routes(
    status: RuleStatus, on_unverifiable: str, on_warning: str
) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    manual_rule = replace(
        plan.rules[0],
        definition=replace(
            plan.rules[0].definition,
            gate_policy=GatePolicy("reject", on_unverifiable, on_warning),
        ),
    )
    plan = replace(plan, rules=(manual_rule,))
    request = replace(
        request,
        compiled_spec=replace(request.compiled_spec, verification_plans=(plan,)),
    )
    report = _report(plan, {"STYLE_LOW": status})

    with pytest.raises(
        DomainError, match="repair selection requires required gate failure"
    ):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


def test_select_rejects_report_rule_order_without_another_forgery() -> None:
    request, plan = _request_and_plan(
        (
            ("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),
            ("FACE_ID_LOW", RuleLevel.L2, RuleScope.ITEM, 2, (REDUCE_DENOISE,)),
        )
    )
    report = _report(
        plan, {"STYLE_LOW": RuleStatus.FAIL, "FACE_ID_LOW": RuleStatus.PASS}
    )

    with pytest.raises(DomainError, match="report does not match plan target"):
        select_repair(
            request,
            plan,
            replace(report, rules=report.rules[::-1]),
            ArtifactId("target"),
            DecisionId("decision"),
        )


@pytest.mark.parametrize(
    ("wrong_context", "message"),
    (
        ("spec", "plan does not match generation request"),
        ("profile", "generation selectors must resolve exactly one graph"),
    ),
)
def test_select_rejects_wrong_spec_and_wrong_profile_independently(
    wrong_context: str, message: str
) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    if wrong_context == "spec":
        wrong_request = replace(request, compiled_spec=_repair_request().compiled_spec)
    else:
        wrong_request = request
        object.__setattr__(wrong_request, "output_profile", "talking_head_cover")

    with pytest.raises(DomainError, match=message):
        select_repair(
            wrong_request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


@pytest.mark.parametrize(
    ("object_name", "field_name", "forged"),
    (
        ("seed", "source_sha256", Sha256("d" * 64)),
        ("seed", "compiled_spec_hash", Sha256("d" * 64)),
        ("seed", "output_profile", "talking_head_cover"),
        ("seed", "variation_index", 1),
        ("seed", "algorithm", "forged.seed.v1"),
        ("seed", "seed", 0),
        ("request_hash", "value", "d" * 64),
        ("generation_fingerprint", "value", "d" * 64),
    ),
)
def test_public_repair_apis_reject_forged_request_provenance(
    object_name: str, field_name: str, forged: object
) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    object.__setattr__(getattr(request, object_name), field_name, forged)

    with pytest.raises(DomainError, match="invalid generation request"):
        repair_state_key(request)
    with pytest.raises(DomainError, match="invalid generation request"):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


@pytest.mark.parametrize(
    "field_name", ("seed", "request_hash", "generation_fingerprint")
)
def test_public_repair_apis_reject_invalid_provenance_object_types(
    field_name: str,
) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    object.__setattr__(request, field_name, object())

    with pytest.raises(DomainError, match="invalid generation request"):
        repair_state_key(request)
    with pytest.raises(DomainError, match="invalid generation request"):
        select_repair(
            request, plan, report, ArtifactId("target"), DecisionId("decision")
        )


@pytest.mark.parametrize("field_name", ("source_sha256", "request_hash"))
def test_public_repair_apis_normalize_hostile_provenance_primitives(
    field_name: str,
) -> None:
    request, plan = _request_and_plan(
        (("STYLE_LOW", RuleLevel.L2, RuleScope.ITEM, 1, (INCREASE_STYLE_SCALE,)),)
    )
    report = _report(plan, {"STYLE_LOW": RuleStatus.FAIL})
    if field_name == "source_sha256":
        object.__setattr__(
            request.seed.source_sha256,
            "value",
            SelfSafeCrossExplodingText(request.seed.source_sha256.value),
        )
    else:
        object.__setattr__(
            request.request_hash,
            "value",
            SelfSafeCrossExplodingText(request.request_hash.value),
        )

    assert repair_state_key(request) == (
        request.execution_parameters,
        request.variation_index,
    )
    assert (
        type(
            select_repair(
                request, plan, report, ArtifactId("target"), DecisionId("decision")
            )
        )
        is RepairDecision
    )
