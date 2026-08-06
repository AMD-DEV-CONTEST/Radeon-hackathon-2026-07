from __future__ import annotations

import pytest
from test_creative_compiler import (
    BASELINE_ASSET_ID,
    BASELINE_ASSET_SHA,
    _baseline,
    _graph,
    _policy,
    _strategy,
)

from colorgraph.agent.creative_compiler import (
    OperationCardRegistry,
    compile_color_strategy,
)
from colorgraph.agent.creative_contracts import StrategyOperation
from colorgraph.agent.operation_catalog import (
    CAPABILITY_CATALOG_VERSION,
    OPERATION_CARD_CATALOG_VERSION,
    build_project_operation_cards,
    build_project_operation_registry,
    build_renderer_capability_catalog,
    operation_card_id,
)
from colorgraph.grading.looks import graph_digest


def test_project_catalog_is_deterministic_and_covers_native_graph_semantics() -> None:
    graph = _graph()
    composite_masks = {"sky_without_mountain": "sky AND NOT mountain"}

    first = build_project_operation_cards(
        graph,
        composite_masks=composite_masks,
    )
    second = build_project_operation_cards(
        graph,
        composite_masks=composite_masks,
    )
    catalog = build_renderer_capability_catalog(graph, cards=first)

    assert first == second
    assert len(first) == 38
    assert {card.operation for card in first} == set(StrategyOperation)
    assert all(card.card_version == OPERATION_CARD_CATALOG_VERSION for card in first)
    assert all(card.provenance.permitted_uses == ["color_strategist", "compiler"] for card in first)
    assert catalog.catalog_version == CAPABILITY_CATALOG_VERSION
    assert catalog.source_graph_digest == graph_digest(graph)
    assert catalog.working_color_space == "acescg"
    assert catalog.allowed_mask_targets == [
        "mountain",
        "sky",
        "sky_without_mountain",
    ]
    assert {capability.capability_id for capability in catalog.capabilities} == {
        card.card_id for card in first
    }


def test_built_in_catalog_drives_the_real_strategy_compiler() -> None:
    graph = _graph()
    strategy = _strategy()
    tone, masked, look = strategy.actions
    strategy = strategy.model_copy(
        update={
            "actions": [
                tone.model_copy(
                    update={
                        "capability_id": operation_card_id(
                            StrategyOperation.TONE,
                            "contrast",
                        )
                    }
                ),
                masked.model_copy(
                    update={
                        "capability_id": operation_card_id(
                            StrategyOperation.MASKED_GRADE,
                            "saturation",
                            mask_target="sky",
                        )
                    }
                ),
                look.model_copy(
                    update={
                        "capability_id": operation_card_id(
                            StrategyOperation.LOOK,
                            "saturation",
                        )
                    }
                ),
            ]
        }
    )
    registry = build_project_operation_registry(graph)

    result = compile_color_strategy(
        strategy,
        source_graph=graph,
        expected_source_graph_digest=graph_digest(graph),
        technical_baseline=_baseline(graph),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        registry=registry,
        policy=_policy(),
    )

    assert result.audit.valid is True
    assert len(result.candidates) == 3
    assert result.candidates[0].contract.operation_card_versions == {
        action.capability_id: OPERATION_CARD_CATALOG_VERSION
        for action in strategy.actions
    }
    assert graph_digest(result.candidates[0].undo_graph) == graph_digest(graph)


def test_catalog_rejects_unsafe_mask_identifiers_and_missing_operands() -> None:
    graph = _graph()
    payload = graph.model_dump(mode="python")
    payload["masks"][0]["target"] = "unsafe target"
    unsafe_graph = type(graph).model_validate(payload)

    with pytest.raises(ValueError, match="strategy-safe"):
        build_project_operation_cards(unsafe_graph)
    with pytest.raises(ValueError, match="unavailable operands"):
        build_project_operation_cards(
            graph,
            composite_masks={"sky_without_person": "sky AND NOT person"},
        )


def test_explicit_cards_and_registry_have_the_same_capability_boundary() -> None:
    graph = _graph()
    cards = build_project_operation_cards(graph)
    explicit = OperationCardRegistry(list(cards))
    helper = build_project_operation_registry(graph)

    assert explicit.digest == helper.digest
    assert build_renderer_capability_catalog(
        graph,
        cards=cards,
    ).source_graph_digest == graph_digest(graph)
