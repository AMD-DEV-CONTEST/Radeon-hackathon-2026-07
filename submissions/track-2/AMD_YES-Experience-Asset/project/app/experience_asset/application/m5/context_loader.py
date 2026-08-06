"""Canonical, current-only context loading shared by M5 HTTP and delivery gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.experience_asset.domain.models import ExperienceAssetV1
from app.experience_asset.persistence import SQLiteAssetRepository

from .contracts import M5ContextProjectionV1, M5RelationProjectionV1, RelationOutcomeV1
from .projection import build_m5_context

ZERO_RELATION_HASH = "0" * 64


@dataclass(frozen=True)
class LoadedM5Context:
    asset: ExperienceAssetV1
    context: M5ContextProjectionV1
    content_hash: str


class M5ContextLoader:
    """Rebuild M5 input from canonical and sidecar truth on every operation."""

    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def load(self, asset_id: UUID) -> LoadedM5Context:
        asset = self.repository.get_current(asset_id)
        content_hash = self.repository.get_version_content_hash(asset.version_id)
        readiness = self.repository.read_active_readiness(asset_id)
        confirmed = self.repository.list_confirmed_relations(asset_id)
        relation = self._relation_projection(asset, content_hash, confirmed)
        return LoadedM5Context(
            asset=asset,
            context=build_m5_context(
                asset,
                content_hash=content_hash,
                readiness=readiness,
                relation=relation,
            ),
            content_hash=content_hash,
        )

    def _relation_projection(
        self,
        asset: ExperienceAssetV1,
        content_hash: str,
        confirmed: list,
    ) -> M5RelationProjectionV1:
        if not confirmed:
            return M5RelationProjectionV1(
                bound_asset_id=asset.asset_id,
                bound_version_id=asset.version_id,
                bound_content_hash=content_hash,
                outcome=RelationOutcomeV1.NO_MATCH,
                projection_hash=ZERO_RELATION_HASH,
                is_current=True,
            )
        # M5 has one exact relation binding. Choosing the first row when more
        # than one confirmation exists makes authorization depend on insertion
        # order, so an ambiguous ledger must stop safely until the user selects
        # one relation.
        if len(confirmed) != 1:
            return M5RelationProjectionV1(
                bound_asset_id=asset.asset_id,
                bound_version_id=asset.version_id,
                bound_content_hash=content_hash,
                outcome=RelationOutcomeV1.STALE,
                projection_hash=self._relations_hash(confirmed),
                is_current=False,
            )
        relation = confirmed[0]
        related_content_hash = self.repository.get_version_content_hash(relation.related_version_id)
        projection_hash = self._relations_hash(
            confirmed,
            related_content_hash=related_content_hash,
        )
        return M5RelationProjectionV1(
            bound_asset_id=asset.asset_id,
            bound_version_id=asset.version_id,
            bound_content_hash=content_hash,
            outcome=RelationOutcomeV1.CONFIRMED_RELATION,
            projection_hash=projection_hash,
            is_current=True,
            confirmed_relation_id=relation.relation_id,
            confirmed_related_asset_id=relation.related_asset_id,
            confirmed_related_version_id=relation.related_version_id,
            confirmed_related_content_hash=related_content_hash,
        )

    @staticmethod
    def _relations_hash(confirmed: list, *, related_content_hash: str | None = None) -> str:
        payload = [
            {
                "relation_id": str(relation.relation_id),
                "relation_type": relation.relation_type.value,
                "current_asset_id": str(relation.current_asset_id),
                "current_version_id": str(relation.current_version_id),
                "current_projection_id": str(relation.current_projection_id),
                "current_knowledge_card_hash": relation.current_knowledge_card_hash,
                "related_asset_id": str(relation.related_asset_id),
                "related_version_id": str(relation.related_version_id),
                "related_content_hash": (related_content_hash if len(confirmed) == 1 else None),
                "historical_projection_id": str(relation.historical_projection_id),
            }
            for relation in sorted(confirmed, key=lambda item: str(item.relation_id))
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["ZERO_RELATION_HASH", "LoadedM5Context", "M5ContextLoader"]
