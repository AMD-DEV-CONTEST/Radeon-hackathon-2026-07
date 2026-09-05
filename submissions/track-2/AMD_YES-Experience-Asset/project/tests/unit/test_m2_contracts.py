from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.application.m2 import invalidate_after_m1_correction
from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m2 import (
    ConflictingTimeMomentV1,
    CriticalMomentMapV1,
    KnownTimeMomentV1,
    MissingTimeMomentV1,
)

SCHEMA_PATH = Path("contracts/json-schema/critical-moment-map-v0.1.schema.json")


def common_moment_fields(*, statement_ids: list[UUID], display_order: int = 0) -> dict:
    return {
        "moment_id": uuid4(),
        "display_order": display_order,
        "title": "The trial changed direction",
        "description": "The user reported a source-supported change.",
        "criticality_status": "AGENT_PROPOSED",
        "criticality_reason": "The event changed the user's next action.",
        "criticality_confirmed_at": None,
        "source_statement_ids": statement_ids,
        "cue_statement_ids": [],
        "change_statement_ids": [statement_ids[-1]],
        "surprise_statement_ids": [],
    }


def known_moment(*, statement_id: UUID, display_order: int = 0) -> KnownTimeMomentV1:
    return KnownTimeMomentV1(
        **common_moment_fields(statement_ids=[statement_id], display_order=display_order),
        temporal_status="KNOWN",
        time_label="First trial",
        conflict_statement_ids=[],
        unresolved_reason=None,
    )


def critical_map(*, statement_id: UUID) -> CriticalMomentMapV1:
    now = datetime(2026, 7, 28, 4, 30, tzinfo=UTC)
    return CriticalMomentMapV1(
        artifact_id=uuid4(),
        asset_id=uuid4(),
        base_m1_version_id=uuid4(),
        generated_by_run_id=uuid4(),
        state=MilestoneState.REVIEW_READY,
        order_basis="NARRATIVE_SEQUENCE",
        moments=[known_moment(statement_id=statement_id)],
        dependency_statement_ids=[statement_id],
        unresolved_question_ids=[],
        created_at=now,
        updated_at=now,
        invalidated_by_m1_version_id=None,
        invalidation_reason=None,
    )


def test_known_time_requires_a_source_supported_label() -> None:
    with pytest.raises(ValidationError):
        KnownTimeMomentV1(
            **common_moment_fields(statement_ids=[uuid4()]),
            temporal_status="KNOWN",
            time_label="",
            conflict_statement_ids=[],
            unresolved_reason=None,
        )


def test_model_facing_contract_cannot_self_assert_user_confirmation() -> None:
    payload = {
        **common_moment_fields(statement_ids=[uuid4()]),
        "criticality_status": "USER_CONFIRMED",
        "temporal_status": "KNOWN",
        "time_label": "First trial",
        "conflict_statement_ids": [],
        "unresolved_reason": None,
    }
    with pytest.raises(ValidationError):
        KnownTimeMomentV1.model_validate(payload)


def test_trusted_user_confirmation_requires_and_retains_provenance() -> None:
    confirmed_at = datetime.now(UTC)
    entry = KnownTimeMomentV1(
        **{
            **common_moment_fields(statement_ids=[uuid4()]),
            "criticality_status": "USER_CONFIRMED",
            "criticality_confirmed_at": confirmed_at,
        },
        temporal_status="KNOWN",
        time_label="First trial",
        conflict_statement_ids=[],
        unresolved_reason=None,
    )
    assert entry.criticality_status == "USER_CONFIRMED"
    assert entry.criticality_confirmed_at == confirmed_at


def test_missing_time_stays_visible_instead_of_being_invented() -> None:
    entry = MissingTimeMomentV1(
        **common_moment_fields(statement_ids=[uuid4()]),
        temporal_status="MISSING",
        time_label=None,
        conflict_statement_ids=[],
        unresolved_reason="The source does not state when this happened.",
    )
    assert entry.time_label is None
    assert entry.unresolved_reason is not None


@pytest.mark.parametrize("conflict_count", [0, 1])
def test_conflicting_time_requires_two_source_statements(conflict_count: int) -> None:
    statement_ids = [uuid4(), uuid4()]
    with pytest.raises(ValidationError):
        ConflictingTimeMomentV1(
            **common_moment_fields(statement_ids=statement_ids),
            temporal_status="CONFLICTING",
            time_label=None,
            conflict_statement_ids=statement_ids[:conflict_count],
            unresolved_reason="The source gives incompatible durations.",
        )


def test_conflicting_time_requires_distinct_source_statements() -> None:
    statement_id = uuid4()
    with pytest.raises(ValidationError, match="must be distinct"):
        ConflictingTimeMomentV1(
            **common_moment_fields(statement_ids=[statement_id]),
            temporal_status="CONFLICTING",
            time_label=None,
            conflict_statement_ids=[statement_id, statement_id],
            unresolved_reason="The source gives incompatible durations.",
        )


def test_known_or_missing_time_cannot_hide_conflict_ids() -> None:
    statement_id = uuid4()
    with pytest.raises(ValidationError):
        MissingTimeMomentV1(
            **common_moment_fields(statement_ids=[statement_id]),
            temporal_status="MISSING",
            time_label=None,
            conflict_statement_ids=[statement_id],
            unresolved_reason="The source does not state when this happened.",
        )


def test_statement_identity_lists_reject_duplicates() -> None:
    statement_id = uuid4()
    with pytest.raises(ValidationError, match="source statement IDs must be unique"):
        KnownTimeMomentV1(
            **common_moment_fields(statement_ids=[statement_id, statement_id]),
            temporal_status="KNOWN",
            time_label="First trial",
            conflict_statement_ids=[],
            unresolved_reason=None,
        )

    artifact = critical_map(statement_id=statement_id)
    payload = artifact.model_dump(mode="python")
    payload["dependency_statement_ids"] = [statement_id, statement_id]
    with pytest.raises(ValidationError, match="dependency statement IDs must be unique"):
        CriticalMomentMapV1.model_validate(payload)


def test_moments_use_display_order_without_claiming_calendar_chronology() -> None:
    statement_id = uuid4()
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="ascending display_order"):
        CriticalMomentMapV1(
            artifact_id=uuid4(),
            asset_id=uuid4(),
            base_m1_version_id=uuid4(),
            generated_by_run_id=uuid4(),
            state=MilestoneState.NEEDS_INPUT,
            order_basis="PARTIAL_ORDER",
            moments=[
                known_moment(statement_id=statement_id, display_order=1),
                known_moment(statement_id=statement_id, display_order=0),
            ],
            dependency_statement_ids=[statement_id],
            unresolved_question_ids=[],
            created_at=now,
            updated_at=now,
            invalidated_by_m1_version_id=None,
            invalidation_reason=None,
        )


@pytest.mark.parametrize(
    ("invalidated_version", "reason"),
    [(uuid4(), None), (None, "orphan reason")],
)
def test_non_invalidated_map_rejects_partial_invalidation_provenance(
    invalidated_version: UUID | None, reason: str | None
) -> None:
    artifact = critical_map(statement_id=uuid4())
    payload = artifact.model_dump(mode="python")
    payload.update(
        invalidated_by_m1_version_id=invalidated_version,
        invalidation_reason=reason,
    )
    with pytest.raises(ValidationError, match="only INVALIDATED"):
        CriticalMomentMapV1.model_validate(payload)


def test_invalidated_map_requires_complete_invalidation_provenance() -> None:
    artifact = critical_map(statement_id=uuid4())
    payload = artifact.model_dump(mode="python")
    payload["state"] = MilestoneState.INVALIDATED
    with pytest.raises(ValidationError, match="requires a version"):
        CriticalMomentMapV1.model_validate(payload)


def test_m1_correction_invalidates_a_dependent_m2_artifact() -> None:
    statement_id = uuid4()
    artifact = critical_map(statement_id=statement_id)
    new_m1_version_id = uuid4()
    changed_at = artifact.updated_at + timedelta(minutes=1)

    invalidated = invalidate_after_m1_correction(
        artifact,
        corrected_statement_ids={statement_id},
        new_m1_version_id=new_m1_version_id,
        changed_at=changed_at,
    )

    assert invalidated.state is MilestoneState.INVALIDATED
    assert invalidated.invalidated_by_m1_version_id == new_m1_version_id
    assert str(statement_id) in (invalidated.invalidation_reason or "")
    assert invalidated.updated_at == changed_at
    assert artifact.state is MilestoneState.REVIEW_READY


def test_invalidation_rejects_naive_or_regressing_timestamps() -> None:
    statement_id = uuid4()
    artifact = critical_map(statement_id=statement_id)
    for changed_at in (
        artifact.updated_at.replace(tzinfo=None),
        artifact.updated_at - timedelta(seconds=1),
    ):
        with pytest.raises(ValueError, match="changed_at"):
            invalidate_after_m1_correction(
                artifact,
                corrected_statement_ids={statement_id},
                new_m1_version_id=uuid4(),
                changed_at=changed_at,
            )


def test_invalidation_requires_a_distinct_m1_version() -> None:
    statement_id = uuid4()
    artifact = critical_map(statement_id=statement_id)

    with pytest.raises(ValueError, match="must differ"):
        invalidate_after_m1_correction(
            artifact,
            corrected_statement_ids={statement_id},
            new_m1_version_id=artifact.base_m1_version_id,
            changed_at=artifact.updated_at + timedelta(minutes=1),
        )


def test_unrelated_m1_correction_preserves_the_current_m2_artifact() -> None:
    artifact = critical_map(statement_id=uuid4())

    unchanged = invalidate_after_m1_correction(
        artifact,
        corrected_statement_ids={uuid4()},
        new_m1_version_id=uuid4(),
        changed_at=artifact.updated_at + timedelta(minutes=1),
    )

    assert unchanged is artifact


def test_checked_in_json_schema_matches_the_isolated_contract() -> None:
    checked_in = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert checked_in == CriticalMomentMapV1.model_json_schema()
