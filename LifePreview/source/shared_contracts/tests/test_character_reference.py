from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from shared_contracts import (
    CharacterReferenceCrossViewQCV1,
    CharacterReferenceModelRevisionV1,
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    CharacterReferenceViewV1,
    H3GenerationMode,
    H3SequencePlanV1,
    character_reference_set_digest,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64

_CHARACTER_ID = "character.protagonist"
_AGE_STAGE = "adult"
_MODEL_ID = "flux2-dev-fp8mixed.v1"


def _now() -> datetime:
    return datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _source_asset() -> CharacterReferenceSourceAssetV1:
    return CharacterReferenceSourceAssetV1(
        asset_id=uuid4(),
        content_digest=DIGEST_A,
        verified=True,
        historical=True,
        ai_derived=False,
        uploaded_by="operator.seed",
        uploaded_at=_now(),
    )


def _model_revision() -> CharacterReferenceModelRevisionV1:
    return CharacterReferenceModelRevisionV1(
        model_family="flux2-dev",
        model_id=_MODEL_ID,
        diffusion_model_sha256=DIGEST_B,
        text_encoder_sha256=DIGEST_C,
        vae_sha256=DIGEST_D,
        workflow_sha256=DIGEST_C,
        revision="flux2-dev-fp8mixed.v1",
    )


def _view(
    view_name: str,
    image_digest: str,
    *,
    attempt_ordinal: int = 0,
    qc_passed: bool = True,
) -> CharacterReferenceViewV1:
    return CharacterReferenceViewV1(
        asset_id=uuid4(),
        view_name=view_name,
        attempt_ordinal=attempt_ordinal,
        image_digest=image_digest,
        ai_derived=True,
        historical=False,
        identity_control=True,
        model_revision=_model_revision(),
        single_view_qc_passed=qc_passed,
        generated_at=_now(),
    )


def _cross_qc() -> CharacterReferenceCrossViewQCV1:
    return CharacterReferenceCrossViewQCV1(
        identity_consistent=True,
        age_consistent=True,
        attire_consistent=True,
        angle_correct=True,
        no_artifact=True,
        qc_run_at=_now(),
    )


def _views(qc_passed: bool = True) -> tuple[CharacterReferenceViewV1, ...]:
    return (
        _view("front", DIGEST_D, qc_passed=qc_passed),
        _view("three_quarter_left", DIGEST_E, qc_passed=qc_passed),
        _view("profile_left", DIGEST_F, qc_passed=qc_passed),
    )


def _set_identity(
    *,
    reference_set_id: UUID | None = None,
    reference_set_revision_id: UUID | None = None,
    state: str = "frozen",
    views: tuple[CharacterReferenceViewV1, ...] | None = None,
    cross_view_qc: CharacterReferenceCrossViewQCV1 | None = None,
    source_asset: CharacterReferenceSourceAssetV1 | None = None,
    include_cross_view_qc: bool = True,
) -> dict:
    selected_views = _views() if views is None else views
    return {
        "reference_set_id": str(reference_set_id or uuid4()),
        "reference_set_revision_id": str(reference_set_revision_id or uuid4()),
        "character_id": _CHARACTER_ID,
        "age_stage": _AGE_STAGE,
        "source_asset": (source_asset or _source_asset()).model_dump(mode="json"),
        "model_revision": _model_revision().model_dump(mode="json"),
        "views": [view.model_dump(mode="json") for view in selected_views],
        "cross_view_qc": (
            (cross_view_qc or _cross_qc()).model_dump(mode="json")
            if include_cross_view_qc
            else None
        ),
        "state": state,
    }


def _set(
    *,
    reference_set_id: UUID | None = None,
    reference_set_revision_id: UUID | None = None,
    state: str = "frozen",
    views: tuple[CharacterReferenceViewV1, ...] | None = None,
    cross_view_qc: CharacterReferenceCrossViewQCV1 | None = None,
    source_asset: CharacterReferenceSourceAssetV1 | None = None,
    include_cross_view_qc: bool = True,
) -> CharacterReferenceSetV1:
    identity = _set_identity(
        reference_set_id=reference_set_id,
        reference_set_revision_id=reference_set_revision_id,
        state=state,
        views=views,
        cross_view_qc=cross_view_qc,
        source_asset=source_asset,
        include_cross_view_qc=include_cross_view_qc,
    )
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    return CharacterReferenceSetV1.model_validate(identity)


def _h3_sequence_payload(reference_set_state: str) -> dict:
    duration = 192 / 24
    bound_set = _set(
        reference_set_id=UUID("33333333-3333-4333-8333-333333333333"),
        state=reference_set_state,
    )
    return {
        "sequence_id": str(UUID("22222222-2222-4222-8222-222222222222")),
        "ordinal": 1,
        "mode": H3GenerationMode.REF2VA,
        "frame_count": 192,
        "fps": 24,
        "duration_seconds": duration,
        "requested_duration_seconds": 8.0,
        "reference_bindings": (
            {
                "subject_id": "subject.protagonist",
                "reference_set": bound_set.model_dump(mode="json"),
            },
        ),
        "shots": (
            {
                "shot_ordinal": 1,
                "start_seconds": 0.0,
                "end_seconds": duration,
                "framing": "medium",
                "camera_move": "slow_push_in",
                "subject_ids": ("subject.protagonist",),
                "action": "整理旧信件",
                "expression": "克制的警觉",
            },
        ),
        "audio_plan": {
            "voice_source": "h3_native",
            "base_ambience": "夜晚书房",
            "tail_guard_seconds": 1.2,
            "narration": {
                "text": "我把那些旧信件一封一封地摊开。",
                "start_seconds": 1.0,
                "end_seconds": 4.0,
            },
            "action_sounds": (),
            "internal_cut_times": (),
        },
        "evidence_ids": ("E-001",),
    }


# ---------------------------------------------------------------------------
# Behavior 1: exactly three independent images in the canonical order
# ---------------------------------------------------------------------------


def test_frozen_set_requires_exactly_three_views_in_canonical_order() -> None:
    reference_set = _set()
    assert [view.view_name for view in reference_set.views] == [
        "front",
        "three_quarter_left",
        "profile_left",
    ]

    out_of_order = (
        _view("profile_left", DIGEST_D),
        _view("three_quarter_left", DIGEST_E),
        _view("front", DIGEST_F),
    )
    identity = _set_identity(views=out_of_order)
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="order"):
        CharacterReferenceSetV1.model_validate(identity)


def test_frozen_set_rejects_duplicate_image_digests() -> None:
    duplicate_views = (
        _view("front", DIGEST_D),
        _view("three_quarter_left", DIGEST_D),
        _view("profile_left", DIGEST_F),
    )
    identity = _set_identity(views=duplicate_views)
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="digest"):
        CharacterReferenceSetV1.model_validate(identity)


@pytest.mark.parametrize(
    "view_name", ["collage", "card", "turnaround", "back", "right_profile"]
)
def test_view_rejects_non_canonical_view_name(view_name: str) -> None:
    with pytest.raises(ValidationError, match="view"):
        _view(view_name, DIGEST_D)


def test_frozen_set_requires_exactly_three_views() -> None:
    two_views = (
        _view("front", DIGEST_D),
        _view("three_quarter_left", DIGEST_E),
    )
    identity = _set_identity(views=two_views)
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="view"):
        CharacterReferenceSetV1.model_validate(identity)


# ---------------------------------------------------------------------------
# Behavior 2: views are AI-derived identity-control; source is verified historical
# ---------------------------------------------------------------------------


def test_views_must_be_ai_derived_non_historical_identity_control() -> None:
    reference_set = _set()
    assert all(view.ai_derived for view in reference_set.views)
    assert all(not view.historical for view in reference_set.views)
    assert all(view.identity_control for view in reference_set.views)
    assert reference_set.source_asset.historical is True
    assert reference_set.source_asset.verified is True
    assert reference_set.source_asset.ai_derived is False


def test_source_asset_must_be_verified_historical() -> None:
    unverified = CharacterReferenceSourceAssetV1(
        asset_id=uuid4(),
        content_digest=DIGEST_A,
        verified=False,
        historical=True,
        ai_derived=False,
        uploaded_by="operator.seed",
        uploaded_at=_now(),
    )
    identity = _set_identity(source_asset=unverified, state="needs_manual_source_fix")
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="verified"):
        CharacterReferenceSetV1.model_validate(identity)


# ---------------------------------------------------------------------------
# Behavior 3: view attempt ordinal is 0 or 1 only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ordinal", [2, 3, -1])
def test_view_rejects_attempt_ordinal_above_one(ordinal: int) -> None:
    with pytest.raises(ValidationError, match="attempt"):
        _view("front", DIGEST_D, attempt_ordinal=ordinal)


# ---------------------------------------------------------------------------
# Behavior 4: generation model family and revision pinned to FLUX.2 dev FP8 mixed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_family", ["flux2-klein-4b", "flux1-schnell", "wan2.2-i2i", "sdxl", "flux2-dev-fp8mixed"]
)
def test_model_revision_must_pin_flux2_dev_family(model_family: str) -> None:
    with pytest.raises(ValidationError, match="flux2-dev"):
        CharacterReferenceModelRevisionV1(
            model_family=model_family,
            model_id=_MODEL_ID,
            diffusion_model_sha256=DIGEST_B,
            text_encoder_sha256=DIGEST_C,
            vae_sha256=DIGEST_D,
            workflow_sha256=DIGEST_C,
            revision="flux2-dev-fp8mixed.v1",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", "flux2-dev"),
        ("model_id", "flux2-dev-*"),
        ("model_id", "flux2-dev-fp8mixed.latest"),
        ("revision", "r1"),
        ("revision", "flux2-dev-fp8mixed.*"),
    ],
)
def test_model_revision_requires_exact_fp8mixed_identity(field: str, value: str) -> None:
    payload = _model_revision().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match=field):
        CharacterReferenceModelRevisionV1.model_validate(payload)


def test_model_revision_requires_all_three_weight_roles_and_workflow_sha() -> None:
    for missing in (
        "diffusion_model_sha256",
        "text_encoder_sha256",
        "vae_sha256",
        "workflow_sha256",
        "model_id",
    ):
        payload = _model_revision().model_dump(mode="json")
        payload.pop(missing)
        with pytest.raises(ValidationError, match=missing):
            CharacterReferenceModelRevisionV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Behavior 5: frozen requires every per-view and cross-view QC flag to pass
# ---------------------------------------------------------------------------


def test_frozen_rejects_a_failing_single_view_qc() -> None:
    views = (
        _view("front", DIGEST_D, qc_passed=True),
        _view("three_quarter_left", DIGEST_E, qc_passed=False),
        _view("profile_left", DIGEST_F, qc_passed=True),
    )
    identity = _set_identity(views=views, state="frozen")
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="qc"):
        CharacterReferenceSetV1.model_validate(identity)


@pytest.mark.parametrize(
    "failing_flag",
    [
        "identity_consistent",
        "age_consistent",
        "attire_consistent",
        "angle_correct",
        "no_artifact",
    ],
)
def test_frozen_rejects_any_failing_cross_view_qc_flag(failing_flag: str) -> None:
    qc_kwargs = {
        "identity_consistent": True,
        "age_consistent": True,
        "attire_consistent": True,
        "angle_correct": True,
        "no_artifact": True,
        "qc_run_at": _now(),
    }
    qc_kwargs[failing_flag] = False
    failing_qc = CharacterReferenceCrossViewQCV1(**qc_kwargs)
    identity = _set_identity(cross_view_qc=failing_qc, state="frozen")
    identity["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in identity.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="qc"):
        CharacterReferenceSetV1.model_validate(identity)


# ---------------------------------------------------------------------------
# Behavior 6: incomplete states allowed; only frozen binds into an H3 sequence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["draft", "generating", "qc_pending"])
def test_incomplete_states_allow_missing_view_qc(state: str) -> None:
    views = (
        _view("front", DIGEST_D, qc_passed=True),
        _view("three_quarter_left", DIGEST_E, qc_passed=False),
        _view("profile_left", DIGEST_F, qc_passed=True),
    )
    reference_set = _set(state=state, views=views)
    assert reference_set.state == state
    assert reference_set.state != "frozen"


def test_draft_reference_set_may_start_without_generated_views_or_cross_view_qc() -> None:
    draft = _set(
        state="draft",
        views=(),
        include_cross_view_qc=False,
    )
    assert draft.views == ()
    assert draft.cross_view_qc is None


def test_pending_is_not_a_valid_reference_set_state() -> None:
    identity = _set_identity(state="pending")
    identity["reference_set_digest"] = character_reference_set_digest(identity)
    with pytest.raises(ValidationError, match="state"):
        CharacterReferenceSetV1.model_validate(identity)


def test_needs_manual_source_fix_is_allowed_without_full_qc() -> None:
    reference_set = _set(
        state="needs_manual_source_fix",
        views=(
            _view("front", DIGEST_D, qc_passed=False),
            _view("three_quarter_left", DIGEST_E, qc_passed=False),
            _view("profile_left", DIGEST_F, qc_passed=False),
        ),
    )
    assert reference_set.state == "needs_manual_source_fix"


@pytest.mark.parametrize("non_frozen_state", ["draft", "generating", "qc_pending", "needs_manual_source_fix"])
def test_only_frozen_reference_sets_may_bind_into_an_h3_sequence(
    non_frozen_state: str,
) -> None:
    payload = _h3_sequence_payload(reference_set_state=non_frozen_state)
    with pytest.raises(ValidationError, match="frozen"):
        H3SequencePlanV1.model_validate(payload)

    payload = _h3_sequence_payload(reference_set_state="frozen")
    sequence = H3SequencePlanV1.model_validate(payload)
    assert sequence.mode is H3GenerationMode.REF2VA


# ---------------------------------------------------------------------------
# Behavior 7: canonical digest, strict extras, immutability, no Wan/subtitle
# ---------------------------------------------------------------------------


def test_reference_set_digest_is_canonical_and_tamper_rejected() -> None:
    reference_set = _set()
    assert CharacterReferenceSetV1.model_validate_json(
        reference_set.model_dump_json()
    ) == reference_set

    tampered = reference_set.model_dump(mode="json")
    tampered["reference_set_digest"] = DIGEST_A
    with pytest.raises(ValidationError, match="digest"):
        CharacterReferenceSetV1.model_validate(tampered)


def test_reference_set_digest_is_deterministic() -> None:
    shared_source = _source_asset()
    shared_views = _views()
    reference_set_id = uuid4()
    reference_set_revision_id = uuid4()
    first = _set(
        reference_set_id=reference_set_id,
        reference_set_revision_id=reference_set_revision_id,
        source_asset=shared_source,
        views=shared_views,
    )
    second = _set(
        reference_set_id=reference_set_id,
        reference_set_revision_id=reference_set_revision_id,
        source_asset=shared_source,
        views=shared_views,
    )
    assert first.reference_set_digest == second.reference_set_digest


def test_reference_set_rejects_extra_fields_and_is_immutable() -> None:
    reference_set = _set()
    extra = reference_set.model_dump(mode="json")
    extra["subtitle_track"] = "zh-CN"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CharacterReferenceSetV1.model_validate(extra)

    assert "wan_model" not in CharacterReferenceSetV1.model_fields
    assert "subtitle_track" not in CharacterReferenceSetV1.model_fields

    with pytest.raises(ValidationError):
        reference_set.state = "draft"  # type: ignore[misc]


def test_generated_views_require_distinct_logical_artifact_ids() -> None:
    reference_set = _set()
    asset_ids = tuple(view.asset_id for view in reference_set.views)
    assert len(asset_ids) == 3
    assert len(set(asset_ids)) == 3

    payload = reference_set.model_dump(mode="json")
    payload["views"][1]["asset_id"] = payload["views"][0]["asset_id"]
    payload["reference_set_digest"] = character_reference_set_digest(
        {key: value for key, value in payload.items() if key != "reference_set_digest"}
    )
    with pytest.raises(ValidationError, match="asset"):
        CharacterReferenceSetV1.model_validate(payload)

    missing = reference_set.views[0].model_dump(mode="json")
    del missing["asset_id"]
    with pytest.raises(ValidationError, match="asset_id"):
        CharacterReferenceViewV1.model_validate(missing)
