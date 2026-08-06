from __future__ import annotations

import json

import pytest
from test_creative_retrieval import (
    _context,
    _filters,
    _index,
    _sha,
    _thesis,
)

from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    BaselineRelationship,
    ColorPipelineFacts,
    ColorProperty,
    ColorStrategy,
    ProtectedAttribute,
    StrategyAction,
    StrategyOperation,
    StrategyParameter,
    StrategyScope,
    TechnicalBaseline,
    canonical_sha256,
)
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    RawProviderResponse,
    RuntimePolicy,
)
from colorgraph.agent.creative_retrieval import retrieve_creative_possibilities
from colorgraph.agent.creative_strategy import (
    CapabilityParameter,
    ColorGraphCapabilityCatalog,
    ColorStrategyValidationError,
    RendererCapability,
    StrategyViolationCode,
    audit_color_strategy,
    audit_color_strategy_set,
    build_color_strategist_request,
    run_color_strategist,
)

BASELINE_ASSET_ID = "asset:baseline"
BASELINE_ASSET_SHA = _sha("signed-baseline")
RETRIEVAL_ASSET_SHA = _sha("signed-retrieval")


def _baseline() -> TechnicalBaseline:
    return TechnicalBaseline(
        graph_digest=_sha("graph"),
        color_pipeline=ColorPipelineFacts(
            input_color_space="bt709_oetf",
            working_color_space="acescg",
            output_color_space="rec1886",
            renderer_version="colorgraph.renderer/v3",
            input_transform_digest=_sha("input-transform"),
            output_transform_digest=_sha("output-transform"),
            information_already_clipped=False,
        ),
        measurements=[],
        diagnostics=[],
        immutable_fact_ids=[
            "fact:input-transform",
            "fact:working-space",
            "fact:output-transform",
        ],
    )


def _catalog() -> ColorGraphCapabilityCatalog:
    return ColorGraphCapabilityCatalog(
        catalog_version="renderer-capabilities:test-v1",
        renderer_version="colorgraph.renderer/v3",
        project_id="project:test",
        source_graph_digest=_sha("graph"),
        working_color_space="acescg",
        allowed_scene_ids=["scene:lake"],
        allowed_shot_ids=["shot:lake"],
        allowed_mask_targets=["sky"],
        capabilities=[
            RendererCapability(
                capability_id="capability:tone",
                operation=StrategyOperation.TONE,
                parameters=[
                    CapabilityParameter(
                        name="contrast",
                        unit="normalized",
                        color_property=ColorProperty.CONTRAST,
                        minimum=-1,
                        maximum=1,
                        neutral_value=0,
                        maximum_minor_deviation=0.1,
                    )
                ],
                allowed_scopes=["project", "scene", "shot"],
                supported_working_color_spaces=["acescg"],
                requires_mask=False,
                allowed_mask_targets=[],
            ),
            RendererCapability(
                capability_id="capability:look-saturation",
                operation=StrategyOperation.LOOK,
                parameters=[
                    CapabilityParameter(
                        name="saturation",
                        unit="normalized",
                        color_property=ColorProperty.SATURATION,
                        minimum=-1,
                        maximum=1,
                        neutral_value=0,
                        maximum_minor_deviation=0.1,
                    )
                ],
                allowed_scopes=["project", "scene", "shot"],
                supported_working_color_spaces=["acescg"],
                requires_mask=False,
                allowed_mask_targets=[],
            ),
            RendererCapability(
                capability_id="capability:masked-saturation",
                operation=StrategyOperation.MASKED_GRADE,
                parameters=[
                    CapabilityParameter(
                        name="saturation",
                        unit="normalized",
                        color_property=ColorProperty.SATURATION,
                        minimum=-0.5,
                        maximum=0.5,
                        neutral_value=0,
                        maximum_minor_deviation=0.08,
                    )
                ],
                allowed_scopes=["mask"],
                supported_working_color_spaces=["acescg"],
                requires_mask=True,
                allowed_mask_targets=["sky"],
            ),
            RendererCapability(
                capability_id="capability:balance-temperature",
                operation=StrategyOperation.BALANCE,
                parameters=[
                    CapabilityParameter(
                        name="temperature",
                        unit="normalized",
                        color_property=ColorProperty.TEMPERATURE,
                        minimum=-1,
                        maximum=1,
                        neutral_value=0,
                        maximum_minor_deviation=0.1,
                    )
                ],
                allowed_scopes=["scene", "shot"],
                supported_working_color_spaces=["acescg"],
                requires_mask=False,
                allowed_mask_targets=[],
            ),
        ],
    )


def _retrieval_inputs():
    thesis = _thesis()
    context = _context()
    result = retrieve_creative_possibilities(
        thesis=thesis,
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=context,
        index=_index(),
        filters=_filters(),
        relevance_threshold=0.24,
        maximum_per_route=2,
    )
    return thesis, context, result.bundle


def _action_for_direction(direction) -> StrategyAction:
    if direction.value == "faithful":
        operation = StrategyOperation.TONE
        capability_id = "capability:tone"
        property_name = ColorProperty.CONTRAST
        adjustment = AdjustmentDirection.PRESERVE
        parameter_name = "contrast"
        minimum, nominal, maximum = -0.1, 0, 0.1
        scope = StrategyScope(
            project_id="project:test",
            scene_id="scene:lake",
        )
    elif direction.value == "amplified":
        operation = StrategyOperation.LOOK
        capability_id = "capability:look-saturation"
        property_name = ColorProperty.SATURATION
        adjustment = AdjustmentDirection.INCREASE
        parameter_name = "saturation"
        minimum, nominal, maximum = 0.05, 0.2, 0.35
        scope = StrategyScope(
            project_id="project:test",
            scene_id="scene:lake",
        )
    else:
        operation = StrategyOperation.MASKED_GRADE
        capability_id = "capability:masked-saturation"
        property_name = ColorProperty.SATURATION
        adjustment = AdjustmentDirection.DECREASE
        parameter_name = "saturation"
        minimum, nominal, maximum = -0.3, -0.15, 0
        scope = StrategyScope(
            project_id="project:test",
            scene_id="scene:lake",
            mask_target="sky",
        )
    return StrategyAction(
        action_id=f"action:{direction.value}",
        operation=operation,
        scope=scope,
        parameters=[
            StrategyParameter(
                name=parameter_name,
                unit="normalized",
                minimum=minimum,
                nominal=nominal,
                maximum=maximum,
            )
        ],
        serves_brief_id=f"brief:{direction.value}",
        evidence_ids=["frame:lake", "measurement:lake"],
        protected_attributes=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        rationale="The bounded action serves the cited hierarchy and physical evidence.",
        capability_id=capability_id,
        intended_property=property_name,
        direction=adjustment,
        baseline_relationship=BaselineRelationship.PRESERVE,
    )


def _strategy(brief, retrieval) -> ColorStrategy:
    selected_ids = sorted(
        {
            result.card_id
            for item in retrieval.retrievals
            if item.brief_id == brief.brief_id
            for result in item.results
            if result.selected_reason is not None
        }
    )
    is_masked = brief.direction.value == "counterpoint"
    return ColorStrategy(
        strategy_id=f"strategy:{brief.direction.value}",
        brief_id=brief.brief_id,
        technical_baseline_asset_id=BASELINE_ASSET_ID,
        technical_baseline_sha256=BASELINE_ASSET_SHA,
        common_language="Preserve restrained highlights and legible spatial separation.",
        actions=[_action_for_direction(brief.direction)],
        alternatives_not_selected=[
            "A stronger global treatment was not selected because it weakens source evidence."
        ],
        continuity_constraints=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        failure_conditions=[
            "Highlights clip, the reflection loses focus, or continuity breaks."
        ],
        project_thesis_sha256=retrieval.thesis_sha256,
        retrieval_bundle_sha256=RETRIEVAL_ASSET_SHA,
        selected_possibility_card_ids=selected_ids[:2],
        scene_role="A restrained movement in the project's visual argument.",
        tonal_structure=["Retain highlight detail while keeping the horizon legible."],
        color_relationships=["Keep source restraint while testing the selected direction."],
        visual_hierarchy=["Lake reflection first, horizon second, shore as anchor."],
        local_region_intents=(
            ["Reduce only the sky contribution without changing the shore."]
            if is_masked
            else []
        ),
    )


def _audit(strategy, brief, thesis, context, retrieval):
    return audit_color_strategy(
        strategy,
        brief=brief,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
    )


def test_three_briefs_translate_to_distinct_internally_valid_strategies() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    strategies = [_strategy(brief, retrieval) for brief in thesis.briefs]

    report = audit_color_strategy_set(
        strategies,
        briefs=thesis.briefs,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
    )

    assert report.valid is True
    assert report.pair_count == 3
    assert report.structurally_distinct_pairs == 3
    assert all(item.valid for item in report.strategy_reports)


def test_strategist_request_contains_only_frozen_inputs_and_possibility_cards() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[0]
    request = build_color_strategist_request(
        brief=brief,
        thesis=thesis,
        thesis_asset_sha256=retrieval.thesis_sha256,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        context_asset_sha256=_sha("signed-context"),
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
        catalog_asset_sha256=_sha("signed-catalog"),
    )
    payload = json.loads(request.prompt)

    assert request.role == CreativeRole.STRATEGIST
    assert request.prompt_version == "color-strategist/v3"
    assert payload["frozen_brief"]["brief_id"] == brief.brief_id
    assert payload["hard_contract"]["brief_id"] == brief.brief_id
    assert payload["hard_contract"]["scene_capabilities"]
    assert payload["hard_contract"]["required_action_signature"] == {
        "capability_id": "capability:tone",
        "operation": "tone",
        "intended_property": "contrast",
        "direction": "preserve",
        "scope_kind": "scene",
        "parameters": [
            {
                "name": "contrast",
                "unit": "normalized",
            }
        ],
    }
    assert payload["hard_contract"]["required_continuity_constraints"] == [
        item.value for item in thesis.shared_protections
    ]
    assert payload["technical_baseline_read_only"]["graph_digest"] == _sha("graph")
    assert payload["retrieval"]["possibility_cards"]
    assert all(
        card["schema_version"] == "colorgraph.creative-possibility-card/v1"
        for card in payload["retrieval"]["possibility_cards"]
    )
    assert "operation_card" not in request.prompt.casefold()
    assert "failure_card" not in request.prompt.casefold()
    assert request.input_asset_digests == (
        retrieval.thesis_sha256,
        RETRIEVAL_ASSET_SHA,
        _sha("signed-context"),
        BASELINE_ASSET_SHA,
        _sha("signed-catalog"),
    )


def test_non_faithful_request_enforces_a_visible_effect_range() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[1]
    request = build_color_strategist_request(
        brief=brief,
        thesis=thesis,
        thesis_asset_sha256=retrieval.thesis_sha256,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        context_asset_sha256=_sha("signed-context"),
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
        catalog_asset_sha256=_sha("signed-catalog"),
    )
    payload = json.loads(request.prompt)
    signature = payload["hard_contract"]["required_action_signature"]

    assert signature["operation"] == "tone"
    assert signature["direction"] == "increase"
    assert signature["minimum_effect_magnitude"] == 0.3

    strategy = _strategy(brief, retrieval)
    weak_action = strategy.actions[0].model_copy(
        update={
            "operation": StrategyOperation.TONE,
            "capability_id": "capability:tone",
            "intended_property": ColorProperty.CONTRAST,
            "direction": AdjustmentDirection.INCREASE,
            "parameters": [
                StrategyParameter(
                    name="contrast",
                    unit="normalized",
                    minimum=0.05,
                    nominal=0.2,
                    maximum=0.25,
                )
            ],
        }
    )
    weak = strategy.model_copy(update={"actions": [weak_action]})
    report = audit_color_strategy(
        weak,
        brief=brief,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
        required_action_signature=signature,
    )

    assert StrategyViolationCode.DIRECTION_CONVERGENCE in {
        item.code for item in report.violations
    }


def test_unknown_capability_parameter_mask_and_scope_fail_before_compiler() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[0]
    valid = _strategy(brief, retrieval)
    action = valid.actions[0]
    unknown_capability = action.model_copy(
        update={"action_id": "action:unknown-capability", "capability_id": "capability:fake"}
    )
    unknown_parameter = action.model_copy(
        update={
            "action_id": "action:unknown-parameter",
            "parameters": [
                action.parameters[0].model_copy(update={"name": "invented_parameter"})
            ],
        }
    )
    missing_mask = _action_for_direction(thesis.briefs[2].direction).model_copy(
        update={
            "action_id": "action:missing-mask",
            "serves_brief_id": brief.brief_id,
            "scope": StrategyScope(
                project_id="project:test",
                scene_id="scene:lake",
            ),
        }
    )
    outside_scope = action.model_copy(
        update={
            "action_id": "action:outside",
            "scope": StrategyScope(
                project_id="project:test",
                scene_id="scene:outside",
            ),
        }
    )
    changed = valid.model_copy(
        update={
            "actions": [
                unknown_capability,
                unknown_parameter,
                missing_mask,
                outside_scope,
            ]
        }
    )

    codes = {item.code for item in _audit(changed, brief, thesis, context, retrieval).violations}

    assert StrategyViolationCode.UNKNOWN_CAPABILITY in codes
    assert StrategyViolationCode.UNKNOWN_PARAMETER in codes
    assert StrategyViolationCode.MASK_VIOLATION in codes
    assert StrategyViolationCode.SCOPE_VIOLATION in codes


def test_baseline_is_read_only_and_balance_adjustments_are_explicitly_bounded() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[0]
    baseline = _baseline()
    baseline_before = canonical_sha256(baseline)
    valid = _strategy(brief, retrieval)
    balance = StrategyAction(
        action_id="action:balance",
        operation=StrategyOperation.BALANCE,
        scope=StrategyScope(project_id="project:test", scene_id="scene:lake"),
        parameters=[
            StrategyParameter(
                name="temperature",
                unit="normalized",
                minimum=-0.1,
                nominal=0.5,
                maximum=0.6,
            )
        ],
        serves_brief_id=brief.brief_id,
        evidence_ids=["frame:lake"],
        protected_attributes=[ProtectedAttribute.PROJECT_CONTINUITY],
        rationale="A claimed preservation that actually changes the measured baseline.",
        capability_id="capability:balance-temperature",
        intended_property=ColorProperty.TEMPERATURE,
        direction=AdjustmentDirection.WARMER,
        baseline_relationship=BaselineRelationship.PRESERVE,
    )
    changed = valid.model_copy(update={"actions": [balance]})

    codes = {
        item.code
        for item in _audit(changed, brief, thesis, context, retrieval).violations
    }

    assert StrategyViolationCode.BASELINE_POLICY in codes
    assert canonical_sha256(baseline) == baseline_before

    minor = balance.model_copy(
        update={
            "parameters": [
                balance.parameters[0].model_copy(
                    update={"minimum": 0, "nominal": 0.05, "maximum": 0.1}
                )
            ],
            "baseline_relationship": BaselineRelationship.MINOR_ADJUSTMENT,
        }
    )
    minor_strategy = valid.model_copy(update={"actions": [minor]})
    assert _audit(minor_strategy, brief, thesis, context, retrieval).valid is True


def test_missing_continuity_invented_evidence_and_lut_language_are_rejected() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[0]
    valid = _strategy(brief, retrieval)
    changed_action = valid.actions[0].model_copy(
        update={
            "evidence_ids": ["evidence:invented"],
            "rationale": "Apply a named LUT as the fixed answer.",
        }
    )
    changed = valid.model_copy(
        update={
            "actions": [changed_action],
            "continuity_constraints": [ProtectedAttribute.HIGHLIGHT_DETAIL],
        }
    )

    codes = {item.code for item in _audit(changed, brief, thesis, context, retrieval).violations}

    assert StrategyViolationCode.EVIDENCE_VIOLATION in codes
    assert StrategyViolationCode.CONTINUITY_VIOLATION in codes
    assert StrategyViolationCode.FORBIDDEN_IMPLEMENTATION in codes


def test_strategy_set_rejects_prose_only_direction_variants() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    faithful = _strategy(thesis.briefs[0], retrieval)
    converged = []
    for brief in thesis.briefs:
        action = faithful.actions[0].model_copy(
            update={
                "action_id": f"action:converged:{brief.direction.value}",
                "serves_brief_id": brief.brief_id,
            }
        )
        converged.append(
            _strategy(brief, retrieval).model_copy(update={"actions": [action]})
        )

    report = audit_color_strategy_set(
        converged,
        briefs=thesis.briefs,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
    )

    assert report.valid is False
    assert report.structurally_distinct_pairs == 0
    assert StrategyViolationCode.DIRECTION_CONVERGENCE in {
        item.code for item in report.violations
    }


async def test_provider_output_is_audited_before_becoming_a_strategy() -> None:
    thesis, context, retrieval = _retrieval_inputs()
    brief = thesis.briefs[0]
    valid = _strategy(brief, retrieval)
    request = build_color_strategist_request(
        brief=brief,
        thesis=thesis,
        thesis_asset_sha256=retrieval.thesis_sha256,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        context_asset_sha256=_sha("signed-context"),
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
        catalog_asset_sha256=_sha("signed-catalog"),
    )
    provider = FakeCreativeModelProvider(
        responses=[RawProviderResponse(text=valid.model_dump_json())]
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )

    outcome = await run_color_strategist(
        runtime,
        request=request,
        brief=brief,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
    )

    assert outcome.strategy_audit.valid is True
    assert outcome.strategy == valid

    invalid_action = valid.actions[0].model_copy(
        update={"capability_id": "capability:invented"}
    )
    invalid = valid.model_copy(update={"actions": [invalid_action]})
    invalid_provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(text=invalid.model_dump_json()),
            RawProviderResponse(text=valid.model_dump_json()),
        ]
    )
    invalid_runtime = CreativeProviderRuntime(
        {role: invalid_provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )
    repaired = await run_color_strategist(
        invalid_runtime,
        request=request,
        brief=brief,
        thesis=thesis,
        retrieval=retrieval,
        retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
        context=context,
        baseline=_baseline(),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        catalog=_catalog(),
    )
    assert repaired.strategy == valid
    assert invalid_provider.calls == 2
    request_payload = json.loads(request.prompt)
    repair_payload = json.loads(invalid_provider.requests[1].prompt)
    assert repair_payload["semantic_repair"]["required_action_bindings"] == [
        {
            "action_id": invalid_action.action_id,
            "serves_brief_id": brief.brief_id,
            "evidence_ids": ["frame:lake"],
            "capability_id": "capability:tone",
            "operation": "tone",
            "intended_property": "contrast",
            "direction": "preserve",
            "baseline_relationship": "preserve",
            "scope": {
                "project_id": "project:test",
                "scene_id": "scene:lake",
                "shot_id": None,
                "time_range": None,
                "mask_target": None,
            },
            "parameters": [
                {
                    "name": "contrast",
                    "unit": "normalized",
                    "minimum": 0.0,
                    "nominal": 0.0,
                    "maximum": 0.0,
                }
            ],
            "parameter_tracks": [],
        }
    ]
    assert repair_payload["semantic_repair"]["required_top_level_bindings"] == {
        "brief_id": brief.brief_id,
        "technical_baseline_asset_id": BASELINE_ASSET_ID,
        "technical_baseline_sha256": BASELINE_ASSET_SHA,
        "project_thesis_sha256": retrieval.thesis_sha256,
        "retrieval_bundle_sha256": RETRIEVAL_ASSET_SHA,
        "continuity_constraints": [
            item.value for item in thesis.shared_protections
        ],
        "selected_possibility_card_ids": request_payload["hard_contract"][
            "selected_possibility_card_ids"
        ],
        "scene_role": request_payload["hard_contract"]["scene_role"],
    }

    stubborn_provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(text=invalid.model_dump_json()),
            RawProviderResponse(text=invalid.model_dump_json()),
        ]
    )
    stubborn_runtime = CreativeProviderRuntime(
        {role: stubborn_provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )
    with pytest.raises(ColorStrategyValidationError) as error:
        await run_color_strategist(
            stubborn_runtime,
            request=request,
            brief=brief,
            thesis=thesis,
            retrieval=retrieval,
            retrieval_asset_sha256=RETRIEVAL_ASSET_SHA,
            context=context,
            baseline=_baseline(),
            baseline_asset_id=BASELINE_ASSET_ID,
            baseline_asset_sha256=BASELINE_ASSET_SHA,
            catalog=_catalog(),
        )
    assert StrategyViolationCode.UNKNOWN_CAPABILITY in {
        item.code for item in error.value.audit.violations
    }
