from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from shared_contracts import (
    CharacterReferenceCrossViewQCV1,
    CharacterReferenceModelRevisionV1,
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    CharacterReferenceViewV1,
    character_reference_set_digest,
)

from .model_registry import Flux2DevCapability, Flux2WorkflowRole
from .prompt_renderer import RenderedCharacterReferencePrompt
from .qc import CrossViewQCResult, ReferenceManufacturingError, ReferenceViewQCResult


_REFERENCE_VIEWS = ("front", "three_quarter_left", "profile_left")


@dataclass(frozen=True, slots=True)
class GeneratedReferenceView:
    asset_id: UUID
    rendered_prompt: RenderedCharacterReferencePrompt
    image_digest: str
    workflow_role: Flux2WorkflowRole
    workflow_template_sha256: str
    workflow_digest: str
    generated_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("image_digest", self.image_digest),
            ("workflow_template_sha256", self.workflow_template_sha256),
            ("workflow_digest", self.workflow_digest),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")


def _fail(message: str) -> None:
    raise ReferenceManufacturingError(message)


def freeze_character_reference_set(
    *,
    reference_set_id: UUID,
    reference_set_revision_id: UUID,
    character_id: str,
    age_stage: str,
    source_asset: CharacterReferenceSourceAssetV1,
    capability: Flux2DevCapability,
    generated_views: tuple[GeneratedReferenceView, ...],
    view_qc: tuple[ReferenceViewQCResult, ...],
    cross_view_qc: CrossViewQCResult,
) -> CharacterReferenceSetV1:
    """Validate complete GLM lineage and construct the immutable frozen contract."""

    if not source_asset.verified or not source_asset.historical or source_asset.ai_derived:
        _fail("character reference source must be verified historical non-AI evidence")
    if not capability.available:
        _fail("FLUX.2-dev capability is unavailable")
    if tuple(item.rendered_prompt.view for item in generated_views) != _REFERENCE_VIEWS:
        _fail("generated views are not the three required independent views")
    if tuple(item.view for item in view_qc) != _REFERENCE_VIEWS:
        _fail("view QC is not in the three required view order")
    if len(generated_views) != 3 or len(view_qc) != 3:
        _fail("reference freezing requires exactly three generated views and QC results")
    if len({item.asset_id for item in generated_views}) != 3:
        _fail("generated reference asset ids must be distinct")
    if len({item.image_digest for item in generated_views}) != 3:
        _fail("generated reference image digests must be distinct")
    if len({item.rendered_prompt.prompt_digest for item in generated_views}) != 3:
        _fail("generated reference prompts must be independent")
    if len({item.rendered_prompt.seed for item in generated_views}) != 3:
        _fail("generated reference seeds must be independent")

    capability_digest = capability.digest
    reference_workflow = capability.workflow("single_reference_edit")
    for generated, qc in zip(generated_views, view_qc, strict=True):
        rendered = generated.rendered_prompt
        if (
            rendered.character_id != character_id
            or rendered.age_stage != age_stage
            or rendered.capability_digest != capability_digest
        ):
            _fail("generated prompt lineage does not match the frozen reference set")
        if rendered.source_asset_digests != (source_asset.content_digest,):
            _fail("generated prompt source does not match the declared source asset")
        if (
            generated.workflow_role != "single_reference_edit"
            or generated.workflow_template_sha256 != reference_workflow.sha256
        ):
            _fail("generated workflow revision does not match the FLUX.2 capability")
        if not qc.passed:
            _fail("character reference view QC failed")
        if (
            qc.evaluator_provider != "zhipu"
            or qc.evaluator_model_id != "glm-4.6v"
            or qc.view != rendered.view
            or qc.image_digest != generated.image_digest
            or qc.prompt_digest != rendered.prompt_digest
            or qc.workflow_digest != generated.workflow_digest
            or qc.attempt != rendered.attempt
        ):
            _fail("view QC lineage does not match the generated artifact")

    image_digests = tuple(item.image_digest for item in generated_views)
    if not cross_view_qc.passed:
        _fail("character reference cross-view QC failed")
    if (
        cross_view_qc.evaluator_provider != "zhipu"
        or cross_view_qc.evaluator_model_id != "glm-4.6v"
        or cross_view_qc.view_image_digests != image_digests
        or any(
            item.policy_snapshot_digest != cross_view_qc.policy_snapshot_digest
            for item in view_qc
        )
    ):
        _fail("cross-view QC lineage does not match the generated artifacts")

    model_revision = CharacterReferenceModelRevisionV1(
        model_family=capability.family,
        model_id=capability.model_id,
        diffusion_model_sha256=capability.diffusion_model.sha256,
        text_encoder_sha256=capability.text_encoder.sha256,
        vae_sha256=capability.vae.sha256,
        workflow_sha256=reference_workflow.sha256,
        revision=capability.revision,
    )
    views = tuple(
        CharacterReferenceViewV1(
            asset_id=generated.asset_id,
            view_name=generated.rendered_prompt.view,
            attempt_ordinal=generated.rendered_prompt.attempt,
            image_digest=generated.image_digest,
            ai_derived=True,
            historical=False,
            identity_control=True,
            model_revision=model_revision,
            single_view_qc_passed=True,
            generated_at=generated.generated_at,
        )
        for generated in generated_views
    )
    cross_contract = CharacterReferenceCrossViewQCV1(
        identity_consistent=cross_view_qc.identity_consistent,
        age_consistent=cross_view_qc.age_consistent,
        attire_consistent=cross_view_qc.attire_consistent,
        angle_correct=cross_view_qc.angle_correct,
        no_artifact=cross_view_qc.artifact_free,
        qc_run_at=cross_view_qc.evaluated_at,
    )
    fields = dict(
        reference_set_id=reference_set_id,
        reference_set_revision_id=reference_set_revision_id,
        character_id=character_id,
        age_stage=age_stage,
        source_asset=source_asset,
        model_revision=model_revision,
        views=views,
        cross_view_qc=cross_contract,
        state="frozen",
    )
    draft = CharacterReferenceSetV1.model_construct(
        **fields,
        reference_set_digest="0" * 64,
    )
    identity = draft.model_dump(mode="json", exclude={"reference_set_digest"})
    return CharacterReferenceSetV1(
        **fields,
        reference_set_digest=character_reference_set_digest(identity),
    )


__all__ = ["GeneratedReferenceView", "freeze_character_reference_set"]
