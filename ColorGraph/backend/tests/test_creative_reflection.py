from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from test_creative_critic import (
    _critic_output,
    _director_identity,
    _requests,
    _runtime,
)
from test_creative_search import _brief

from colorgraph.agent.creative_contracts import (
    CritiqueDimension,
    StrategyScope,
    TimeSpan,
    canonical_sha256,
)
from colorgraph.agent.creative_critic import (
    BlindPairwiseCriticOutput,
    build_blind_pairwise_critic_requests,
    run_blind_pairwise_critic,
)
from colorgraph.agent.creative_reflection import (
    FailureCaseReuseReview,
    FailureReuseTarget,
    PatchDirection,
    ReflectionBudget,
    ReflectionCompilePolicy,
    ReflectionDirective,
    ReflectionOutcomeStatus,
    ReflectionParameterTarget,
    ReflectionRunner,
    ReflectionSource,
    ReflectionStore,
    UserFeedbackAxis,
    build_user_reflection_directive,
    compile_reflection_directive,
    finalize_reflection,
    interpret_user_feedback,
    plan_critic_reflection_directive,
    promote_failure_case_for_reuse,
)
from colorgraph.agent.creative_search import (
    CandidateAttemptStatus,
    RenderedSearchSample,
)
from colorgraph.domain.grade_graph import GradeGraph, NodeType
from colorgraph.grading.looks import graph_digest

EVALUATED_AT = datetime(2026, 7, 30, 3, tzinfo=UTC)
THESIS_DIGEST = hashlib.sha256(b"reflection-thesis").hexdigest()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parent(tmp_path: Path):
    _, records = _requests(tmp_path)
    return records[0]


def _graph(record) -> GradeGraph:
    return GradeGraph.model_validate_json(
        Path(record.graph_path).read_text(encoding="utf-8"),
    )


def _target(
    record,
    *,
    direction: PatchDirection = PatchDirection.INCREASE,
    delta: float = 0.02,
) -> ReflectionParameterTarget:
    graph = _graph(record)
    node = next(
        item
        for item in graph.nodes
        if str(item.metadata.get("source", "")).startswith(
            "colorgraph.deterministic-strategy-compiler/"
        )
        and any(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in item.parameters.values()
        )
    )
    parameter, raw_value = next(
        (key, value)
        for key, value in sorted(node.parameters.items())
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    current = float(raw_value)
    return ReflectionParameterTarget(
        node_id=node.id,
        parameter=parameter,
        direction=direction,
        expected_current_value=current,
        absolute_delta=delta,
        minimum_allowed_value=current - 1,
        maximum_allowed_value=current + 1,
        scope=StrategyScope(
            project_id=graph.project_id,
            scene_id=node.temporal_scope.scene_id,
            shot_id=node.temporal_scope.shot_id,
            time_range=(
                TimeSpan(
                    start_seconds=node.temporal_scope.time_range.start_seconds,
                    end_seconds=node.temporal_scope.time_range.end_seconds,
                )
                if node.temporal_scope.time_range is not None
                else None
            ),
            mask_target=node.spatial_scope.target,
        ),
    )


def _directive(
    record,
    *,
    target: ReflectionParameterTarget | None = None,
    dimensions: list[CritiqueDimension] | None = None,
    confidence: float = 0.8,
) -> ReflectionDirective:
    selected_target = target or _target(record)
    return ReflectionDirective(
        directive_id="directive:test",
        source=ReflectionSource.CRITIC,
        parent_candidate_id=record.candidate_id,
        hypothesis="A minimal bounded change should improve the cited concept evidence.",
        target_dimensions=dimensions
        or [CritiqueDimension.CONCEPT_ALIGNMENT],
        evidence_ids=["critic:counterevidence:001"],
        expected_improvement="Improve the target without moving locked nodes.",
        maximum_allowed_regression=0.05,
        targets=[selected_target],
        confidence=confidence,
    )


class _ReflectionRenderer:
    renderer_version = "fake-reflection-renderer/v1"

    def __init__(self) -> None:
        self.calls = 0

    def render(self, *, parent_record, graph, output_dir):
        del graph
        self.calls += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered = []
        for sample in parent_record.samples:
            path = output_dir / f"refined-{sample.frame_index:08d}.png"
            Image.new("RGB", (32, 18), (122, 127, 132)).save(path)
            rendered.append(
                RenderedSearchSample(
                    frame_index=sample.frame_index,
                    time_seconds=sample.time_seconds,
                    source_path=sample.source_path,
                    source_sha256=sample.source_sha256,
                    current_path=sample.candidate_path,
                    current_sha256=sample.candidate_sha256,
                    candidate_path=str(path.resolve()),
                    candidate_sha256=_digest(path),
                    width=32,
                    height=18,
                )
            )
        return rendered


class _EscapingReflectionRenderer(_ReflectionRenderer):
    renderer_version = "fake-escaping-reflection-renderer/v1"

    def render(self, *, parent_record, graph, output_dir):
        rendered = super().render(
            parent_record=parent_record,
            graph=graph,
            output_dir=output_dir,
        )
        escaped = output_dir.parent / "escaped.png"
        Image.new("RGB", (32, 18), (122, 127, 132)).save(escaped)
        return [
            item.model_copy(
                update={
                    "candidate_path": str(escaped.resolve()),
                    "candidate_sha256": _digest(escaped),
                }
            )
            for item in rendered
        ]


class _IllegalReflectionRenderer(_ReflectionRenderer):
    renderer_version = "fake-illegal-reflection-renderer/v1"

    def render(self, *, parent_record, graph, output_dir):
        return [
            item.model_copy(update={"unclamped_finite_invalid": 1})
            for item in super().render(
                parent_record=parent_record,
                graph=graph,
                output_dir=output_dir,
            )
        ]


def _prepare(tmp_path: Path):
    parent = _parent(tmp_path)
    renderer = _ReflectionRenderer()
    store = ReflectionStore(tmp_path / "reflection")
    result = ReflectionRunner(renderer=renderer, store=store).prepare(
        run_id="reflection:run",
        parent_record=parent,
        directive=_directive(parent),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )
    assert result.preparation is not None
    return parent, result.preparation, renderer, store


def _profiled_output(
    context,
    *,
    preferred_candidate_id: str,
    profiles: dict[str, dict[CritiqueDimension, float]],
    confidences: dict[str, float] | None = None,
) -> BlindPairwiseCriticOutput:
    output = _critic_output(
        context,
        preferred_candidate_id=preferred_candidate_id,
    )
    assessments = []
    for assessment in output.assessments:
        candidate_id = context.label_to_candidate_id[assessment.label]
        profile = profiles[candidate_id]
        confidence = (confidences or {}).get(candidate_id, 0.8)
        assessments.append(
            assessment.model_copy(
                update={
                    "scores": [
                        score.model_copy(
                            update={
                                "score": profile.get(
                                    score.dimension,
                                    score.score,
                                ),
                                "confidence": confidence,
                            }
                        )
                        for score in assessment.scores
                    ]
                }
            )
        )
    return output.model_copy(update={"assessments": assessments})


async def _pairwise_report(
    parent,
    refined,
    *,
    preferred_candidate_id: str,
    profiles: dict[str, dict[CritiqueDimension, float]] | None = None,
    confidences: dict[str, float] | None = None,
):
    brief = _brief(parent.direction)
    requests = build_blind_pairwise_critic_requests(
        pair_id="pair:reflection",
        left_record=parent,
        left_brief=brief,
        left_exceptions=[],
        right_record=refined,
        right_brief=brief,
        right_exceptions=[],
        randomization_seed="reflection-seed",
    )
    if profiles is None:
        outputs = [
            _critic_output(
                context,
                preferred_candidate_id=preferred_candidate_id,
            )
            for context in requests
        ]
    else:
        outputs = [
            _profiled_output(
                context,
                preferred_candidate_id=preferred_candidate_id,
                profiles=profiles,
                confidences=confidences,
            )
            for context in requests
        ]
    return await run_blind_pairwise_critic(
        _runtime(outputs),
        requests=requests,
        director_identity=_director_identity(),
    )


async def test_critic_reflection_planner_selects_one_bounded_compiler_parameter(
    tmp_path: Path,
) -> None:
    _, records = _requests(tmp_path)
    parent, peer = records[:2]
    report = await _pairwise_report(
        parent,
        peer,
        preferred_candidate_id=parent.candidate_id,
    )
    critique = next(
        item
        for item in report.critiques
        if item.candidate_id == parent.candidate_id
    )

    directive = plan_critic_reflection_directive(
        parent_record=parent,
        critique=critique,
    )
    compiled = compile_reflection_directive(
        parent_record=parent,
        directive=directive,
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )

    assert directive.parent_candidate_id == parent.candidate_id
    assert len(directive.targets) == 1
    assert len(directive.target_dimensions) == 1
    target = directive.targets[0]
    assert (
        target.minimum_allowed_value
        <= target.expected_current_value
        <= target.maximum_allowed_value
    )
    assert target.absolute_delta <= (
        target.maximum_allowed_value - target.minimum_allowed_value
    ) * 0.025 + 1e-12
    assert compiled.compilation is not None
    assert len(compiled.compilation.patch.changes) == 1


def test_compiler_changes_only_named_creative_parameter_and_preserves_undo(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    source = _graph(parent)
    source_payload = source.model_dump(mode="json")
    directive = _directive(parent)

    result = compile_reflection_directive(
        parent_record=parent,
        directive=directive,
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )

    assert result.compilation is not None
    compiled = result.compilation
    change = compiled.patch.changes[0]
    before_nodes = {item.id: item for item in source.nodes}
    after_nodes = {item.id: item for item in compiled.graph.nodes}
    assert change.after_value - change.before_value == pytest.approx(0.02)
    assert (
        after_nodes[change.node_id].parameters[change.parameter]
        == change.after_value
    )
    for node_id in compiled.patch.locked_node_ids:
        assert after_nodes[node_id] == before_nodes[node_id]
    assert compiled.graph.masks == source.masks
    assert compiled.locked_mask_digests
    assert compiled.undo_graph.model_dump(mode="json") == source_payload
    assert graph_digest(compiled.undo_graph) == parent.compiled_graph_digest
    assert _graph(parent).model_dump(mode="json") == source_payload


def test_compiler_rejects_technical_stale_scope_and_nonminimal_targets(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    graph = _graph(parent)
    technical = next(
        item for item in graph.nodes if item.type == NodeType.INPUT_TRANSFORM
    )
    technical_parameter, value = next(iter(technical.parameters.items()))
    technical_target = ReflectionParameterTarget(
        node_id=technical.id,
        parameter=technical_parameter,
        direction=PatchDirection.INCREASE,
        expected_current_value=float(value) if isinstance(value, (int, float)) else 0,
        absolute_delta=0.01,
        minimum_allowed_value=-2,
        maximum_allowed_value=2,
        scope=StrategyScope(project_id=graph.project_id),
    )
    with pytest.raises(ValueError, match="color-management"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=technical_target),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
        )

    target = _target(parent)
    stale = target.model_copy(
        update={"expected_current_value": target.expected_current_value + 0.1}
    )
    with pytest.raises(ValueError, match="stale"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=stale),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
        )

    wrong_scope = target.model_copy(
        update={
            "scope": target.scope.model_copy(update={"scene_id": "scene:other"})
        }
    )
    with pytest.raises(ValueError, match="outside"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=wrong_scope),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
        )

    missing_time = target.model_copy(
        update={"scope": target.scope.model_copy(update={"time_range": None})}
    )
    with pytest.raises(ValueError, match="time range"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=missing_time),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
        )

    missing_region = target.model_copy(
        update={"scope": target.scope.model_copy(update={"mask_target": None})}
    )
    with pytest.raises(ValueError, match="mask target"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=missing_region),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
        )

    too_large = target.model_copy(update={"absolute_delta": 0.6})
    with pytest.raises(ValueError, match="minimal domain fraction"):
        compile_reflection_directive(
            parent_record=parent,
            directive=_directive(parent, target=too_large),
            project_thesis_digest=THESIS_DIGEST,
            evaluated_at=EVALUATED_AT,
            policy=ReflectionCompilePolicy(
                maximum_changed_parameters=2,
                maximum_parameter_domain_fraction=0.25,
                minimum_directive_confidence=0.5,
            ),
        )


def test_prepare_rerenders_same_frames_runs_qc_and_reuses_valid_cache(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    renderer = _ReflectionRenderer()
    runner = ReflectionRunner(
        renderer=renderer,
        store=ReflectionStore(tmp_path / "reflection-cache"),
    )
    arguments = {
        "run_id": "reflection:cache",
        "parent_record": parent,
        "directive": _directive(parent),
        "project_thesis_digest": THESIS_DIGEST,
        "evaluated_at": EVALUATED_AT,
    }

    first = runner.prepare(**arguments)
    second = runner.prepare(**arguments)

    assert first.preparation is not None
    assert second.preparation is not None
    assert first.preparation.cache_hit is False
    assert second.preparation.cache_hit is True
    assert renderer.calls == 1
    refined = first.preparation.refined_record
    assert refined.is_refinement is True
    assert refined.parent_candidate_id == parent.candidate_id
    assert refined.status == CandidateAttemptStatus.HARD_PASS
    assert refined.qc.hard_passed is True
    assert [item.frame_index for item in refined.samples] == [
        item.frame_index for item in parent.samples
    ]
    assert all(
        child.current_sha256 == source.candidate_sha256
        for child, source in zip(refined.samples, parent.samples, strict=True)
    )
    assert Path(refined.graph_path).is_file()
    assert Path(refined.undo_graph_path).is_file()


def test_corrupt_cache_is_rebuilt_and_store_paths_cannot_escape(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    renderer = _ReflectionRenderer()
    store = ReflectionStore(tmp_path / "reflection-cache")
    runner = ReflectionRunner(renderer=renderer, store=store)
    arguments = {
        "run_id": "..\\reflection/../../cache",
        "parent_record": parent,
        "directive": _directive(parent),
        "project_thesis_digest": THESIS_DIGEST,
        "evaluated_at": EVALUATED_AT,
    }
    first = runner.prepare(**arguments)
    assert first.preparation is not None
    preparation_path = store.preparation_path(
        arguments["run_id"],
        first.preparation.cache_key,
    )
    preparation_path.write_text("{corrupt", encoding="utf-8")

    rebuilt = runner.prepare(**arguments)
    cached = runner.prepare(**arguments)

    assert rebuilt.preparation is not None
    assert rebuilt.preparation.cache_hit is False
    assert cached.preparation is not None
    assert cached.preparation.cache_hit is True
    assert renderer.calls == 2
    assert preparation_path.is_relative_to(store.root)
    with pytest.raises(ValueError, match="SHA-256"):
        store.cache_dir("reflection", "..\\outside")


def test_escaped_render_output_and_unclamped_invalid_values_fail_closed(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    arguments = {
        "run_id": "reflection:invalid",
        "parent_record": parent,
        "directive": _directive(parent),
        "project_thesis_digest": THESIS_DIGEST,
        "evaluated_at": EVALUATED_AT,
    }
    escaped = ReflectionRunner(
        renderer=_EscapingReflectionRenderer(),
        store=ReflectionStore(tmp_path / "escaped"),
    ).prepare(**arguments)
    illegal = ReflectionRunner(
        renderer=_IllegalReflectionRenderer(),
        store=ReflectionStore(tmp_path / "illegal"),
    ).prepare(**arguments)

    assert escaped.preparation is not None
    assert (
        escaped.preparation.refined_record.status
        == CandidateAttemptStatus.RENDER_FAILED
    )
    assert "escaped assets" in escaped.preparation.refined_record.failure_detail
    assert illegal.preparation is not None
    assert (
        illegal.preparation.refined_record.status
        == CandidateAttemptStatus.HARD_FAIL
    )
    assert illegal.preparation.refined_record.qc.hard_passed is False
    finite = next(
        item
        for item in illegal.preparation.refined_record.qc.checks
        if item.check_id == "finite_values"
    )
    assert finite.passed is False


def test_pairwise_call_budget_stops_before_rendering(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    renderer = _ReflectionRenderer()
    result = ReflectionRunner(
        renderer=renderer,
        store=ReflectionStore(tmp_path / "budget"),
    ).prepare(
        run_id="reflection:budget",
        parent_record=parent,
        directive=_directive(parent),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
        budget=ReflectionBudget(
            maximum_refinements=1,
            maximum_rendered_frames=3,
            maximum_model_calls=1,
            maximum_cost_usd=1,
        ),
    )

    assert result.status == ReflectionOutcomeStatus.STOPPED_BUDGET
    assert result.preparation is None
    assert renderer.calls == 0


def test_budget_low_confidence_and_duplicate_patch_stop_without_rendering(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    low = compile_reflection_directive(
        parent_record=parent,
        directive=_directive(parent, confidence=0.2),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )
    first = compile_reflection_directive(
        parent_record=parent,
        directive=_directive(parent),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )
    duplicate = compile_reflection_directive(
        parent_record=parent,
        directive=_directive(parent),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
        prior_patch_digests=[first.patch_digest],
    )
    exhausted = compile_reflection_directive(
        parent_record=parent,
        directive=_directive(parent),
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
        budget=ReflectionBudget(
            maximum_refinements=0,
            maximum_rendered_frames=3,
            maximum_model_calls=0,
            maximum_cost_usd=0,
        ),
    )

    assert low.status == ReflectionOutcomeStatus.STOPPED_LOW_CONFIDENCE
    assert duplicate.status == ReflectionOutcomeStatus.STOPPED_DUPLICATE
    assert exhausted.status == ReflectionOutcomeStatus.STOPPED_BUDGET
    assert all(
        item.compilation is None for item in (low, duplicate, exhausted)
    )


def test_user_feedback_updates_existing_strategy_or_creates_explicit_branch(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    restrained = interpret_user_feedback(
        feedback="请让这个方向更克制一些",
        parent_strategy_id=parent.strategy_id,
        parent_thesis_digest=THESIS_DIGEST,
    )
    rewrite = interpret_user_feedback(
        feedback="更梦幻，并改写命题",
        parent_strategy_id=parent.strategy_id,
        parent_thesis_digest=THESIS_DIGEST,
    )
    directive = build_user_reflection_directive(
        branch=restrained,
        parent_record=parent,
        targets=[_target(parent, direction=PatchDirection.DECREASE)],
        maximum_allowed_regression=0.05,
    )

    assert restrained.axes == [UserFeedbackAxis.RESTRAINED]
    assert restrained.reanalyze_project is False
    assert restrained.requires_new_thesis_branch is False
    assert directive.source == ReflectionSource.USER
    assert CritiqueDimension.OVERGRADING_RISK in directive.target_dimensions
    assert rewrite.requires_new_thesis_branch is True
    assert rewrite.reanalyze_project is False
    with pytest.raises(ValueError, match="new explicit branch"):
        build_user_reflection_directive(
            branch=rewrite,
            parent_record=parent,
            targets=[_target(parent)],
            maximum_allowed_regression=0.05,
        )


async def test_accepted_reflection_selects_child_but_never_mutates_current_graph(
    tmp_path: Path,
) -> None:
    parent, preparation, _, store = _prepare(tmp_path)
    parent_before = Path(parent.graph_path).read_bytes()
    report = await _pairwise_report(
        parent,
        preparation.refined_record,
        preferred_candidate_id=preparation.refined_record.candidate_id,
    )

    first = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=report,
        store=store,
    )
    second = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=report,
        store=store,
    )

    assert first == second
    assert first.status == ReflectionOutcomeStatus.ACCEPTED
    assert first.accepted is True
    assert first.selected_candidate_id == preparation.refined_record.candidate_id
    assert first.failure_case is None
    assert first.current_graph_unchanged is True
    assert Path(parent.graph_path).read_bytes() == parent_before


async def test_finalize_rejects_evidence_changed_after_pairwise_review(
    tmp_path: Path,
) -> None:
    parent, preparation, _, _ = _prepare(tmp_path)
    report = await _pairwise_report(
        parent,
        preparation.refined_record,
        preferred_candidate_id=preparation.refined_record.candidate_id,
    )
    Image.new("RGB", (32, 18), (0, 0, 0)).save(
        parent.samples[0].candidate_path
    )

    with pytest.raises(ValueError, match="evidence assets changed"):
        finalize_reflection(
            parent_record=parent,
            preparation=preparation,
            pairwise_report=report,
        )


async def test_no_improvement_rolls_back_and_records_private_failure_case(
    tmp_path: Path,
) -> None:
    parent, preparation, _, _ = _prepare(tmp_path)
    refined = preparation.refined_record
    flat = {dimension: 0.6 for dimension in CritiqueDimension}
    report = await _pairwise_report(
        parent,
        refined,
        preferred_candidate_id=refined.candidate_id,
        profiles={
            parent.candidate_id: flat,
            refined.candidate_id: flat,
        },
    )

    outcome = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=report,
    )

    assert outcome.status == ReflectionOutcomeStatus.REJECTED_NO_PARETO_IMPROVEMENT
    assert outcome.accepted is False
    assert outcome.selected_candidate_id == parent.candidate_id
    assert outcome.selected_graph_digest == parent.compiled_graph_digest
    assert outcome.rollback_graph_digest == parent.compiled_graph_digest
    assert outcome.failure_case is not None
    assert outcome.failure_case.contains_private_data is True
    assert outcome.failure_case.reviewed_for_reuse is False
    assert outcome.failure_case.context_asset_id.startswith("context:project:")
    assert outcome.failure_case.repair_summary.startswith("Rolled back")


async def test_failure_case_requires_bound_human_review_before_reuse(
    tmp_path: Path,
) -> None:
    parent, preparation, _, _ = _prepare(tmp_path)
    refined = preparation.refined_record
    flat = {dimension: 0.6 for dimension in CritiqueDimension}
    report = await _pairwise_report(
        parent,
        refined,
        preferred_candidate_id=refined.candidate_id,
        profiles={
            parent.candidate_id: flat,
            refined.candidate_id: flat,
        },
    )
    outcome = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=report,
    )
    failure = outcome.failure_case
    assert failure is not None
    review = FailureCaseReuseReview(
        source_failure_id=failure.failure_id,
        source_failure_digest=canonical_sha256(failure),
        reviewer_id="reviewer:qualified:001",
        reviewed_at=EVALUATED_AT,
        human_review_completed=True,
        private_data_redacted=True,
        target=FailureReuseTarget.REGRESSION_FIXTURE,
        version="1.0.0",
        sanitized_context_asset_id="context:public:look-overreach",
        sanitized_operation_summary="A bounded look adjustment overreached.",
        sanitized_actual_harm="The target dimension did not improve.",
        sanitized_responsible_node_roles=["node-role:creative-look"],
        sanitized_repair_summary="Restore the immutable parent graph.",
        sanitized_evidence_ids=["fixture:public:look-overreach"],
    )

    promoted = promote_failure_case_for_reuse(
        failure_case=failure,
        review=review,
    )

    assert promoted.source_failure_digest == canonical_sha256(failure)
    assert promoted.sanitized_failure_case.reviewed_for_reuse is True
    assert promoted.sanitized_failure_case.contains_private_data is False
    assert promoted.sanitized_failure_case.candidate_id is None
    assert promoted.sanitized_failure_case.patch_id is None
    with pytest.raises(ValueError, match="another source"):
        promote_failure_case_for_reuse(
            failure_case=failure,
            review=review.model_copy(
                update={"source_failure_digest": "0" * 64}
            ),
        )
    with pytest.raises(ValueError):
        FailureCaseReuseReview(
            **{
                **review.model_dump(mode="python"),
                "human_review_completed": False,
            }
        )


async def test_untargeted_regression_and_intent_drift_are_distinct_stops(
    tmp_path: Path,
) -> None:
    parent, preparation, _, _ = _prepare(tmp_path)
    refined = preparation.refined_record
    baseline = {dimension: 0.6 for dimension in CritiqueDimension}
    improved = dict(baseline)
    improved[CritiqueDimension.CONCEPT_ALIGNMENT] = 0.8
    improved[CritiqueDimension.NATURALNESS] = 0.3
    regression_report = await _pairwise_report(
        parent,
        refined,
        preferred_candidate_id=refined.candidate_id,
        profiles={
            parent.candidate_id: baseline,
            refined.candidate_id: improved,
        },
    )
    regression = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=regression_report,
    )

    expressive_directive = _directive(
        parent,
        dimensions=[CritiqueDimension.EXPRESSIVE_STRENGTH],
    )
    expressive_result = compile_reflection_directive(
        parent_record=parent,
        directive=expressive_directive,
        project_thesis_digest=THESIS_DIGEST,
        evaluated_at=EVALUATED_AT,
    )
    expressive_preparation = preparation.model_copy(
        update={"compilation": expressive_result.compilation}
    )
    intent_refined = dict(baseline)
    intent_refined[CritiqueDimension.EXPRESSIVE_STRENGTH] = 0.8
    intent_refined[CritiqueDimension.CONCEPT_ALIGNMENT] = 0.3
    intent_report = await _pairwise_report(
        parent,
        refined,
        preferred_candidate_id=refined.candidate_id,
        profiles={
            parent.candidate_id: baseline,
            refined.candidate_id: intent_refined,
        },
    )
    drift = finalize_reflection(
        parent_record=parent,
        preparation=expressive_preparation,
        pairwise_report=intent_report,
    )

    assert regression.status == ReflectionOutcomeStatus.REJECTED_REGRESSION
    assert drift.status == ReflectionOutcomeStatus.REJECTED_INTENT_DRIFT
    assert any("intent_drift" in item for item in drift.stop_reasons)


async def test_pairwise_parent_preference_and_hard_qc_failure_both_roll_back(
    tmp_path: Path,
) -> None:
    parent, preparation, _, _ = _prepare(tmp_path)
    refined = preparation.refined_record
    baseline = {dimension: 0.6 for dimension in CritiqueDimension}
    improved = dict(baseline)
    improved[CritiqueDimension.CONCEPT_ALIGNMENT] = 0.8
    parent_preferred = await _pairwise_report(
        parent,
        refined,
        preferred_candidate_id=parent.candidate_id,
        profiles={
            parent.candidate_id: baseline,
            refined.candidate_id: improved,
        },
    )
    pairwise_rejected = finalize_reflection(
        parent_record=parent,
        preparation=preparation,
        pairwise_report=parent_preferred,
    )

    failed_checks = [
        item.model_copy(update={"passed": False})
        for item in refined.qc.checks
    ]
    failed_record = refined.model_copy(
        update={
            "status": CandidateAttemptStatus.HARD_FAIL,
            "qc": refined.qc.model_copy(
                update={"hard_passed": False, "checks": failed_checks}
            ),
        }
    )
    failed_preparation = preparation.model_copy(
        update={"refined_record": failed_record}
    )
    hard_rejected = finalize_reflection(
        parent_record=parent,
        preparation=failed_preparation,
        pairwise_report=parent_preferred,
    )

    assert pairwise_rejected.status == ReflectionOutcomeStatus.REJECTED_PAIRWISE
    assert hard_rejected.status == ReflectionOutcomeStatus.REJECTED_HARD_GATE
    assert pairwise_rejected.selected_candidate_id == parent.candidate_id
    assert hard_rejected.selected_candidate_id == parent.candidate_id
