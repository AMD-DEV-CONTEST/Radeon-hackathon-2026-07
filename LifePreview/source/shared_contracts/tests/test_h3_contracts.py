from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

import shared_contracts

from shared_contracts import (
    CharacterReferenceCrossViewQCV1,
    CharacterReferenceModelRevisionV1,
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    CharacterReferenceViewV1,
    EpisodeGenerationIRV1,
    H3AudioPlanV1,
    H3AudioSafetyError,
    H3AttemptSelectionV1,
    H3CandidateScoreV1,
    H3GenerationMode,
    H3NarratorLockV1,
    H3SelectedResonanceV1,
    H3SequencePlanV1,
    H3SequenceV1,
    H3ShotV1,
    H3SourceLineageV1,
    H3SpeechWindowV1,
    ProjectCreativeIRV1,
    character_reference_set_digest,
    estimate_h3_speech_seconds,
    h3_contract_digest,
    select_best_h3_attempt,
    validate_h3_audio_safety,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64

_PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
_SEQ_ID = UUID("22222222-2222-4222-8222-222222222222")
_REF_SET_ID = UUID("33333333-3333-4333-8333-333333333333")
_REF_SET_REVISION_ID = UUID("55555555-5555-4555-8555-555555555555")
_SELECTION_REASON = "初版媒体完整性更高，依据 h3.selection.v1 固定排序选中。"


def _now() -> datetime:
    return datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _narrator_lock() -> H3NarratorLockV1:
    return H3NarratorLockV1(
        narrator_id="narrator.protagonist",
        voice_source="h3_native",
        disclosure="第一人称主角旁白，由 H3 原生声音生成，不调用外部 TTS。",
    )


def _resonance() -> H3SelectedResonanceV1:
    return H3SelectedResonanceV1(
        resonance_id="resonance.facing-loss",
        revision_id=uuid4(),
        label="面对失去时仍保留选择",
        source_pack_revision_id=uuid4(),
    )


def _scene_plan(scene_number: int = 1) -> dict:
    return {
        "scene_number": scene_number,
        "location": "旧书房",
        "interior_exterior": "interior",
        "day_night": "night",
        "subject_ids": ("subject.protagonist",),
        "evidence_ids": ("E-001", "E-004"),
        "resonance_role": "建立主角面对失去时的克制选择。",
        "narration_intent": "主角第一次独自整理旧信件。",
        "target_duration_seconds": 12.0,
    }


def _project_ir_identity() -> dict:
    return {
        "project_id": str(_PROJECT_ID),
        "source_document_revision_ids": [str(uuid4())],
        "evidence_pack_revision_id": str(uuid4()),
        "selected_resonance": _resonance().model_dump(mode="json"),
        "trial_script_revision_id": str(uuid4()),
        "narrator_lock": _narrator_lock().model_dump(mode="json"),
        "subjects": (
            {
                "subject_id": "subject.protagonist",
                "character_id": "character.protagonist",
                "age_stage": "adult",
            },
        ),
        "character_reference_requirements": (
            {
                "character_id": "character.protagonist",
                "age_stage": "adult",
                "views_required": ("front", "three_quarter_left", "profile_left"),
            },
        ),
        "scene_plans": [_scene_plan()],
        "target_duration_seconds": 90,
        "aspect_ratio": "16:9",
        "narrative_point_of_view": "first_person",
        "creative_model_trace": {"primary": "qwen3.7-plus", "fallback": "glm"},
    }


def _project_ir() -> ProjectCreativeIRV1:
    identity = _project_ir_identity()
    identity["revision_digest"] = h3_contract_digest(
        {key: value for key, value in identity.items() if key != "revision_digest"}
    )
    return ProjectCreativeIRV1.model_validate(identity)


def _shot(
    *,
    shot_ordinal: int = 1,
    start_seconds: float = 0.0,
    end_seconds: float = 209 / 24,
) -> H3ShotV1:
    return H3ShotV1(
        shot_ordinal=shot_ordinal,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        framing="medium",
        camera_move="slow_push_in",
        subject_ids=("subject.protagonist",),
        action="整理旧信件",
        expression="克制的警觉",
    )


def _source_lineage(ordinal: int = 0) -> H3SourceLineageV1:
    return H3SourceLineageV1(
        attempt_ordinal=ordinal,
        artifact_digest=DIGEST_A if ordinal == 0 else DIGEST_B,
        qc_evidence_ids=(f"qc.sequence-1.attempt-{ordinal}",),
        repair_trigger_codes=() if ordinal == 0 else ("H3_FLICKER",),
        generated_at=_now(),
    )


def _speech_window() -> H3SpeechWindowV1:
    return H3SpeechWindowV1(
        text="我把那些旧信件一封一封地摊开。",
        start_seconds=1.0,
        end_seconds=3.8,
    )


def _audio_plan() -> H3AudioPlanV1:
    return H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房，远处轻微风声",
        tail_guard_seconds=1.2,
        narration=_speech_window(),
        action_sounds=(
            {"role": "overlay", "label": "纸张摩擦", "start_seconds": 1.4, "end_seconds": 1.9},
        ),
        internal_cut_times=(),
    )


def _three_second_audio_plan() -> H3AudioPlanV1:
    return H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房，远处轻微风声",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我终于拆开了那封旧信。",
            start_seconds=0.5,
            end_seconds=1.7,
        ),
        action_sounds=(
            {
                "role": "overlay",
                "label": "纸张摩擦",
                "start_seconds": 0.7,
                "end_seconds": 1.2,
            },
        ),
        internal_cut_times=(),
    )


def _frozen_reference_set(
    *,
    reference_set_id: UUID = _REF_SET_ID,
    reference_set_revision_id: UUID = _REF_SET_REVISION_ID,
    state: str = "frozen",
) -> CharacterReferenceSetV1:
    model_revision = CharacterReferenceModelRevisionV1(
        model_family="flux2-dev",
        model_id="flux2-dev-fp8mixed.v1",
        diffusion_model_sha256=DIGEST_A,
        text_encoder_sha256=DIGEST_B,
        vae_sha256=DIGEST_C,
        workflow_sha256=DIGEST_B,
        revision="flux2-dev-fp8mixed.v1",
    )
    source_asset = CharacterReferenceSourceAssetV1(
        asset_id=UUID("44444444-4444-4444-8444-444444444444"),
        content_digest=DIGEST_C,
        verified=True,
        historical=True,
        ai_derived=False,
        uploaded_by="operator.seed",
        uploaded_at=_now(),
    )
    views = tuple(
        CharacterReferenceViewV1(
            asset_id=uuid4(),
            view_name=view_name,
            attempt_ordinal=0,
            image_digest=digest,
            ai_derived=True,
            historical=False,
            identity_control=True,
            model_revision=model_revision,
            single_view_qc_passed=True,
            generated_at=_now(),
        )
        for view_name, digest in (
            ("front", DIGEST_D),
            ("three_quarter_left", DIGEST_E),
            ("profile_left", "f" * 64),
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
        "reference_set_id": str(reference_set_id),
        "reference_set_revision_id": str(reference_set_revision_id),
        "character_id": "character.protagonist",
        "age_stage": "adult",
        "source_asset": source_asset.model_dump(mode="json"),
        "model_revision": model_revision.model_dump(mode="json"),
        "views": [view.model_dump(mode="json") for view in views],
        "cross_view_qc": cross_qc.model_dump(mode="json"),
        "state": state,
    }
    identity["reference_set_digest"] = character_reference_set_digest(identity)
    return CharacterReferenceSetV1.model_validate(identity)


def _sequence(
    *,
    frame_count: int = 209,
    requested_duration_seconds: float = 8.7,
    reference_set_id: UUID = _REF_SET_ID,
    reference_set_state: str = "frozen",
    shots: tuple[H3ShotV1, ...] | None = None,
    audio_plan: H3AudioPlanV1 | None = None,
) -> H3SequencePlanV1:
    duration = frame_count / 24
    return H3SequencePlanV1(
        sequence_id=_SEQ_ID,
        ordinal=1,
        mode=H3GenerationMode.REF2VA,
        frame_count=frame_count,
        fps=24,
        duration_seconds=duration,
        requested_duration_seconds=requested_duration_seconds,
        reference_bindings=(
            {
                "subject_id": "subject.protagonist",
                "reference_set": _frozen_reference_set(
                    reference_set_id=reference_set_id,
                    state=reference_set_state,
                ).model_dump(mode="json"),
            },
        ),
        shots=shots or (_shot(end_seconds=duration),),
        audio_plan=audio_plan or _audio_plan(),
        evidence_ids=("E-001",),
    )


def _final_sequence(
    *,
    plan: H3SequencePlanV1 | None = None,
    repair: H3SourceLineageV1 | None = None,
    selection: H3AttemptSelectionV1 | None = None,
    state: str = "generated",
) -> H3SequenceV1:
    return H3SequenceV1(
        plan=plan or _sequence(),
        prompt_digest=DIGEST_D,
        workflow_digest=DIGEST_E,
        initial_attempt=_source_lineage(0),
        repair_attempt=repair,
        selection_policy_revision="h3.selection.v1",
        selection=selection,
        state=state,
    )


def _episode_ir() -> EpisodeGenerationIRV1:
    project = _project_ir()
    identity = {
        "episode_revision_id": str(uuid4()),
        "project_ir_id": str(_PROJECT_ID),
        "project_ir_revision_digest": project.revision_digest,
        "project_ir": project.model_dump(mode="json"),
        "reference_set_revision_ids": [str(_REF_SET_REVISION_ID)],
        "model_family": "minimax-h3",
        "sequence_plans": [_sequence().model_dump(mode="json")],
        "duration_allocation_digest": DIGEST_A,
        "model_trace": {"episode_router": "qwen3.7-plus", "fallback": "glm"},
    }
    identity["revision_digest"] = h3_contract_digest(
        {key: value for key, value in identity.items() if key != "revision_digest"}
    )
    return EpisodeGenerationIRV1.model_validate(identity)


def _score(
    *,
    attempt_ordinal: int,
    media_integrity: float,
    identity_and_semantics: float,
    technical_quality: float,
    aesthetic_quality: float,
    exception_codes: tuple[str, ...] = (),
    sequence_id: UUID = _SEQ_ID,
) -> H3CandidateScoreV1:
    return H3CandidateScoreV1(
        sequence_id=sequence_id,
        attempt_ordinal=attempt_ordinal,
        media_integrity=media_integrity,
        identity_and_semantics=identity_and_semantics,
        technical_quality=technical_quality,
        aesthetic_quality=aesthetic_quality,
        exception_codes=exception_codes,
    )


def _select(
    candidates: tuple[H3CandidateScoreV1, ...],
) -> H3AttemptSelectionV1:
    return select_best_h3_attempt(
        candidates=candidates,
        sequence_id=_SEQ_ID,
        qc_policy_revision="h3.selection.v1",
        selected_at=_now(),
        selection_reason=_SELECTION_REASON,
    )


# ---------------------------------------------------------------------------
# Behavior 1: strict frozen models, canonical digests
# ---------------------------------------------------------------------------


def test_h3_generation_mode_only_supports_ref2va_in_first_release() -> None:
    distinct = {member.value for member in H3GenerationMode}
    assert distinct == {"ref2va"}
    assert H3GenerationMode.REF2VA.value == "ref2va"


def test_project_ir_rejects_extra_fields_and_tampered_canonical_digest() -> None:
    project = _project_ir()
    assert project.target_duration_seconds == 90
    assert ProjectCreativeIRV1.model_validate_json(project.model_dump_json()) == project

    extra = project.model_dump(mode="json")
    extra["wan_model"] = "wan2.2"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectCreativeIRV1.model_validate(extra)

    tampered = project.model_dump(mode="json")
    tampered["revision_digest"] = DIGEST_D
    with pytest.raises(ValidationError, match="digest"):
        ProjectCreativeIRV1.model_validate(tampered)


def test_project_ir_nested_authorities_are_deeply_immutable() -> None:
    project = _project_ir()

    assert isinstance(project.subjects[0], BaseModel)
    assert isinstance(project.character_reference_requirements[0], BaseModel)
    assert isinstance(project.scene_plans[0], BaseModel)
    assert isinstance(project.creative_model_trace, BaseModel)

    with pytest.raises(ValidationError):
        project.subjects[0].age_stage = "tampered"
    with pytest.raises(ValidationError):
        project.character_reference_requirements[0].age_stage = "tampered"
    with pytest.raises(ValidationError):
        project.scene_plans[0].location = "tampered"
    with pytest.raises(ValidationError):
        project.creative_model_trace.primary = "tampered"

    assert ProjectCreativeIRV1.model_validate_json(project.model_dump_json()) == project


@pytest.mark.parametrize(
    "field,value",
    [
        ("local_path", "/persistent/douyin-amd/models/forbidden.safetensors"),
        ("model_filename", "flux2_dev_fp8mixed.safetensors"),
        ("node_id", "MiniMaxH3ReferenceToVideo"),
        ("gpu", "cuda:0"),
    ],
)
def test_project_ir_nested_authorities_reject_physical_binding_fields(
    field: str,
    value: str,
) -> None:
    identity = _project_ir_identity()
    identity["scene_plans"][0][field] = value
    identity["revision_digest"] = h3_contract_digest(identity)

    with pytest.raises(ValidationError):
        ProjectCreativeIRV1.model_validate(identity)


# ---------------------------------------------------------------------------
# Behavior 2: Project IR fixes 90s, 16:9, first person and binds upstream locks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_duration_seconds", 60),
        ("target_duration_seconds", 120),
        ("aspect_ratio", "9:16"),
        ("narrative_point_of_view", "third_person"),
    ],
)
def test_project_ir_fixed_values_cannot_be_relaxed(field: str, value: object) -> None:
    identity = _project_ir_identity()
    identity[field] = value
    identity["revision_digest"] = h3_contract_digest(
        {key: value_ for key, value_ in identity.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError):
        ProjectCreativeIRV1.model_validate(identity)


def test_project_ir_binds_every_upstream_authority() -> None:
    project = _project_ir()
    assert project.source_document_revision_ids
    assert project.evidence_pack_revision_id is not None
    assert project.selected_resonance.label.startswith("面对失去")
    assert project.trial_script_revision_id is not None
    assert project.narrator_lock.voice_source == "h3_native"
    assert project.subjects[0].subject_id == "subject.protagonist"
    assert project.subjects[0].character_id == "character.protagonist"
    assert project.character_reference_requirements[0].views_required == (
        "front",
        "three_quarter_left",
        "profile_left",
    )
    assert project.scene_plans[0].scene_number == 1


def test_project_ir_subjects_map_exactly_to_character_reference_requirements() -> None:
    identity = _project_ir_identity()
    identity["subjects"][0]["character_id"] = "character.undeclared"
    identity["revision_digest"] = h3_contract_digest(identity)
    with pytest.raises(ValidationError, match="character reference"):
        ProjectCreativeIRV1.model_validate(identity)

    dangling = _project_ir_identity()
    dangling["character_reference_requirements"] = (
        *dangling["character_reference_requirements"],
        {
            "character_id": "character.unused",
            "age_stage": "adult",
            "views_required": ("front", "three_quarter_left", "profile_left"),
        },
    )
    dangling["revision_digest"] = h3_contract_digest(dangling)
    with pytest.raises(ValidationError, match="character reference"):
        ProjectCreativeIRV1.model_validate(dangling)


# ---------------------------------------------------------------------------
# Behavior 3: Episode IR fixes minimax-h3 family and only Ref2VA sequences
# ---------------------------------------------------------------------------


def test_episode_ir_freezes_model_family_and_rejects_non_ref2va_sequences() -> None:
    episode = _episode_ir()
    assert episode.model_family == "minimax-h3"
    assert episode.sequence_plans[0].mode is H3GenerationMode.REF2VA

    project = _project_ir()
    identity = {
        "episode_revision_id": str(uuid4()),
        "project_ir_id": str(_PROJECT_ID),
        "project_ir_revision_digest": project.revision_digest,
        "project_ir": project.model_dump(mode="json"),
        "reference_set_revision_ids": [str(_REF_SET_REVISION_ID)],
        "model_family": "wan2.2",
        "sequence_plans": [_sequence().model_dump(mode="json")],
        "duration_allocation_digest": DIGEST_A,
        "model_trace": {"episode_router": "qwen3.7-plus"},
    }
    identity["revision_digest"] = h3_contract_digest(
        {key: value for key, value in identity.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError, match="minimax-h3"):
        EpisodeGenerationIRV1.model_validate(identity)


def test_episode_ir_rejects_sequence_whose_mode_is_not_ref2va() -> None:
    episode = _episode_ir()
    payload = episode.model_dump(mode="json")
    payload["sequence_plans"][0]["mode"] = "t2va"
    with pytest.raises(ValidationError):
        EpisodeGenerationIRV1.model_validate(payload)


def test_episode_ir_binds_every_sequence_reference_to_declared_frozen_set() -> None:
    episode = _episode_ir()
    assert isinstance(episode.model_trace, BaseModel)
    with pytest.raises(ValidationError):
        episode.model_trace.episode_router = "tampered"

    undeclared = episode.model_dump(mode="json")
    undeclared_set = _frozen_reference_set(
        reference_set_id=uuid4(),
        reference_set_revision_id=uuid4(),
    )
    undeclared["sequence_plans"][0]["reference_bindings"][0]["reference_set"] = (
        undeclared_set.model_dump(mode="json")
    )
    undeclared["revision_digest"] = h3_contract_digest(
        {key: value for key, value in undeclared.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError, match="reference"):
        EpisodeGenerationIRV1.model_validate(undeclared)

    dangling = episode.model_dump(mode="json")
    dangling["reference_set_revision_ids"].append(str(uuid4()))
    dangling["revision_digest"] = h3_contract_digest(
        {key: value for key, value in dangling.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError, match="reference"):
        EpisodeGenerationIRV1.model_validate(dangling)


def test_episode_model_trace_rejects_physical_binding_fields() -> None:
    episode = _episode_ir()
    payload = episode.model_dump(mode="json")
    payload["model_trace"]["model_filename"] = "minimax_h3_ref2va.safetensors"
    payload["revision_digest"] = h3_contract_digest(
        {key: value for key, value in payload.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError):
        EpisodeGenerationIRV1.model_validate(payload)


def test_episode_contains_logical_sequence_plans_not_runtime_attempts() -> None:
    episode = _episode_ir()
    assert "sequence_plans" in EpisodeGenerationIRV1.model_fields
    assert "sequences" not in EpisodeGenerationIRV1.model_fields
    plan_payload = episode.sequence_plans[0].model_dump(mode="json")
    for runtime_field in (
        "prompt_digest",
        "workflow_digest",
        "initial_attempt",
        "repair_attempt",
        "selection",
        "state",
    ):
        assert runtime_field not in plan_payload


def test_episode_cross_checks_bound_reference_character_against_project_subject() -> None:
    episode = _episode_ir()
    payload = episode.model_dump(mode="json")
    bound_set = payload["sequence_plans"][0]["reference_bindings"][0][
        "reference_set"
    ]
    bound_set["character_id"] = "character.antagonist"
    bound_set["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in bound_set.items() if key != "reference_set_digest"}
    )
    payload["revision_digest"] = h3_contract_digest(
        {key: value for key, value in payload.items() if key != "revision_digest"}
    )

    with pytest.raises(ValidationError, match="subject authority"):
        EpisodeGenerationIRV1.model_validate(payload)


def test_episode_reference_declaration_uses_revision_id_not_set_id() -> None:
    episode = _episode_ir()
    assert episode.reference_set_revision_ids == (_REF_SET_REVISION_ID,)
    assert _REF_SET_REVISION_ID != _REF_SET_ID

    payload = episode.model_dump(mode="json")
    payload["reference_set_revision_ids"] = [str(_REF_SET_ID)]
    payload["revision_digest"] = h3_contract_digest(
        {key: value for key, value in payload.items() if key != "revision_digest"}
    )
    with pytest.raises(ValidationError, match="reference"):
        EpisodeGenerationIRV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Behavior 4: legal frame grid, fps=24, requested duration window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frame_count",
    [72, 123, 363, 125, 140, 160],
)
def test_sequence_rejects_illegal_h3_frame_grid(frame_count: int) -> None:
    with pytest.raises(ValidationError, match="frame"):
        _sequence(frame_count=frame_count, requested_duration_seconds=10.0)


def test_sequence_accepts_legal_frame_grid_endpoints() -> None:
    low = _sequence(
        frame_count=73,
        requested_duration_seconds=3.0,
        audio_plan=_three_second_audio_plan(),
    )
    high = _sequence(frame_count=362, requested_duration_seconds=15.0)
    assert low.frame_count == 73
    assert high.frame_count == 362
    assert low.duration_seconds == pytest.approx(73 / 24)
    assert high.duration_seconds == pytest.approx(362 / 24)


def test_sequence_actual_duration_must_equal_frame_count_over_fps() -> None:
    sequence = _sequence()
    payload = sequence.model_dump(mode="json")
    payload["duration_seconds"] = sequence.duration_seconds + 0.5
    with pytest.raises(ValidationError, match="duration"):
        H3SequencePlanV1.model_validate(payload)


@pytest.mark.parametrize("requested", [2.9, 15.1, 0.0])
def test_sequence_requested_duration_must_stay_between_3_and_15_seconds(
    requested: float,
) -> None:
    with pytest.raises(ValidationError, match="duration"):
        _sequence(requested_duration_seconds=requested)


def test_three_second_request_uses_upward_73_frame_snap_without_truncation() -> None:
    sequence = _sequence(
        frame_count=73,
        requested_duration_seconds=3.0,
        audio_plan=_three_second_audio_plan(),
    )

    assert sequence.duration_seconds == pytest.approx(3.0416666666666665)
    assert sequence.duration_seconds >= sequence.requested_duration_seconds
    with pytest.raises(ValidationError, match="frame"):
        _sequence(
            frame_count=72,
            requested_duration_seconds=3.0,
            audio_plan=_three_second_audio_plan(),
        )


def test_sequence_frame_grid_must_be_the_upward_snap_of_requested_duration() -> None:
    with pytest.raises(ValidationError, match="requested duration"):
        _sequence(frame_count=192, requested_duration_seconds=12.0)


def test_sequence_allows_at_most_two_shots_and_binds_audio_cuts_to_shot_boundaries() -> None:
    duration = 209 / 24
    two_shots = (
        _shot(shot_ordinal=1, start_seconds=0.0, end_seconds=4.0),
        _shot(shot_ordinal=2, start_seconds=4.0, end_seconds=duration),
    )
    safe_audio = H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我把那些旧信件一封一封地摊开。",
            start_seconds=1.0,
            end_seconds=3.0,
        ),
        action_sounds=(),
        internal_cut_times=(4.0,),
    )
    sequence = _sequence(shots=two_shots, audio_plan=safe_audio)
    assert sequence.audio_plan.internal_cut_times == (4.0,)

    missing_cut = safe_audio.model_copy(update={"internal_cut_times": ()})
    with pytest.raises(ValidationError, match="shot boundaries"):
        _sequence(shots=two_shots, audio_plan=missing_cut)

    three_shots = (
        _shot(shot_ordinal=1, start_seconds=0.0, end_seconds=2.0),
        _shot(shot_ordinal=2, start_seconds=2.0, end_seconds=4.0),
        _shot(shot_ordinal=3, start_seconds=4.0, end_seconds=duration),
    )
    three_cut_audio = safe_audio.model_copy(update={"internal_cut_times": (2.0, 4.0)})
    with pytest.raises(ValidationError, match="shot"):
        _sequence(shots=three_shots, audio_plan=three_cut_audio)


# ---------------------------------------------------------------------------
# Behavior 5: Ref2VA requires frozen reference sets; legacy fields rejected
# ---------------------------------------------------------------------------


def test_ref2va_sequence_requires_at_least_one_frozen_reference_set() -> None:
    sequence = _sequence()
    payload = sequence.model_dump(mode="json")
    payload["reference_bindings"] = []
    with pytest.raises(ValidationError, match="reference"):
        H3SequencePlanV1.model_validate(payload)


def test_ref2va_sequence_rejects_non_frozen_reference_set_state() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _sequence(reference_set_state="generating")


def test_sequence_subjects_map_exactly_to_reference_bindings() -> None:
    sequence = _sequence()
    payload = sequence.model_dump(mode="json")
    payload["reference_bindings"][0]["subject_id"] = "subject.someone-else"
    with pytest.raises(ValidationError, match="subject"):
        H3SequencePlanV1.model_validate(payload)

    assert sequence.reference_bindings[0].subject_id == "subject.protagonist"
    assert (
        sequence.reference_bindings[0].reference_set.character_id
        == "character.protagonist"
    )


def test_sequence_compilation_identity_is_only_the_logical_plan() -> None:
    compilation_identity = getattr(
        shared_contracts,
        "h3_sequence_compilation_identity",
        None,
    )
    assert callable(compilation_identity)

    plan = _sequence()
    final = _final_sequence(plan=plan)
    expected = plan.model_dump(mode="json")

    assert compilation_identity(plan) == expected
    assert compilation_identity(final) == expected

    changed_runtime = final.model_dump(mode="json")
    changed_runtime["prompt_digest"] = DIGEST_A
    changed_runtime["workflow_digest"] = DIGEST_B
    changed_runtime["initial_attempt"]["artifact_digest"] = DIGEST_C
    changed_runtime["state"] = "generated"
    assert compilation_identity(changed_runtime) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("t2va_text", "自由文本不能直接进 H3"),
        ("fl2va_first_image", DIGEST_A),
        ("wan_model", "wan2.2_ti2v_5B_fp16.safetensors"),
        ("local_path", r"F:\media\reference.png"),
        ("model_filename", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
        ("comfyui_node_id", "MiniMaxH3ReferenceToVideo"),
        ("subtitle_track", "zh-CN"),
        ("tts_provider", "azure-tts"),
    ],
)
def test_sequence_rejects_t2va_fl2va_wan_physical_and_legacy_fields(
    field: str,
    value: object,
) -> None:
    sequence = _sequence()
    payload = sequence.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        H3SequencePlanV1.model_validate(payload)


def test_sequence_mode_literal_rejects_non_ref2va_values() -> None:
    sequence = _sequence()
    for invalid_mode in ("t2va", "fl2va", "i2v", "wan"):
        payload = sequence.model_dump(mode="json")
        payload["mode"] = invalid_mode
        with pytest.raises(ValidationError):
            H3SequencePlanV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Behavior 6: native audio plan, single ambience, overlay foley, safety windows
# ---------------------------------------------------------------------------


def test_audio_plan_requires_h3_native_voice_and_single_ambience() -> None:
    plan = _audio_plan()
    assert plan.tail_guard_seconds == 1.2
    assert plan.voice_source == "h3_native"
    assert "background_music" not in H3AudioPlanV1.model_fields

    payload = plan.model_dump(mode="json")
    payload["voice_source"] = "external_tts"
    with pytest.raises(ValidationError, match="native"):
        H3AudioPlanV1.model_validate(payload)

    payload = plan.model_dump(mode="json")
    payload["base_ambience"] = ["夜晚书房", "远处车流"]
    with pytest.raises(ValidationError, match="ambience"):
        H3AudioPlanV1.model_validate(payload)

    missing_tail_guard = plan.model_dump(mode="json")
    del missing_tail_guard["tail_guard_seconds"]
    with pytest.raises(ValidationError, match="tail_guard_seconds"):
        H3AudioPlanV1.model_validate(missing_tail_guard)


def test_audio_plan_action_sounds_must_be_overlay_only_foley() -> None:
    plan = _audio_plan()
    payload = plan.model_dump(mode="json")
    payload["action_sounds"] = [
        {"role": "main", "label": "整段混音", "start_seconds": 0.0, "end_seconds": 5.0},
    ]
    with pytest.raises(ValidationError, match="overlay"):
        H3AudioPlanV1.model_validate(payload)


def test_speech_window_must_accommodate_estimated_mandarin_duration() -> None:
    text = "我把那些旧信件一封一封地摊开，试图读懂父亲留下的沉默。"
    required = estimate_h3_speech_seconds(text)
    assert required > 0
    with pytest.raises(ValidationError, match="speech"):
        H3SpeechWindowV1(text=text, start_seconds=1.0, end_seconds=1.0 + required / 4)


def test_estimate_h3_speech_seconds_is_deterministic_and_monotonic() -> None:
    short = "她推开门。"
    medium = "她推开门，走廊里只剩下自己的呼吸。"
    long = "她推开门，走廊里只剩下自己的呼吸，每一步都像踩在回忆的边缘。"
    assert estimate_h3_speech_seconds(short) == estimate_h3_speech_seconds(short)
    assert estimate_h3_speech_seconds(short) < estimate_h3_speech_seconds(medium)
    assert estimate_h3_speech_seconds(medium) < estimate_h3_speech_seconds(long)


def test_validate_h3_audio_safety_enforces_lead_in_tail_and_cut_clearance() -> None:
    duration = 141 / 24
    ok = _audio_plan()
    assert validate_h3_audio_safety(ok, sequence_duration_seconds=duration) is None

    lead_in_too_short = H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我把那些旧信件一封一封地摊开。",
            start_seconds=0.3,
            end_seconds=4.0,
        ),
        action_sounds=(),
        internal_cut_times=(),
    )
    with pytest.raises(H3AudioSafetyError, match="lead"):
        validate_h3_audio_safety(
            lead_in_too_short, sequence_duration_seconds=duration
        )

    tail_too_short = H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我把那些旧信件一封一封地摊开。",
            start_seconds=1.0,
            end_seconds=duration - 0.4,
        ),
        action_sounds=(),
        internal_cut_times=(),
    )
    with pytest.raises(H3AudioSafetyError, match="tail"):
        validate_h3_audio_safety(
            tail_too_short, sequence_duration_seconds=duration
        )


def test_validate_h3_audio_safety_rejects_narration_crossing_internal_cut() -> None:
    duration = 240 / 24
    plan = H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我把那些旧信件一封一封地摊开。",
            start_seconds=1.0,
            end_seconds=6.0,
        ),
        action_sounds=(),
        internal_cut_times=(3.0,),
    )
    with pytest.raises(H3AudioSafetyError, match="cut"):
        validate_h3_audio_safety(plan, sequence_duration_seconds=duration)

    safe_plan = H3AudioPlanV1(
        voice_source="h3_native",
        base_ambience="夜晚书房",
        tail_guard_seconds=1.2,
        narration=H3SpeechWindowV1(
            text="我把那些旧信件一封一封地摊开。",
            start_seconds=1.0,
            end_seconds=2.0,
        ),
        action_sounds=(),
        internal_cut_times=(3.0,),
    )
    assert (
        validate_h3_audio_safety(safe_plan, sequence_duration_seconds=duration)
        is None
    )


# ---------------------------------------------------------------------------
# Behavior 7: attempt ordinal 0 initial and optional 1 repair only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ordinal", [2, 3, -1])
def test_source_lineage_rejects_attempt_ordinal_above_one(ordinal: int) -> None:
    with pytest.raises(ValidationError, match="attempt"):
        _source_lineage(ordinal=ordinal)


def test_sequence_may_carry_initial_and_optional_repair_only() -> None:
    with_initial_only = _final_sequence()
    assert with_initial_only.initial_attempt.attempt_ordinal == 0
    assert with_initial_only.repair_attempt is None

    with_repair = _final_sequence(repair=_source_lineage(1))
    assert with_repair.repair_attempt.attempt_ordinal == 1

    sequence = _final_sequence(repair=_source_lineage(1))
    payload = sequence.model_dump(mode="json")
    payload["repair_attempt"]["attempt_ordinal"] = 2
    with pytest.raises(ValidationError, match="attempt"):
        H3SequenceV1.model_validate(payload)


def test_final_sequence_rejects_planned_state_and_requires_runtime_attempt() -> None:
    payload = _final_sequence().model_dump(mode="json")
    payload["state"] = "planned"
    with pytest.raises(ValidationError, match="state"):
        H3SequenceV1.model_validate(payload)

    payload = _final_sequence().model_dump(mode="json")
    payload.pop("initial_attempt")
    with pytest.raises(ValidationError, match="initial_attempt"):
        H3SequenceV1.model_validate(payload)


def test_final_sequence_state_strictly_controls_selection_authority() -> None:
    one_candidate = _select(
        (
            _score(
                attempt_ordinal=0,
                media_integrity=0.9,
                identity_and_semantics=0.9,
                technical_quality=0.9,
                aesthetic_quality=0.9,
            ),
        )
    )

    with pytest.raises(ValidationError, match="selection"):
        _final_sequence(selection=one_candidate, state="generated")
    for state in ("selected", "delivered"):
        with pytest.raises(ValidationError, match="selection"):
            _final_sequence(state=state)
        assert _final_sequence(selection=one_candidate, state=state).selection


def test_final_sequence_selection_candidates_exactly_match_available_attempts() -> None:
    initial_only_selection = _select(
        (
            _score(
                attempt_ordinal=0,
                media_integrity=0.9,
                identity_and_semantics=0.9,
                technical_quality=0.9,
                aesthetic_quality=0.9,
            ),
        )
    )
    two_candidate_selection = _select(
        (
            _score(
                attempt_ordinal=0,
                media_integrity=0.9,
                identity_and_semantics=0.9,
                technical_quality=0.9,
                aesthetic_quality=0.9,
            ),
            _score(
                attempt_ordinal=1,
                media_integrity=0.8,
                identity_and_semantics=0.8,
                technical_quality=0.8,
                aesthetic_quality=0.8,
            ),
        )
    )

    with pytest.raises(ValidationError, match="attempt"):
        _final_sequence(selection=two_candidate_selection, state="selected")
    with pytest.raises(ValidationError, match="attempt"):
        _final_sequence(
            repair=_source_lineage(1),
            selection=initial_only_selection,
            state="selected",
        )
    assert _final_sequence(
        repair=_source_lineage(1),
        selection=two_candidate_selection,
        state="delivered",
    ).state == "delivered"


# ---------------------------------------------------------------------------
# Behavior 8: deterministic lexicographic candidate selection
# ---------------------------------------------------------------------------


def test_selection_prioritizes_media_integrity_over_lower_dimensions() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.5,
            technical_quality=0.5,
            aesthetic_quality=0.5,
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.8,
            identity_and_semantics=1.0,
            technical_quality=1.0,
            aesthetic_quality=1.0,
        ),
    )
    selection = _select(candidates)
    assert selection.selected_attempt_ordinal == 0


def test_selection_prioritizes_identity_over_technical_and_aesthetic() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.9,
            technical_quality=0.2,
            aesthetic_quality=0.2,
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.9,
            identity_and_semantics=0.8,
            technical_quality=1.0,
            aesthetic_quality=1.0,
        ),
    )
    selection = _select(candidates)
    assert selection.selected_attempt_ordinal == 0


def test_equal_score_vectors_select_initial_attempt_ordinal_zero() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.8,
            identity_and_semantics=0.8,
            technical_quality=0.8,
            aesthetic_quality=0.8,
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.8,
            identity_and_semantics=0.8,
            technical_quality=0.8,
            aesthetic_quality=0.8,
        ),
    )
    selection = _select(candidates)
    assert selection.selected_attempt_ordinal == 0


def test_selection_allows_one_or_two_candidates_only() -> None:
    single = _select(
        (
            _score(
                attempt_ordinal=0,
                media_integrity=0.9,
                identity_and_semantics=0.9,
                technical_quality=0.9,
                aesthetic_quality=0.9,
            ),
        )
    )
    assert single.selected_attempt_ordinal == 0

    with pytest.raises(ValueError, match="candidate"):
        _select(
            (
                _score(
                    attempt_ordinal=0,
                    media_integrity=0.9,
                    identity_and_semantics=0.9,
                    technical_quality=0.9,
                    aesthetic_quality=0.9,
                ),
                _score(
                    attempt_ordinal=1,
                    media_integrity=0.8,
                    identity_and_semantics=0.8,
                    technical_quality=0.8,
                    aesthetic_quality=0.8,
                ),
                _score(
                    attempt_ordinal=1,
                    media_integrity=0.7,
                    identity_and_semantics=0.7,
                    technical_quality=0.7,
                    aesthetic_quality=0.7,
                ),
            )
        )


def test_selection_rejects_candidate_from_another_sequence() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.9,
            technical_quality=0.9,
            aesthetic_quality=0.9,
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.95,
            identity_and_semantics=0.95,
            technical_quality=0.95,
            aesthetic_quality=0.95,
            sequence_id=UUID("33333333-3333-4333-8333-333333333333"),
        ),
    )
    with pytest.raises(ValueError, match="sequence"):
        _select(candidates)


# ---------------------------------------------------------------------------
# Behavior 9: clean vs QC-exception semantics, immutable deterministic record
# ---------------------------------------------------------------------------


def test_clean_selection_has_no_exception_codes() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.9,
            technical_quality=0.9,
            aesthetic_quality=0.9,
            exception_codes=(),
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.8,
            identity_and_semantics=0.8,
            technical_quality=0.8,
            aesthetic_quality=0.8,
            exception_codes=(),
        ),
    )
    selection = _select(candidates)
    assert selection.selected_cleanly is True
    assert selection.selected_with_qc_exception is False
    assert selection.exception_codes == ()


def test_clean_repair_wins_before_score_ranking_against_imperfect_initial() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.99,
            identity_and_semantics=0.99,
            technical_quality=0.99,
            aesthetic_quality=0.99,
            exception_codes=("H3_FLICKER",),
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.8,
            identity_and_semantics=0.8,
            technical_quality=0.8,
            aesthetic_quality=0.8,
            exception_codes=(),
        ),
    )

    selection = _select(candidates)

    assert selection.selected_attempt_ordinal == 1
    assert selection.selected_cleanly is True
    assert selection.selected_with_qc_exception is False
    assert selection.exception_codes == ()


def test_imperfect_best_candidate_records_qc_exception_semantics() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.9,
            technical_quality=0.5,
            aesthetic_quality=0.5,
            exception_codes=("H3_FLICKER",),
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.6,
            identity_and_semantics=0.6,
            technical_quality=0.9,
            aesthetic_quality=0.9,
            exception_codes=("H3_IDENTITY_DRIFT", "H3_ASR_MISMATCH"),
        ),
    )
    selection = _select(candidates)
    assert selection.selected_attempt_ordinal == 0
    assert selection.selected_cleanly is False
    assert selection.selected_with_qc_exception is True
    assert selection.exception_codes == ("H3_FLICKER",)


def test_selection_digest_is_deterministic_and_record_is_immutable() -> None:
    candidates = (
        _score(
            attempt_ordinal=0,
            media_integrity=0.9,
            identity_and_semantics=0.9,
            technical_quality=0.9,
            aesthetic_quality=0.9,
        ),
        _score(
            attempt_ordinal=1,
            media_integrity=0.8,
            identity_and_semantics=0.8,
            technical_quality=0.8,
            aesthetic_quality=0.8,
        ),
    )
    first = _select(candidates)
    second = _select(candidates)
    assert first.selection_digest == second.selection_digest
    assert first.selection_digest != DIGEST_A

    with pytest.raises(ValidationError):
        first.selected_attempt_ordinal = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Behavior 12: delivery is frozen, self-authenticating, and fully assembled
# ---------------------------------------------------------------------------


def _delivery_identity(*, source_grounded: bool = False) -> dict:
    disclosure = (
        {
            "code": "SOURCE_GROUNDED",
            "content_mode": "source_grounded",
            "label": "原文与资料核验改写",
            "notice": "内容根据已核验原文与资料进行改写。",
        }
        if source_grounded
        else {
            "code": "AI_COMPLETED_NON_ORIGINAL",
            "content_mode": "ai_completed",
            "label": "AI 补全剧情（非原文）",
            "notice": "未找到可核验原文；内容由 AI 补全，可能存在偏差。",
        }
    )
    identity = {
        "episode_revision_id": str(uuid4()),
        "status": "succeeded",
        "assembly_manifest": {
            "sequence_sources": [
                {
                    "sequence_id": str(_SEQ_ID),
                    "selected_attempt_ordinal": 0,
                    "source_artifact_digest": DIGEST_A,
                }
            ],
            "playback_asset_id": str(uuid4()),
            "download_asset_id": str(uuid4()),
        },
        "disclosure": disclosure,
    }
    identity["delivery_digest"] = h3_contract_digest(identity)
    return identity


def test_delivery_contracts_are_typed_exports_without_replacing_qc_abi() -> None:
    expected = {
        "H3DeliveryAssemblyManifestV1",
        "H3DeliveryDisclosureV1",
        "H3DeliverySequenceSourceV1",
        "H3DeliveryV1",
        "H3AttemptQCEvidenceV1",
        "H3QCDefectEvidenceV1",
    }

    assert expected <= set(shared_contracts.__all__)
    assert all(hasattr(shared_contracts, name) for name in expected)


@pytest.mark.parametrize("source_grounded", [False, True])
def test_delivery_accepts_both_frozen_public_disclosures(
    source_grounded: bool,
) -> None:
    model = shared_contracts.H3DeliveryV1.model_validate(  # type: ignore[attr-defined]
        _delivery_identity(source_grounded=source_grounded)
    )

    assert model.disclosure.content_mode == (
        "source_grounded" if source_grounded else "ai_completed"
    )
    with pytest.raises(ValidationError):
        model.status = "failed"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"episode_revision_id": str(uuid4())}),
        lambda payload: payload["assembly_manifest"].update(
            {"playback_asset_id": str(uuid4())}
        ),
        lambda payload: payload["assembly_manifest"].update(
            {"download_asset_id": str(uuid4())}
        ),
        lambda payload: payload["assembly_manifest"]["sequence_sources"][0].update(
            {"source_artifact_digest": DIGEST_B}
        ),
        lambda payload: payload["disclosure"].update(
            {"notice": "AI 补全（非原文）的公开披露已被篡改。"}
        ),
    ],
)
def test_delivery_digest_covers_public_identity_assembly_assets_and_disclosure(
    mutate,
) -> None:
    payload = _delivery_identity()
    mutate(payload)

    with pytest.raises(ValidationError, match="delivery_digest"):
        shared_contracts.H3DeliveryV1.model_validate(payload)  # type: ignore[attr-defined]
