from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.creative_contracts import (
    ColorStrategy,
    CompiledCandidate,
    GraphChange,
    NonEmptyString,
    OperationCard,
    ProtectedAttribute,
    Sha256,
    StrategyAction,
    StrategyOperation,
    StrictFrozenModel,
    TechnicalBaseline,
    canonical_sha256,
)
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    GradeNode,
    Interpolation,
    Keyframe,
    NodeType,
    ParameterTrack,
    ScopeLevel,
    SpatialKind,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.masks import validate_mask_expression

CREATIVE_COMPILER_VERSION = "colorgraph.deterministic-strategy-compiler/v1"
MANDATORY_COMPILER_QC_CHECKS = frozenset(
    {
        "color_pipeline_schema",
        "finite_values",
        "asset_integrity",
        "legal_output_gamut",
    }
)

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")
_NODE_TYPE_BY_OPERATION = {
    StrategyOperation.BALANCE: NodeType.BALANCE,
    StrategyOperation.TONE: NodeType.TONE,
    StrategyOperation.LOOK: NodeType.LOOK,
    StrategyOperation.MASKED_GRADE: NodeType.MASKED_GRADE,
}
_OPERATION_BY_NODE_TYPE = {
    NodeType.BALANCE: StrategyOperation.BALANCE,
    NodeType.TONE: StrategyOperation.TONE,
    NodeType.LOOK: StrategyOperation.LOOK,
    NodeType.MASKED_GRADE: StrategyOperation.MASKED_GRADE,
}
_LINEAR_WORKING_SPACES = {ColorSpace.LINEAR_REC709, ColorSpace.ACESCG}
_RENDERER_PARAMETERS = {
    NodeType.BALANCE: {
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
        "midtones",
        "curve_highlights",
        "slope_r",
        "slope_g",
        "slope_b",
        "offset_r",
        "offset_g",
        "offset_b",
        "power_r",
        "power_g",
        "power_b",
    },
    NodeType.TONE: {
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
        "midtones",
        "curve_highlights",
        "slope_r",
        "slope_g",
        "slope_b",
        "offset_r",
        "offset_g",
        "offset_b",
        "power_r",
        "power_g",
        "power_b",
    },
    NodeType.MASKED_GRADE: {
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
        "midtones",
        "curve_highlights",
        "mask_strength",
    },
    NodeType.LOOK: {
        "strength",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
    },
    NodeType.POST_LOOK: {"contrast", "saturation"},
}


class CompilationPolicy(StrictFrozenModel):
    maximum_variants: int = Field(default=2, ge=0, le=16)
    variation_fraction: float = Field(default=0.25, gt=0, le=0.5)
    non_waivable_qc_checks: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def preserve_delivery_gates(self) -> CompilationPolicy:
        missing = MANDATORY_COMPILER_QC_CHECKS - set(self.non_waivable_qc_checks)
        if missing:
            raise ValueError(
                f"compiler policy omits mandatory QC checks: {sorted(missing)}"
            )
        return self


class CompileViolationCode(StrEnum):
    STALE_INPUT = "stale_input"
    BASELINE_MISMATCH = "baseline_mismatch"
    UNKNOWN_CARD = "unknown_card"
    CARD_MAPPING = "card_mapping"
    PARAMETER_INVALID = "parameter_invalid"
    COLOR_SPACE_INVALID = "color_space_invalid"
    SCOPE_INVALID = "scope_invalid"
    MASK_UNAVAILABLE = "mask_unavailable"
    DEPENDENCY_INVALID = "dependency_invalid"
    CONFLICT = "conflict"
    PROTECTION_CONFLICT = "protection_conflict"
    KEYFRAME_INVALID = "keyframe_invalid"
    TRANSFORM_MUTATION = "transform_mutation"
    QC_BYPASS = "qc_bypass"
    EXCEPTION_INVALID = "exception_invalid"


class CompileViolation(StrictFrozenModel):
    code: CompileViolationCode
    detail: NonEmptyString
    action_id: str | None = None


class CompilationAuditReport(StrictFrozenModel):
    schema_version: Literal["colorgraph.strategy-compilation-audit/v1"] = (
        "colorgraph.strategy-compilation-audit/v1"
    )
    compiler_version: str = CREATIVE_COMPILER_VERSION
    valid: bool
    source_graph_digest: Sha256
    strategy_digest: Sha256
    operation_registry_digest: Sha256
    required_qc_checks: list[str]
    violations: list[CompileViolation]


class CompiledGraphCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: CompiledCandidate
    graph: GradeGraph
    undo_graph: GradeGraph
    variant_id: str
    strategy_digest: Sha256
    required_qc_checks: list[str]

    @model_validator(mode="after")
    def validate_graph_bindings(self) -> CompiledGraphCandidate:
        if graph_digest(self.graph) != self.contract.compiled_graph_digest:
            raise ValueError("compiled graph digest does not match its contract")
        if graph_digest(self.undo_graph) != self.contract.undo_graph_digest:
            raise ValueError("undo graph digest does not match its contract")
        return self


@dataclass(frozen=True, slots=True)
class StrategyCompilationResult:
    candidates: tuple[CompiledGraphCandidate, ...]
    audit: CompilationAuditReport


class AppliedCompiledCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    confirmation: Literal["user", "selector"]
    graph: GradeGraph
    undo_graph: GradeGraph
    previous_graph_digest: Sha256
    applied_graph_digest: Sha256


class ColorStrategyCompileError(ValueError):
    def __init__(self, audit: CompilationAuditReport) -> None:
        super().__init__(
            "color strategy compilation failed: "
            + ", ".join(item.code for item in audit.violations)
        )
        self.audit = audit


class OperationCardRegistry:
    def __init__(self, cards: list[OperationCard]) -> None:
        if not cards:
            raise ValueError("operation card registry cannot be empty")
        self._cards: dict[str, OperationCard] = {}
        for card in cards:
            existing = self._cards.get(card.card_id)
            if existing is not None and existing != card:
                raise ValueError(f"duplicate operation card ID {card.card_id}")
            self._cards[card.card_id] = card

    @property
    def digest(self) -> str:
        return canonical_sha256(
            {
                "cards": [
                    self._cards[card_id].model_dump(mode="json")
                    for card_id in sorted(self._cards)
                ]
            }
        )

    def get(self, card_id: str | None) -> OperationCard | None:
        if card_id is None:
            return None
        return self._cards.get(card_id)


def _scope_kind(action: StrategyAction) -> str:
    if action.scope.mask_target is not None:
        return "mask"
    if action.scope.time_range is not None:
        return "time"
    if action.scope.shot_id is not None:
        return "shot"
    if action.scope.scene_id is not None:
        return "scene"
    return "project"


def _renderer_node_type(card: OperationCard) -> NodeType | None:
    if card.renderer_node_type is None:
        return None
    try:
        node_type = NodeType(card.renderer_node_type)
    except ValueError:
        return None
    if node_type in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
        return None
    return node_type


def _source_operations(graph: GradeGraph) -> dict[StrategyOperation, list[int]]:
    operations: dict[StrategyOperation, list[int]] = {}
    for node in graph.nodes:
        operation = _OPERATION_BY_NODE_TYPE.get(node.type)
        if operation is not None:
            operations.setdefault(operation, []).append(node.order)
        compiled_operation = node.metadata.get("strategy_operation")
        if isinstance(compiled_operation, str):
            try:
                operation = StrategyOperation(compiled_operation)
            except ValueError:
                continue
            operations.setdefault(operation, []).append(node.order)
    return operations


def _card_parameter_map(card: OperationCard) -> dict[str, object]:
    return {item.name: item for item in card.parameters}


def _mapped_parameter_name(card: OperationCard, strategy_name: str) -> str | None:
    return card.parameter_mapping.get(strategy_name)


def _exception_covered_protections(
    strategy: ColorStrategy,
    action: StrategyAction,
) -> set[ProtectedAttribute]:
    covered: set[ProtectedAttribute] = set()
    for exception in strategy.intentional_exceptions:
        if exception.scope.project_id != action.scope.project_id:
            continue
        if (
            exception.scope.scene_id is not None
            and exception.scope.scene_id != action.scope.scene_id
        ):
            continue
        if (
            exception.scope.shot_id is not None
            and exception.scope.shot_id != action.scope.shot_id
        ):
            continue
        if (
            exception.scope.mask_target is not None
            and exception.scope.mask_target != action.scope.mask_target
        ):
            continue
        if not set(exception.evidence_ids) & set(action.evidence_ids):
            continue
        covered.update(exception.protected_attributes)
    return covered


def _resolve_time_scope(
    graph: GradeGraph,
    action: StrategyAction,
) -> tuple[TemporalScope, TimeRange]:
    project_range = TimeRange(
        start_seconds=0,
        end_seconds=max(graph.media.duration_seconds, 0.001),
    )
    scene = next(
        (item for item in graph.scenes if item.id == action.scope.scene_id),
        None,
    )
    shot = next(
        (item for item in graph.shots if item.id == action.scope.shot_id),
        None,
    )
    if action.scope.shot_id is not None and shot is None:
        raise ValueError("strategy scope references an unknown shot")
    if action.scope.scene_id is not None and scene is None:
        raise ValueError("strategy scope references an unknown scene")
    if shot is not None and action.scope.scene_id != shot.scene_id:
        raise ValueError("strategy shot does not belong to its scene")
    if action.scope.time_range is not None:
        time_range = TimeRange(
            start_seconds=action.scope.time_range.start_seconds,
            end_seconds=action.scope.time_range.end_seconds,
        )
        containing = (
            shot.time_range
            if shot is not None
            else (
                TimeRange(
                    start_seconds=min(
                        item.time_range.start_seconds
                        for item in graph.shots
                        if item.scene_id == scene.id
                    ),
                    end_seconds=max(
                        item.time_range.end_seconds
                        for item in graph.shots
                        if item.scene_id == scene.id
                    ),
                )
                if scene is not None
                else project_range
            )
        )
        if (
            time_range.start_seconds < containing.start_seconds
            or time_range.end_seconds > containing.end_seconds
        ):
            raise ValueError("strategy time range exceeds its containing scope")
        level = (
            ScopeLevel.SUB_SHOT
            if shot is not None
            else ScopeLevel.SCENE if scene is not None else ScopeLevel.PROJECT
        )
    elif shot is not None:
        time_range = shot.time_range
        level = ScopeLevel.SHOT
    elif scene is not None:
        scene_shots = [item for item in graph.shots if item.scene_id == scene.id]
        if not scene_shots:
            raise ValueError("strategy scene has no shots")
        time_range = TimeRange(
            start_seconds=min(item.time_range.start_seconds for item in scene_shots),
            end_seconds=max(item.time_range.end_seconds for item in scene_shots),
        )
        level = ScopeLevel.SCENE
    else:
        time_range = project_range
        level = ScopeLevel.PROJECT
    return (
        TemporalScope(
            level=level,
            project_id=graph.project_id,
            scene_id=action.scope.scene_id,
            shot_id=action.scope.shot_id,
            time_range=time_range,
        ),
        time_range,
    )


def _resolve_spatial_scope(
    graph: GradeGraph,
    action: StrategyAction,
    card: OperationCard,
) -> SpatialScope:
    target = action.scope.mask_target
    if card.operation == StrategyOperation.COMPOSITE_MASK:
        assert card.composite_expression is not None
        operands = validate_mask_expression(card.composite_expression)
        available = {
            value
            for asset in graph.masks
            for value in (asset.id, asset.target)
        }
        missing = operands - available
        if missing:
            raise ValueError(
                f"composite mask references unavailable operands: {sorted(missing)}"
            )
        return SpatialScope(
            kind=SpatialKind.COMPOSITE,
            target=target or "composite",
            expression=card.composite_expression,
        )
    if target is None:
        return SpatialScope(kind=SpatialKind.GLOBAL)
    asset = next(
        (
            item
            for item in graph.masks
            if item.id == target or item.target == target
        ),
        None,
    )
    if asset is None:
        raise ValueError(f"mask target {target!r} is unavailable")
    return SpatialScope(
        kind=asset.kind,
        target=asset.target,
        mask_asset_id=asset.id,
    )


def _dependency_edges(
    strategy: ColorStrategy,
    cards: dict[str, OperationCard],
) -> tuple[dict[str, set[str]], list[CompileViolation]]:
    edges = {action.action_id: set() for action in strategy.actions}
    violations: list[CompileViolation] = []
    actions_by_operation: dict[StrategyOperation, list[StrategyAction]] = {}
    for action in strategy.actions:
        actions_by_operation.setdefault(action.operation, []).append(action)
    for action in strategy.actions:
        card = cards.get(action.action_id)
        if card is None:
            continue
        for operation in card.must_follow:
            for dependency in actions_by_operation.get(operation, []):
                edges[action.action_id].add(dependency.action_id)
        for operation in card.must_precede:
            for dependent in actions_by_operation.get(operation, []):
                edges[dependent.action_id].add(action.action_id)
        conflicts = set(card.conflicts_with) & set(actions_by_operation)
        if conflicts:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.CONFLICT,
                    action_id=action.action_id,
                    detail=f"operation conflicts with {sorted(conflicts)}",
                )
            )
    return edges, violations


def _topological_actions(
    strategy: ColorStrategy,
    cards: dict[str, OperationCard],
    edges: dict[str, set[str]],
) -> list[StrategyAction] | None:
    by_id = {item.action_id: item for item in strategy.actions}
    remaining = {action_id: set(values) for action_id, values in edges.items()}
    ordered: list[StrategyAction] = []
    while remaining:
        ready = [
            by_id[action_id]
            for action_id, dependencies in remaining.items()
            if not dependencies
        ]
        if not ready:
            return None
        ready.sort(
            key=lambda action: (
                cards[action.action_id].order_hint or 199,
                action.action_id,
            )
        )
        selected = ready[0]
        ordered.append(selected)
        remaining.pop(selected.action_id)
        for dependencies in remaining.values():
            dependencies.discard(selected.action_id)
    return ordered


def audit_compiler_inputs(
    strategy: ColorStrategy,
    *,
    source_graph: GradeGraph,
    expected_source_graph_digest: str,
    technical_baseline: TechnicalBaseline,
    baseline_asset_id: str,
    baseline_asset_sha256: str,
    registry: OperationCardRegistry,
    policy: CompilationPolicy,
) -> CompilationAuditReport:
    violations: list[CompileViolation] = []
    source_digest = graph_digest(source_graph)
    if source_digest != expected_source_graph_digest:
        violations.append(
            CompileViolation(
                code=CompileViolationCode.STALE_INPUT,
                detail="source Grade Graph changed after the strategy was frozen",
            )
        )
    if (
        technical_baseline.graph_digest != source_digest
        or strategy.technical_baseline_asset_id != baseline_asset_id
        or strategy.technical_baseline_sha256 != baseline_asset_sha256
    ):
        violations.append(
            CompileViolation(
                code=CompileViolationCode.BASELINE_MISMATCH,
                detail="strategy or TechnicalBaseline does not bind to the source graph",
            )
        )
    input_nodes = [
        item for item in source_graph.nodes if item.type == NodeType.INPUT_TRANSFORM
    ]
    output_nodes = [
        item for item in source_graph.nodes if item.type == NodeType.OUTPUT_TRANSFORM
    ]
    if len(input_nodes) != 1 or len(output_nodes) != 1:
        violations.append(
            CompileViolation(
                code=CompileViolationCode.TRANSFORM_MUTATION,
                detail="source graph must contain exactly one input and output transform",
            )
        )
    if not policy.non_waivable_qc_checks:
        violations.append(
            CompileViolation(
                code=CompileViolationCode.QC_BYPASS,
                detail="compiler policy must retain non-waivable QC checks",
            )
        )

    cards: dict[str, OperationCard] = {}
    source_operations = _source_operations(source_graph)
    for action in strategy.actions:
        card = registry.get(action.capability_id)
        if card is None:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.UNKNOWN_CARD,
                    action_id=action.action_id,
                    detail="strategy capability has no versioned operation card",
                )
            )
            continue
        cards[action.action_id] = card
        node_type = _renderer_node_type(card)
        if (
            card.operation != action.operation
            or node_type is None
            or card.order_hint is None
            or not card.parameter_mapping
        ):
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.CARD_MAPPING,
                    action_id=action.action_id,
                    detail="operation card lacks a complete deterministic renderer mapping",
                )
            )
        elif not set(card.parameter_mapping.values()) <= _RENDERER_PARAMETERS.get(
            node_type,
            set(),
        ):
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.CARD_MAPPING,
                    action_id=action.action_id,
                    detail="operation card maps to an unsupported renderer parameter",
                )
            )
        if source_graph.working_color_space.value not in card.supported_color_spaces:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.COLOR_SPACE_INVALID,
                    action_id=action.action_id,
                    detail="operation card does not support the graph working space",
                )
            )
        if (
            card.requires_linear_light
            and source_graph.working_color_space not in _LINEAR_WORKING_SPACES
        ):
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.COLOR_SPACE_INVALID,
                    action_id=action.action_id,
                    detail="operation requires a linear-light working space",
                )
            )
        scope_kind = _scope_kind(action)
        if action.scope.project_id != source_graph.project_id or scope_kind not in card.scopes:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.SCOPE_INVALID,
                    action_id=action.action_id,
                    detail="strategy action scope is not permitted by the operation card",
                )
            )
        try:
            _resolve_time_scope(source_graph, action)
        except ValueError as exc:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.SCOPE_INVALID,
                    action_id=action.action_id,
                    detail=str(exc),
                )
            )
        if card.requires_mask and action.scope.mask_target not in card.allowed_mask_targets:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.MASK_UNAVAILABLE,
                    action_id=action.action_id,
                    detail="operation card requires an allowlisted mask target",
                )
            )
        try:
            _resolve_spatial_scope(source_graph, action, card)
        except ValueError as exc:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.MASK_UNAVAILABLE,
                    action_id=action.action_id,
                    detail=str(exc),
                )
            )
        parameters = _card_parameter_map(card)
        supplied = [item.name for item in action.parameters]
        required = {
            item.name for item in card.parameters
        }
        if len(supplied) != len(set(supplied)) or set(supplied) != required:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.PARAMETER_INVALID,
                    action_id=action.action_id,
                    detail="strategy parameters do not exactly match the operation card",
                )
            )
        for parameter in action.parameters:
            specification = parameters.get(parameter.name)
            mapped = _mapped_parameter_name(card, parameter.name)
            if specification is None or mapped is None:
                continue
            if (
                parameter.unit != specification.unit
                or parameter.minimum < specification.minimum
                or parameter.maximum > specification.maximum
            ):
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.PARAMETER_INVALID,
                        action_id=action.action_id,
                        detail=f"parameter {parameter.name} exceeds card semantics",
                    )
                )
        if action.operation == StrategyOperation.KEYFRAME:
            if not action.parameter_tracks:
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.KEYFRAME_INVALID,
                        action_id=action.action_id,
                        detail="keyframe operation requires typed parameter tracks",
                    )
                )
        elif action.parameter_tracks:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.KEYFRAME_INVALID,
                    action_id=action.action_id,
                    detail="only a keyframe operation may carry parameter tracks",
                )
            )
        ranges = {item.name: item for item in action.parameters}
        for track in action.parameter_tracks:
            parameter = ranges[track.parameter]
            if any(
                point.value < parameter.minimum or point.value > parameter.maximum
                for point in track.points
            ):
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.KEYFRAME_INVALID,
                        action_id=action.action_id,
                        detail=f"track {track.parameter} exceeds the strategy range",
                    )
                )
            try:
                temporal, _ = _resolve_time_scope(source_graph, action)
                assert temporal.time_range is not None
                if any(
                    point.time_seconds < temporal.time_range.start_seconds
                    or point.time_seconds > temporal.time_range.end_seconds
                    for point in track.points
                ):
                    raise ValueError("track point exceeds the action time range")
                Interpolation(track.interpolation)
            except ValueError as exc:
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.KEYFRAME_INVALID,
                        action_id=action.action_id,
                        detail=str(exc),
                    )
                )
        protection_conflicts = (
            set(card.conflicts_with_protections)
            - _exception_covered_protections(strategy, action)
        ) & (
            set(strategy.continuity_constraints)
            | set(action.protected_attributes)
        )
        if protection_conflicts:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.PROTECTION_CONFLICT,
                    action_id=action.action_id,
                    detail=(
                        "operation conflicts with protected attributes: "
                        f"{sorted(protection_conflicts)}"
                    ),
                )
            )
        for dependency in card.must_follow:
            if dependency not in source_operations and not any(
                item.operation == dependency for item in strategy.actions
            ):
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.DEPENDENCY_INVALID,
                        action_id=action.action_id,
                        detail=f"missing required predecessor {dependency.value}",
                    )
                )
        for dependency in card.must_precede:
            if dependency not in source_operations and not any(
                item.operation == dependency for item in strategy.actions
            ):
                violations.append(
                    CompileViolation(
                        code=CompileViolationCode.DEPENDENCY_INVALID,
                        action_id=action.action_id,
                        detail=f"missing required successor {dependency.value}",
                    )
                )
    edges, edge_violations = _dependency_edges(strategy, cards)
    violations.extend(edge_violations)
    if cards and _topological_actions(strategy, cards, edges) is None:
        violations.append(
            CompileViolation(
                code=CompileViolationCode.DEPENDENCY_INVALID,
                detail="operation card dependency graph contains a cycle",
            )
        )
    if strategy.intentional_exceptions:
        if policy.maximum_variants:
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.EXCEPTION_INVALID,
                    detail="exception-bound strategies cannot generate unbound variants",
                )
            )
        if any(
            item.source_graph_digest != source_digest
            for item in strategy.intentional_exceptions
        ):
            violations.append(
                CompileViolation(
                    code=CompileViolationCode.EXCEPTION_INVALID,
                    detail="intentional exception is bound to another source graph",
                )
            )
    return CompilationAuditReport(
        valid=not violations,
        source_graph_digest=source_digest,
        strategy_digest=canonical_sha256(strategy),
        operation_registry_digest=registry.digest,
        required_qc_checks=policy.non_waivable_qc_checks,
        violations=violations,
    )


def _assign_orders(
    source_graph: GradeGraph,
    ordered_actions: list[StrategyAction],
    cards: dict[str, OperationCard],
) -> dict[str, int]:
    used = {node.order for node in source_graph.nodes}
    input_max = max(
        node.order
        for node in source_graph.nodes
        if node.type == NodeType.INPUT_TRANSFORM
    )
    output_min = min(
        node.order
        for node in source_graph.nodes
        if node.type == NodeType.OUTPUT_TRANSFORM
    )
    source_operations = _source_operations(source_graph)
    assigned: dict[str, int] = {}
    for action in ordered_actions:
        card = cards[action.action_id]
        lower = input_max + 1
        for operation in card.must_follow:
            lower = max(
                lower,
                max(source_operations.get(operation, [input_max])) + 1,
                max(
                    (
                        assigned[item.action_id] + 1
                        for item in ordered_actions
                        if item.operation == operation and item.action_id in assigned
                    ),
                    default=lower,
                ),
            )
        order = max(card.order_hint or lower, lower)
        while order in used:
            order += 1
        if order >= output_min:
            raise ValueError("operation ordering leaves no slot before the output transform")
        assigned[action.action_id] = order
        used.add(order)
    for action in ordered_actions:
        card = cards[action.action_id]
        action_order = assigned[action.action_id]
        for operation in card.must_precede:
            successor_orders = [
                *source_operations.get(operation, []),
                *(
                    assigned[item.action_id]
                    for item in ordered_actions
                    if item.operation == operation
                ),
            ]
            if successor_orders and action_order >= min(successor_orders):
                raise ValueError(
                    f"operation {action.action_id} violates must_precede {operation.value}"
                )
    return assigned


def _node_id(strategy: ColorStrategy, action: StrategyAction) -> str:
    safe_strategy = _SAFE_ID.sub("-", strategy.strategy_id).strip("-")
    safe_action = _SAFE_ID.sub("-", action.action_id).strip("-")
    return f"creative_{safe_strategy}_{safe_action}"


def _compile_graph(
    *,
    source_graph: GradeGraph,
    strategy: ColorStrategy,
    ordered_actions: list[StrategyAction],
    cards: dict[str, OperationCard],
    orders: dict[str, int],
    variant_id: str,
    overrides: dict[tuple[str, str], float],
    policy: CompilationPolicy,
) -> tuple[GradeGraph, list[GraphChange]]:
    nodes = [item.model_copy(deep=True) for item in source_graph.nodes]
    changes: list[GraphChange] = []
    for action in ordered_actions:
        card = cards[action.action_id]
        node_type = _renderer_node_type(card)
        assert node_type is not None
        temporal_scope, _ = _resolve_time_scope(source_graph, action)
        spatial_scope = _resolve_spatial_scope(source_graph, action, card)
        parameters = {
            card.parameter_mapping[item.name]: overrides.get(
                (action.action_id, item.name),
                item.nominal,
            )
            for item in action.parameters
        }
        tracks = [
            ParameterTrack(
                parameter=card.parameter_mapping[item.parameter],
                keyframes=[
                    Keyframe(
                        time_seconds=point.time_seconds,
                        value=point.value,
                    )
                    for point in item.points
                ],
                interpolation=Interpolation(item.interpolation),
            )
            for item in action.parameter_tracks
        ]
        node_id = _node_id(strategy, action)
        node = GradeNode(
            id=node_id,
            type=node_type,
            label=f"Creative strategy · {action.action_id}",
            order=orders[action.action_id],
            temporal_scope=temporal_scope,
            spatial_scope=spatial_scope,
            parameters=parameters,
            tracks=tracks,
            metadata={
                "source": CREATIVE_COMPILER_VERSION,
                "strategy_id": strategy.strategy_id,
                "strategy_action_id": action.action_id,
                "strategy_operation": action.operation.value,
                "operation_card_id": card.card_id,
                "operation_card_version": card.card_version,
                "variant_id": variant_id,
                "required_qc_checks": policy.non_waivable_qc_checks,
                "reversibility": card.reversibility,
                "information_loss": card.information_loss,
                "may_cause": card.may_cause,
            },
        )
        nodes.append(node)
        changes.append(
            GraphChange(
                action_id=action.action_id,
                node_id=node_id,
                operation="add",
                after_value=node_type.value,
            )
        )
    payload = source_graph.model_dump(mode="python")
    payload["nodes"] = [
        item.model_dump(mode="python")
        for item in sorted(nodes, key=lambda value: value.order)
    ]
    metadata = dict(source_graph.metadata)
    metadata["creative_compilation"] = {
        "compiler_version": CREATIVE_COMPILER_VERSION,
        "strategy_id": strategy.strategy_id,
        "variant_id": variant_id,
        "operation_cards": {
            card.card_id: card.card_version for card in cards.values()
        },
        "required_qc_checks": policy.non_waivable_qc_checks,
    }
    payload["metadata"] = metadata
    return GradeGraph.model_validate(payload), changes


def _variant_overrides(
    strategy: ColorStrategy,
    policy: CompilationPolicy,
) -> list[tuple[str, dict[tuple[str, str], float]]]:
    variants: list[tuple[str, dict[tuple[str, str], float]]] = [("nominal", {})]
    for action in strategy.actions:
        for parameter in action.parameters:
            if len(variants) - 1 >= policy.maximum_variants:
                return variants
            lower = parameter.nominal - (
                parameter.nominal - parameter.minimum
            ) * policy.variation_fraction
            if abs(lower - parameter.nominal) > 1e-12:
                variants.append(
                    (
                        f"{action.action_id}:{parameter.name}:lower",
                        {(action.action_id, parameter.name): lower},
                    )
                )
            if len(variants) - 1 >= policy.maximum_variants:
                return variants
            upper = parameter.nominal + (
                parameter.maximum - parameter.nominal
            ) * policy.variation_fraction
            if abs(upper - parameter.nominal) > 1e-12:
                variants.append(
                    (
                        f"{action.action_id}:{parameter.name}:upper",
                        {(action.action_id, parameter.name): upper},
                    )
                )
    return variants


def compile_color_strategy(
    strategy: ColorStrategy,
    *,
    source_graph: GradeGraph,
    expected_source_graph_digest: str,
    technical_baseline: TechnicalBaseline,
    baseline_asset_id: str,
    baseline_asset_sha256: str,
    registry: OperationCardRegistry,
    policy: CompilationPolicy,
) -> StrategyCompilationResult:
    source_snapshot = source_graph.model_dump(mode="json")
    audit = audit_compiler_inputs(
        strategy,
        source_graph=source_graph,
        expected_source_graph_digest=expected_source_graph_digest,
        technical_baseline=technical_baseline,
        baseline_asset_id=baseline_asset_id,
        baseline_asset_sha256=baseline_asset_sha256,
        registry=registry,
        policy=policy,
    )
    if not audit.valid:
        raise ColorStrategyCompileError(audit)
    cards = {
        action.action_id: registry.get(action.capability_id)
        for action in strategy.actions
    }
    typed_cards = {
        action_id: card
        for action_id, card in cards.items()
        if card is not None
    }
    edges, _ = _dependency_edges(strategy, typed_cards)
    ordered_actions = _topological_actions(strategy, typed_cards, edges)
    assert ordered_actions is not None
    try:
        orders = _assign_orders(source_graph, ordered_actions, typed_cards)
    except ValueError as exc:
        failed = audit.model_copy(
            update={
                "valid": False,
                "violations": [
                    *audit.violations,
                    CompileViolation(
                        code=CompileViolationCode.DEPENDENCY_INVALID,
                        detail=str(exc),
                    ),
                ],
            }
        )
        raise ColorStrategyCompileError(failed) from exc

    source_digest = graph_digest(source_graph)
    strategy_digest = canonical_sha256(strategy)
    candidates: list[CompiledGraphCandidate] = []
    for variant_id, overrides in _variant_overrides(strategy, policy):
        compiled_graph, changes = _compile_graph(
            source_graph=source_graph,
            strategy=strategy,
            ordered_actions=ordered_actions,
            cards=typed_cards,
            orders=orders,
            variant_id=variant_id,
            overrides=overrides,
            policy=policy,
        )
        compiled_digest = graph_digest(compiled_graph)
        if any(
            exception.candidate_digest != compiled_digest
            for exception in strategy.intentional_exceptions
        ):
            failed = audit.model_copy(
                update={
                    "valid": False,
                    "violations": [
                        CompileViolation(
                            code=CompileViolationCode.EXCEPTION_INVALID,
                            detail=(
                                "intentional exception candidate digest does not match "
                                "the compiled graph"
                            ),
                        )
                    ],
                }
            )
            raise ColorStrategyCompileError(failed)
        contract = CompiledCandidate(
            candidate_id=f"candidate:{compiled_digest[:24]}",
            strategy_id=strategy.strategy_id,
            source_graph_digest=source_digest,
            compiled_graph_digest=compiled_digest,
            undo_graph_digest=source_digest,
            graph_changes=changes,
            operation_card_versions={
                card.card_id: card.card_version for card in typed_cards.values()
            },
            compiler_version=CREATIVE_COMPILER_VERSION,
            validation_passed=True,
        )
        candidates.append(
            CompiledGraphCandidate(
                contract=contract,
                graph=compiled_graph,
                undo_graph=source_graph.model_copy(deep=True),
                variant_id=variant_id,
                strategy_digest=strategy_digest,
                required_qc_checks=policy.non_waivable_qc_checks,
            )
        )
    if source_graph.model_dump(mode="json") != source_snapshot:
        raise RuntimeError("strategy compiler mutated the source Grade Graph")
    source_nodes = {
        item.id: item.model_dump(mode="json") for item in source_graph.nodes
    }
    for candidate in candidates:
        compiled_nodes = {
            item.id: item.model_dump(mode="json") for item in candidate.graph.nodes
        }
        if any(compiled_nodes.get(node_id) != value for node_id, value in source_nodes.items()):
            raise RuntimeError("strategy compiler modified an existing source node")
    return StrategyCompilationResult(
        candidates=tuple(candidates),
        audit=audit,
    )


def apply_compiled_candidate(
    candidate: CompiledGraphCandidate,
    *,
    current_graph: GradeGraph,
    confirmation: Literal["user", "selector"],
) -> AppliedCompiledCandidate:
    if confirmation not in {"user", "selector"}:
        raise ValueError("compiled candidate requires user or selector confirmation")
    current_digest = graph_digest(current_graph)
    if current_digest != candidate.contract.source_graph_digest:
        raise ValueError("cannot apply a compiled candidate to a stale Grade Graph")
    if graph_digest(candidate.undo_graph) != current_digest:
        raise ValueError("candidate undo graph differs from current project state")
    graph = candidate.graph.model_copy(deep=True)
    return AppliedCompiledCandidate(
        candidate_id=candidate.contract.candidate_id,
        confirmation=confirmation,
        graph=graph,
        undo_graph=current_graph.model_copy(deep=True),
        previous_graph_digest=current_digest,
        applied_graph_digest=graph_digest(graph),
    )
