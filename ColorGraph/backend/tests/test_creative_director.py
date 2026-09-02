from __future__ import annotations

import hashlib
import json

import pytest

from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    AllowedCreativeDeviation,
    ColorLanguageCue,
    ColorProperty,
    ContextBudget,
    ContrastCharacter,
    CreativeBrief,
    CreativeDirection,
    EvidenceKind,
    EvidenceReference,
    PaletteCharacter,
    ProjectContextPack,
    ProjectVisualThesis,
    ProtectedAttribute,
    SceneNarrativeRole,
    VisualHierarchyItem,
)
from colorgraph.agent.creative_director import (
    CREATIVE_DIRECTOR_VERSION,
    CreativeDirectorValidationError,
    DirectorViolationCode,
    audit_closed_book_thesis,
    build_closed_book_director_request,
    run_closed_book_director,
)
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    ProviderImage,
    RawProviderResponse,
    RuntimePolicy,
)


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _context(
    scene_summaries: dict[str, str] | None = None,
    *,
    include_measurements: bool = True,
    visual_kind: EvidenceKind = EvidenceKind.FRAME,
) -> ProjectContextPack:
    summaries = scene_summaries or {
        "scene:lake": "A still lake reflects an overcast sky and a dark shore."
    }
    evidence: list[EvidenceReference] = []
    shot_ids: list[str] = []
    for index, (scene_id, summary) in enumerate(summaries.items()):
        shot_id = f"shot:{index + 1:03d}"
        shot_ids.append(shot_id)
        visual_id = f"visual:{index + 1:03d}"
        content = f"{scene_id}:visual".encode()
        evidence.append(
            EvidenceReference(
                evidence_id=visual_id,
                kind=visual_kind,
                digest=_sha(content),
                summary=summary,
                frame_index=index * 24 if visual_kind == EvidenceKind.FRAME else None,
                scene_id=scene_id,
                shot_id=shot_id,
            )
        )
        if include_measurements:
            evidence.append(
                EvidenceReference(
                    evidence_id=f"measurement:{index + 1:03d}",
                    kind=EvidenceKind.MEASUREMENT,
                    digest=_sha(f"{scene_id}:measurement"),
                    summary="Highlights retain detail and the source palette is restrained.",
                    scene_id=scene_id,
                    shot_id=shot_id,
                )
            )
    return ProjectContextPack(
        technical_baseline_asset_id="technical-baseline:test",
        technical_baseline_sha256=_sha("technical-baseline"),
        graph_digest=_sha("graph"),
        evidence_bundle_schema_version="colorgraph.agent-evidence-bundle/v1",
        evidence_bundle_digest=_sha("evidence-bundle"),
        allowed_scene_ids=list(summaries),
        allowed_shot_ids=shot_ids,
        evidence=evidence,
        budget=ContextBudget(
            maximum_images=16,
            maximum_image_edge=1_024,
            maximum_audio_seconds=30,
            maximum_tokens=16_000,
            maximum_context_bytes=16_000_000,
        ),
        omitted_evidence_ids=[],
    )


def _scene_evidence_ids(
    context: ProjectContextPack,
    scene_id: str,
) -> tuple[str, str]:
    scene_evidence = [item for item in context.evidence if item.scene_id == scene_id]
    visual = next(
        item.evidence_id
        for item in scene_evidence
        if item.kind in {EvidenceKind.FRAME, EvidenceKind.CONTACT_SHEET}
    )
    counter = next(
        (
            item.evidence_id
            for item in scene_evidence
            if item.kind == EvidenceKind.MEASUREMENT
        ),
        visual,
    )
    return visual, counter


def _brief(
    *,
    scene_id: str,
    direction: CreativeDirection,
    evidence_for: str,
    evidence_against: str,
    sufficient: bool = True,
) -> CreativeBrief:
    structured_intent = {
        CreativeDirection.FAITHFUL: (
            "source-relationship",
            "color_separation",
            ColorProperty.COLOR_SEPARATION,
            AdjustmentDirection.PRESERVE,
            "observational restraint",
            1,
        ),
        CreativeDirection.AMPLIFIED: (
            "primary-hierarchy",
            "contrast",
            ColorProperty.CONTRAST,
            AdjustmentDirection.INCREASE,
            "controlled emphasis",
            1,
        ),
        CreativeDirection.COUNTERPOINT: (
            "negative-space",
            "saturation",
            ColorProperty.SATURATION,
            AdjustmentDirection.DECREASE,
            "quiet tension",
            1,
        ),
    }[direction]
    (
        hierarchy_target,
        color_target,
        property_name,
        adjustment,
        emotion,
        priority,
    ) = structured_intent
    return CreativeBrief(
        brief_id=f"brief:{scene_id}:{direction.value}",
        scene_id=scene_id,
        direction=direction,
        interpretation=(
            f"{direction.value} reading of the observed spatial and tonal relationships."
        ),
        evidence_for=[evidence_for],
        evidence_against=[evidence_against],
        emotional_target=emotion,
        visual_hierarchy=[
            VisualHierarchyItem(
                target=hierarchy_target,
                priority=priority,
                rationale="The cited visual evidence identifies this as the primary anchor.",
                evidence_ids=[evidence_for],
            )
        ],
        possible_color_language=[
            ColorLanguageCue(
                target=color_target,
                property=property_name,
                direction=adjustment,
                minimum_strength=0,
                maximum_strength=0.4,
                rationale="Keep the proposal bounded by observed source relationships.",
            )
        ],
        cliche_risks=["Avoid a generic landscape treatment or scene-label shortcut."],
        confidence=0.74 if sufficient else 0.4,
        uncertainties=[] if sufficient else ["unknown; needs_user_intent"],
        failure_conditions=["The cited visual anchor stops reading as the intended focus."],
    )


def _thesis(context: ProjectContextPack) -> ProjectVisualThesis:
    briefs: list[CreativeBrief] = []
    roles: list[SceneNarrativeRole] = []
    deviations: list[AllowedCreativeDeviation] = []
    sufficient_by_scene: dict[str, bool] = {}
    for scene_id in context.allowed_scene_ids:
        visual_id, counter_id = _scene_evidence_ids(context, scene_id)
        scene_items = [item for item in context.evidence if item.scene_id == scene_id]
        sufficient = len(scene_items) >= 2
        sufficient_by_scene[scene_id] = sufficient
        briefs.extend(
            _brief(
                scene_id=scene_id,
                direction=direction,
                evidence_for=visual_id,
                evidence_against=counter_id,
                sufficient=sufficient,
            )
            for direction in CreativeDirection
        )
        shot_ids = sorted(
            {
                item.shot_id
                for item in scene_items
                if item.shot_id is not None
            }
        )
        roles.append(
            SceneNarrativeRole(
                scene_id=scene_id,
                shot_ids=shot_ids,
                narrative_role="A distinct movement in the project's visual argument.",
                relationship_to_project_thesis=(
                    "Develops the shared restraint through this scene's observed hierarchy."
                ),
                evidence_ids=[visual_id, counter_id],
            )
        )
        deviations.append(
            AllowedCreativeDeviation(
                scene_id=scene_id,
                property=ColorProperty.SATURATION,
                maximum_normalized_strength=0.35,
                rationale="A bounded departure is allowed only when the cited anchor survives.",
                evidence_ids=[visual_id],
            )
        )
    first_visual, first_counter = _scene_evidence_ids(
        context,
        context.allowed_scene_ids[0],
    )
    sufficient = all(sufficient_by_scene.values())
    return ProjectVisualThesis(
        thesis_id="thesis:closed-book",
        project_interpretation=(
            "A restrained study of changing spatial attention across the supplied scenes."
        ),
        palette_character=PaletteCharacter.SOURCE_FAITHFUL,
        contrast_character=ContrastCharacter.NATURAL,
        shared_protections=[
            ProtectedAttribute.COLOR_PIPELINE,
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.PROJECT_CONTINUITY,
        ],
        evidence_for=[first_visual],
        evidence_against=[first_counter],
        confidence=0.72 if sufficient else 0.4,
        uncertainties=[] if sufficient else ["Some scene readings remain unknown."],
        briefs=briefs,
        scene_roles=roles,
        allowed_deviations=deviations,
    )


def _violation_codes(thesis: ProjectVisualThesis, context: ProjectContextPack) -> set[str]:
    return {
        item.code
        for item in audit_closed_book_thesis(thesis, context=context).violations
    }


def test_valid_closed_book_thesis_is_grounded_and_structurally_distinct() -> None:
    context = _context()
    report = audit_closed_book_thesis(_thesis(context), context=context)

    assert report.valid is True
    assert report.director_version == CREATIVE_DIRECTOR_VERSION
    assert report.closed_book_inputs == ["project_context_pack"]
    assert report.direction_distinctness[0].structurally_distinct_pairs == 3


def test_request_contains_only_closed_book_inputs_and_signed_context_images() -> None:
    context = _context(visual_kind=EvidenceKind.CONTACT_SHEET)
    visual = next(item for item in context.evidence if item.kind == EvidenceKind.CONTACT_SHEET)
    content = b"scene:lake:visual"
    image = ProviderImage(
        asset_id=visual.evidence_id,
        sha256=_sha(content),
        media_type="image/jpeg",
        content=content,
    )

    request = build_closed_book_director_request(
        context=context,
        context_asset_digest=_sha("signed-context"),
        images=(image,),
        user_intent="Preserve ambiguity and avoid spectacle.",
        user_intent_digest=_sha("user-intent"),
    )
    payload = json.loads(request.prompt)

    assert set(payload) == {
        "hard_contract",
        "protocol",
        "instructions",
        "project_context_pack",
        "user_intent",
    }
    assert request.role == CreativeRole.DIRECTOR
    assert request.prompt_version == "closed-book-director/v3"
    assert request.input_asset_digests == (
        _sha("signed-context"),
        _sha("user-intent"),
    )
    assert "retrieval_bundle" not in request.prompt.casefold()
    assert image.asset_id in request.prompt
    assert "never place sentinels" in request.prompt.casefold()
    expected_structured_intents = {
        CreativeDirection.FAITHFUL: {
            "emotional_target": "observational restraint",
            "visual_hierarchy": {
                "target": "source-relationship",
                "priority": 1,
            },
            "color_language": {
                "target": "color_separation",
                "property": "color_separation",
                "direction": "preserve",
            },
        },
        CreativeDirection.AMPLIFIED: {
            "emotional_target": "controlled emphasis",
            "visual_hierarchy": {
                "target": "primary-hierarchy",
                "priority": 1,
            },
            "color_language": {
                "target": "contrast",
                "property": "contrast",
                "direction": "increase",
            },
        },
        CreativeDirection.COUNTERPOINT: {
            "emotional_target": "quiet tension",
            "visual_hierarchy": {
                "target": "negative-space",
                "priority": 1,
            },
            "color_language": {
                "target": "saturation",
                "property": "saturation",
                "direction": "decrease",
            },
        },
    }
    assert payload["hard_contract"]["brief_bindings"] == [
        {
            "brief_id": f"brief:scene:lake:{direction.value}",
            "scene_id": "scene:lake",
            "direction": direction.value,
            "required_structured_intent": expected_structured_intents[direction],
        }
        for direction in CreativeDirection
    ]
    assert payload["hard_contract"]["scenes"] == [
        {
            "scene_id": "scene:lake",
            "shot_ids": ["shot:001"],
            "evidence_ids": ["measurement:001", "visual:001"],
        }
    ]
    assert request.max_output_tokens == 4_096

    mismatched_content = b"different-image"
    mismatched = ProviderImage(
        asset_id=visual.evidence_id,
        sha256=_sha(mismatched_content),
        media_type="image/jpeg",
        content=mismatched_content,
    )
    with pytest.raises(ValueError, match="digest differs"):
        build_closed_book_director_request(
            context=context,
            context_asset_digest=_sha("signed-context"),
            images=(mismatched,),
        )


def test_unknown_and_cross_scene_evidence_are_rejected() -> None:
    context = _context(
        {
            "scene:one": "A pale waterfall crosses a dark rock face.",
            "scene:two": "Clouds flatten the horizon above a winter lake.",
        }
    )
    thesis = _thesis(context)
    first = thesis.briefs[0].model_copy(
        update={
            "evidence_for": ["evidence:not-in-context"],
            "evidence_against": ["visual:002"],
        }
    )
    changed = thesis.model_copy(update={"briefs": [first, *thesis.briefs[1:]]})

    codes = _violation_codes(changed, context)

    assert DirectorViolationCode.UNKNOWN_EVIDENCE in codes
    assert DirectorViolationCode.CROSS_SCENE_EVIDENCE in codes


def test_prose_only_variants_parameters_and_scene_cliches_are_rejected() -> None:
    context = _context()
    thesis = _thesis(context)
    faithful = thesis.briefs[0]
    prose_only = [
        faithful.model_copy(
            update={
                "brief_id": brief.brief_id,
                "direction": brief.direction,
                "emotional_target": brief.emotional_target,
                "interpretation": (
                    "Snow always means blue with 2 EV added through a LUT recipe."
                    if index == 1
                    else brief.interpretation
                ),
            }
        )
        for index, brief in enumerate(thesis.briefs)
    ]
    changed = thesis.model_copy(update={"briefs": prose_only})

    codes = _violation_codes(changed, context)

    assert DirectorViolationCode.DIRECTION_STRUCTURE in codes
    assert DirectorViolationCode.FORBIDDEN_IMPLEMENTATION in codes
    assert DirectorViolationCode.NUMERIC_RENDER_PARAMETER in codes
    assert DirectorViolationCode.CLICHE_SHORTCUT in codes


def test_insufficient_evidence_requires_explicit_uncertainty_and_low_confidence() -> None:
    context = _context(include_measurements=False)
    valid = _thesis(context)
    assert audit_closed_book_thesis(valid, context=context).valid is True

    overclaim = valid.briefs[0].model_copy(
        update={"confidence": 0.9, "uncertainties": []}
    )
    changed = valid.model_copy(update={"briefs": [overclaim, *valid.briefs[1:]]})

    assert (
        DirectorViolationCode.INSUFFICIENT_EVIDENCE_OVERCLAIM
        in _violation_codes(changed, context)
    )


def test_scene_role_shot_scope_evidence_scope_and_deviation_coverage_are_enforced() -> None:
    context = _context(
        {
            "scene:one": "A pale waterfall crosses a dark rock face.",
            "scene:two": "Clouds flatten the horizon above a winter lake.",
        }
    )
    thesis = _thesis(context)
    changed_role = thesis.scene_roles[0].model_copy(
        update={"shot_ids": ["shot:002"], "evidence_ids": ["visual:002"]}
    )
    changed = thesis.model_copy(
        update={
            "scene_roles": [changed_role, thesis.scene_roles[1]],
            "allowed_deviations": [thesis.allowed_deviations[0]],
        }
    )

    codes = _violation_codes(changed, context)

    assert DirectorViolationCode.SHOT_SCOPE in codes
    assert DirectorViolationCode.CROSS_SCENE_EVIDENCE in codes
    assert DirectorViolationCode.DEVIATION_COVERAGE in codes


@pytest.mark.parametrize(
    "summary",
    [
        "Snow and falling water share a bright field against textured rock.",
        "A cloudy winter lake holds a low-contrast horizon and sparse reeds.",
        "A sunny lake mirrors the sky while a dark shoreline anchors the frame.",
        "Warm foliage crosses cool water without either color family dominating.",
    ],
)
def test_frozen_scene_cases_each_produce_three_grounded_directions(summary: str) -> None:
    context = _context({"scene:frozen": summary})
    thesis = _thesis(context)

    report = audit_closed_book_thesis(thesis, context=context)

    assert report.valid is True
    assert len(thesis.briefs) == 3
    assert {brief.direction for brief in thesis.briefs} == set(CreativeDirection)
    assert all(brief.evidence_for and brief.evidence_against for brief in thesis.briefs)


async def test_runtime_accepts_valid_output_repairs_once_and_rejects_invalid_repair(
) -> None:
    context = _context()
    thesis = _thesis(context)
    request = build_closed_book_director_request(
        context=context,
        context_asset_digest=_sha("signed-context"),
    )
    provider = FakeCreativeModelProvider(
        responses=[RawProviderResponse(text=thesis.model_dump_json())]
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )

    result = await run_closed_book_director(
        runtime,
        request=request,
        context=context,
    )

    assert result.director_audit.valid is True
    assert result.thesis == thesis

    invalid_brief = thesis.briefs[0].model_copy(
        update={
            "evidence_for": ["evidence:invented"],
            "emotional_target": "unbound provider invention",
        }
    )
    invalid = thesis.model_copy(
        update={"briefs": [invalid_brief, *thesis.briefs[1:]]}
    )
    invalid_provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(text=invalid.model_dump_json()),
            RawProviderResponse(text=thesis.model_dump_json()),
        ]
    )
    invalid_runtime = CreativeProviderRuntime(
        {role: invalid_provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )

    repaired = await run_closed_book_director(
        invalid_runtime,
        request=request,
        context=context,
    )
    assert repaired.thesis == thesis
    assert repaired.director_audit.valid
    assert repaired.provider_audit.prompt_version == "closed-book-director/v3-repair1"
    assert invalid_provider.calls == 2

    persistently_invalid_provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(text=invalid.model_dump_json()),
            RawProviderResponse(text=invalid.model_dump_json()),
        ]
    )
    persistently_invalid_runtime = CreativeProviderRuntime(
        {role: persistently_invalid_provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )
    with pytest.raises(CreativeDirectorValidationError) as error:
        await run_closed_book_director(
            persistently_invalid_runtime,
            request=request,
            context=context,
        )
    assert DirectorViolationCode.UNKNOWN_EVIDENCE in {
        item.code for item in error.value.audit.violations
    }
    assert DirectorViolationCode.DIRECTION_STRUCTURE in {
        item.code for item in error.value.audit.violations
    }
