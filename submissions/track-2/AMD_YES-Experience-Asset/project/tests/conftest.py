from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    SourceAuthorship,
    SourceKind,
    StatementStatus,
)
from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.models import (
    ExperienceAssetV1,
    SourceReference,
    Statement,
)


@pytest.fixture
def public_ready_asset() -> ExperienceAssetV1:
    now = datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    asset = new_empty_asset(now=now)
    source_id = uuid4()
    statement_id = uuid4()
    source = SourceReference(
        source_id=source_id,
        kind=SourceKind.CONVERSATION,
        display_label="Sanitized E1-A contract fixture",
        source_hash="a" * 64,
        ingested_at=now,
        authorship=SourceAuthorship.USER_AUTHORED,
    )
    statement = Statement(
        statement_id=statement_id,
        text="The fixture describes one user-provided event.",
        status=StatementStatus.SOURCE_FACT,
        source_refs=[source_id],
        confirmation=ConfirmationState.CONFIRMED,
        evidence_strength=EvidenceStrength.DIRECT,
        created_in_version=asset.version_id,
        last_changed_in_version=asset.version_id,
    )
    payload = asset.model_dump(mode="python")
    payload["sources"] = [source]
    payload["statements"] = [statement]
    payload["context"] = "A public, synthetic contract scenario."
    payload["goal"] = "Validate canonical and public serialization boundaries."
    return ExperienceAssetV1.model_validate(payload)
