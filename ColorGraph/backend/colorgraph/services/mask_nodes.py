from __future__ import annotations

from datetime import UTC, datetime

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

DEFAULT_MASK_GRADES: dict[str, dict[str, float]] = {
    "sky": {"highlights": -0.14, "saturation": 0.02},
    "vegetation": {"saturation": -0.08, "temperature": 0.02},
    "water": {"saturation": 0.04, "contrast": 0.03},
    "mountain": {"contrast": 0.05, "temperature": -0.025},
    "rock": {"contrast": 0.04, "temperature": -0.015},
    "cliff": {"contrast": 0.04, "highlights": -0.04},
    "land": {"saturation": -0.03, "contrast": 0.02},
    "sand": {"highlights": -0.05, "temperature": 0.015},
    "depth_far": {"contrast": -0.03, "temperature": -0.04, "saturation": -0.03},
}


def ensure_default_mask_nodes(graph: GradeGraph) -> GradeGraph:
    nodes = [node.model_copy(deep=True) for node in graph.nodes]
    existing_targets = {
        node.spatial_scope.target for node in nodes if node.type == NodeType.MASKED_GRADE
    }
    asset_targets = {asset.target: asset for asset in graph.masks}
    used_orders = {node.order for node in nodes}
    full_range = TimeRange(
        start_seconds=0,
        end_seconds=max(graph.media.duration_seconds, 0.001),
    )

    next_order = 60
    for target, parameters in DEFAULT_MASK_GRADES.items():
        if target in existing_targets or target not in asset_targets:
            continue
        while next_order in used_orders:
            next_order += 1
        asset = asset_targets[target]
        nodes.append(
            GradeNode(
                id=f"grade_{target}_default",
                type=NodeType.MASKED_GRADE,
                label=f"{target.replace('_', ' ').title()} protection",
                order=next_order,
                temporal_scope=TemporalScope(
                    level=ScopeLevel.PROJECT,
                    project_id=graph.project_id,
                    time_range=full_range,
                ),
                spatial_scope=SpatialScope(
                    kind=(
                        SpatialKind.DEPTH if target.startswith("depth_") else SpatialKind.SEMANTIC
                    ),
                    target=target,
                    mask_asset_id=asset.id,
                ),
                parameters={**parameters, "mask_strength": 1.0},
                metadata={"source": "landscape-default-recipe/v1"},
            )
        )
        used_orders.add(next_order)
        next_order += 1

    payload = graph.model_dump(mode="python")
    payload["nodes"] = [node.model_dump(mode="python") for node in nodes]
    payload["updated_at"] = datetime.now(UTC)
    return GradeGraph.model_validate(payload)
