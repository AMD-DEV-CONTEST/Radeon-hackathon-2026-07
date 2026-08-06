from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from colorgraph.domain.grade_graph import (
    GradeGraph,
    GradeNode,
    NodeType,
    ScopeLevel,
    SpatialKind,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading.looks import LOOK_RECIPES, sync_look_instances


class CommandContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_time: Annotated[float, Field(ge=0)] = 0
    selected_shot_id: str | None = None
    selected_node_id: str | None = None


class NodeEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    operation: str
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    affected_range: TimeRange


class CommandPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GradeGraph
    # An exact pre-command snapshot makes every grammar edit reversible,
    # including created nodes, keyframes, masks and metadata.
    undo_graph: GradeGraph
    edits: list[NodeEdit]
    required_mask_targets: list[str]
    invalidated_ranges: list[TimeRange]
    explanation: str
    planner: str = "landscape-grade-grammar/v2"


@dataclass(frozen=True, slots=True)
class _CommandScope:
    time_range: TimeRange
    level: ScopeLevel
    scene_id: str | None
    shot_id: str | None
    partial: bool = False


TARGET_PATTERNS: dict[str, re.Pattern[str]] = {
    "sky": re.compile(r"天空|云层|高光|sky|cloud|highlight", re.IGNORECASE),
    "vegetation": re.compile(
        r"植被|森林|树木|绿色|草地|vegetation|forest|tree|greenery",
        re.IGNORECASE,
    ),
    "water": re.compile(r"水面|海面|湖面|河流|water|sea|lake|river", re.IGNORECASE),
    "mountain": re.compile(r"山体|远山|山丘|mountain|hill", re.IGNORECASE),
    "rock": re.compile(r"岩石|石头|rock|stone", re.IGNORECASE),
    "cliff": re.compile(r"悬崖|峭壁|cliff", re.IGNORECASE),
    "land": re.compile(r"土地|地面|泥土|land|earth|ground|soil|dirt", re.IGNORECASE),
    "sand": re.compile(r"沙地|沙滩|沙漠|sand|beach|desert", re.IGNORECASE),
    "depth_far": re.compile(r"远景|远处|空间层次|depth|distance|background", re.IGNORECASE),
}

_PROJECT_SCOPE = re.compile(
    r"整段|全片|整体|整个|全程|all\s*(?:video|clip)|whole\s*(?:video|clip)?",
    re.IGNORECASE,
)
_CURRENT_SHOT_SCOPE = re.compile(
    r"这个镜头|当前镜头|本镜头|this\s+shot|current\s+shot",
    re.IGNORECASE,
)
_FIRST_HALF = re.compile(
    r"前半段|前一半|前段|开头|first\s+half|beginning",
    re.IGNORECASE,
)
_SECOND_HALF = re.compile(
    r"后半段|后一半|后段|后面|second\s+half|latter\s+half|ending",
    re.IGNORECASE,
)


def _contains(prompt: str, *patterns: str) -> bool:
    return any(re.search(pattern, prompt, re.IGNORECASE) for pattern in patterns)


def _project_range(graph: GradeGraph) -> TimeRange:
    latest_shot_end = max(
        (shot.time_range.end_seconds for shot in graph.shots),
        default=0.0,
    )
    return TimeRange(
        start_seconds=0.0,
        end_seconds=max(graph.media.duration_seconds, latest_shot_end, 0.001),
    )


def _find_shot(graph: GradeGraph, context: CommandContext):
    if context.selected_shot_id:
        shot = next(
            (item for item in graph.shots if item.id == context.selected_shot_id),
            None,
        )
        if shot is not None:
            return shot
    return next(
        (
            item
            for item in graph.shots
            if item.time_range.start_seconds
            <= context.current_time
            < item.time_range.end_seconds
        ),
        graph.shots[0] if graph.shots else None,
    )


def _chinese_number(value: str) -> int | None:
    normalized = value.strip()
    if normalized.isdigit():
        return int(normalized)
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if normalized in digits:
        return digits[normalized]
    if normalized.startswith("十") and len(normalized) == 2:
        tail = digits.get(normalized[1])
        return 10 + tail if tail is not None else None
    if normalized.endswith("十") and len(normalized) == 2:
        head = digits.get(normalized[0])
        return head * 10 if head is not None else None
    if len(normalized) == 3 and normalized[1] == "十":
        head = digits.get(normalized[0])
        tail = digits.get(normalized[2])
        return head * 10 + tail if head is not None and tail is not None else None
    return None


def _scene_from_prompt(graph: GradeGraph, prompt: str):
    for scene in graph.scenes:
        if re.search(rf"(?<![\w-]){re.escape(scene.id)}(?![\w-])", prompt, re.IGNORECASE):
            return scene

    match = re.search(
        r"(?:scene|场景)[\s_#-]*(\d+)",
        prompt,
        re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r"第\s*([一二两三四五六七八九十\d]{1,3})\s*(?:个)?场景",
            prompt,
            re.IGNORECASE,
        )
    if match is None:
        return None
    scene_number = _chinese_number(match.group(1))
    if scene_number is None or scene_number < 1:
        raise ValueError(f"invalid scene selector: {match.group(0)!r}")
    ordered = sorted(graph.scenes, key=lambda scene: scene.index)
    if scene_number > len(ordered):
        raise ValueError(
            f"scene {scene_number} does not exist; project contains {len(ordered)} scenes"
        )
    return ordered[scene_number - 1]


def _scene_range(graph: GradeGraph, scene_id: str) -> TimeRange:
    shot_ranges = [
        shot.time_range
        for shot in graph.shots
        if shot.scene_id == scene_id
    ]
    if shot_ranges:
        return TimeRange(
            start_seconds=min(item.start_seconds for item in shot_ranges),
            end_seconds=max(item.end_seconds for item in shot_ranges),
        )
    look_range = next(
        (
            node.temporal_scope.time_range
            for node in graph.nodes
            if node.type == NodeType.LOOK
            and node.temporal_scope.scene_id == scene_id
            and node.temporal_scope.time_range is not None
        ),
        None,
    )
    if look_range is None:
        raise ValueError(f"scene {scene_id!r} has no resolvable time range")
    return look_range


def _half_range(time_range: TimeRange, *, second: bool) -> TimeRange:
    midpoint = (time_range.start_seconds + time_range.end_seconds) / 2
    return TimeRange(
        start_seconds=midpoint if second else time_range.start_seconds,
        end_seconds=time_range.end_seconds if second else midpoint,
    )


def _command_scope(
    graph: GradeGraph,
    prompt: str,
    context: CommandContext,
) -> _CommandScope:
    project_requested = _PROJECT_SCOPE.search(prompt) is not None
    scene = _scene_from_prompt(graph, prompt)
    shot_requested = _CURRENT_SHOT_SCOPE.search(prompt) is not None
    first_half = _FIRST_HALF.search(prompt) is not None
    second_half = _SECOND_HALF.search(prompt) is not None
    if first_half and second_half:
        raise ValueError("command cannot select both the first and second half")
    if project_requested and scene is not None:
        raise ValueError("command contains conflicting project and scene scopes")

    shot = _find_shot(graph, context)
    if scene is not None:
        base = _CommandScope(
            time_range=_scene_range(graph, scene.id),
            level=ScopeLevel.SCENE,
            scene_id=scene.id,
            shot_id=None,
        )
    elif project_requested:
        base = _CommandScope(
            time_range=_project_range(graph),
            level=ScopeLevel.PROJECT,
            scene_id=None,
            shot_id=None,
        )
    elif shot_requested or first_half or second_half:
        if shot is None:
            raise ValueError("command requests a shot scope but the graph contains no shots")
        base = _CommandScope(
            time_range=shot.time_range,
            level=ScopeLevel.SHOT,
            scene_id=shot.scene_id,
            shot_id=shot.id,
        )
    else:
        base = _CommandScope(
            time_range=_project_range(graph),
            level=ScopeLevel.PROJECT,
            scene_id=None,
            shot_id=None,
        )

    if first_half or second_half:
        return _CommandScope(
            time_range=_half_range(base.time_range, second=second_half),
            level=(
                ScopeLevel.SUB_SHOT
                if base.level == ScopeLevel.SHOT
                else base.level
            ),
            scene_id=base.scene_id,
            shot_id=base.shot_id,
            partial=True,
        )
    return base


def _look_recipe(prompt: str) -> str | None:
    if _contains(
        prompt,
        r"清冷风格|冷系纪录片|纪录片风格|cool\s+documentary|cool\s+look",
    ):
        return "cool"
    if _contains(prompt, r"日落风格|暖色风格|黄金时刻|sunset|warm\s+look"):
        return "warm"
    if _contains(prompt, r"雾境|雾感|柔和雾|foggy|mist"):
        return "foggy"
    if _contains(prompt, r"自然风格|旅行风格|natural\s+look|travel\s+look"):
        return "natural"
    return None


def _target_adjustments(prompt: str, target: str) -> dict[str, float]:
    parameters: dict[str, float] = {}
    darker = _contains(prompt, r"压暗|更暗|降低亮度|darken|darker")
    brighter = _contains(prompt, r"提亮|更亮|增加亮度|brighten|brighter")
    less_saturated = _contains(
        prompt,
        r"不要太艳|降低饱和|去饱和|克制|desaturat|less\s+saturat",
    )
    more_saturated = _contains(prompt, r"更鲜艳|增加饱和|more\s+saturat|vivid")
    cooler = _contains(prompt, r"更冷|偏冷|变冷|cooler|colder")
    warmer = _contains(prompt, r"更暖|偏暖|变暖|warmer")

    if darker:
        parameters["exposure"] = -0.18 if target == "sky" else -0.12
    if brighter:
        parameters["exposure"] = 0.14
    if target == "sky" and _contains(prompt, r"高光|云层|层次|highlight|cloud"):
        parameters["highlights"] = -0.22
    if less_saturated:
        parameters["saturation"] = -0.14
    if more_saturated:
        parameters["saturation"] = 0.12
    if cooler:
        parameters["temperature"] = -0.12
    if warmer:
        parameters["temperature"] = 0.12
    if target == "mountain" and _contains(prompt, r"层次|空间|depth|dimension"):
        parameters.setdefault("contrast", 0.08)
        parameters.setdefault("temperature", -0.06)
    if target == "depth_far" and not parameters:
        parameters = {
            "contrast": -0.04,
            "temperature": -0.06,
            "saturation": -0.04,
        }
    return parameters


def _global_adjustments(prompt: str) -> dict[str, float]:
    parameters: dict[str, float] = {}
    if _contains(prompt, r"提亮|更亮|增加亮度|brighten|brighter"):
        parameters["exposure"] = 0.12
    if _contains(prompt, r"压暗|更暗|降低亮度|darken|darker"):
        parameters["exposure"] = -0.12
    if _contains(prompt, r"更冷|偏冷|变冷|cooler|colder"):
        parameters["temperature"] = -0.10
    if _contains(prompt, r"更暖|偏暖|变暖|warmer"):
        parameters["temperature"] = 0.10
    return parameters


def _target_is_locked(prompt: str, target: str) -> bool:
    pattern = TARGET_PATTERNS[target]
    for match in pattern.finditer(prompt):
        prefix = prompt[max(0, match.start() - 24) : match.start()]
        suffix = prompt[match.end() : match.end() + 12]
        if re.search(
            r"(不要改变|不要动|不改变|别动|锁定|保护|"
            r"do\s+not\s+change|don't\s+change|lock|protect|preserve)"
            r"(?:\s+the)?\s*$",
            prefix,
            re.IGNORECASE,
        ):
            return True
        if re.match(
            r"\s*(?:保持不变|不变|不要变|unchanged|protected|locked)",
            suffix,
            re.IGNORECASE,
        ):
            return True
    return False


def _next_order(nodes: list[GradeNode]) -> int:
    used = {node.order for node in nodes}
    for candidate in range(60, 100):
        if candidate not in used:
            return candidate
    return max(used, default=0) + 1


def _unique_node_id(prefix: str, nodes: list[GradeNode]) -> str:
    used = {node.id for node in nodes}
    candidate = prefix
    suffix = 2
    while candidate in used:
        candidate = f"{prefix}_{suffix:02d}"
        suffix += 1
    return candidate


def _validated_graph(graph: GradeGraph, nodes: list[GradeNode]) -> GradeGraph:
    payload = graph.model_dump(mode="python")
    payload["nodes"] = [node.model_dump(mode="python") for node in nodes]
    payload["updated_at"] = datetime.now(UTC)
    return GradeGraph.model_validate(payload)


def _scope_matches(node: GradeNode, scope: _CommandScope) -> bool:
    temporal = node.temporal_scope
    return (
        temporal.level == scope.level
        and temporal.scene_id == scope.scene_id
        and temporal.shot_id == scope.shot_id
        and temporal.time_range == scope.time_range
    )


def _matching_balance_nodes(
    nodes: list[GradeNode],
    scope: _CommandScope,
) -> list[GradeNode]:
    if scope.partial:
        return []
    enabled_balances = [
        node
        for node in nodes
        if node.enabled and node.type == NodeType.BALANCE
    ]
    shot_balances = [
        node
        for node in enabled_balances
        if node.temporal_scope.shot_id is not None
    ]
    if scope.level == ScopeLevel.PROJECT:
        # The v2 grammar deliberately expands project commands over the
        # existing per-shot Balance model instead of creating an ambiguous
        # second project-level base grade.
        return shot_balances or [
            node
            for node in enabled_balances
            if node.temporal_scope.level == ScopeLevel.PROJECT
        ]
    if scope.level == ScopeLevel.SCENE:
        return [
            node
            for node in shot_balances
            if node.temporal_scope.scene_id == scope.scene_id
        ]
    if scope.level == ScopeLevel.SHOT:
        return [
            node
            for node in shot_balances
            if node.temporal_scope.shot_id == scope.shot_id
        ]
    return []


def _shift_balance(
    node: GradeNode,
    adjustments: dict[str, float],
) -> None:
    for parameter, delta in adjustments.items():
        current = float(node.parameters.get(parameter, 0.0))
        node.parameters[parameter] = round(current + delta, 5)
        for track in node.tracks:
            if track.parameter != parameter:
                continue
            for keyframe in track.keyframes:
                keyframe.value = round(keyframe.value + delta, 5)


def _new_temporal_scope(graph: GradeGraph, scope: _CommandScope) -> TemporalScope:
    return TemporalScope(
        level=scope.level,
        project_id=graph.project_id,
        scene_id=scope.scene_id,
        shot_id=scope.shot_id,
        time_range=scope.time_range,
    )


def _create_scoped_balance(
    graph: GradeGraph,
    nodes: list[GradeNode],
    scope: _CommandScope,
    adjustments: dict[str, float],
    prompt: str,
) -> GradeNode:
    scope_label = (
        scope.shot_id
        or scope.scene_id
        or f"{scope.time_range.start_seconds:g}-{scope.time_range.end_seconds:g}"
    )
    node = GradeNode(
        id=_unique_node_id(f"balance_command_{scope_label}", nodes),
        type=NodeType.BALANCE,
        label="Scoped command balance",
        order=_next_order(nodes),
        temporal_scope=_new_temporal_scope(graph, scope),
        parameters=dict(adjustments),
        metadata={
            "created_by": "landscape-grade-grammar/v2",
            "prompt": prompt,
            "adjustment_model": "scoped_overlay",
        },
    )
    nodes.append(node)
    return node


def _upsert_masked_grade(
    graph: GradeGraph,
    nodes: list[GradeNode],
    scope: _CommandScope,
    *,
    target: str,
    adjustments: dict[str, float],
    protected_targets: list[str],
    prompt: str,
) -> tuple[GradeNode, str]:
    protected_expression = (
        " AND ".join(f"NOT {item}" for item in protected_targets)
        if protected_targets
        else None
    )
    if target == "global":
        mask_expression = protected_expression
    else:
        mask_expression = (
            f"{target} AND {protected_expression}"
            if protected_expression
            else None
        )
    asset_id = f"mask_{target}"
    node = next(
        (
            candidate
            for candidate in nodes
            if candidate.type == NodeType.MASKED_GRADE
            and candidate.spatial_scope.target == target
            and candidate.spatial_scope.expression == mask_expression
            and _scope_matches(candidate, scope)
        ),
        None,
    )
    if node is None:
        node = GradeNode(
            id=_unique_node_id(f"grade_{target}_command", nodes),
            type=NodeType.MASKED_GRADE,
            label=(
                "Global grade with protected regions"
                if target == "global"
                else f"{target.replace('_', ' ').title()} grade"
            ),
            order=_next_order(nodes),
            temporal_scope=_new_temporal_scope(graph, scope),
            spatial_scope=SpatialScope(
                kind=(
                    SpatialKind.COMPOSITE
                    if mask_expression
                    else (
                        SpatialKind.DEPTH
                        if target.startswith("depth_")
                        else SpatialKind.SEMANTIC
                    )
                ),
                target=target,
                mask_asset_id=None if mask_expression else asset_id,
                expression=mask_expression,
            ),
            parameters={**adjustments, "mask_strength": 1.0},
            metadata={
                "created_by": "landscape-grade-grammar/v2",
                "prompt": prompt,
                "protected_targets": protected_targets,
            },
        )
        nodes.append(node)
        return node, "create_masked_grade"

    for parameter, delta in adjustments.items():
        current = float(node.parameters.get(parameter, 0.0))
        node.parameters[parameter] = round(current + delta, 5)
    node.metadata["prompt"] = prompt
    node.metadata["protected_targets"] = protected_targets
    return node, "update_masked_grade"


class GradeCommandPlanner:
    def plan(
        self,
        graph: GradeGraph,
        prompt: str,
        context: CommandContext | None = None,
    ) -> CommandPlan:
        normalized = prompt.strip()
        if not normalized:
            raise ValueError("prompt cannot be empty")
        command_context = context or CommandContext()
        scope = _command_scope(graph, normalized, command_context)
        nodes = [node.model_copy(deep=True) for node in graph.nodes]
        edits: list[NodeEdit] = []
        required_masks: list[str] = []
        reasons: list[str] = []

        recipe_id = _look_recipe(normalized)
        if recipe_id:
            if scope.partial or scope.level in {ScopeLevel.SHOT, ScopeLevel.SUB_SHOT}:
                raise ValueError(
                    "Look recipes can target the whole project or a complete scene; "
                    "use balance adjustments for partial-shot commands"
                )
            recipe = LOOK_RECIPES[recipe_id]
            looks = [
                node
                for node in nodes
                if node.enabled
                and node.type == NodeType.LOOK
                and (
                    scope.level == ScopeLevel.PROJECT
                    or node.temporal_scope.scene_id == scope.scene_id
                )
            ]
            if not looks:
                raise ValueError("grade graph does not contain an applicable scene Look node")
            for look in looks:
                look.label = str(recipe["label"])
                look.parameters.update(
                    {
                        key: value
                        for key, value in recipe.items()
                        if key != "label"
                    }
                )
                look.metadata.pop("look_instance", None)
                look.metadata["recipe_id"] = recipe_id
                edits.append(
                    NodeEdit(
                        node_id=look.id,
                        operation="update_look",
                        parameters=dict(look.parameters),
                        affected_range=scope.time_range,
                    )
                )
            reasons.append(
                f"将 {len(looks)} 个场景 Look 切换为 {str(recipe['label'])}"
            )

        matched_targets = [
            target
            for target, pattern in TARGET_PATTERNS.items()
            if pattern.search(normalized)
        ]
        protected_targets = [
            target
            for target in matched_targets
            if _target_is_locked(normalized, target)
        ]
        editable_targets = [
            target
            for target in matched_targets
            if target not in protected_targets
        ]

        for target in editable_targets:
            adjustments = _target_adjustments(normalized, target)
            if not adjustments:
                continue
            node, operation = _upsert_masked_grade(
                graph,
                nodes,
                scope,
                target=target,
                adjustments=adjustments,
                protected_targets=protected_targets,
                prompt=normalized,
            )
            edits.append(
                NodeEdit(
                    node_id=node.id,
                    operation=operation,
                    parameters=dict(node.parameters),
                    affected_range=scope.time_range,
                )
            )
            required_masks.extend([target, *protected_targets])
            reasons.append(f"为 {target} 区域创建局部调色")

        if not editable_targets:
            global_adjustments = _global_adjustments(normalized)
            if global_adjustments and protected_targets:
                node, operation = _upsert_masked_grade(
                    graph,
                    nodes,
                    scope,
                    target="global",
                    adjustments=global_adjustments,
                    protected_targets=protected_targets,
                    prompt=normalized,
                )
                edits.append(
                    NodeEdit(
                        node_id=node.id,
                        operation=operation,
                        parameters=dict(node.parameters),
                        affected_range=scope.time_range,
                    )
                )
                required_masks.extend(protected_targets)
                reasons.append(
                    "在保护区域之外应用全局调整"
                )
            elif global_adjustments:
                balances = _matching_balance_nodes(nodes, scope)
                if balances:
                    for balance in balances:
                        _shift_balance(balance, global_adjustments)
                        edits.append(
                            NodeEdit(
                                node_id=balance.id,
                                operation="update_balance",
                                parameters=dict(balance.parameters),
                                affected_range=scope.time_range,
                            )
                        )
                    reasons.append(
                        f"将调整展开到 {len(balances)} 个适用的镜头 Balance，"
                        "并同步偏移对应关键帧"
                    )
                else:
                    balance = _create_scoped_balance(
                        graph,
                        nodes,
                        scope,
                        global_adjustments,
                        normalized,
                    )
                    edits.append(
                        NodeEdit(
                            node_id=balance.id,
                            operation="create_scoped_balance",
                            parameters=dict(balance.parameters),
                            affected_range=scope.time_range,
                        )
                    )
                    reasons.append("创建与命令时间范围完全一致的叠加 Balance")

        if not edits:
            reasons.append("未发现可安全映射的调色操作，节点保持不变")
        updated = sync_look_instances(_validated_graph(graph, nodes))
        return CommandPlan(
            graph=updated,
            undo_graph=graph.model_copy(deep=True),
            edits=edits,
            required_mask_targets=sorted(set(required_masks)),
            invalidated_ranges=[scope.time_range] if edits else [],
            explanation="；".join(reasons),
        )
