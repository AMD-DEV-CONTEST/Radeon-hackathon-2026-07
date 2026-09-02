from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from colorgraph.agent.creative_compiler import OperationCardRegistry
from colorgraph.agent.creative_contracts import (
    CardProvenance,
    ColorProperty,
    OperationCard,
    OperationParameterSpec,
    StrategyOperation,
)
from colorgraph.agent.creative_strategy import (
    CapabilityParameter,
    ColorGraphCapabilityCatalog,
    RendererCapability,
)
from colorgraph.domain.grade_graph import GradeGraph, NodeType
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.masks import validate_mask_expression

OPERATION_CARD_CATALOG_VERSION = "colorgraph.renderer-operation-cards/v1"
CAPABILITY_CATALOG_VERSION = "colorgraph.renderer-capabilities/v1"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_./:-]+$")


@dataclass(frozen=True, slots=True)
class _ParameterDefinition:
    unit: str
    minimum: float
    maximum: float
    neutral: float
    maximum_minor_deviation: float
    color_property: ColorProperty
    semantic: str


_PARAMETERS = {
    "exposure": _ParameterDefinition(
        unit="ev",
        minimum=-1.5,
        maximum=1.5,
        neutral=0,
        maximum_minor_deviation=0.25,
        color_property=ColorProperty.EXPOSURE,
        semantic="Scene-referred exposure offset in photographic stops.",
    ),
    "temperature": _ParameterDefinition(
        unit="normalized",
        minimum=-0.65,
        maximum=0.65,
        neutral=0,
        maximum_minor_deviation=0.12,
        color_property=ColorProperty.TEMPERATURE,
        semantic="Signed blue-to-amber chromatic adaptation intent.",
    ),
    "tint": _ParameterDefinition(
        unit="normalized",
        minimum=-0.5,
        maximum=0.5,
        neutral=0,
        maximum_minor_deviation=0.1,
        color_property=ColorProperty.TINT,
        semantic="Signed green-to-magenta chromatic adaptation intent.",
    ),
    "contrast": _ParameterDefinition(
        unit="normalized",
        minimum=-1,
        maximum=1,
        neutral=0,
        maximum_minor_deviation=0.15,
        color_property=ColorProperty.CONTRAST,
        semantic="Normalized contrast shaping around the renderer pivot.",
    ),
    "saturation": _ParameterDefinition(
        unit="normalized",
        minimum=-1,
        maximum=1,
        neutral=0,
        maximum_minor_deviation=0.15,
        color_property=ColorProperty.SATURATION,
        semantic="Normalized chroma magnitude adjustment in the working pipeline.",
    ),
    "highlights": _ParameterDefinition(
        unit="normalized",
        minimum=-1,
        maximum=1,
        neutral=0,
        maximum_minor_deviation=0.15,
        color_property=ColorProperty.HIGHLIGHT_ROLLOFF,
        semantic="Normalized highlight compression or expansion intent.",
    ),
    "shadows": _ParameterDefinition(
        unit="normalized",
        minimum=-1,
        maximum=1,
        neutral=0,
        maximum_minor_deviation=0.15,
        color_property=ColorProperty.SHADOW_DENSITY,
        semantic="Normalized shadow density and separation intent.",
    ),
}

_OPERATION_PARAMETERS = {
    StrategyOperation.BALANCE: ("exposure", "temperature", "tint"),
    StrategyOperation.TONE: (
        "exposure",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
    ),
    StrategyOperation.LOOK: (
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
    ),
    StrategyOperation.MASKED_GRADE: (
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
    ),
    StrategyOperation.KEYFRAME: (
        "exposure",
        "temperature",
        "contrast",
        "saturation",
    ),
    StrategyOperation.COMPOSITE_MASK: (
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "saturation",
        "highlights",
        "shadows",
    ),
}

_NODE_TYPE = {
    StrategyOperation.BALANCE: NodeType.BALANCE,
    StrategyOperation.TONE: NodeType.TONE,
    StrategyOperation.LOOK: NodeType.LOOK,
    StrategyOperation.MASKED_GRADE: NodeType.MASKED_GRADE,
    StrategyOperation.KEYFRAME: NodeType.TONE,
    StrategyOperation.COMPOSITE_MASK: NodeType.MASKED_GRADE,
}

_ORDER_HINT = {
    StrategyOperation.BALANCE: 30,
    StrategyOperation.TONE: 50,
    StrategyOperation.KEYFRAME: 60,
    StrategyOperation.MASKED_GRADE: 70,
    StrategyOperation.COMPOSITE_MASK: 75,
    StrategyOperation.LOOK: 120,
}

_SCOPES = {
    StrategyOperation.BALANCE: ["scene", "shot", "time"],
    StrategyOperation.TONE: ["scene", "shot", "time"],
    StrategyOperation.LOOK: ["scene", "shot"],
    StrategyOperation.MASKED_GRADE: ["mask"],
    StrategyOperation.KEYFRAME: ["time"],
    StrategyOperation.COMPOSITE_MASK: ["mask"],
}


def operation_card_id(
    operation: StrategyOperation,
    parameter: str,
    *,
    mask_target: str | None = None,
) -> str:
    suffix = f":{mask_target}" if mask_target is not None else ""
    identifier = f"colorgraph.operation:{operation.value}:{parameter}{suffix}"
    if not _IDENTIFIER.fullmatch(identifier):
        raise ValueError(
            "operation-card IDs and mask targets must use identifier-safe characters"
        )
    return identifier


def _provenance(graph: GradeGraph) -> CardProvenance:
    return CardProvenance(
        source_id="colorgraph.renderer-contract",
        source_uri=f"internal://colorgraph/renderer/{graph.renderer_version}",
        source_version=graph.renderer_version,
        rights="internal-authorized",
        permitted_uses=["color_strategist", "compiler"],
        redistributable=False,
    )


def _ordering(
    operation: StrategyOperation,
) -> tuple[list[StrategyOperation], list[StrategyOperation]]:
    if operation == StrategyOperation.LOOK:
        return [StrategyOperation.BALANCE], []
    if operation == StrategyOperation.BALANCE:
        return [], [StrategyOperation.LOOK]
    return [StrategyOperation.BALANCE], [StrategyOperation.LOOK]


def _card(
    graph: GradeGraph,
    *,
    operation: StrategyOperation,
    parameter: str,
    mask_target: str | None = None,
    composite_expression: str | None = None,
) -> OperationCard:
    definition = _PARAMETERS[parameter]
    must_follow, must_precede = _ordering(operation)
    requires_mask = operation in {
        StrategyOperation.MASKED_GRADE,
        StrategyOperation.COMPOSITE_MASK,
    }
    return OperationCard(
        card_id=operation_card_id(
            operation,
            parameter,
            mask_target=mask_target,
        ),
        card_version=OPERATION_CARD_CATALOG_VERSION,
        provenance=_provenance(graph),
        operation=operation,
        parameters=[
            OperationParameterSpec(
                name=parameter,
                unit=definition.unit,
                minimum=definition.minimum,
                maximum=definition.maximum,
                semantic=definition.semantic,
            )
        ],
        supported_color_spaces=["acescg", "linear_rec709"],
        scopes=_SCOPES[operation],
        reversibility=True,
        information_loss=False,
        requires_linear_light=False,
        must_precede=must_precede,
        must_follow=must_follow,
        conflicts_with=[],
        may_cause=[
            "clipping, gamut excursion, temporal discontinuity, or protected-detail loss"
        ],
        validation_checks=[
            "finite_values",
            "legal_output_gamut",
            "scope_integrity",
            "temporal_continuity",
        ],
        repair_guidance=[
            "Reduce the parameter magnitude within its declared range and rerun QC."
        ],
        invalidation_scope=(
            "The compiled candidate, its preview cache, critic evidence, and dependent QC."
        ),
        renderer_node_type=_NODE_TYPE[operation].value,
        parameter_mapping={parameter: parameter},
        order_hint=_ORDER_HINT[operation],
        requires_mask=requires_mask,
        allowed_mask_targets=[mask_target] if mask_target is not None else [],
        composite_expression=composite_expression,
    )


def build_project_operation_cards(
    graph: GradeGraph,
    *,
    composite_masks: Mapping[str, str] | None = None,
) -> tuple[OperationCard, ...]:
    """Build the immutable renderer capability boundary for one source graph."""

    node_types = {node.type for node in graph.nodes}
    required = {
        NodeType.INPUT_TRANSFORM,
        NodeType.BALANCE,
        NodeType.LOOK,
        NodeType.OUTPUT_TRANSFORM,
    }
    missing = required - node_types
    if missing:
        raise ValueError(
            f"operation-card catalog requires a technical baseline: {sorted(missing)}"
        )

    mask_targets = sorted({asset.target for asset in graph.masks})
    for target in mask_targets:
        if not _IDENTIFIER.fullmatch(target):
            raise ValueError(f"mask target is not strategy-safe: {target!r}")

    composites = dict(composite_masks or {})
    available_operands = set(mask_targets)
    for target, expression in sorted(composites.items()):
        if not _IDENTIFIER.fullmatch(target):
            raise ValueError(f"composite mask target is not strategy-safe: {target!r}")
        operands = validate_mask_expression(expression)
        missing_operands = operands - available_operands
        if missing_operands:
            raise ValueError(
                f"composite mask {target!r} references unavailable operands: "
                f"{sorted(missing_operands)}"
            )

    cards: list[OperationCard] = []
    for operation in (
        StrategyOperation.BALANCE,
        StrategyOperation.TONE,
        StrategyOperation.LOOK,
        StrategyOperation.KEYFRAME,
    ):
        cards.extend(
            _card(
                graph,
                operation=operation,
                parameter=parameter,
            )
            for parameter in _OPERATION_PARAMETERS[operation]
        )
    for target in mask_targets:
        cards.extend(
            _card(
                graph,
                operation=StrategyOperation.MASKED_GRADE,
                parameter=parameter,
                mask_target=target,
            )
            for parameter in _OPERATION_PARAMETERS[StrategyOperation.MASKED_GRADE]
        )
    for target, expression in sorted(composites.items()):
        cards.extend(
            _card(
                graph,
                operation=StrategyOperation.COMPOSITE_MASK,
                parameter=parameter,
                mask_target=target,
                composite_expression=expression,
            )
            for parameter in _OPERATION_PARAMETERS[
                StrategyOperation.COMPOSITE_MASK
            ]
        )
    return tuple(sorted(cards, key=lambda item: item.card_id))


def build_renderer_capability_catalog(
    graph: GradeGraph,
    *,
    cards: Sequence[OperationCard] | None = None,
    composite_masks: Mapping[str, str] | None = None,
) -> ColorGraphCapabilityCatalog:
    resolved_cards = tuple(
        cards
        if cards is not None
        else build_project_operation_cards(
            graph,
            composite_masks=composite_masks,
        )
    )
    if not resolved_cards:
        raise ValueError("renderer capability catalog cannot be empty")

    capabilities: list[RendererCapability] = []
    for card in resolved_cards:
        parameters: list[CapabilityParameter] = []
        for specification in card.parameters:
            definition = _PARAMETERS.get(specification.name)
            if definition is None:
                raise ValueError(
                    f"operation card uses unknown renderer parameter "
                    f"{specification.name!r}"
                )
            parameters.append(
                CapabilityParameter(
                    name=specification.name,
                    unit=specification.unit,
                    color_property=definition.color_property,
                    minimum=specification.minimum,
                    maximum=specification.maximum,
                    neutral_value=definition.neutral,
                    maximum_minor_deviation=definition.maximum_minor_deviation,
                )
            )
        capabilities.append(
            RendererCapability(
                capability_id=card.card_id,
                operation=card.operation,
                parameters=parameters,
                allowed_scopes=card.scopes,
                supported_working_color_spaces=card.supported_color_spaces,
                requires_mask=card.requires_mask,
                allowed_mask_targets=card.allowed_mask_targets,
            )
        )

    advertised_masks = {
        target
        for capability in capabilities
        for target in capability.allowed_mask_targets
    }
    return ColorGraphCapabilityCatalog(
        catalog_version=CAPABILITY_CATALOG_VERSION,
        renderer_version=graph.renderer_version,
        project_id=graph.project_id,
        source_graph_digest=graph_digest(graph),
        working_color_space=graph.working_color_space.value,
        allowed_scene_ids=sorted(scene.id for scene in graph.scenes),
        allowed_shot_ids=sorted(shot.id for shot in graph.shots),
        allowed_mask_targets=sorted(advertised_masks),
        capabilities=sorted(
            capabilities,
            key=lambda item: item.capability_id,
        ),
    )


def build_project_operation_registry(
    graph: GradeGraph,
    *,
    composite_masks: Mapping[str, str] | None = None,
) -> OperationCardRegistry:
    return OperationCardRegistry(
        list(
            build_project_operation_cards(
                graph,
                composite_masks=composite_masks,
            )
        )
    )
