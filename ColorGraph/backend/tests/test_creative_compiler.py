from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_creative_retrieval import _sha

from colorgraph.agent.creative_compiler import (
    MANDATORY_COMPILER_QC_CHECKS,
    ColorStrategyCompileError,
    CompilationPolicy,
    CompileViolationCode,
    OperationCardRegistry,
    apply_compiled_candidate,
    compile_color_strategy,
)
from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    BaselineRelationship,
    CardProvenance,
    ColorPipelineFacts,
    ColorProperty,
    ColorStrategy,
    ExceptionApprovalSource,
    ExceptionMetric,
    IntentionalException,
    IntentionalExceptionKind,
    OperationCard,
    OperationParameterSpec,
    ProtectedAttribute,
    StrategyAction,
    StrategyOperation,
    StrategyParameter,
    StrategyParameterTrack,
    StrategyScope,
    StrategyTrackPoint,
    TechnicalBaseline,
    TimeSpan,
)
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    MaskAsset,
    MediaInfo,
    NodeType,
    SpatialKind,
    TimeRange,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.services.graph_builder import build_initial_graph

BASELINE_ASSET_ID = "asset:compiler-baseline"
BASELINE_ASSET_SHA = _sha("compiler-baseline")


def _graph() -> GradeGraph:
    graph = build_initial_graph(
        project_id="project:test",
        project_name="Compiler Test",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=10,
            width=640,
            height=360,
            fps=25,
            frame_count=250,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=10)],
        representative_frames=[Path("shot.jpg")],
        scene_groups=[[0]],
    )
    payload = graph.model_dump(mode="python")
    payload["masks"] = [
        MaskAsset(
            id="mask:sky",
            kind=SpatialKind.SEMANTIC,
            target="sky",
            path="masks/sky",
            frame_count=250,
        ).model_dump(mode="python"),
        MaskAsset(
            id="mask:mountain",
            kind=SpatialKind.SEMANTIC,
            target="mountain",
            path="masks/mountain",
            frame_count=250,
        ).model_dump(mode="python"),
    ]
    return GradeGraph.model_validate(payload)


def _baseline(graph: GradeGraph) -> TechnicalBaseline:
    return TechnicalBaseline(
        graph_digest=graph_digest(graph),
        color_pipeline=ColorPipelineFacts(
            input_color_space=graph.media.input_color_space.value,
            working_color_space=graph.working_color_space.value,
            output_color_space=graph.output_color_space.value,
            renderer_version=graph.renderer_version,
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


def _provenance() -> CardProvenance:
    return CardProvenance(
        source_id="source:renderer-contract",
        source_uri="internal://renderer-contract",
        source_version="v1",
        rights="internal-authorized",
        permitted_uses=["compiler"],
        redistributable=False,
    )


def _card(
    *,
    card_id: str,
    operation: StrategyOperation,
    parameter: str,
    node_type: NodeType,
    order_hint: int,
    scopes: list[str],
    must_follow: list[StrategyOperation] | None = None,
    must_precede: list[StrategyOperation] | None = None,
    conflicts_with: list[StrategyOperation] | None = None,
    requires_mask: bool = False,
    allowed_mask_targets: list[str] | None = None,
    composite_expression: str | None = None,
    conflicts_with_protections: list[ProtectedAttribute] | None = None,
    renderer_parameter: str | None = None,
) -> OperationCard:
    return OperationCard(
        card_id=card_id,
        card_version="v1",
        provenance=_provenance(),
        operation=operation,
        parameters=[
            OperationParameterSpec(
                name=parameter,
                unit="normalized",
                minimum=-1,
                maximum=1,
                semantic=f"Normalized {parameter} renderer intent.",
            )
        ],
        supported_color_spaces=["acescg"],
        scopes=scopes,
        reversibility=True,
        information_loss=False,
        requires_linear_light=False,
        must_precede=must_precede or [],
        must_follow=must_follow or [],
        conflicts_with=conflicts_with or [],
        may_cause=["bounded tonal or chromatic change"],
        validation_checks=["finite_values", "legal_output_gamut"],
        repair_guidance=["Reduce the bounded parameter range."],
        invalidation_scope="Only the compiled candidate and its previews.",
        renderer_node_type=node_type.value,
        parameter_mapping={parameter: renderer_parameter or parameter},
        order_hint=order_hint,
        requires_mask=requires_mask,
        allowed_mask_targets=allowed_mask_targets or [],
        composite_expression=composite_expression,
        conflicts_with_protections=conflicts_with_protections or [],
    )


def _cards() -> list[OperationCard]:
    return [
        _card(
            card_id="capability:tone",
            operation=StrategyOperation.TONE,
            parameter="contrast",
            node_type=NodeType.TONE,
            order_hint=50,
            scopes=["scene", "shot", "time"],
            must_follow=[StrategyOperation.BALANCE],
            must_precede=[StrategyOperation.LOOK],
        ),
        _card(
            card_id="capability:masked-saturation",
            operation=StrategyOperation.MASKED_GRADE,
            parameter="saturation",
            node_type=NodeType.MASKED_GRADE,
            order_hint=70,
            scopes=["mask"],
            must_follow=[StrategyOperation.BALANCE],
            must_precede=[StrategyOperation.LOOK],
            requires_mask=True,
            allowed_mask_targets=["sky"],
        ),
        _card(
            card_id="capability:look-saturation",
            operation=StrategyOperation.LOOK,
            parameter="saturation",
            node_type=NodeType.LOOK,
            order_hint=120,
            scopes=["scene", "shot"],
            must_follow=[StrategyOperation.BALANCE],
        ),
    ]


def _parameter(
    name: str,
    *,
    minimum: float,
    nominal: float,
    maximum: float,
) -> StrategyParameter:
    return StrategyParameter(
        name=name,
        unit="normalized",
        minimum=minimum,
        nominal=nominal,
        maximum=maximum,
    )


def _action(
    *,
    action_id: str,
    operation: StrategyOperation,
    capability_id: str,
    parameter: StrategyParameter,
    property_name: ColorProperty,
    direction: AdjustmentDirection,
    mask_target: str | None = None,
) -> StrategyAction:
    return StrategyAction(
        action_id=action_id,
        operation=operation,
        scope=StrategyScope(
            project_id="project:test",
            scene_id="scene_001",
            mask_target=mask_target,
        ),
        parameters=[parameter],
        serves_brief_id="brief:amplified",
        evidence_ids=["frame:001"],
        protected_attributes=[ProtectedAttribute.PROJECT_CONTINUITY],
        rationale="A bounded action grounded in the frozen visual hierarchy.",
        capability_id=capability_id,
        intended_property=property_name,
        direction=direction,
        baseline_relationship=BaselineRelationship.PRESERVE,
    )


def _strategy() -> ColorStrategy:
    return ColorStrategy(
        strategy_id="strategy:compiler-test",
        brief_id="brief:amplified",
        technical_baseline_asset_id=BASELINE_ASSET_ID,
        technical_baseline_sha256=BASELINE_ASSET_SHA,
        common_language="Preserve the source pipeline and create bounded separation.",
        actions=[
            _action(
                action_id="action:tone",
                operation=StrategyOperation.TONE,
                capability_id="capability:tone",
                parameter=_parameter(
                    "contrast",
                    minimum=-0.1,
                    nominal=0.1,
                    maximum=0.3,
                ),
                property_name=ColorProperty.CONTRAST,
                direction=AdjustmentDirection.INCREASE,
            ),
            _action(
                action_id="action:sky",
                operation=StrategyOperation.MASKED_GRADE,
                capability_id="capability:masked-saturation",
                parameter=_parameter(
                    "saturation",
                    minimum=-0.3,
                    nominal=-0.1,
                    maximum=0.1,
                ),
                property_name=ColorProperty.SATURATION,
                direction=AdjustmentDirection.DECREASE,
                mask_target="sky",
            ),
            _action(
                action_id="action:look",
                operation=StrategyOperation.LOOK,
                capability_id="capability:look-saturation",
                parameter=_parameter(
                    "saturation",
                    minimum=0,
                    nominal=0.15,
                    maximum=0.3,
                ),
                property_name=ColorProperty.SATURATION,
                direction=AdjustmentDirection.INCREASE,
            ),
        ],
        alternatives_not_selected=["A stronger global contrast move was not selected."],
        continuity_constraints=[ProtectedAttribute.PROJECT_CONTINUITY],
        failure_conditions=["Output gamut or project continuity fails."],
        scene_role="A bounded scene-level movement.",
        tonal_structure=["Tone precedes local shaping and the final look."],
        color_relationships=["The sky remains subordinate to the reflection."],
        visual_hierarchy=["Reflection first, sky second."],
        local_region_intents=["Reduce only the declared sky mask."],
    )


def _policy(*, maximum_variants: int = 2) -> CompilationPolicy:
    return CompilationPolicy(
        maximum_variants=maximum_variants,
        variation_fraction=0.25,
        non_waivable_qc_checks=sorted(MANDATORY_COMPILER_QC_CHECKS),
    )


def _compile(
    graph: GradeGraph,
    *,
    strategy: ColorStrategy | None = None,
    cards: list[OperationCard] | None = None,
    policy: CompilationPolicy | None = None,
    expected_digest: str | None = None,
):
    return compile_color_strategy(
        strategy or _strategy(),
        source_graph=graph,
        expected_source_graph_digest=expected_digest or graph_digest(graph),
        technical_baseline=_baseline(graph),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        registry=OperationCardRegistry(cards or _cards()),
        policy=policy or _policy(),
    )


def test_compiler_is_deterministic_reversible_and_never_mutates_source() -> None:
    graph = _graph()
    source_payload = graph.model_dump(mode="json")

    first = _compile(graph)
    second = _compile(graph)

    assert first.audit.valid is True
    assert len(first.candidates) == 3
    assert [
        item.contract.model_dump(mode="json") for item in first.candidates
    ] == [
        item.contract.model_dump(mode="json") for item in second.candidates
    ]
    assert graph.model_dump(mode="json") == source_payload
    assert all(
        item.undo_graph.model_dump(mode="json") == source_payload
        for item in first.candidates
    )
    nominal = first.candidates[0]
    creative_nodes = [
        node
        for node in nominal.graph.nodes
        if node.metadata.get("source")
        == "colorgraph.deterministic-strategy-compiler/v1"
    ]
    assert [node.order for node in creative_nodes] == [50, 70, 120]
    assert [node.type for node in creative_nodes] == [
        NodeType.TONE,
        NodeType.MASKED_GRADE,
        NodeType.LOOK,
    ]
    assert nominal.contract.operation_card_versions == {
        "capability:tone": "v1",
        "capability:masked-saturation": "v1",
        "capability:look-saturation": "v1",
    }
    assert set(nominal.required_qc_checks) == MANDATORY_COMPILER_QC_CHECKS


def test_candidate_graphs_do_not_share_mutable_state() -> None:
    graph = _graph()
    result = _compile(graph)
    first_node = next(
        node
        for node in result.candidates[0].graph.nodes
        if node.id.startswith("creative_")
    )
    second_node = next(
        node
        for node in result.candidates[1].graph.nodes
        if node.id == first_node.id
    )
    original_second = dict(second_node.parameters)

    first_node.parameters["contrast"] = 0.99

    assert second_node.parameters == original_second
    assert all(
        not node.id.startswith("creative_")
        for node in graph.nodes
    )


def test_invalid_parameter_mask_scope_and_stale_input_fail_as_a_whole() -> None:
    graph = _graph()
    strategy = _strategy()
    tone, masked, look = strategy.actions
    invalid_parameter = tone.model_copy(
        update={
            "parameters": [
                tone.parameters[0].model_copy(update={"name": "invented_parameter"})
            ]
        }
    )
    missing_mask = masked.model_copy(
        update={
            "scope": StrategyScope(
                project_id="project:test",
                scene_id="scene_001",
            )
        }
    )
    outside = look.model_copy(
        update={
            "scope": StrategyScope(
                project_id="project:test",
                scene_id="scene:outside",
            )
        }
    )
    changed = strategy.model_copy(
        update={"actions": [invalid_parameter, missing_mask, outside]}
    )
    source_before = graph.model_dump(mode="json")

    with pytest.raises(ColorStrategyCompileError) as error:
        _compile(
            graph,
            strategy=changed,
            expected_digest=_sha("stale"),
        )

    codes = {item.code for item in error.value.audit.violations}
    assert CompileViolationCode.STALE_INPUT in codes
    assert CompileViolationCode.PARAMETER_INVALID in codes
    assert CompileViolationCode.MASK_UNAVAILABLE in codes
    assert CompileViolationCode.SCOPE_INVALID in codes
    assert graph.model_dump(mode="json") == source_before


def test_wrong_color_space_unknown_renderer_mapping_and_protection_conflict_fail() -> None:
    graph = _graph()
    graph_payload = graph.model_dump(mode="python")
    graph_payload["working_color_space"] = ColorSpace.ACESCCT
    wrong_space = GradeGraph.model_validate(graph_payload)
    bad_tone = _cards()[0].model_copy(
        update={
            "parameter_mapping": {"contrast": "lut_path"},
            "conflicts_with_protections": [ProtectedAttribute.PROJECT_CONTINUITY],
        }
    )

    with pytest.raises(ColorStrategyCompileError) as error:
        compile_color_strategy(
            _strategy(),
            source_graph=wrong_space,
            expected_source_graph_digest=graph_digest(wrong_space),
            technical_baseline=_baseline(wrong_space),
            baseline_asset_id=BASELINE_ASSET_ID,
            baseline_asset_sha256=BASELINE_ASSET_SHA,
            registry=OperationCardRegistry([bad_tone, *_cards()[1:]]),
            policy=_policy(),
        )

    codes = {item.code for item in error.value.audit.violations}
    assert CompileViolationCode.COLOR_SPACE_INVALID in codes
    assert CompileViolationCode.CARD_MAPPING in codes
    assert CompileViolationCode.PROTECTION_CONFLICT in codes


def test_dependency_cycles_and_operation_conflicts_are_rejected() -> None:
    graph = _graph()
    tone, masked, look = _cards()
    cyclic_tone = tone.model_copy(
        update={"must_follow": [StrategyOperation.LOOK]}
    )
    cyclic_look = look.model_copy(
        update={"must_follow": [StrategyOperation.TONE]}
    )
    conflicting_mask = masked.model_copy(
        update={"conflicts_with": [StrategyOperation.LOOK]}
    )

    with pytest.raises(ColorStrategyCompileError) as error:
        _compile(
            graph,
            cards=[cyclic_tone, conflicting_mask, cyclic_look],
        )

    codes = {item.code for item in error.value.audit.violations}
    assert CompileViolationCode.DEPENDENCY_INVALID in codes
    assert CompileViolationCode.CONFLICT in codes


def test_keyframe_and_composite_mask_cards_compile_to_existing_graph_semantics() -> None:
    graph = _graph()
    keyframe_card = _card(
        card_id="capability:keyframe-exposure",
        operation=StrategyOperation.KEYFRAME,
        parameter="exposure",
        node_type=NodeType.TONE,
        order_hint=55,
        scopes=["time"],
        must_follow=[StrategyOperation.BALANCE],
        must_precede=[StrategyOperation.LOOK],
    )
    composite_card = _card(
        card_id="capability:composite-sky",
        operation=StrategyOperation.COMPOSITE_MASK,
        parameter="highlights",
        node_type=NodeType.MASKED_GRADE,
        order_hint=75,
        scopes=["mask"],
        must_follow=[StrategyOperation.BALANCE],
        must_precede=[StrategyOperation.LOOK],
        requires_mask=True,
        allowed_mask_targets=["sky_without_mountain"],
        composite_expression="sky AND NOT mountain",
    )
    keyframe = StrategyAction(
        action_id="action:keyframe",
        operation=StrategyOperation.KEYFRAME,
        scope=StrategyScope(
            project_id="project:test",
            scene_id="scene_001",
            shot_id="shot_001",
            time_range=TimeSpan(start_seconds=1, end_seconds=9),
        ),
        parameters=[
            _parameter("exposure", minimum=-0.2, nominal=0, maximum=0.2)
        ],
        serves_brief_id="brief:amplified",
        evidence_ids=["frame:001"],
        protected_attributes=[ProtectedAttribute.PROJECT_CONTINUITY],
        rationale="Track only the declared lighting interval.",
        capability_id="capability:keyframe-exposure",
        intended_property=ColorProperty.EXPOSURE,
        direction=AdjustmentDirection.CONTEXT_DEPENDENT,
        parameter_tracks=[
            StrategyParameterTrack(
                parameter="exposure",
                points=[
                    StrategyTrackPoint(time_seconds=1, value=-0.1),
                    StrategyTrackPoint(time_seconds=5, value=0.1),
                    StrategyTrackPoint(time_seconds=9, value=0),
                ],
            )
        ],
    )
    composite = _action(
        action_id="action:composite",
        operation=StrategyOperation.COMPOSITE_MASK,
        capability_id="capability:composite-sky",
        parameter=_parameter(
            "highlights",
            minimum=-0.3,
            nominal=-0.15,
            maximum=0,
        ),
        property_name=ColorProperty.HIGHLIGHT_ROLLOFF,
        direction=AdjustmentDirection.DECREASE,
        mask_target="sky_without_mountain",
    )
    strategy = _strategy().model_copy(update={"actions": [keyframe, composite]})

    result = _compile(
        graph,
        strategy=strategy,
        cards=[keyframe_card, composite_card],
        policy=_policy(maximum_variants=0),
    )
    nodes = [
        item
        for item in result.candidates[0].graph.nodes
        if item.id.startswith("creative_")
    ]

    assert len(nodes[0].tracks) == 1
    assert [point.value for point in nodes[0].tracks[0].keyframes] == [
        -0.1,
        0.1,
        0,
    ]
    assert nodes[1].spatial_scope.kind == SpatialKind.COMPOSITE
    assert nodes[1].spatial_scope.expression == "sky AND NOT mountain"


def test_invalid_keyframe_or_composite_operand_is_rejected_before_graph_creation() -> None:
    graph = _graph()
    keyframe_card = _card(
        card_id="capability:keyframe-exposure",
        operation=StrategyOperation.KEYFRAME,
        parameter="exposure",
        node_type=NodeType.TONE,
        order_hint=55,
        scopes=["time"],
        must_follow=[StrategyOperation.BALANCE],
        must_precede=[StrategyOperation.LOOK],
    )
    bad_composite_card = _card(
        card_id="capability:bad-composite",
        operation=StrategyOperation.COMPOSITE_MASK,
        parameter="highlights",
        node_type=NodeType.MASKED_GRADE,
        order_hint=75,
        scopes=["mask"],
        must_follow=[StrategyOperation.BALANCE],
        must_precede=[StrategyOperation.LOOK],
        requires_mask=True,
        allowed_mask_targets=["bad-composite"],
        composite_expression="sky AND missing_mask",
    )
    missing_track = _action(
        action_id="action:keyframe",
        operation=StrategyOperation.KEYFRAME,
        capability_id="capability:keyframe-exposure",
        parameter=_parameter("exposure", minimum=-0.2, nominal=0, maximum=0.2),
        property_name=ColorProperty.EXPOSURE,
        direction=AdjustmentDirection.CONTEXT_DEPENDENT,
    ).model_copy(
        update={
            "scope": StrategyScope(
                project_id="project:test",
                scene_id="scene_001",
                time_range=TimeSpan(start_seconds=1, end_seconds=9),
            )
        }
    )
    bad_composite = _action(
        action_id="action:bad-composite",
        operation=StrategyOperation.COMPOSITE_MASK,
        capability_id="capability:bad-composite",
        parameter=_parameter(
            "highlights",
            minimum=-0.3,
            nominal=-0.1,
            maximum=0,
        ),
        property_name=ColorProperty.HIGHLIGHT_ROLLOFF,
        direction=AdjustmentDirection.DECREASE,
        mask_target="bad-composite",
    )
    strategy = _strategy().model_copy(
        update={"actions": [missing_track, bad_composite]}
    )

    with pytest.raises(ColorStrategyCompileError) as error:
        _compile(
            graph,
            strategy=strategy,
            cards=[keyframe_card, bad_composite_card],
            policy=_policy(maximum_variants=0),
        )

    codes = {item.code for item in error.value.audit.violations}
    assert CompileViolationCode.KEYFRAME_INVALID in codes
    assert CompileViolationCode.MASK_UNAVAILABLE in codes


def test_candidate_application_requires_confirmation_and_current_source_digest() -> None:
    graph = _graph()
    candidate = _compile(graph).candidates[0]

    applied = apply_compiled_candidate(
        candidate,
        current_graph=graph,
        confirmation="user",
    )

    assert applied.previous_graph_digest == graph_digest(graph)
    assert applied.applied_graph_digest == candidate.contract.compiled_graph_digest
    assert applied.undo_graph.model_dump(mode="json") == graph.model_dump(mode="json")
    with pytest.raises(ValueError, match="confirmation"):
        apply_compiled_candidate(
            candidate,
            current_graph=graph,
            confirmation="automatic",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="stale"):
        apply_compiled_candidate(
            candidate,
            current_graph=candidate.graph,
            confirmation="selector",
        )


def test_intentional_exception_must_bind_source_and_compiled_candidate() -> None:
    graph = _graph()
    masked_card = _cards()[1]
    single_strategy = _strategy().model_copy(
        update={"actions": [_strategy().actions[1]]}
    )
    base = _compile(
        graph,
        strategy=single_strategy,
        cards=[masked_card],
        policy=_policy(maximum_variants=0),
    )
    candidate_digest = base.candidates[0].contract.compiled_graph_digest
    exception = IntentionalException(
        exception_id="exception:sky-saturation",
        kind=IntentionalExceptionKind.SELECTIVE_SATURATION_PUSH,
        reason="A bounded local departure serves the declared sky relationship.",
        evidence_ids=["frame:001"],
        scope=StrategyScope(
            project_id="project:test",
            scene_id="scene_001",
            mask_target="sky",
        ),
        metric=ExceptionMetric.OVERSATURATION_RATIO,
        maximum_metric_value=0.03,
        protected_attributes=[ProtectedAttribute.NATURAL_SATURATION],
        approval_source=ExceptionApprovalSource.AUTOMATIC,
        source_graph_digest=graph_digest(graph),
        candidate_digest=candidate_digest,
        declared_at=datetime(2026, 7, 29, 10, tzinfo=UTC),
        invalidation_conditions=["Graph, candidate, scope, or evidence digest changes."],
    )
    conflict_card = masked_card.model_copy(
        update={
            "conflicts_with_protections": [
                ProtectedAttribute.NATURAL_SATURATION
            ]
        }
    )
    with_exception = single_strategy.model_copy(
        update={
            "continuity_constraints": [
                ProtectedAttribute.PROJECT_CONTINUITY,
                ProtectedAttribute.NATURAL_SATURATION,
            ],
            "actions": [
                single_strategy.actions[0].model_copy(
                    update={
                        "protected_attributes": [
                            ProtectedAttribute.PROJECT_CONTINUITY,
                            ProtectedAttribute.NATURAL_SATURATION,
                        ]
                    }
                )
            ],
            "intentional_exceptions": [exception],
        }
    )

    result = _compile(
        graph,
        strategy=with_exception,
        cards=[conflict_card],
        policy=_policy(maximum_variants=0),
    )
    assert result.candidates[0].contract.compiled_graph_digest == candidate_digest

    stale_exception = exception.model_copy(
        update={"candidate_digest": _sha("another-candidate")}
    )
    stale = with_exception.model_copy(
        update={"intentional_exceptions": [stale_exception]}
    )
    with pytest.raises(ColorStrategyCompileError) as error:
        _compile(
            graph,
            strategy=stale,
            cards=[conflict_card],
            policy=_policy(maximum_variants=0),
        )
    assert CompileViolationCode.EXCEPTION_INVALID in {
        item.code for item in error.value.audit.violations
    }


def test_compiler_policy_cannot_drop_non_waivable_delivery_checks() -> None:
    with pytest.raises(ValueError, match="mandatory QC"):
        CompilationPolicy(
            maximum_variants=0,
            variation_fraction=0.25,
            non_waivable_qc_checks=["finite_values"],
        )
