from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from colorgraph.domain.grade_graph import (
    GradeGraph,
    GradeNode,
    Interpolation,
    NodeType,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.quality.models import (
    CheckStatus,
    QualityCategory,
    QualityCheck,
    QualityReport,
)
from colorgraph.quality.temporal_motion import TemporalClassification

REPAIR_SEARCH_VERSION = "colorgraph.responsibility-repair/v1"


@dataclass(frozen=True, slots=True)
class RepairResult:
    graph: GradeGraph
    actions: list[str]


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    evaluation_budget: int = 8
    maximum_rounds: int = 3
    maximum_ablation_nodes: int = 4
    beam_width: int = 2
    minimum_objective_improvement: float = 0.05
    maximum_intent_drift: float = 0.35
    temporal_padding_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.evaluation_budget <= 0:
            raise ValueError("evaluation_budget must be positive")
        if self.maximum_rounds <= 0:
            raise ValueError("maximum_rounds must be positive")
        if self.maximum_ablation_nodes <= 0:
            raise ValueError("maximum_ablation_nodes must be positive")
        if self.beam_width <= 0:
            raise ValueError("beam_width must be positive")
        if self.minimum_objective_improvement <= 0:
            raise ValueError("minimum_objective_improvement must be positive")
        if not 0 <= self.maximum_intent_drift <= 1:
            raise ValueError("maximum_intent_drift must be in [0, 1]")
        if self.temporal_padding_seconds <= 0:
            raise ValueError("temporal_padding_seconds must be positive")


@dataclass(frozen=True, slots=True)
class RepairScopeEvidence:
    time_ranges: tuple[tuple[float, float], ...] = ()
    mask_targets: tuple[str, ...] = ()
    region_count: int = 0
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class RepairAblationEvidence:
    node_id: str
    objective_ids: tuple[str, ...]
    baseline_loss: float
    ablated_loss: float | None
    improvement: float
    hard_safe: bool
    evaluator_error: str | None = None


class RepairAttemptDecision(StrEnum):
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded_by_better_candidate"
    NO_TARGET_IMPROVEMENT = "no_target_improvement"
    HARD_METRIC_REGRESSION = "hard_metric_regression"
    QUALITY_SIDE_EFFECT = "non_target_quality_regression"
    INTENT_DRIFT_EXCEEDED = "intent_drift_exceeded"
    EVALUATOR_ERROR = "evaluator_error"


@dataclass(slots=True)
class RepairAttempt:
    round_index: int
    node_id: str
    objective_ids: tuple[str, ...]
    graph_digest: str
    actions: tuple[str, ...]
    objective_loss: float | None
    improvement: float
    hard_safe: bool
    side_effect_safe: bool
    intent_drift: float
    decision: RepairAttemptDecision
    evaluator_error: str | None = None


@dataclass(frozen=True, slots=True)
class RepairSearchResult:
    graph: GradeGraph
    report: QualityReport
    actions: list[str]
    accepted: bool
    evaluations: int
    accepted_rounds: int
    rollback_count: int
    initial_objective_loss: float
    final_objective_loss: float
    objective_ids: tuple[str, ...]
    scope: RepairScopeEvidence
    ablations: list[RepairAblationEvidence] = field(default_factory=list)
    attempts: list[RepairAttempt] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RepairBenchmarkCase:
    case_id: str
    should_accept: bool
    result: RepairSearchResult


@dataclass(frozen=True, slots=True)
class RepairBenchmarkSummary:
    total_cases: int
    repairable_cases: int
    accepted_repairs: int
    repair_acceptance_rate: float
    successful_repairs: int
    repair_success_rate: float
    expected_rollback_cases: int
    successful_rollbacks: int
    rollback_accuracy: float
    unexpected_acceptances: int
    candidate_attempts: int
    candidate_rollbacks: int
    candidate_rollback_rate: float
    unsafe_acceptances: int
    mean_evaluations: float
    p95_accepted_intent_drift: float


@dataclass(frozen=True, slots=True)
class _RepairRule:
    node_types: frozenset[NodeType]
    parameters: tuple[str, ...]
    track_parameters: tuple[str, ...] = ()


_RULES: dict[str, _RepairRule] = {
    "highlight_clipping": _RepairRule(
        frozenset(
            {
                NodeType.BALANCE,
                NodeType.TONE,
                NodeType.LOOK,
                NodeType.MASKED_GRADE,
            }
        ),
        ("highlights", "curve_highlights", "exposure"),
        ("exposure",),
    ),
    "shadow_crush": _RepairRule(
        frozenset({NodeType.BALANCE, NodeType.TONE, NodeType.MASKED_GRADE}),
        ("shadows", "offset_r", "offset_g", "offset_b", "exposure"),
        ("exposure",),
    ),
    "oversaturation": _RepairRule(
        frozenset(
            {
                NodeType.BALANCE,
                NodeType.TONE,
                NodeType.LOOK,
                NodeType.POST_LOOK,
                NodeType.MASKED_GRADE,
            }
        ),
        ("saturation", "strength", "mask_strength"),
    ),
    "temporal_flicker": _RepairRule(
        frozenset(
            {
                NodeType.BALANCE,
                NodeType.TONE,
                NodeType.LOOK,
                NodeType.MASKED_GRADE,
            }
        ),
        (),
        ("exposure", "temperature"),
    ),
    "mask_halo": _RepairRule(
        frozenset({NodeType.MASKED_GRADE}),
        ("mask_strength", "highlights", "contrast"),
    ),
    "sky_banding": _RepairRule(
        frozenset({NodeType.MASKED_GRADE, NodeType.TONE, NodeType.LOOK}),
        ("contrast", "saturation", "strength", "mask_strength"),
    ),
    "banding_risk": _RepairRule(
        frozenset(
            {
                NodeType.TONE,
                NodeType.LOOK,
                NodeType.POST_LOOK,
                NodeType.MASKED_GRADE,
            }
        ),
        ("contrast", "saturation", "strength", "mask_strength"),
    ),
    "structure_loss": _RepairRule(
        frozenset({NodeType.TONE, NodeType.LOOK, NodeType.POST_LOOK}),
        ("contrast", "strength"),
    ),
}

_PARAMETER_SCALES: dict[str, float] = {
    "exposure": 2.0,
    "temperature": 1.0,
    "tint": 1.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "highlights": 1.0,
    "curve_highlights": 1.0,
    "shadows": 1.0,
    "strength": 1.0,
    "mask_strength": 1.0,
    "offset_r": 0.10,
    "offset_g": 0.10,
    "offset_b": 0.10,
}

RepairEvaluator = Callable[[GradeGraph], QualityReport]
IntentDriftEvaluator = Callable[[GradeGraph, GradeGraph], float]


def _failed_or_warned(report: QualityReport, identifier: str) -> bool:
    check = next((item for item in report.checks if item.id == identifier), None)
    return check is not None and check.status in {CheckStatus.WARN, CheckStatus.FAIL}


def repairable_objective_ids(report: QualityReport) -> tuple[str, ...]:
    return tuple(
        check.id
        for check in report.checks
        if check.id in _RULES and check.status in {CheckStatus.WARN, CheckStatus.FAIL}
    )


def _check_map(report: QualityReport) -> dict[str, QualityCheck]:
    return {check.id: check for check in report.checks}


def _check_loss(check: QualityCheck) -> float:
    status_penalty = {
        CheckStatus.PASS: 0.0,
        CheckStatus.WARN: 1.0,
        CheckStatus.FAIL: 3.0,
    }[check.status]
    ratio = max(0.0, check.value) / max(abs(check.threshold), 1e-9)
    return status_penalty + min(ratio, 4.0)


def _objective_loss(report: QualityReport, objective_ids: Sequence[str]) -> float:
    checks = _check_map(report)
    if any(identifier not in checks for identifier in objective_ids):
        return float("inf")
    return float(sum(_check_loss(checks[identifier]) for identifier in objective_ids))


def _hard_metrics_safe(baseline: QualityReport, candidate: QualityReport) -> bool:
    status_rank = {
        CheckStatus.PASS: 0,
        CheckStatus.WARN: 1,
        CheckStatus.FAIL: 2,
    }
    baseline_checks = {
        check.id: check
        for check in baseline.checks
        if check.category == QualityCategory.HARD_TECHNICAL
    }
    candidate_checks = {
        check.id: check
        for check in candidate.checks
        if check.category == QualityCategory.HARD_TECHNICAL
    }
    if set(baseline_checks) - set(candidate_checks):
        return False
    if any(
        status_rank[candidate_checks[identifier].status]
        > status_rank[baseline_check.status]
        for identifier, baseline_check in baseline_checks.items()
    ):
        return False
    return set(candidate.technical_hard_failures) <= set(
        baseline.technical_hard_failures
    )


def _non_target_metrics_safe(
    baseline: QualityReport,
    candidate: QualityReport,
    objective_ids: Sequence[str],
) -> bool:
    status_rank = {
        CheckStatus.PASS: 0,
        CheckStatus.WARN: 1,
        CheckStatus.FAIL: 2,
    }
    baseline_checks = _check_map(baseline)
    candidate_checks = _check_map(candidate)
    for identifier, baseline_check in baseline_checks.items():
        if identifier in objective_ids:
            continue
        candidate_check = candidate_checks.get(identifier)
        if candidate_check is None:
            return False
        if status_rank[candidate_check.status] > status_rank[baseline_check.status]:
            return False
    return True


def _merge_ranges(
    ranges: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    if not ranges:
        return ()
    ordered = sorted(ranges)
    merged: list[list[float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return tuple((start, end) for start, end in merged)


def _scope_evidence(
    graph: GradeGraph,
    report: QualityReport,
    policy: RepairPolicy,
) -> RepairScopeEvidence:
    evidence = report.temporal_evidence
    if evidence is None:
        return RepairScopeEvidence()
    ranges: list[tuple[float, float]] = []
    targets: set[str] = set()
    region_count = 0
    confidences: list[float] = []
    for transition in evidence.transitions:
        if (
            transition.excluded
            or transition.classification
            != TemporalClassification.GRADE_INDUCED_FLICKER
        ):
            continue
        ranges.append(
            (
                max(0.0, transition.time_seconds - policy.temporal_padding_seconds),
                min(
                    graph.media.duration_seconds,
                    transition.time_seconds + policy.temporal_padding_seconds,
                ),
            )
        )
        confidences.append(transition.confidence)
        region_count += len(transition.regions)
        targets.update(
            target
            for region in transition.regions
            for target in region.overlapping_mask_targets
        )
    return RepairScopeEvidence(
        time_ranges=_merge_ranges(ranges),
        mask_targets=tuple(sorted(targets)),
        region_count=region_count,
        confidence=float(np.mean(confidences)) if confidences else 0.0,
    )


def _node_intersects_scope(node: GradeNode, scope: RepairScopeEvidence) -> bool:
    if scope.mask_targets and node.spatial_scope.target not in {
        "global",
        *scope.mask_targets,
    }:
        return False
    node_range = node.temporal_scope.time_range
    if node_range is None or not scope.time_ranges:
        return True
    return any(
        node_range.start_seconds < end and start < node_range.end_seconds
        for start, end in scope.time_ranges
    )


def _node_objectives(
    node: GradeNode,
    objective_ids: Sequence[str],
    scope: RepairScopeEvidence,
) -> tuple[str, ...]:
    if not node.enabled or not _node_intersects_scope(node, scope):
        return ()
    matches: list[str] = []
    for identifier in objective_ids:
        rule = _RULES[identifier]
        if node.type not in rule.node_types:
            continue
        has_parameter = any(
            parameter in node.parameters
            and (
                not isinstance(node.parameters[parameter], int | float)
                or isinstance(node.parameters[parameter], bool)
                or abs(float(node.parameters[parameter])) > 1e-9
            )
            for parameter in rule.parameters
        )
        has_track = any(
            track.parameter in rule.track_parameters for track in node.tracks
        )
        if has_parameter or has_track:
            matches.append(identifier)
    return tuple(matches)


def _node_priority(
    node: GradeNode,
    objective_ids: Sequence[str],
    scope: RepairScopeEvidence,
) -> tuple[float, int, str]:
    score = float(len(objective_ids))
    if scope.mask_targets and node.spatial_scope.target in scope.mask_targets:
        score += 2.0
    if scope.time_ranges and node.temporal_scope.time_range is not None:
        score += 1.0
    score += min(
        1.0,
        sum(
            abs(float(value))
            for value in node.parameters.values()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ),
    )
    score += 0.5 * sum(
        bool(track.keyframes) for track in node.tracks
    )
    return (-score, node.order, node.id)


def _candidate_nodes(
    graph: GradeGraph,
    objective_ids: Sequence[str],
    scope: RepairScopeEvidence,
) -> list[tuple[GradeNode, tuple[str, ...]]]:
    candidates = [
        (node, matches)
        for node in graph.nodes
        if (matches := _node_objectives(node, objective_ids, scope))
    ]
    candidates.sort(
        key=lambda item: _node_priority(item[0], item[1], scope)
    )
    return candidates


def _graph_with_nodes(
    graph: GradeGraph,
    nodes: Sequence[GradeNode],
    *,
    metadata: Mapping[str, object] | None = None,
) -> GradeGraph:
    payload = graph.model_dump(mode="python")
    payload["nodes"] = [node.model_dump(mode="python") for node in nodes]
    payload["updated_at"] = datetime.now(UTC)
    if metadata is not None:
        payload["metadata"] = dict(metadata)
    return GradeGraph.model_validate(payload)


def _ablate_node(graph: GradeGraph, node_id: str) -> GradeGraph:
    nodes = [node.model_copy(deep=True) for node in graph.nodes]
    target = next(node for node in nodes if node.id == node_id)
    target.enabled = False
    return _graph_with_nodes(graph, nodes)


def _in_scope(
    time_seconds: float,
    ranges: Sequence[tuple[float, float]],
) -> bool:
    return not ranges or any(start <= time_seconds <= end for start, end in ranges)


def _smooth_track(
    node: GradeNode,
    parameter: str,
    scope: RepairScopeEvidence,
    strength: float,
) -> bool:
    track = next((item for item in node.tracks if item.parameter == parameter), None)
    if track is None:
        return False
    values = [keyframe.value for keyframe in track.keyframes]
    changed = False
    for index, keyframe in enumerate(track.keyframes):
        if not _in_scope(keyframe.time_seconds, scope.time_ranges):
            continue
        neighbors = [
            values[neighbor]
            for neighbor in (index - 1, index + 1)
            if 0 <= neighbor < len(values)
        ]
        if not neighbors:
            continue
        target = float(np.mean(neighbors))
        repaired = keyframe.value + (target - keyframe.value) * min(strength, 1.0)
        if abs(repaired - keyframe.value) > 1e-9:
            keyframe.value = repaired
            changed = True
    if changed:
        track.interpolation = Interpolation.LINEAR
        if parameter == "exposure":
            track.max_velocity = min(track.max_velocity or 0.5, 0.35)
        elif parameter == "temperature":
            track.max_velocity = min(track.max_velocity or 0.2, 0.16)
    return changed


def _adjust_direct(
    node: GradeNode,
    objective_id: str,
    strength: float,
    scope: RepairScopeEvidence,
) -> list[str]:
    actions: list[str] = []
    if objective_id == "highlight_clipping":
        key = "highlights" if "highlights" in node.parameters else "curve_highlights"
        current = float(node.parameters.get(key, 0.0))
        node.parameters[key] = max(-0.55, current - 0.08 * strength)
        actions.append(f"{node.id}:{key}-={0.08 * strength:.4f}")
    elif objective_id == "shadow_crush":
        if any(key in node.parameters for key in ("offset_r", "offset_g", "offset_b")):
            for key in ("offset_r", "offset_g", "offset_b"):
                current = float(node.parameters.get(key, 0.0))
                node.parameters[key] = min(0.05, current + 0.012 * strength)
            actions.append(f"{node.id}:CDL offsets+={0.012 * strength:.4f}")
        else:
            current = float(node.parameters.get("shadows", 0.0))
            node.parameters["shadows"] = min(0.45, current + 0.06 * strength)
            actions.append(f"{node.id}:shadows+={0.06 * strength:.4f}")
    elif objective_id == "oversaturation":
        current = float(node.parameters.get("saturation", 0.0))
        node.parameters["saturation"] = max(-0.45, current - 0.10 * strength)
        actions.append(f"{node.id}:saturation-={0.10 * strength:.4f}")
    elif objective_id == "temporal_flicker":
        changed = False
        for parameter in ("exposure", "temperature"):
            changed = (
                _smooth_track(node, parameter, scope, 0.45 * strength)
                or changed
            )
        if changed:
            actions.append(f"{node.id}:smoothed scoped exposure/temperature tracks")
    elif objective_id == "mask_halo":
        current = float(node.parameters.get("mask_strength", 1.0))
        node.parameters["mask_strength"] = max(0.45, current * (1 - 0.15 * strength))
        actions.append(f"{node.id}:mask_strength*={1 - 0.15 * strength:.4f}")
    elif objective_id in {"sky_banding", "banding_risk"}:
        contrast = float(node.parameters.get("contrast", 0.0))
        saturation = float(node.parameters.get("saturation", 0.0))
        node.parameters["contrast"] = max(-0.35, contrast - 0.03 * strength)
        node.parameters["saturation"] = max(-0.35, saturation - 0.04 * strength)
        actions.append(f"{node.id}:softened contrast/saturation")
    elif objective_id == "structure_loss":
        if "strength" in node.parameters:
            current = float(node.parameters["strength"])
            node.parameters["strength"] = max(0.35, current * (1 - 0.12 * strength))
            actions.append(f"{node.id}:strength*={1 - 0.12 * strength:.4f}")
        else:
            current = float(node.parameters.get("contrast", 0.0))
            node.parameters["contrast"] = current * (1 - 0.15 * strength)
            actions.append(f"{node.id}:contrast*={1 - 0.15 * strength:.4f}")
    return actions


def _repair_graph(
    graph: GradeGraph,
    node_id: str,
    objective_ids: Sequence[str],
    scope: RepairScopeEvidence,
    *,
    round_index: int,
) -> tuple[GradeGraph | None, tuple[str, ...]]:
    nodes = [node.model_copy(deep=True) for node in graph.nodes]
    target = next((node for node in nodes if node.id == node_id), None)
    if target is None:
        return None, ()
    strength = min(1.75, 0.65 + round_index * 0.35)
    actions: list[str] = []
    for objective_id in objective_ids:
        actions.extend(_adjust_direct(target, objective_id, strength, scope))
    if not actions:
        return None, ()
    return _graph_with_nodes(graph, nodes), tuple(actions)


def _numeric_parameters(node: GradeNode) -> dict[str, float]:
    values = {
        f"parameter:{key}": float(value)
        for key, value in node.parameters.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    for track in node.tracks:
        for keyframe in track.keyframes:
            values[
                f"track:{track.parameter}:{keyframe.time_seconds:.9f}"
            ] = keyframe.value
    return values


def parameter_intent_drift(baseline: GradeGraph, candidate: GradeGraph) -> float:
    baseline_nodes = {node.id: node for node in baseline.nodes}
    candidate_nodes = {node.id: node for node in candidate.nodes}
    drift = 0.0
    for node_id in baseline_nodes.keys() | candidate_nodes.keys():
        before = baseline_nodes.get(node_id)
        after = candidate_nodes.get(node_id)
        if before is None or after is None:
            drift = max(drift, 1.0)
            continue
        if before.enabled != after.enabled:
            drift = max(drift, 1.0)
        before_values = _numeric_parameters(before)
        after_values = _numeric_parameters(after)
        for key in before_values.keys() | after_values.keys():
            parameter = key.split(":", 2)[1]
            scale = _PARAMETER_SCALES.get(parameter, 1.0)
            drift = max(
                drift,
                abs(after_values.get(key, 0.0) - before_values.get(key, 0.0))
                / scale,
            )
    return float(np.clip(drift, 0.0, 1.0))


def _record_history(
    graph: GradeGraph,
    *,
    baseline_graph: GradeGraph,
    baseline_report: QualityReport,
    final_report: QualityReport,
    objective_ids: Sequence[str],
    actions: Sequence[str],
    evaluations: int,
    accepted_rounds: int,
    rollback_count: int,
    scope: RepairScopeEvidence,
) -> GradeGraph:
    metadata = dict(graph.metadata)
    history = list(metadata.get("verifier_repairs", []))
    history.append(
        {
            "schema": REPAIR_SEARCH_VERSION,
            "at": datetime.now(UTC).isoformat(),
            "source_graph_digest": graph_digest(baseline_graph),
            "result_graph_digest": graph_digest(graph),
            "input_score": baseline_report.score,
            "output_score": final_report.score,
            "objective_ids": list(objective_ids),
            "actions": list(actions),
            "evaluations": evaluations,
            "accepted_rounds": accepted_rounds,
            "rollback_count": rollback_count,
            "scope": asdict(scope),
        }
    )
    metadata["verifier_repairs"] = history
    return _graph_with_nodes(graph, graph.nodes, metadata=metadata)


def search_technical_repairs(
    graph: GradeGraph,
    report: QualityReport,
    evaluator: RepairEvaluator,
    *,
    policy: RepairPolicy | None = None,
    intent_drift_evaluator: IntentDriftEvaluator | None = None,
) -> RepairSearchResult:
    """Run bounded responsibility ablation and accept only safe local improvements."""

    selected_policy = policy or RepairPolicy()
    objective_ids = repairable_objective_ids(report)
    scope = _scope_evidence(graph, report, selected_policy)
    initial_loss = _objective_loss(report, objective_ids)
    if not objective_ids:
        return RepairSearchResult(
            graph=graph,
            report=report,
            actions=[],
            accepted=False,
            evaluations=0,
            accepted_rounds=0,
            rollback_count=0,
            initial_objective_loss=0.0,
            final_objective_loss=0.0,
            objective_ids=(),
            scope=scope,
        )
    drift_evaluator = intent_drift_evaluator or parameter_intent_drift
    candidates = _candidate_nodes(graph, objective_ids, scope)
    evaluations = 0
    ablations: list[RepairAblationEvidence] = []
    ablation_limit = min(
        selected_policy.maximum_ablation_nodes,
        max(0, selected_policy.evaluation_budget - 1),
    )
    for node, node_objectives in candidates[:ablation_limit]:
        if evaluations >= selected_policy.evaluation_budget:
            break
        try:
            ablated_report = evaluator(_ablate_node(graph, node.id))
            evaluations += 1
            ablated_loss = _objective_loss(ablated_report, objective_ids)
            hard_safe = _hard_metrics_safe(report, ablated_report)
            improvement = (
                initial_loss - ablated_loss
                if np.isfinite(ablated_loss)
                else 0.0
            )
            ablations.append(
                RepairAblationEvidence(
                    node_id=node.id,
                    objective_ids=node_objectives,
                    baseline_loss=initial_loss,
                    ablated_loss=ablated_loss,
                    improvement=improvement,
                    hard_safe=hard_safe,
                )
            )
        except Exception as exc:  # evaluator boundary must fail closed
            evaluations += 1
            ablations.append(
                RepairAblationEvidence(
                    node_id=node.id,
                    objective_ids=node_objectives,
                    baseline_loss=initial_loss,
                    ablated_loss=None,
                    improvement=0.0,
                    hard_safe=False,
                    evaluator_error=type(exc).__name__,
                )
            )
    attribution = sorted(
        (
            item
            for item in ablations
            if item.hard_safe and item.improvement > 0
        ),
        key=lambda item: (-item.improvement, item.node_id),
    )
    if not attribution:
        attribution = [
            RepairAblationEvidence(
                node_id=node.id,
                objective_ids=node_objectives,
                baseline_loss=initial_loss,
                ablated_loss=None,
                improvement=0.0,
                hard_safe=True,
            )
            for node, node_objectives in candidates
        ]

    current_graph = graph
    current_report = report
    current_loss = initial_loss
    accepted_actions: list[str] = []
    attempts: list[RepairAttempt] = []
    accepted_rounds = 0
    for round_index in range(1, selected_policy.maximum_rounds + 1):
        if evaluations >= selected_policy.evaluation_budget or not attribution:
            break
        round_candidates: list[
            tuple[float, float, GradeGraph, QualityReport, RepairAttempt]
        ] = []
        for responsibility in attribution[: selected_policy.beam_width]:
            if evaluations >= selected_policy.evaluation_budget:
                break
            candidate_graph, actions = _repair_graph(
                current_graph,
                responsibility.node_id,
                responsibility.objective_ids,
                scope,
                round_index=round_index,
            )
            if candidate_graph is None:
                continue
            candidate_digest = graph_digest(candidate_graph)
            try:
                candidate_report = evaluator(candidate_graph)
                evaluations += 1
            except Exception as exc:  # evaluator boundary must fail closed
                evaluations += 1
                attempts.append(
                    RepairAttempt(
                        round_index=round_index,
                        node_id=responsibility.node_id,
                        objective_ids=responsibility.objective_ids,
                        graph_digest=candidate_digest,
                        actions=actions,
                        objective_loss=None,
                        improvement=0.0,
                        hard_safe=False,
                        side_effect_safe=False,
                        intent_drift=1.0,
                        decision=RepairAttemptDecision.EVALUATOR_ERROR,
                        evaluator_error=type(exc).__name__,
                    )
                )
                continue
            candidate_loss = _objective_loss(candidate_report, objective_ids)
            improvement = current_loss - candidate_loss
            hard_safe = _hard_metrics_safe(report, candidate_report)
            side_effect_safe = _non_target_metrics_safe(
                report,
                candidate_report,
                objective_ids,
            )
            intent_drift = float(drift_evaluator(graph, candidate_graph))
            if not hard_safe:
                decision = RepairAttemptDecision.HARD_METRIC_REGRESSION
            elif not side_effect_safe:
                decision = RepairAttemptDecision.QUALITY_SIDE_EFFECT
            elif intent_drift > selected_policy.maximum_intent_drift:
                decision = RepairAttemptDecision.INTENT_DRIFT_EXCEEDED
            elif improvement < selected_policy.minimum_objective_improvement:
                decision = RepairAttemptDecision.NO_TARGET_IMPROVEMENT
            else:
                decision = RepairAttemptDecision.ACCEPTED
            attempt = RepairAttempt(
                round_index=round_index,
                node_id=responsibility.node_id,
                objective_ids=responsibility.objective_ids,
                graph_digest=candidate_digest,
                actions=actions,
                objective_loss=candidate_loss,
                improvement=improvement,
                hard_safe=hard_safe,
                side_effect_safe=side_effect_safe,
                intent_drift=intent_drift,
                decision=decision,
            )
            attempts.append(attempt)
            if decision == RepairAttemptDecision.ACCEPTED:
                round_candidates.append(
                    (
                        candidate_loss,
                        intent_drift,
                        candidate_graph,
                        candidate_report,
                        attempt,
                    )
                )
        if not round_candidates:
            break
        _, _, current_graph, current_report, accepted_attempt = min(
            round_candidates,
            key=lambda item: (item[0], item[1], item[4].graph_digest),
        )
        for attempt in attempts:
            if (
                attempt.round_index == round_index
                and attempt is not accepted_attempt
                and attempt.decision == RepairAttemptDecision.ACCEPTED
            ):
                attempt.decision = RepairAttemptDecision.SUPERSEDED
        current_loss = _objective_loss(current_report, objective_ids)
        accepted_actions.extend(accepted_attempt.actions)
        accepted_rounds += 1
        if all(
            _check_map(current_report)[identifier].status == CheckStatus.PASS
            for identifier in objective_ids
        ):
            break

    accepted = accepted_rounds > 0
    rollback_count = sum(
        attempt.decision != RepairAttemptDecision.ACCEPTED
        for attempt in attempts
    )
    if accepted:
        current_graph = _record_history(
            current_graph,
            baseline_graph=graph,
            baseline_report=report,
            final_report=current_report,
            objective_ids=objective_ids,
            actions=accepted_actions,
            evaluations=evaluations,
            accepted_rounds=accepted_rounds,
            rollback_count=rollback_count,
            scope=scope,
        )
    else:
        current_graph = graph
        current_report = report
        current_loss = initial_loss
    return RepairSearchResult(
        graph=current_graph,
        report=current_report,
        actions=accepted_actions,
        accepted=accepted,
        evaluations=evaluations,
        accepted_rounds=accepted_rounds,
        rollback_count=rollback_count,
        initial_objective_loss=initial_loss,
        final_objective_loss=current_loss,
        objective_ids=objective_ids,
        scope=scope,
        ablations=ablations,
        attempts=attempts,
    )


def summarize_repair_benchmark(
    cases: Sequence[RepairBenchmarkCase],
) -> RepairBenchmarkSummary:
    repairable = [case for case in cases if case.should_accept]
    rollback_cases = [case for case in cases if not case.should_accept]
    accepted_repairs = sum(case.result.accepted for case in repairable)
    successful_repairs = sum(
        case.result.accepted
        and all(
            _check_map(case.result.report)[identifier].status == CheckStatus.PASS
            for identifier in case.result.objective_ids
        )
        for case in repairable
    )
    successful_rollbacks = sum(not case.result.accepted for case in rollback_cases)
    attempts = [attempt for case in cases for attempt in case.result.attempts]
    accepted_attempts = [
        attempt
        for attempt in attempts
        if attempt.decision == RepairAttemptDecision.ACCEPTED
    ]
    candidate_rollbacks = len(attempts) - len(accepted_attempts)
    unsafe_acceptances = sum(
        not attempt.hard_safe or not attempt.side_effect_safe
        for attempt in accepted_attempts
    )
    return RepairBenchmarkSummary(
        total_cases=len(cases),
        repairable_cases=len(repairable),
        accepted_repairs=accepted_repairs,
        repair_acceptance_rate=(
            accepted_repairs / len(repairable) if repairable else 0.0
        ),
        successful_repairs=successful_repairs,
        repair_success_rate=(
            successful_repairs / len(repairable) if repairable else 0.0
        ),
        expected_rollback_cases=len(rollback_cases),
        successful_rollbacks=successful_rollbacks,
        rollback_accuracy=(
            successful_rollbacks / len(rollback_cases) if rollback_cases else 0.0
        ),
        unexpected_acceptances=sum(
            case.result.accepted for case in rollback_cases
        ),
        candidate_attempts=len(attempts),
        candidate_rollbacks=candidate_rollbacks,
        candidate_rollback_rate=(
            candidate_rollbacks / len(attempts) if attempts else 0.0
        ),
        unsafe_acceptances=unsafe_acceptances,
        mean_evaluations=(
            float(np.mean([case.result.evaluations for case in cases]))
            if cases
            else 0.0
        ),
        p95_accepted_intent_drift=(
            float(
                np.percentile(
                    [attempt.intent_drift for attempt in accepted_attempts],
                    95,
                )
            )
            if accepted_attempts
            else 0.0
        ),
    )


def propose_technical_repairs(
    graph: GradeGraph,
    report: QualityReport,
) -> RepairResult:
    """Return a conservative one-shot proposal for compatibility callers."""

    objective_ids = repairable_objective_ids(report)
    if not objective_ids:
        return RepairResult(graph=graph, actions=[])
    scope = _scope_evidence(graph, report, RepairPolicy())
    candidates = _candidate_nodes(graph, objective_ids, scope)
    if not candidates:
        return RepairResult(graph=graph, actions=[])
    candidate_graph, actions = _repair_graph(
        graph,
        candidates[0][0].id,
        candidates[0][1],
        scope,
        round_index=1,
    )
    if candidate_graph is None:
        return RepairResult(graph=graph, actions=[])
    metadata = dict(candidate_graph.metadata)
    history = list(metadata.get("verifier_repairs", []))
    history.append(
        {
            "schema": f"{REPAIR_SEARCH_VERSION}/proposal",
            "at": datetime.now(UTC).isoformat(),
            "input_score": report.score,
            "objective_ids": list(objective_ids),
            "actions": list(actions),
            "scope": asdict(scope),
        }
    )
    metadata["verifier_repairs"] = history
    return RepairResult(
        graph=_graph_with_nodes(candidate_graph, candidate_graph.nodes, metadata=metadata),
        actions=list(actions),
    )
