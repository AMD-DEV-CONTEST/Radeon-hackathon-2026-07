from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.experience_asset.domain.enums import RelationLifecycle, RelationType
from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.public_serialization import (
    PublicSerializationError,
    to_public_asset,
)
from app.experience_asset.domain.relation import ConfirmedAssetRelationV1
from qa.scripts.check_asset_schema import check


def test_public_adapter_passes_frozen_qa_schema(public_ready_asset) -> None:
    public_asset = to_public_asset(public_ready_asset, relations=())
    assert check(public_asset) == []


def test_public_adapter_does_not_invent_missing_statements() -> None:
    with pytest.raises(PublicSerializationError, match="at least one statement"):
        to_public_asset(new_empty_asset(), relations=())


def test_confirmed_relations_reach_the_public_output(public_ready_asset) -> None:
    """A ledger with relations must not serialize as though it had none.

    Before `relations` was required, every caller omitted it and the output
    claimed there were no relations while the ledger held several — with nothing
    at the call site to reveal the difference.
    """
    relation = ConfirmedAssetRelationV1(
        relation_id=uuid4(),
        source_candidate_id=uuid4(),
        relation_type=RelationType.METHOD_REUSE,
        current_asset_id=public_ready_asset.asset_id,
        current_version_id=public_ready_asset.version_id,
        current_projection_id=uuid4(),
        current_knowledge_card_hash="a" * 64,
        related_asset_id=uuid4(),
        related_version_id=uuid4(),
        historical_projection_id=uuid4(),
        lifecycle=RelationLifecycle.CONFIRMED,
        confirmed_at=datetime.now(UTC),
    )

    output = to_public_asset(public_ready_asset, relations=[relation])

    assert output["relations"] == [
        {
            "relation_id": str(relation.relation_id),
            "related_asset_id": str(relation.related_asset_id),
            "relation": "METHOD_REUSE",
            "confirmed_by_user": True,
        }
    ]


def test_a_relation_bound_to_another_version_is_refused(public_ready_asset) -> None:
    """Its stated reason was formed against content this export does not contain."""
    relation = ConfirmedAssetRelationV1(
        relation_id=uuid4(),
        source_candidate_id=uuid4(),
        relation_type=RelationType.SAME_THEME,
        current_asset_id=public_ready_asset.asset_id,
        current_version_id=uuid4(),
        current_projection_id=uuid4(),
        current_knowledge_card_hash="a" * 64,
        related_asset_id=uuid4(),
        related_version_id=uuid4(),
        historical_projection_id=uuid4(),
        lifecycle=RelationLifecycle.CONFIRMED,
        confirmed_at=datetime.now(UTC),
    )

    with pytest.raises(PublicSerializationError, match="different version"):
        to_public_asset(public_ready_asset, relations=[relation])


def test_a_stale_relation_is_dropped_rather_than_refused(public_ready_asset) -> None:
    """Staleness is a normal outcome of a correction; the export simply omits it."""
    relation = ConfirmedAssetRelationV1(
        relation_id=uuid4(),
        source_candidate_id=uuid4(),
        relation_type=RelationType.SAME_THEME,
        current_asset_id=public_ready_asset.asset_id,
        current_version_id=public_ready_asset.version_id,
        current_projection_id=uuid4(),
        current_knowledge_card_hash="a" * 64,
        related_asset_id=uuid4(),
        related_version_id=uuid4(),
        historical_projection_id=uuid4(),
        lifecycle=RelationLifecycle.STALE,
        confirmed_at=datetime.now(UTC),
        invalidated_at=datetime.now(UTC),
        invalidation_reason="the related asset was corrected",
    )

    assert to_public_asset(public_ready_asset, relations=[relation])["relations"] == []
