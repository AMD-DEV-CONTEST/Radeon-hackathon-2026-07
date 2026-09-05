from types import SimpleNamespace
from uuid import uuid4

from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.application.m5.contracts import RelationOutcomeV1
from app.experience_asset.domain.relation import RelationType
from tests.e7_fixtures import make_asset


class _VersionHashes:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_version_content_hash(self, _version_id):
        return self.value


def _relation(asset, *, suffix: int = 1):
    return SimpleNamespace(
        relation_id=uuid4(),
        relation_type=RelationType.SAME_THEME,
        current_asset_id=asset.asset_id,
        current_version_id=asset.version_id,
        current_projection_id=uuid4(),
        current_knowledge_card_hash="a" * 64,
        related_asset_id=uuid4(),
        related_version_id=uuid4(),
        historical_projection_id=uuid4(),
        suffix=suffix,
    )


def test_confirmed_relation_binds_the_related_versions_real_content_hash():
    asset = make_asset("complete")
    loader = M5ContextLoader(_VersionHashes("b" * 64))
    projected = loader._relation_projection(asset, "c" * 64, [_relation(asset)])

    assert projected.outcome is RelationOutcomeV1.CONFIRMED_RELATION
    assert projected.confirmed_related_content_hash == "b" * 64
    assert projected.projection_hash not in {"a" * 64, "b" * 64, "c" * 64}


def test_multiple_confirmed_relations_fail_closed_instead_of_choosing_first():
    asset = make_asset("complete")
    loader = M5ContextLoader(_VersionHashes("b" * 64))
    projected = loader._relation_projection(
        asset,
        "c" * 64,
        [_relation(asset, suffix=1), _relation(asset, suffix=2)],
    )

    assert projected.outcome is RelationOutcomeV1.STALE
    assert projected.is_current is False
    assert projected.confirmed_relation_id is None
