from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drama.flux2_reference.freezer import (
    GeneratedReferenceView,
    freeze_character_reference_set,
)
from drama.flux2_reference.model_registry import (
    Flux2CapabilityUnavailable,
    load_flux2_dev_capability,
)
from drama.flux2_reference.prompt_renderer import (
    CharacterReferencePromptInput,
    render_character_reference_prompt,
)
from drama.flux2_reference.qc import (
    CrossViewQCResult,
    ReferenceManufacturingError,
    ReferenceViewQCResult,
    next_reference_attempt,
)
from drama.flux2_reference.workflows import (
    compile_flux2_workflow,
    load_flux2_workflow_templates,
)
from shared_contracts import CharacterReferenceSourceAssetV1


A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
VIEWS = ("front", "three_quarter_left", "profile_left")
CAPABILITY = Path(__file__).parents[1] / "config" / "flux2_dev_fp8mixed_amd_capability.json"
WORKFLOWS = Path(__file__).parents[1] / "workflows"


def _now() -> datetime:
    return datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _prompt_input(view: str = "front", attempt: int = 0) -> CharacterReferencePromptInput:
    return CharacterReferencePromptInput(
        character_id="character.protagonist",
        age_stage="adult",
        identity_lock="稳定骨相、五官比例、黑色短发",
        attire_lock="黑色高领上衣，无配饰",
        source_asset_digests=(A,),
        view=view,
        attempt=attempt,
        capability_digest=load_flux2_dev_capability(CAPABILITY).capability.digest,
    )


def _source() -> CharacterReferenceSourceAssetV1:
    return CharacterReferenceSourceAssetV1(
        asset_id=UUID("11111111-1111-4111-8111-111111111111"),
        content_digest=A,
        verified=True,
        historical=True,
        ai_derived=False,
        uploaded_by="operator.seed",
        uploaded_at=_now(),
    )


def _generated_views() -> tuple[GeneratedReferenceView, ...]:
    digests = (B, C, D)
    template_sha256 = load_flux2_dev_capability(CAPABILITY).capability.workflow(
        "single_reference_edit"
    ).sha256
    return tuple(
        GeneratedReferenceView(
            asset_id=UUID(f"22222222-2222-4222-8222-22222222222{index}"),
            rendered_prompt=render_character_reference_prompt(_prompt_input(view)),
            image_digest=digest,
            workflow_role="single_reference_edit",
            workflow_template_sha256=template_sha256,
            workflow_digest=f"{index}" * 64,
            generated_at=_now(),
        )
        for index, (view, digest) in enumerate(zip(VIEWS, digests, strict=True), 1)
    )


def _view_qc() -> tuple[ReferenceViewQCResult, ...]:
    return tuple(
        ReferenceViewQCResult(
            view=item.rendered_prompt.view,
            image_digest=item.image_digest,
            prompt_digest=item.rendered_prompt.prompt_digest,
            workflow_digest=item.workflow_digest,
            attempt=item.rendered_prompt.attempt,
            evaluator_provider="zhipu",
            evaluator_model_id="glm-4.6v",
            evaluator_response_digest=A,
            angle_match=True,
            single_subject=True,
            artifact_free=True,
            source_fidelity=True,
            policy_snapshot_digest=B,
            evaluated_at=_now(),
        )
        for item in _generated_views()
    )


def _cross_qc(**overrides: object) -> CrossViewQCResult:
    fields: dict[str, object] = {
        "view_image_digests": tuple(item.image_digest for item in _generated_views()),
        "evaluator_provider": "zhipu",
        "evaluator_model_id": "glm-4.6v",
        "evaluator_response_digest": A,
        "identity_consistent": True,
        "age_consistent": True,
        "attire_consistent": True,
        "angle_correct": True,
        "artifact_free": True,
        "policy_snapshot_digest": B,
        "evaluated_at": _now(),
    }
    fields.update(overrides)
    return CrossViewQCResult(**fields)


def test_capability_pins_exact_flux2_dev_files_and_pvc_truth() -> None:
    loaded = load_flux2_dev_capability(CAPABILITY)
    capability = loaded.capability
    assert capability.family == "flux2-dev"
    assert capability.model_id == "flux2-dev-fp8mixed.v1"
    assert capability.revision == "flux2-dev-fp8mixed.v1"
    assert capability.diffusion_model.sha256 == "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486"
    assert capability.text_encoder.sha256 == "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e"
    assert capability.vae.sha256 == "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5"
    assert str(loaded.model_root).replace("\\", "/").startswith("/persistent/douyin-amd/models/")
    assert capability.execution.width == 512
    assert capability.execution.height == 768
    assert capability.license_snapshot == "FLUX Non-Commercial License"

    payload = CAPABILITY.read_text(encoding="utf-8").replace('"flux2-dev"', '"flux2-klein-4b"', 1)
    with pytest.raises((Flux2CapabilityUnavailable, ValidationError), match="flux2-dev"):
        load_flux2_dev_capability(payload)


def test_three_prompts_are_independent_deterministic_single_view_requests() -> None:
    prompts = [render_character_reference_prompt(_prompt_input(view)) for view in VIEWS]
    assert prompts == [render_character_reference_prompt(_prompt_input(view)) for view in VIEWS]
    assert len({item.seed for item in prompts}) == 3
    assert len({item.prompt_digest for item in prompts}) == 3
    assert tuple(item.view for item in prompts) == VIEWS
    for item in prompts:
        assert "稳定骨相" in item.prompt
        assert item.view_instruction in item.prompt
        for forbidden in ("collage", "label", "watermark", "logo", "text", "subtitle"):
            assert forbidden in item.negative_prompt


def test_reference_retry_is_limited_to_one_and_freeze_requires_all_glm_qc() -> None:
    failed = _view_qc()[0].model_copy(update={"angle_match": False})
    assert next_reference_attempt(0, failed) == 1
    with pytest.raises(ReferenceManufacturingError):
        next_reference_attempt(1, failed)

    capability = load_flux2_dev_capability(CAPABILITY).capability
    frozen = freeze_character_reference_set(
        reference_set_id=UUID("33333333-3333-4333-8333-333333333333"),
        reference_set_revision_id=UUID("44444444-4444-4444-8444-444444444444"),
        character_id="character.protagonist",
        age_stage="adult",
        source_asset=_source(),
        capability=capability,
        generated_views=_generated_views(),
        view_qc=_view_qc(),
        cross_view_qc=_cross_qc(),
    )
    assert frozen.state == "frozen"
    assert tuple(view.view_name for view in frozen.views) == VIEWS
    assert frozen.model_revision.diffusion_model_sha256 == capability.diffusion_model.sha256
    assert frozen.model_revision.text_encoder_sha256 == capability.text_encoder.sha256
    assert frozen.model_revision.vae_sha256 == capability.vae.sha256
    assert (
        frozen.model_revision.workflow_sha256
        == capability.workflow("single_reference_edit").sha256
    )

    with pytest.raises(ReferenceManufacturingError, match="QC"):
        freeze_character_reference_set(
            reference_set_id=UUID("33333333-3333-4333-8333-333333333333"),
            reference_set_revision_id=UUID("44444444-4444-4444-8444-444444444444"),
            character_id="character.protagonist",
            age_stage="adult",
            source_asset=_source(),
            capability=capability,
            generated_views=_generated_views(),
            view_qc=_view_qc(),
            cross_view_qc=_cross_qc(identity_consistent=False),
        )


@pytest.mark.parametrize(
    ("role", "references"),
    [("text_to_image", ()), ("single_reference_edit", ("source/front.png",)), ("dual_reference_edit", ("source/front.png", "source/profile.png"))],
)
def test_three_core_workflows_are_digest_bound_and_compile_without_placeholders(
    role: str,
    references: tuple[str, ...],
) -> None:
    capability = load_flux2_dev_capability(CAPABILITY).capability
    templates = load_flux2_workflow_templates(WORKFLOWS, capability)
    compiled = compile_flux2_workflow(
        role=role,
        templates=templates,
        capability=capability,
        prompt="single historical character portrait",
        width=512,
        height=768,
        seed=7,
        reference_images=references,
        filename_prefix=f"flux2/{role}",
    )
    assert compiled == compile_flux2_workflow(
        role=role,
        templates=templates,
        capability=capability,
        prompt="single historical character portrait",
        width=512,
        height=768,
        seed=7,
        reference_images=references,
        filename_prefix=f"flux2/{role}",
    )
    assert "{{" not in repr(compiled.workflow)
    assert capability.diffusion_model.filename in repr(compiled.workflow)
    assert capability.text_encoder.filename in repr(compiled.workflow)
    assert capability.vae.filename in repr(compiled.workflow)
    assert len(compiled.workflow_digest) == 64


def test_compiled_workflow_cannot_be_mutated_after_digest_verification() -> None:
    capability = load_flux2_dev_capability(CAPABILITY).capability
    templates = load_flux2_workflow_templates(WORKFLOWS, capability)
    compiled = compile_flux2_workflow(
        role="single_reference_edit",
        templates=templates,
        capability=capability,
        prompt="single historical character portrait",
        width=512,
        height=768,
        seed=7,
        reference_images=("source/front.png",),
        filename_prefix="flux2/front",
    )
    original_digest = compiled.workflow_digest
    exposed = compiled.workflow
    exposed["1"]["inputs"]["unet_name"] = "flux2-klein-latest*.safetensors"
    exposed["20"]["inputs"]["image"] = "../escape.png"

    assert compiled.workflow_digest == original_digest
    assert compiled.workflow["1"]["inputs"]["unet_name"] == capability.diffusion_model.filename
    assert compiled.workflow["20"]["inputs"]["image"] == "source/front.png"


def test_freeze_rejects_unknown_workflow_revision_and_undeclared_second_source() -> None:
    capability = load_flux2_dev_capability(CAPABILITY).capability
    generated = _generated_views()
    unknown_revision = tuple(
        item if index else GeneratedReferenceView(
            asset_id=item.asset_id,
            rendered_prompt=item.rendered_prompt,
            image_digest=item.image_digest,
            workflow_role=item.workflow_role,
            workflow_template_sha256=A,
            workflow_digest=item.workflow_digest,
            generated_at=item.generated_at,
        )
        for index, item in enumerate(generated)
    )
    with pytest.raises(ReferenceManufacturingError, match="workflow"):
        freeze_character_reference_set(
            reference_set_id=UUID("33333333-3333-4333-8333-333333333333"),
            reference_set_revision_id=UUID("44444444-4444-4444-8444-444444444444"),
            character_id="character.protagonist",
            age_stage="adult",
            source_asset=_source(),
            capability=capability,
            generated_views=unknown_revision,
            view_qc=_view_qc(),
            cross_view_qc=_cross_qc(),
        )

    undeclared = tuple(
        GeneratedReferenceView(
            asset_id=item.asset_id,
            rendered_prompt=render_character_reference_prompt(
                _prompt_input(item.rendered_prompt.view).model_copy(
                    update={"source_asset_digests": (A, B)}
                )
            ),
            image_digest=item.image_digest,
            workflow_role=item.workflow_role,
            workflow_template_sha256=item.workflow_template_sha256,
            workflow_digest=item.workflow_digest,
            generated_at=item.generated_at,
        )
        for item in generated
    )
    with pytest.raises(ReferenceManufacturingError, match="source"):
        freeze_character_reference_set(
            reference_set_id=UUID("33333333-3333-4333-8333-333333333333"),
            reference_set_revision_id=UUID("44444444-4444-4444-8444-444444444444"),
            character_id="character.protagonist",
            age_stage="adult",
            source_asset=_source(),
            capability=capability,
            generated_views=undeclared,
            view_qc=_view_qc(),
            cross_view_qc=_cross_qc(),
        )


def test_character_prompt_submits_all_no_layout_constraints_to_flux_graph() -> None:
    capability = load_flux2_dev_capability(CAPABILITY).capability
    rendered = render_character_reference_prompt(_prompt_input())
    submitted = compile_flux2_workflow(
        role="single_reference_edit",
        templates=load_flux2_workflow_templates(WORKFLOWS, capability),
        capability=capability,
        prompt=rendered.prompt,
        width=512,
        height=768,
        seed=rendered.seed,
        reference_images=("source/front.png",),
        filename_prefix="flux2/front",
    ).workflow["3"]["inputs"]["text"]
    for constraint in ("no collage", "no text", "no label", "no watermark", "no border"):
        assert constraint in submitted.casefold()


def test_production_file_verification_cannot_override_the_pvc_truth() -> None:
    assert "model_root_override" not in signature(
        load_flux2_dev_capability
    ).parameters
