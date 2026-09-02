from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from colorgraph.domain.grade_graph import (
    ColorSpace,
    Interpolation,
    Keyframe,
    MediaInfo,
    NodeType,
    ParameterTrack,
    SpatialKind,
    SpatialScope,
    TimeRange,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.quality.models import (
    CheckStatus,
    QualityCategory,
    QualityCheck,
    QualityReport,
)
from colorgraph.quality.repair import (
    REPAIR_SEARCH_VERSION,
    RepairAttempt,
    RepairAttemptDecision,
    RepairBenchmarkCase,
    RepairPolicy,
    RepairScopeEvidence,
    RepairSearchResult,
    search_technical_repairs,
    summarize_repair_benchmark,
)
from colorgraph.quality.temporal_motion import analyze_temporal_frames
from colorgraph.services.graph_builder import build_initial_graph


def _graph():
    return build_initial_graph(
        project_id="repair-search",
        project_name="Repair search",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=4,
            width=640,
            height=360,
            fps=25,
            frame_count=100,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=4)],
        representative_frames=[Path("shot.jpg")],
    )


def _check(
    identifier: str,
    value: float,
    *,
    warning: float,
    failure: float,
    category: QualityCategory,
) -> QualityCheck:
    status = (
        CheckStatus.FAIL
        if value >= failure
        else CheckStatus.WARN if value >= warning else CheckStatus.PASS
    )
    return QualityCheck(
        id=identifier,
        label=identifier,
        status=status,
        value=value,
        threshold=failure,
        unit="ratio",
        detail="deterministic repair fixture",
        category=category,
        metric_version="test/v1",
    )


def _report(
    objective_id: str,
    value: float,
    *,
    warning: float,
    failure: float,
    hard_failure: bool = False,
    temporal_evidence=None,
) -> QualityReport:
    objective = _check(
        objective_id,
        value,
        warning=warning,
        failure=failure,
        category=QualityCategory.PERCEPTUAL_RISK,
    )
    metadata = QualityCheck(
        id="metadata",
        label="metadata",
        status=CheckStatus.FAIL if hard_failure else CheckStatus.PASS,
        value=0.0 if hard_failure else 1.0,
        threshold=1.0,
        unit="boolean",
        detail="deterministic hard gate",
        category=QualityCategory.HARD_TECHNICAL,
        metric_version="test/v1",
    )
    return QualityReport(
        source_path="source.mp4",
        output_path="graded.mp4",
        sampled_frames=10,
        score=50 if objective.status == CheckStatus.FAIL else 90,
        hard_checks_passed=not hard_failure,
        checks=[metadata, objective],
        summary="fixture",
        technical_score=0 if hard_failure else 100,
        perceptual_risk_score=50 if objective.status == CheckStatus.FAIL else 90,
        technical_hard_failures=["metadata"] if hard_failure else [],
        perceptual_risks=(
            [objective_id] if objective.status != CheckStatus.PASS else []
        ),
        temporal_evidence=temporal_evidence,
    )


def _saturation_value(graph) -> float:
    return sum(
        max(0.0, float(node.parameters.get("saturation", 0.0)))
        for node in graph.nodes
        if node.enabled and node.type == NodeType.LOOK
    )


def test_search_ablates_responsible_node_and_improves_over_multiple_rounds() -> None:
    graph = _graph()
    original_look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    original_look.parameters = {
        "strength": 0.72,
        "saturation": 0.03,
    }
    culprit = original_look.model_copy(deep=True)
    culprit.id = "look_culprit"
    culprit.order = original_look.order + 1
    culprit.parameters = {
        "strength": 1.0,
        "saturation": 0.45,
    }
    graph.nodes.insert(-1, culprit)

    def evaluate(candidate):
        return _report(
            "oversaturation",
            _saturation_value(candidate),
            warning=0.10,
            failure=0.20,
        )

    baseline = evaluate(graph)
    result = search_technical_repairs(
        graph,
        baseline,
        evaluate,
        policy=RepairPolicy(
            evaluation_budget=8,
            maximum_rounds=3,
            maximum_ablation_nodes=3,
            beam_width=2,
            maximum_intent_drift=0.60,
        ),
    )

    assert result.accepted is True
    assert result.accepted_rounds == 3
    assert result.final_objective_loss < result.initial_objective_loss
    assert result.report.perceptual_risks == []
    assert result.evaluations <= 8
    responsible = max(result.ablations, key=lambda item: item.improvement)
    assert responsible.node_id == "look_culprit"
    repaired_culprit = next(
        node for node in result.graph.nodes if node.id == "look_culprit"
    )
    repaired_safe = next(
        node for node in result.graph.nodes if node.id == original_look.id
    )
    assert repaired_culprit.parameters["saturation"] < 0.10
    assert repaired_safe.parameters["saturation"] == pytest.approx(0.03)
    history = result.graph.metadata["verifier_repairs"][-1]
    assert history["schema"] == REPAIR_SEARCH_VERSION
    assert history["accepted_rounds"] == 3
    assert history["rollback_count"] == result.rollback_count


def test_search_rolls_back_when_a_repair_regresses_a_hard_metric() -> None:
    graph = _graph()
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters["saturation"] = 0.45
    original_digest = graph_digest(graph)

    def evaluate(candidate):
        saturation = _saturation_value(candidate)
        return _report(
            "oversaturation",
            saturation,
            warning=0.10,
            failure=0.20,
            hard_failure=saturation < 0.40,
        )

    result = search_technical_repairs(
        graph,
        evaluate(graph),
        evaluate,
        policy=RepairPolicy(evaluation_budget=5, maximum_ablation_nodes=1),
    )

    assert result.accepted is False
    assert graph_digest(result.graph) == original_digest
    assert result.report.hard_checks_passed is True
    assert result.rollback_count >= 1
    assert RepairAttemptDecision.HARD_METRIC_REGRESSION in {
        attempt.decision for attempt in result.attempts
    }
    assert all(
        attempt.decision != RepairAttemptDecision.ACCEPTED
        for attempt in result.attempts
    )


def test_search_rolls_back_when_external_intent_drift_exceeds_budget() -> None:
    graph = _graph()
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters["saturation"] = 0.35
    baseline = _report(
        "oversaturation",
        _saturation_value(graph),
        warning=0.10,
        failure=0.20,
    )

    result = search_technical_repairs(
        graph,
        baseline,
        lambda candidate: _report(
            "oversaturation",
            _saturation_value(candidate),
            warning=0.10,
            failure=0.20,
        ),
        policy=RepairPolicy(
            evaluation_budget=4,
            maximum_ablation_nodes=1,
            maximum_intent_drift=0.10,
        ),
        intent_drift_evaluator=lambda baseline_graph, candidate_graph: 0.50,
    )

    assert result.accepted is False
    assert result.rollback_count >= 1
    assert {
        attempt.decision for attempt in result.attempts
    } == {RepairAttemptDecision.INTENT_DRIFT_EXCEEDED}


def test_search_rejects_non_target_quality_side_effects() -> None:
    graph = _graph()
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters["saturation"] = 0.35

    def evaluate(candidate):
        saturation = _saturation_value(candidate)
        report = _report(
            "oversaturation",
            saturation,
            warning=0.10,
            failure=0.20,
        )
        banding = _check(
            "banding_risk",
            0.40 if saturation < 0.30 else 0.0,
            warning=0.18,
            failure=0.30,
            category=QualityCategory.PERCEPTUAL_RISK,
        )
        report.checks.append(banding)
        if banding.status != CheckStatus.PASS:
            report.perceptual_risks.append(banding.id)
        return report

    result = search_technical_repairs(
        graph,
        evaluate(graph),
        evaluate,
        policy=RepairPolicy(evaluation_budget=4, maximum_ablation_nodes=1),
    )

    assert result.accepted is False
    assert RepairAttemptDecision.QUALITY_SIDE_EFFECT in {
        attempt.decision for attempt in result.attempts
    }


def test_temporal_evidence_limits_track_repair_to_offending_keyframes() -> None:
    graph = _graph()
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.tracks = [
        ParameterTrack(
            parameter="exposure",
            keyframes=[
                Keyframe(time_seconds=0, value=0),
                Keyframe(time_seconds=1, value=0),
                Keyframe(time_seconds=2, value=1),
                Keyframe(time_seconds=3, value=0),
                Keyframe(time_seconds=4, value=0),
            ],
            interpolation=Interpolation.PCHIP,
        )
    ]
    rng = np.random.default_rng(91)
    source = np.round(
        np.repeat(
            (rng.random((64, 96), dtype=np.float32) * 0.60 + 0.20)[..., None],
            3,
            axis=2,
        )
        * 255
    ).astype(np.uint8)
    changed = source.astype(np.float32) / 255.0
    changed[16:48, 24:72] = np.clip(
        changed[16:48, 24:72] + 0.10,
        0,
        1,
    )
    temporal = analyze_temporal_frames(
        [source, source],
        [source, changed],
        frame_indices=[49, 50],
        fps=25,
    )

    def evaluate(candidate):
        candidate_balance = next(
            node for node in candidate.nodes if node.id == balance.id
        )
        track = candidate_balance.tracks[0]
        center = (
            next(
                keyframe.value
                for keyframe in track.keyframes
                if keyframe.time_seconds == 2
            )
            if candidate_balance.enabled
            else 0.0
        )
        return _report(
            "temporal_flicker",
            abs(center),
            warning=0.15,
            failure=0.35,
            temporal_evidence=temporal,
        )

    result = search_technical_repairs(
        graph,
        evaluate(graph),
        evaluate,
        policy=RepairPolicy(
            evaluation_budget=6,
            maximum_rounds=3,
            maximum_ablation_nodes=2,
            beam_width=1,
            maximum_intent_drift=0.60,
        ),
    )

    assert result.accepted is True
    assert len(result.scope.time_ranges) == 1
    assert result.scope.time_ranges[0] == pytest.approx((1.75, 2.25))
    repaired = next(node for node in result.graph.nodes if node.id == balance.id)
    values = {
        keyframe.time_seconds: keyframe.value
        for keyframe in repaired.tracks[0].keyframes
    }
    assert values[2] < 0.15
    assert values[0] == values[1] == values[3] == values[4] == 0
    assert repaired.tracks[0].interpolation == Interpolation.LINEAR


def test_region_targets_exclude_unrelated_mask_nodes_from_ablation() -> None:
    graph = _graph()
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters.pop("saturation", None)
    look.parameters.pop("strength", None)
    template = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    template.type = NodeType.MASKED_GRADE
    template.parameters = {"saturation": 0.40, "mask_strength": 1.0}
    template.spatial_scope = SpatialScope(
        kind=SpatialKind.SEMANTIC,
        target="sky",
    )
    template.id = "sky-grade"
    water = template.model_copy(deep=True)
    water.id = "water-grade"
    water.order = template.order + 1
    water.spatial_scope.target = "water"
    graph.nodes.insert(-1, water)

    rng = np.random.default_rng(99)
    source_luma = rng.random((64, 96), dtype=np.float32) * 0.60 + 0.20
    source = np.round(np.repeat(source_luma[..., None], 3, axis=2) * 255).astype(
        np.uint8
    )
    output = source.astype(np.float32) / 255.0
    output[8:32, 16:80] = np.clip(output[8:32, 16:80] + 0.10, 0, 1)
    sky_mask = np.zeros((64, 96), dtype=np.float32)
    sky_mask[:40] = 1
    temporal = analyze_temporal_frames(
        [source, source],
        [source, output],
        frame_indices=[24, 25],
        fps=25,
        masks={"sky-mask": [sky_mask, sky_mask]},
        mask_targets={"sky-mask": "sky"},
    )
    baseline = _report(
        "oversaturation",
        0.40,
        warning=0.10,
        failure=0.20,
        temporal_evidence=temporal,
    )

    result = search_technical_repairs(
        graph,
        baseline,
        lambda candidate: _report(
            "oversaturation",
            sum(
                float(node.parameters.get("saturation", 0.0))
                for node in candidate.nodes
                if node.enabled and node.id == "sky-grade"
            ),
            warning=0.10,
            failure=0.20,
            temporal_evidence=temporal,
        ),
        policy=RepairPolicy(evaluation_budget=4, maximum_ablation_nodes=3),
    )

    assert result.scope.mask_targets == ("sky",)
    assert {item.node_id for item in result.ablations} == {"sky-grade"}
    assert all(attempt.node_id == "sky-grade" for attempt in result.attempts)


def test_repair_benchmark_summary_quantifies_success_rollbacks_and_safety() -> None:
    graph = _graph()
    report = _report(
        "oversaturation",
        0.30,
        warning=0.10,
        failure=0.20,
    )

    def result(
        accepted: bool,
        decision: RepairAttemptDecision,
        evaluations: int,
    ) -> RepairSearchResult:
        attempt = RepairAttempt(
            round_index=1,
            node_id="look_scene_001",
            objective_ids=("oversaturation",),
            graph_digest=graph_digest(graph),
            actions=("bounded saturation change",),
            objective_loss=1.0,
            improvement=1.0,
            hard_safe=decision != RepairAttemptDecision.HARD_METRIC_REGRESSION,
            side_effect_safe=decision != RepairAttemptDecision.QUALITY_SIDE_EFFECT,
            intent_drift=0.10,
            decision=decision,
        )
        return RepairSearchResult(
            graph=graph,
            report=(
                _report(
                    "oversaturation",
                    0.05,
                    warning=0.10,
                    failure=0.20,
                )
                if accepted
                else report
            ),
            actions=["bounded saturation change"] if accepted else [],
            accepted=accepted,
            evaluations=evaluations,
            accepted_rounds=1 if accepted else 0,
            rollback_count=0 if accepted else 1,
            initial_objective_loss=4.0,
            final_objective_loss=1.0 if accepted else 4.0,
            objective_ids=("oversaturation",),
            scope=RepairScopeEvidence(),
            attempts=[attempt],
        )

    summary = summarize_repair_benchmark(
        [
            RepairBenchmarkCase(
                case_id="repairable",
                should_accept=True,
                result=result(True, RepairAttemptDecision.ACCEPTED, 3),
            ),
            RepairBenchmarkCase(
                case_id="side-effect",
                should_accept=False,
                result=result(False, RepairAttemptDecision.QUALITY_SIDE_EFFECT, 2),
            ),
        ]
    )

    assert summary.repair_acceptance_rate == 1
    assert summary.repair_success_rate == 1
    assert summary.rollback_accuracy == 1
    assert summary.candidate_rollback_rate == 0.5
    assert summary.unexpected_acceptances == 0
    assert summary.unsafe_acceptances == 0
    assert summary.mean_evaluations == 2.5
