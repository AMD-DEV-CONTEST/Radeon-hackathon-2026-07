from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from uuid import UUID

import pytest

from drama.h3 import model_registry
from drama.h3.model_registry import (
    H3ModelFileRevision,
    H3CapabilityUnavailable,
    load_h3_amd_capability,
)
from drama.h3.prompt_renderer import (
    H3PromptRenderer,
    H3PromptRenderError,
    H3RenderedPrompt,
    _rendered_prompt_digest,
)
from drama.h3.reference_binder import (
    ApprovedH3Asset,
    H3ReferenceBindingError,
    bind_h3_references,
)
from drama.h3.workflows import (
    H3CompiledWorkflow,
    H3ConcreteWorkflow,
    H3StagedReference,
    H3WorkflowBuildError,
    build_competition_single_reference_comfy_api_workflow,
    build_h3_comfy_api_workflow,
    build_h3_workflow,
    validate_h3_comfy_api_workflow,
)
from shared_contracts import (
    CharacterReferenceCrossViewQCV1,
    CharacterReferenceModelRevisionV1,
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    CharacterReferenceViewV1,
    H3AudioPlanV1,
    H3GenerationMode,
    H3SequencePlanV1,
    H3ShotV1,
    H3SpeechWindowV1,
    character_reference_set_digest,
)


A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
CONFIG = Path(__file__).parents[1] / "config" / "h3_ref2va_amd_capability.json"
WORKFLOW = Path(__file__).parents[1] / "workflows" / "h3_ref2va_amd_api.json"
LIVE_SCHEMA_FIXTURE = Path(__file__).parent / "fixtures" / "h3_live_object_info.json"
SEQ_ID = UUID("11111111-1111-4111-8111-111111111111")


def _now() -> datetime:
    return datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _reference_set(*, state: str = "frozen") -> CharacterReferenceSetV1:
    revision = CharacterReferenceModelRevisionV1(
        model_family="flux2-dev",
        model_id="flux2-dev-fp8mixed.v1",
        diffusion_model_sha256="863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486",
        text_encoder_sha256="e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e",
        vae_sha256="d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5",
        workflow_sha256=A,
        revision="flux2-dev-fp8mixed.v1",
    )
    source = CharacterReferenceSourceAssetV1(
        asset_id=UUID("22222222-2222-4222-8222-222222222222"),
        content_digest=A,
        verified=True,
        historical=True,
        ai_derived=False,
        uploaded_by="operator.seed",
        uploaded_at=_now(),
    )
    views = tuple(
        CharacterReferenceViewV1(
            asset_id=UUID(f"33333333-3333-4333-8333-33333333333{index}"),
            view_name=view,
            attempt_ordinal=0,
            image_digest=digest,
            ai_derived=True,
            historical=False,
            identity_control=True,
            model_revision=revision,
            single_view_qc_passed=True,
            generated_at=_now(),
        )
        for index, (view, digest) in enumerate(
            zip(("front", "three_quarter_left", "profile_left"), (B, C, D), strict=True),
            1,
        )
    )
    cross_qc = CharacterReferenceCrossViewQCV1(
        identity_consistent=True,
        age_consistent=True,
        attire_consistent=True,
        angle_correct=True,
        no_artifact=True,
        qc_run_at=_now(),
    )
    identity = {
        "reference_set_id": "44444444-4444-4444-8444-444444444444",
        "reference_set_revision_id": "55555555-5555-4555-8555-555555555555",
        "character_id": "character.protagonist",
        "age_stage": "adult",
        "source_asset": source.model_dump(mode="json"),
        "model_revision": revision.model_dump(mode="json"),
        "views": [view.model_dump(mode="json") for view in views],
        "cross_view_qc": cross_qc.model_dump(mode="json"),
        "state": state,
    }
    identity["reference_set_digest"] = character_reference_set_digest(identity)
    return CharacterReferenceSetV1.model_validate(identity)


def _plan() -> H3SequencePlanV1:
    duration = 209 / 24
    return H3SequencePlanV1(
        sequence_id=SEQ_ID,
        ordinal=1,
        mode=H3GenerationMode.REF2VA,
        frame_count=209,
        fps=24,
        duration_seconds=duration,
        requested_duration_seconds=8.7,
        reference_bindings=(
            {
                "subject_id": "subject.protagonist",
                "reference_set": _reference_set().model_dump(mode="json"),
            },
        ),
        shots=(
            H3ShotV1(
                shot_ordinal=1,
                start_seconds=0.0,
                end_seconds=duration,
                framing="medium",
                camera_move="slow_push_in",
                subject_ids=("subject.protagonist",),
                action="整理旧信件",
                expression="克制的警觉",
            ),
        ),
        audio_plan=H3AudioPlanV1(
            voice_source="h3_native",
            base_ambience="夜晚书房，远处轻微风声",
            tail_guard_seconds=1.2,
            narration=H3SpeechWindowV1(
                text="我把那些旧信件一封一封地摊开。",
                start_seconds=1.0,
                end_seconds=3.8,
            ),
            action_sounds=(
                {
                    "role": "overlay",
                    "label": "纸张摩擦",
                    "start_seconds": 1.4,
                    "end_seconds": 1.9,
                },
            ),
            internal_cut_times=(),
        ),
        evidence_ids=("E-001",),
    )


def _short_plan(*, frame_count: int = 73) -> H3SequencePlanV1:
    """Build the short-slice authority used by the AMD 3-second path.

    The isolated compiler worktree predates the shared-contract lower-bound
    change, so ``model_copy`` deliberately preserves the typed nested
    authorities while exercising the concrete runtime boundary directly.
    The integrated tree validates the same values through ``H3SequencePlanV1``.
    """

    base = _plan()
    duration = frame_count / 24
    audio = base.audio_plan.model_copy(
        update={
            "tail_guard_seconds": 0.5,
            "narration": H3SpeechWindowV1(
                text="我把旧信摊开。",
                start_seconds=0.5,
                end_seconds=min(2.5, duration - 0.6),
            ),
            "action_sounds": (),
        }
    )
    shot = base.shots[0].model_copy(update={"end_seconds": duration})
    return base.model_copy(
        update={
            "frame_count": frame_count,
            "duration_seconds": duration,
            "requested_duration_seconds": 3.0 if frame_count == 73 else 2.0,
            "shots": (shot,),
            "audio_plan": audio,
        }
    )


def _assets() -> dict[UUID, ApprovedH3Asset]:
    return {
        view.asset_id: ApprovedH3Asset(
            asset_id=view.asset_id,
            artifact_ref=f"artifact://reference/{view.view_name}",
            sha256=view.image_digest,
            media_type="image",
        )
        for view in _reference_set().views
    }


def _staged(binding) -> tuple[H3StagedReference, ...]:
    return tuple(
        H3StagedReference(
            asset_id=item.asset_id,
            sha256=item.sha256,
            remote_name=f"h3/reference/{item.view_name}.png",
        )
        for item in binding.items
    )


def test_h3_capability_pins_amd_ref2va_only_and_all_four_model_roles() -> None:
    loaded = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW)
    capability = loaded.capability
    assert capability.family == "minimax-h3"
    assert capability.revision == "h3-amd-local-v1"
    assert tuple(capability.model_files) == (
        "h3_ref2va_diffusion",
        "qwen3vl_text_encoder",
        "h3_video_vae",
        "h3_audio_vae",
    )
    assert capability.supported_modes == (H3GenerationMode.REF2VA,)
    assert capability.execution.width == 1344
    assert capability.execution.height == 768
    assert capability.execution.fps == 24
    assert str(loaded.model_root).replace("\\", "/").startswith("/persistent/douyin-amd/models/")
    assert capability.node_schema_sha256["MiniMaxH3ReferenceToVideo"] == "5fb5d6ad93a32fa0729d4f8bad8067ed12e06c0526fa9b5278fdf533be7281e4"
    assert capability.node_schema_sha256["MiniMaxH3SigmaShift"] == "c64f72f3d1a67d027e79433c7f5d5e20f2689ef29545bcbab6a230487c0ce6b6"

    with pytest.raises(H3CapabilityUnavailable):
        load_h3_amd_capability(CONFIG.read_text(encoding="utf-8").replace("ref2va", "t2va"), workflow_path=WORKFLOW)


def test_competition_single_reference_builds_one_real_73_frame_input() -> None:
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    prompt = "A calm historical scholar, front three-quarter portrait."
    reference = H3StagedReference(
        asset_id=UUID("66666666-6666-4666-8666-666666666666"),
        sha256=B,
        remote_name="h3/reference/front-three-quarter.png",
    )

    concrete = build_competition_single_reference_comfy_api_workflow(
        capability=capability,
        template_path=WORKFLOW,
        sequence_id=str(SEQ_ID),
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        staged_reference=reference,
        seed=1234,
    )

    graph = concrete.workflow
    assert graph["6"]["inputs"]["length"] == 73
    assert graph["14"]["inputs"]["fps"] == 24.0
    assert graph["16"]["inputs"]["image"] == reference.remote_name
    assert tuple(node for node in graph if node in {str(value) for value in range(16, 25)}) == (
        "16",
    )
    assert tuple(
        key
        for key in graph["6"]["inputs"]
        if key.startswith("ref_images.ref_image_")
    ) == ("ref_images.ref_image_0",)


def test_binder_assigns_three_contiguous_picture_tokens_from_frozen_asset_ids() -> None:
    plan = _plan()
    first = bind_h3_references(plan, _assets())
    second = bind_h3_references(plan, _assets())
    assert first == second
    assert tuple(item.token for item in first.items) == ("<Picture 1>", "<Picture 2>", "<Picture 3>")
    assert tuple(item.view_name for item in first.items) == (
        "front",
        "three_quarter_left",
        "profile_left",
    )
    assert first.reference_set_revision_ids == (
        UUID("55555555-5555-4555-8555-555555555555"),
    )

    missing = dict(_assets())
    missing.pop(next(iter(missing)))
    with pytest.raises(H3ReferenceBindingError, match="approved"):
        bind_h3_references(plan, missing)
    bad = dict(_assets())
    asset_id = next(iter(bad))
    bad[asset_id] = ApprovedH3Asset(
        asset_id=asset_id,
        artifact_ref="artifact://reference/tampered",
        sha256=A,
        media_type="image",
    )
    with pytest.raises(H3ReferenceBindingError, match="digest"):
        bind_h3_references(plan, bad)


def test_prompt_and_h3_workflow_are_deterministic_native_audio_ref2va() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    rendered = H3PromptRenderer().render(plan, binding, capability)
    assert rendered == H3PromptRenderer().render(plan, binding, capability)
    assert all(token in rendered.prompt for token in ("<Picture 1>", "<Picture 2>", "<Picture 3>"))
    assert "我把那些旧信件" in rendered.prompt
    assert "夜晚书房" in rendered.prompt
    assert "subtitle_track" not in rendered.prompt

    compiled = build_h3_workflow(plan, rendered, binding, capability)
    concrete = build_h3_comfy_api_workflow(
        compiled,
        plan=plan,
        rendered=rendered,
        binding=binding,
        capability=capability,
        template_path=WORKFLOW,
        staged_references=_staged(binding),
        seed=20260806,
    )
    repeated = build_h3_comfy_api_workflow(
        compiled,
        plan=plan,
        rendered=rendered,
        binding=binding,
        capability=capability,
        template_path=WORKFLOW,
        staged_references=_staged(binding),
        seed=20260806,
    )
    assert concrete == repeated
    graph = concrete.workflow
    assert "{{" not in repr(graph)
    assert "MiniMaxH3ReferenceToVideo" in repr(graph)
    assert "MiniMaxH3SigmaShift" in repr(graph)
    assert "VAEDecodeAudio" in repr(graph)
    assert "SaveVideo" in repr(graph)
    assert capability.model_files["h3_ref2va_diffusion"].filename in repr(graph)
    assert graph["6"]["inputs"]["width"] == 1344
    assert graph["6"]["inputs"]["height"] == 768
    assert graph["6"]["inputs"]["length"] == 209
    assert tuple(sorted(key for key in graph["6"]["inputs"] if key.startswith("ref_images."))) == (
        "ref_images.ref_image_0",
        "ref_images.ref_image_1",
        "ref_images.ref_image_2",
    )
    assert len(concrete.workflow_digest) == 64


def test_concrete_h3_workflow_accepts_73_frame_short_slice_and_rejects_less() -> None:
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability

    short = _short_plan()
    binding = bind_h3_references(short, _assets())
    rendered = H3PromptRenderer().render(short, binding, capability)
    compiled = build_h3_workflow(short, rendered, binding, capability)
    concrete = build_h3_comfy_api_workflow(
        compiled,
        plan=short,
        rendered=rendered,
        binding=binding,
        capability=capability,
        template_path=WORKFLOW,
        staged_references=_staged(binding),
        seed=20260806,
    )
    assert concrete.workflow["6"]["inputs"]["length"] == 73

    below_minimum = _short_plan(frame_count=56)
    binding = bind_h3_references(below_minimum, _assets())
    rendered = H3PromptRenderer().render(below_minimum, binding, capability)
    compiled = build_h3_workflow(
        below_minimum,
        rendered,
        binding,
        capability,
    )
    with pytest.raises(H3WorkflowBuildError, match="execution authority"):
        build_h3_comfy_api_workflow(
            compiled,
            plan=below_minimum,
            rendered=rendered,
            binding=binding,
            capability=capability,
            template_path=WORKFLOW,
            staged_references=_staged(binding),
            seed=20260806,
        )


def test_h3_compiler_rejects_unsafe_remote_reference_and_non_ref2va_capability() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    rendered = H3PromptRenderer().render(plan, binding, capability)
    compiled = build_h3_workflow(plan, rendered, binding, capability)
    with pytest.raises(ValueError, match="reference"):
        build_h3_comfy_api_workflow(
            compiled,
            plan=plan,
            rendered=rendered,
            binding=binding,
            capability=capability,
            template_path=WORKFLOW,
            staged_references=(
                H3StagedReference(
                    asset_id=binding.items[0].asset_id,
                    sha256=binding.items[0].sha256,
                    remote_name="../front.png",
                ),
                *_staged(binding)[1:],
            ),
            seed=1,
        )


def test_capability_mutation_cannot_replace_models_or_node_schema_after_load() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    capability.model_files["h3_ref2va_diffusion"] = H3ModelFileRevision(
        role="h3_ref2va_diffusion",
        filename="evil_ref2va.safetensors",
        size_bytes=1,
        sha256="0" * 64,
    )
    capability.node_schema_sha256["MiniMaxH3ReferenceToVideo"] = "0" * 64

    with pytest.raises((H3PromptRenderError, H3WorkflowBuildError, ValueError)):
        H3PromptRenderer().render(plan, binding, capability)


def test_concrete_staging_is_asset_and_digest_bound_in_canonical_order() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    compiled = build_h3_workflow(
        plan,
        H3PromptRenderer().render(plan, binding, capability),
        binding,
        capability,
    )
    staged = _staged(binding)
    with pytest.raises(H3WorkflowBuildError, match="staged|binding|digest|asset"):
        build_h3_comfy_api_workflow(
            compiled,
            plan=plan,
            rendered=H3PromptRenderer().render(plan, binding, capability),
            binding=binding,
            capability=capability,
            template_path=WORKFLOW,
            staged_references=(staged[1], staged[0], staged[2]),
            seed=7,
        )
    with pytest.raises(H3WorkflowBuildError, match="staged|binding|digest|asset"):
        build_h3_comfy_api_workflow(
            compiled,
            plan=plan,
            rendered=H3PromptRenderer().render(plan, binding, capability),
            binding=binding,
            capability=capability,
            template_path=WORKFLOW,
            staged_references=(
                H3StagedReference(
                    asset_id=staged[0].asset_id,
                    sha256="0" * 64,
                    remote_name=staged[0].remote_name,
                ),
                *staged[1:],
            ),
            seed=7,
        )


def test_workflow_rejects_resigned_noncanonical_prompt_and_physical_paths() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    canonical = H3PromptRenderer().render(plan, binding, capability)
    attacker_prompt = "completely attacker-authored prompt"
    resigned = H3RenderedPrompt(
        sequence_id=canonical.sequence_id,
        compilation_identity_digest=canonical.compilation_identity_digest,
        binding_digest=canonical.binding_digest,
        capability_digest=canonical.capability_digest,
        reference_set_revision_ids=canonical.reference_set_revision_ids,
        prompt=attacker_prompt,
        prompt_digest=_rendered_prompt_digest(
            sequence_id=canonical.sequence_id,
            compilation_identity_digest=canonical.compilation_identity_digest,
            binding_digest=canonical.binding_digest,
            capability_digest=canonical.capability_digest,
            reference_set_revision_ids=canonical.reference_set_revision_ids,
            prompt=attacker_prompt,
        ),
    )
    with pytest.raises(H3WorkflowBuildError, match="prompt|authority"):
        build_h3_workflow(plan, resigned, binding, capability)

    leaky_shot = plan.shots[0].model_copy(
        update={"action": "read /persistent/douyin-amd/models/evil.safetensors"}
    )
    leaky_plan = plan.model_copy(update={"shots": (leaky_shot,)})
    leaky_binding = bind_h3_references(leaky_plan, _assets())
    with pytest.raises(H3PromptRenderError, match="path|physical|prompt"):
        H3PromptRenderer().render(leaky_plan, leaky_binding, capability)

    for leaked_value in (
        "/opt/models/secret.bin",
        "/var/lib/private/model.bin",
        "../private/model.bin",
        "s3://private-bucket/secret",
        "gs://private-bucket/secret",
        "ftp://private.example/secret",
    ):
        leaky_shot = plan.shots[0].model_copy(update={"action": f"read {leaked_value}"})
        leaky_plan = plan.model_copy(update={"shots": (leaky_shot,)})
        leaky_binding = bind_h3_references(leaky_plan, _assets())
        with pytest.raises(H3PromptRenderError, match="path|physical|prompt"):
            H3PromptRenderer().render(leaky_plan, leaky_binding, capability)


def test_concrete_builder_rejects_self_signed_forged_compiled_prompt() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    rendered = H3PromptRenderer().render(plan, binding, capability)
    compiled = build_h3_workflow(plan, rendered, binding, capability)
    forged_payload = compiled.workflow
    forged_payload["prompt"] = "attacker-authored but syntactically safe"
    forged_payload["prompt_digest"] = "0" * 64
    forged_json = json.dumps(
        forged_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    forged = H3CompiledWorkflow(
        workflow_json=forged_json,
        workflow_digest=hashlib.sha256(forged_json.encode("utf-8")).hexdigest(),
    )

    with pytest.raises(H3WorkflowBuildError, match="canonical|authority|compiled"):
        build_h3_comfy_api_workflow(
            forged,
            plan=plan,
            rendered=rendered,
            binding=binding,
            capability=capability,
            template_path=WORKFLOW,
            staged_references=_staged(binding),
            seed=7,
        )


def test_h3_model_file_verification_cannot_override_pvc_truth() -> None:
    assert "model_root_override" not in signature(load_h3_amd_capability).parameters


def test_archive_layout_and_model_symlinks_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / "comfy"
    release_root.mkdir()
    (release_root / ".source-revision").write_text(
        "6f7cd7fceaaf60d2669b554936394a7412c6fde5\n",
        encoding="utf-8",
    )
    (release_root / ".source-archive-sha256").write_text(
        "4ab47e702474df58971b381884a86da392cab0219c0312f98d4ae860fc110caf\n",
        encoding="utf-8",
    )
    model_registry.verify_h3_comfy_archive_release(
        release_root,
        expected_commit="6f7cd7fceaaf60d2669b554936394a7412c6fde5",
        expected_archive_sha256="4ab47e702474df58971b381884a86da392cab0219c0312f98d4ae860fc110caf",
    )
    (release_root / ".source-archive-sha256").write_text("0" * 64, encoding="utf-8")
    with pytest.raises(H3CapabilityUnavailable, match="archive|release"):
        model_registry.verify_h3_comfy_archive_release(
            release_root,
            expected_commit="6f7cd7fceaaf60d2669b554936394a7412c6fde5",
            expected_archive_sha256="4ab47e702474df58971b381884a86da392cab0219c0312f98d4ae860fc110caf",
        )

    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    model_root = tmp_path / "models"
    target = model_root / "diffusion_models" / capability.ref2va.filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-the-real-model")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self == target or original_is_symlink(self),
    )
    with pytest.raises(H3CapabilityUnavailable, match="symlink"):
        model_registry.verify_h3_capability_files(capability, model_root)


def test_live_h3_node_schema_hashes_are_enforced_and_unknown_inputs_rejected() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    compiled = build_h3_workflow(
        plan,
        H3PromptRenderer().render(plan, binding, capability),
        binding,
        capability,
    )
    concrete = build_h3_comfy_api_workflow(
        compiled,
        plan=plan,
        rendered=H3PromptRenderer().render(plan, binding, capability),
        binding=binding,
        capability=capability,
        template_path=WORKFLOW,
        staged_references=_staged(binding),
        seed=7,
    )
    live_schema = json.loads(LIVE_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
    permissive = {
        node["class_type"]: {
            "input": {
                "required": {key: ["ANY"] for key in node["inputs"]},
                "optional": {},
                "hidden": {},
            }
        }
        for node in concrete.workflow.values()
    }
    permissive.update(live_schema)
    validate_h3_comfy_api_workflow(
        concrete,
        permissive,
        capability=capability,
    )

    unknown_graph = concrete.workflow
    unknown_graph["6"]["inputs"]["attacker_input"] = "bad"
    unknown = H3ConcreteWorkflow(
        workflow_json=json.dumps(
            unknown_graph,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        workflow_digest=hashlib.sha256(
            json.dumps(
                unknown_graph,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        source_workflow_digest=concrete.source_workflow_digest,
        template_sha256=concrete.template_sha256,
        output_node_id=concrete.output_node_id,
    )
    with pytest.raises(H3WorkflowBuildError, match="unknown input"):
        validate_h3_comfy_api_workflow(unknown, permissive, capability=capability)

    invalid_autogrow_graph = concrete.workflow
    invalid_autogrow_graph["6"]["inputs"]["ref_images.attacker"] = ["16", 0]
    invalid_autogrow_json = json.dumps(
        invalid_autogrow_graph,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    invalid_autogrow = H3ConcreteWorkflow(
        workflow_json=invalid_autogrow_json,
        workflow_digest=hashlib.sha256(invalid_autogrow_json.encode("utf-8")).hexdigest(),
        source_workflow_digest=concrete.source_workflow_digest,
        template_sha256=concrete.template_sha256,
        output_node_id=concrete.output_node_id,
    )
    with pytest.raises(H3WorkflowBuildError, match="unknown input|autogrow"):
        validate_h3_comfy_api_workflow(
            invalid_autogrow,
            permissive,
            capability=capability,
        )

    permissive["MiniMaxH3ReferenceToVideo"]["display_name"] = "tampered"
    with pytest.raises(H3WorkflowBuildError, match="schema"):
        validate_h3_comfy_api_workflow(
            concrete,
            permissive,
            capability=capability,
        )


def test_compiled_and_concrete_workflows_expose_only_disposable_payload_copies() -> None:
    plan = _plan()
    binding = bind_h3_references(plan, _assets())
    capability = load_h3_amd_capability(CONFIG, workflow_path=WORKFLOW).capability
    compiled = build_h3_workflow(
        plan,
        H3PromptRenderer().render(plan, binding, capability),
        binding,
        capability,
    )
    exposed = compiled.workflow
    exposed["prompt"] = "attacker"
    assert compiled.workflow["prompt"] != "attacker"

    concrete = build_h3_comfy_api_workflow(
        compiled,
        plan=plan,
        rendered=H3PromptRenderer().render(plan, binding, capability),
        binding=binding,
        capability=capability,
        template_path=WORKFLOW,
        staged_references=_staged(binding),
        seed=7,
    )
    graph = concrete.workflow
    graph["1"]["inputs"]["unet_name"] = "evil_ref2va.safetensors"
    assert concrete.workflow["1"]["inputs"]["unet_name"] == capability.ref2va.filename
