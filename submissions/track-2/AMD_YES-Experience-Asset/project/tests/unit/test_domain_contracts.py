from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.domain.enums import (
    EvidenceStrength,
    ProgressState,
    RouteEligibility,
    StatementStatus,
)
from app.experience_asset.domain.models import ProgressEventV1, Statement
from app.experience_asset.domain.public_serialization import (
    eligibility_from_public,
    eligibility_to_public,
    statement_status_from_public,
    statement_status_to_public,
)


@pytest.mark.parametrize("status", list(StatementStatus))
def test_statement_public_mapping_round_trips(status: StatementStatus) -> None:
    assert statement_status_from_public(statement_status_to_public(status)) is status


@pytest.mark.parametrize("eligibility", list(RouteEligibility))
def test_eligibility_public_mapping_round_trips(eligibility: RouteEligibility) -> None:
    assert eligibility_from_public(eligibility_to_public(eligibility)) is eligibility


def test_source_fact_requires_a_source_reference() -> None:
    with pytest.raises(ValidationError, match="SOURCE_FACT requires"):
        Statement(
            statement_id=uuid4(),
            text="Unsupported fact",
            status=StatementStatus.SOURCE_FACT,
            evidence_strength=EvidenceStrength.NONE,
            created_in_version=uuid4(),
            last_changed_in_version=uuid4(),
        )


def test_material_agent_inference_requires_derivation() -> None:
    with pytest.raises(ValidationError, match="AGENT_INFERENCE requires"):
        Statement(
            statement_id=uuid4(),
            text="Unsupported inference",
            status=StatementStatus.AGENT_INFERENCE,
            created_in_version=uuid4(),
            last_changed_in_version=uuid4(),
        )


def test_progress_percentage_must_come_from_work_units() -> None:
    with pytest.raises(ValidationError, match="percent requires the frozen"):
        ProgressEventV1(
            event_id=uuid4(),
            run_id=uuid4(),
            sequence=1,
            stage="contract-test",
            state=ProgressState.RUNNING,
            percent=80,
            message="Running",
            occurred_at=datetime.now(UTC),
        )


def test_determinate_progress_uses_public_milestone_basis() -> None:
    event = ProgressEventV1(
        event_id=uuid4(),
        run_id=uuid4(),
        sequence=2,
        stage="contract-test",
        state=ProgressState.RUNNING,
        percent=40,
        percent_basis="milestones_done/milestones_total",
        milestones_done=2,
        milestones_total=5,
        message="Running",
        occurred_at=datetime.now(UTC),
    )
    assert event.percent == 40


def test_indeterminate_progress_omits_percentage_fields() -> None:
    event = ProgressEventV1(
        event_id=uuid4(),
        run_id=uuid4(),
        sequence=1,
        stage="model-wait",
        state=ProgressState.RUNNING,
        message="Waiting for a non-determinate model operation.",
        occurred_at=datetime.now(UTC),
    )
    assert event.percent is None
    assert event.percent_basis is None
