from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    CardProvenance,
    ColorLanguageCue,
    ColorProperty,
    ContextBudget,
    ContrastCharacter,
    CreativeBrief,
    CreativeDirection,
    CreativePossibilityCard,
    EvidenceKind,
    EvidenceReference,
    FailureCard,
    OperationCard,
    OperationParameterSpec,
    PaletteCharacter,
    ProjectContextPack,
    ProjectVisualThesis,
    ProtectedAttribute,
    RetrievalRoute,
    StrategyOperation,
    VisualHierarchyItem,
    canonical_sha256,
)
from colorgraph.agent.creative_retrieval import (
    CreativeKnowledgeIndex,
    RetrievalFilterContext,
    retrieve_creative_possibilities,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _context() -> ProjectContextPack:
    return ProjectContextPack(
        technical_baseline_asset_id="baseline:test",
        technical_baseline_sha256=_sha("baseline"),
        graph_digest=_sha("graph"),
        evidence_bundle_schema_version="colorgraph.agent-evidence-bundle/v1",
        evidence_bundle_digest=_sha("evidence"),
        allowed_scene_ids=["scene:lake"],
        allowed_shot_ids=["shot:lake"],
        evidence=[
            EvidenceReference(
                evidence_id="frame:lake",
                kind=EvidenceKind.FRAME,
                digest=_sha("frame"),
                summary=(
                    "A still winter lake reflects an overcast sky above a restrained shore."
                ),
                frame_index=12,
                scene_id="scene:lake",
                shot_id="shot:lake",
            ),
            EvidenceReference(
                evidence_id="measurement:lake",
                kind=EvidenceKind.MEASUREMENT,
                digest=_sha("measurement"),
                summary="Highlights retain detail and the palette remains restrained.",
                scene_id="scene:lake",
                shot_id="shot:lake",
            ),
        ],
        budget=ContextBudget(
            maximum_images=8,
            maximum_image_edge=1_024,
            maximum_audio_seconds=0,
            maximum_tokens=8_000,
            maximum_context_bytes=8_000_000,
        ),
        omitted_evidence_ids=[],
    )


def _brief(direction: CreativeDirection) -> CreativeBrief:
    emotion = {
        CreativeDirection.FAITHFUL: "quiet stillness",
        CreativeDirection.AMPLIFIED: "held stillness and anticipation",
        CreativeDirection.COUNTERPOINT: "unsettled stillness",
    }[direction]
    return CreativeBrief(
        brief_id=f"brief:{direction.value}",
        scene_id="scene:lake",
        direction=direction,
        interpretation=(
            f"A {direction.value} interpretation of contemplative stillness at the lake."
        ),
        evidence_for=["frame:lake"],
        evidence_against=["measurement:lake"],
        emotional_target=emotion,
        visual_hierarchy=[
            VisualHierarchyItem(
                target=f"lake-{direction.value}",
                priority=1,
                rationale="The reflection and low horizon hold the visual focus.",
                evidence_ids=["frame:lake"],
            )
        ],
        possible_color_language=[
            ColorLanguageCue(
                target=f"lake-{direction.value}",
                property=ColorProperty.CONTRAST,
                direction=AdjustmentDirection.PRESERVE,
                minimum_strength=0,
                maximum_strength=0.3,
                rationale="Preserve the restrained relationship in the source.",
            )
        ],
        cliche_risks=["Avoid a fixed winter preset or automatic blue cast."],
        confidence=0.7,
        uncertainties=["The author's intended emotion is not explicit."],
        failure_conditions=["The reflection loses visual focus or feels formulaic."],
    )


def _thesis() -> ProjectVisualThesis:
    return ProjectVisualThesis(
        thesis_id="thesis:retrieval",
        project_interpretation="A restrained study of stillness and reflected light.",
        palette_character=PaletteCharacter.RESTRAINED,
        contrast_character=ContrastCharacter.NATURAL,
        shared_protections=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        evidence_for=["frame:lake"],
        evidence_against=["measurement:lake"],
        confidence=0.7,
        uncertainties=[],
        briefs=[_brief(direction) for direction in CreativeDirection],
    )


def _provenance(
    source_id: str,
    *,
    rights: str = "cc-by-4.0",
    use: str = "creative_retrieval",
    redistributable: bool = True,
) -> CardProvenance:
    return CardProvenance(
        source_id=source_id,
        source_uri=f"https://knowledge.example/{source_id}",
        source_version="v1",
        rights=rights,
        permitted_uses=[use],
        redistributable=redistributable,
    )


def _card(
    card_id: str,
    *,
    source_id: str,
    concept: str,
    scene_terms: list[str],
    emotion_terms: list[str],
    routes: list[RetrievalRoute],
    template_family: str,
    media_types: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    provenance: CardProvenance | None = None,
    reference_asset_uris: list[str] | None = None,
    lake_related: bool = True,
) -> CreativePossibilityCard:
    if lake_related:
        visual_cue = (
            f"{concept}; observe still lake reflection, horizon, and highlight detail."
        )
        cliche_risk = (
            "Avoid a winter preset, automatic blue cast, and formulaic landscape contrast."
        )
        counterexample = (
            "A bright mirrored lake can feel exposed; neutral snow can resist a blue shortcut."
        )
        strategy = (
            f"Explore {concept} through bounded relationships rather than fixed parameters."
        )
        alternative = (
            f"Question {concept} with a different emotional reading of the same evidence."
        )
    else:
        visual_cue = f"{concept}; observe crowd rhythm, practical lights, and movement."
        cliche_risk = "Avoid treating every dance floor as euphoric spectacle."
        counterexample = "An empty venue can feel suspended rather than energetic."
        strategy = "Follow pulsing practical lights and rapid crowd motion."
        alternative = "An empty venue could emphasize the aftermath of a gathering."
    return CreativePossibilityCard(
        card_id=card_id,
        card_version="v1",
        provenance=provenance or _provenance(source_id),
        concept=concept,
        possible_visual_cues=[visual_cue],
        possible_grade_strategies=[strategy],
        alternatives=[alternative],
        cliche_risks=[cliche_risk],
        counterexamples=[counterexample],
        scene_terms=scene_terms,
        emotion_terms=emotion_terms,
        route_support=routes,
        media_types=media_types or ["video"],
        color_domains=["scene_linear"],
        scopes=["scene"],
        required_capabilities=required_capabilities or ["tone"],
        compatible_protections=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        template_family=template_family,
        reference_asset_uris=reference_asset_uris or [],
    )


def _index(*, include_unrelated: bool = True) -> CreativeKnowledgeIndex:
    index = CreativeKnowledgeIndex("possibilities:test-v1")
    index.publish_possibility(
        _card(
            "possibility:same-scene",
            source_id="source:field-notes",
            concept="Reserved melancholy within a still lake reflection",
            scene_terms=["winter lake", "reflection", "restrained shore"],
            emotion_terms=["melancholy", "watchful quiet"],
            routes=[RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION],
            template_family="family:observational",
        )
    )
    index.publish_possibility(
        _card(
            "possibility:same-emotion",
            source_id="source:architecture-notes",
            concept="Contemplative stillness through sparse spatial separation",
            scene_terms=["sparse architecture", "empty room"],
            emotion_terms=["quiet stillness", "held anticipation", "unsettled calm"],
            routes=[RetrievalRoute.SAME_EMOTION_DIFFERENT_SCENE],
            template_family="family:spatial",
        )
    )
    index.publish_possibility(
        _card(
            "possibility:counterexample",
            source_id="source:winter-counterexamples",
            concept="Neutral winter highlights that resist an automatic blue shortcut",
            scene_terms=["snow", "winter lake", "mixed light"],
            emotion_terms=["ambiguity", "exposure"],
            routes=[RetrievalRoute.COUNTEREXAMPLE_OR_FAILURE],
            template_family="family:counterexample",
        )
    )
    if include_unrelated:
        index.publish_possibility(
            _card(
                "possibility:unrelated",
                source_id="source:nightclub",
                concept="Pulsing magenta energy on a crowded dance floor",
                scene_terms=["nightclub", "crowd", "strobe"],
                emotion_terms=["euphoria", "velocity"],
                routes=list(RetrievalRoute),
                template_family="family:nightlife",
                lake_related=False,
            )
        )
    return index


def _filters() -> RetrievalFilterContext:
    return RetrievalFilterContext(
        media_type="video",
        color_domain="scene_linear",
        scope="scene",
        available_capabilities=["tone", "look"],
        allowed_rights=["cc-by-4.0"],
        required_protections=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
    )


def _operation_card() -> OperationCard:
    return OperationCard(
        card_id="operation:tone",
        card_version="v1",
        provenance=_provenance(
            "source:renderer-manual",
            rights="internal-authorized",
            use="compiler",
            redistributable=False,
        ),
        operation=StrategyOperation.TONE,
        parameters=[
            OperationParameterSpec(
                name="contrast",
                unit="normalized",
                minimum=-1,
                maximum=1,
                semantic="Normalized contrast intent.",
            )
        ],
        supported_color_spaces=["acescg"],
        scopes=["project", "scene", "shot"],
        reversibility=True,
        information_loss=False,
        requires_linear_light=True,
        must_precede=[],
        must_follow=[StrategyOperation.BALANCE],
        conflicts_with=[],
        may_cause=["highlight clipping"],
        validation_checks=["finite_values", "highlight_clipping"],
        repair_guidance=["Reduce the bounded contrast intent."],
        invalidation_scope="The compiled candidate only.",
    )


def _failure_card() -> FailureCard:
    return FailureCard(
        card_id="failure:blue-snow",
        card_version="v1",
        provenance=_provenance(
            "source:qc-manual",
            rights="internal-authorized",
            use="qc",
            redistributable=False,
        ),
        failure_class="snow_neutrality",
        applicable_operations=[StrategyOperation.BALANCE, StrategyOperation.LOOK],
        failure_evidence=["Neutral snow drifts toward an unsupported blue cast."],
        detection_checks=["snow_color_delta"],
        repair_steps=["Reduce the responsible local or look contribution."],
    )


def test_three_route_retrieval_preserves_frozen_briefs_and_records_decisions() -> None:
    thesis = _thesis()
    before = canonical_sha256(thesis)

    result = retrieve_creative_possibilities(
        thesis=thesis,
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=_index(),
        filters=_filters(),
        relevance_threshold=0.24,
        maximum_per_route=2,
    )

    assert canonical_sha256(thesis) == before
    assert result.audit.thesis_digest_before == result.audit.thesis_digest_after
    assert len(result.bundle.retrievals) == 9
    assert result.audit.metrics.route_coverage == 1
    assert result.audit.metrics.counterexample_hit_rate == 1
    assert result.audit.metrics.source_diversity >= 0.75
    assert result.audit.metrics.low_relevance_rejection_rate == 1
    assert result.audit.metrics.convergence_risk_rate == 0
    assert all(
        item.selected_reason is not None or item.excluded_reason is not None
        for retrieval in result.bundle.retrievals
        for item in retrieval.results
    )
    assert all(
        expansion.frozen_brief_sha256
        == result.audit.brief_digests_before[expansion.brief_id]
        for expansion in result.bundle.expansions
    )
    assert all(expansion.expanded_possibilities for expansion in result.bundle.expansions)
    assert all(expansion.challenges for expansion in result.bundle.expansions)


def test_card_boundaries_keep_operation_and_failure_knowledge_out_of_rag() -> None:
    index = _index(include_unrelated=False)
    index.publish_operation(_operation_card())
    index.publish_failure(_failure_card())

    result = retrieve_creative_possibilities(
        thesis=_thesis(),
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=index,
        filters=_filters(),
        relevance_threshold=0.24,
    )
    result_ids = {
        item.card_id
        for retrieval in result.bundle.retrievals
        for item in retrieval.results
    }

    assert "operation:tone" not in result_ids
    assert "failure:blue-snow" not in result_ids
    assert {card.card_id for card in index.operation_cards_for_compiler()} == {
        "operation:tone"
    }
    assert {card.card_id for card in index.failure_cards_for_qc()} == {
        "failure:blue-snow"
    }


def test_hard_filters_are_non_emotional_and_record_every_rejection() -> None:
    index = _index(include_unrelated=False)
    index.publish_possibility(
        _card(
            "possibility:image-only",
            source_id="source:image",
            concept="Stillness in a photographic sequence",
            scene_terms=["lake", "reflection"],
            emotion_terms=["stillness"],
            routes=list(RetrievalRoute),
            template_family="family:photo",
            media_types=["image"],
        )
    )

    result = retrieve_creative_possibilities(
        thesis=_thesis(),
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=index,
        filters=_filters(),
        relevance_threshold=0.24,
    )
    decisions = [
        next(
            item
            for item in route.hard_filters
            if item.card_id == "possibility:image-only"
        )
        for route in result.audit.route_audits
    ]

    assert all(decision.allowed is False for decision in decisions)
    assert all(decision.reasons == ["media_type"] for decision in decisions)
    assert result.audit.metrics.hard_filter_rejection_count == 9


def test_ood_queries_return_an_explicit_empty_bundle() -> None:
    index = CreativeKnowledgeIndex("possibilities:ood-v1")
    index.publish_possibility(
        _card(
            "possibility:nightclub-only",
            source_id="source:nightclub",
            concept="Pulsing magenta energy on a crowded dance floor",
            scene_terms=["nightclub", "crowd", "strobe"],
            emotion_terms=["euphoria", "velocity"],
            routes=list(RetrievalRoute),
            template_family="family:nightlife",
            lake_related=False,
        )
    )

    result = retrieve_creative_possibilities(
        thesis=_thesis(),
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=index,
        filters=_filters(),
        relevance_threshold=0.7,
    )

    assert result.bundle.selected_cards == []
    assert result.bundle.empty_bundle_reason is not None
    assert result.audit.metrics.route_coverage == 0
    assert all(
        item.selected_reason is None
        and item.excluded_reason.startswith("ood_below_threshold")
        for retrieval in result.bundle.retrievals
        for item in retrieval.results
    )


def test_source_deletion_removes_cards_and_invalidates_derived_embeddings() -> None:
    index = _index(include_unrelated=False)
    embedding_id = index.embedding_id("possibility:same-scene")
    assert embedding_id is not None
    before_count = index.embedding_count()

    report = index.delete_source("source:field-notes")

    assert report.removed_possibility_card_ids == ["possibility:same-scene"]
    assert report.invalidated_embedding_ids == [embedding_id]
    assert index.embedding_id("possibility:same-scene") is None
    assert index.embedding_count() == before_count - 1


def test_unlicensed_reference_assets_cannot_enter_the_publishable_index() -> None:
    with pytest.raises(ValidationError, match="must be redistributable"):
        _card(
            "possibility:unlicensed-frame",
            source_id="source:private-frame",
            concept="A private film frame",
            scene_terms=["lake"],
            emotion_terms=["quiet"],
            routes=list(RetrievalRoute),
            template_family="family:private",
            provenance=_provenance(
                "source:private-frame",
                rights="project-only",
                redistributable=False,
            ),
            reference_asset_uris=["private://frame"],
        )

    non_distributable_text = _card(
        "possibility:private-text",
        source_id="source:private-text",
        concept="Private notes",
        scene_terms=["lake"],
        emotion_terms=["quiet"],
        routes=list(RetrievalRoute),
        template_family="family:private",
        provenance=_provenance(
            "source:private-text",
            rights="project-only",
            redistributable=False,
        ),
    )
    with pytest.raises(ValueError, match="redistributable"):
        CreativeKnowledgeIndex("publishable:v1").publish_possibility(
            non_distributable_text
        )


def test_diversity_selection_prefers_an_independent_source_and_template() -> None:
    index = CreativeKnowledgeIndex("possibilities:diversity-v1")
    index.publish_possibility(
        _card(
            "possibility:similar-a",
            source_id="source:same",
            concept="Quiet still lake reflection",
            scene_terms=["winter lake", "reflection"],
            emotion_terms=["quiet stillness"],
            routes=[RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION],
            template_family="family:same",
        )
    )
    index.publish_possibility(
        _card(
            "possibility:similar-b",
            source_id="source:same",
            concept="Quiet still lake reflection with a restrained shore",
            scene_terms=["winter lake", "reflection"],
            emotion_terms=["quiet stillness"],
            routes=[RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION],
            template_family="family:same",
        )
    )
    index.publish_possibility(
        _card(
            "possibility:diverse",
            source_id="source:independent",
            concept="Watchful exposure across a mirrored horizon",
            scene_terms=["lake horizon", "mirror"],
            emotion_terms=["watchful", "exposed stillness"],
            routes=[RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION],
            template_family="family:independent",
        )
    )

    result = retrieve_creative_possibilities(
        thesis=_thesis(),
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=index,
        filters=_filters(),
        relevance_threshold=0.15,
        maximum_per_route=2,
    )
    first_route = next(
        item
        for item in result.audit.route_audits
        if item.brief_id == "brief:faithful"
        and item.route == RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION
    )

    assert "possibility:diverse" in first_route.selected_card_ids
    assert len(
        set(first_route.selected_card_ids)
        & {"possibility:similar-a", "possibility:similar-b"}
    ) == 1


def test_retrieval_flags_template_convergence_across_closed_book_directions() -> None:
    index = CreativeKnowledgeIndex("possibilities:convergence-v1")
    for index_value, route in enumerate(RetrievalRoute):
        index.publish_possibility(
            _card(
                f"possibility:template:{index_value}",
                source_id=f"source:template:{index_value}",
                concept=(
                    "Winter lake stillness, fixed preset, counterexample failure assumption"
                ),
                scene_terms=["winter lake", "reflection"],
                emotion_terms=["quiet stillness", "anticipation", "unsettled stillness"],
                routes=[route],
                template_family="family:single-template",
            )
        )

    result = retrieve_creative_possibilities(
        thesis=_thesis(),
        thesis_asset_id="asset:thesis",
        thesis_sha256=_sha("signed-thesis"),
        context=_context(),
        index=index,
        filters=_filters(),
        relevance_threshold=0.15,
        maximum_per_route=1,
    )

    assert result.audit.metrics.convergence_risk_rate == 1
    assert all(item.convergence_risk for item in result.bundle.expansions)
