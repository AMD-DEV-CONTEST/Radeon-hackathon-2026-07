"""Ticket 08 — evidence-card rendering, bounded read, and non-contamination.

These run against ticket 01's frozen projection-pair and confirmed-relation
fixtures. GRAG-13 (the card's content) and the bounded-read and determinism
properties are verifiable now. GRAG-14 through the real confirm-then-read flow
needs ticket 07 and stays out of Wave 1: asserting it here would mean the flow
was never exercised, only its last step.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.experience_asset.application.relation_evidence import (
    BoundedDetailRequest,
    EvidenceCardRefusal,
    EvidenceCardRefusalReason,
    EvidenceCardV1,
    render_evidence_card,
    resolve_bounded_detail,
)
from app.experience_asset.domain.enums import RelationLifecycle, RelationType
from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.retrieval import SQLiteSummaryLexicalRepository
from app.experience_asset.role_graph import build_role_graph_projection
from tests.integration.test_e5_role_graph_projection import (
    NOW,
    _persist_ready_inputs,
    _ready_asset,
)


def _real_side(repository: SQLiteAssetRepository) -> dict[str, Any]:
    """One asset persisted end to end, with an activated projection."""
    asset, artifact, readiness = _ready_asset()
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset, m4_artifact=artifact, readiness=readiness, created_at=NOW
    )
    repository.activate_projection(projection)
    return {"asset": asset, "readiness": readiness, "projection": projection}

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "e5" / "instance"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def relation() -> ConfirmedAssetRelationV1:
    return ConfirmedAssetRelationV1.model_validate(_load("confirmed-asset-relation"))


@pytest.fixture
def candidate() -> RelationCandidateV1:
    return RelationCandidateV1.model_validate(_load("relation-candidate"))


@pytest.fixture
def current_projection() -> RoleGraphProjectionV1:
    return RoleGraphProjectionV1.model_validate(_load("role-graph-projection-current"))


@pytest.fixture
def historical_projection() -> RoleGraphProjectionV1:
    return RoleGraphProjectionV1.model_validate(
        _load("role-graph-projection-historical")
    )


def _render(relation, candidate, current_projection, historical_projection, **kwargs):
    return render_evidence_card(
        relation=relation,
        candidate=candidate,
        current_projection=current_projection,
        historical_projection=historical_projection,
        **kwargs,
    )


class TestBoundedDetailRead:
    """The read is bounded by the approved closure, not by the asset."""

    def test_closure_covers_mapped_and_boundary_nodes_only(self, candidate):
        closure = BoundedDetailRequest.from_candidate(candidate)

        expected_current = {m.current_node_id for m in candidate.node_mappings}
        expected_current |= set(candidate.current_boundary_node_ids)
        expected_historical = {m.historical_node_id for m in candidate.node_mappings}
        expected_historical |= set(candidate.historical_boundary_node_ids)

        assert set(closure.current_node_ids) == expected_current
        assert set(closure.historical_node_ids) == expected_historical

    def test_read_does_not_reach_beyond_the_closure(
        self, candidate, historical_projection
    ):
        """An unrestricted read would turn one approved comparison into a
        general search over that history."""
        closure = BoundedDetailRequest.from_candidate(candidate)
        detail = resolve_bounded_detail(
            historical_projection, closure.historical_node_ids
        )

        all_node_ids = {node.node_id for node in historical_projection.nodes}
        unapproved = all_node_ids - set(closure.historical_node_ids)
        assert unapproved, "fixture must carry nodes outside the closure to be a test"
        assert set(detail.provenance_by_node) <= set(closure.historical_node_ids)

        unapproved_statements: set[str] = set()
        for entry in historical_projection.provenance:
            if entry.node_id in unapproved:
                unapproved_statements |= {str(v) for v in entry.statement_ids}
        read_statements = {str(v) for v in detail.statement_ids}
        assert not (read_statements & unapproved_statements - _approved_statements(
            historical_projection, closure.historical_node_ids
        ))

    def test_missing_node_is_reported_not_skipped(self, historical_projection):
        detail = resolve_bounded_detail(
            historical_projection, ("NODE:does-not-exist",)
        )
        assert detail.missing_node_ids == ("NODE:does-not-exist",)
        assert not detail.is_complete


def _approved_statements(projection, node_ids) -> set[str]:
    approved: set[str] = set()
    for entry in projection.provenance:
        if entry.node_id in set(node_ids):
            approved |= {str(v) for v in entry.statement_ids}
    return approved


class TestEvidenceCardContent:
    """GRAG-13 — what the card must carry."""

    def test_card_carries_the_required_content(
        self, relation, candidate, current_projection, historical_projection
    ):
        card = _render(relation, candidate, current_projection, historical_projection)
        assert isinstance(card, EvidenceCardV1)

        assert card.relation_type is relation.relation_type
        assert len(card.mapped_roles) == len(candidate.node_mappings)
        assert card.boundaries, "the transfer boundary is not optional"
        assert {entry.side for entry in card.provenance} == {"CURRENT", "HISTORICAL"}

    def test_labels_are_copied_verbatim_from_the_projections(
        self, relation, candidate, current_projection, historical_projection
    ):
        """The text the user can open must be the text the card shows."""
        card = _render(relation, candidate, current_projection, historical_projection)
        current_nodes = {n.node_id: n for n in current_projection.nodes}
        historical_nodes = {n.node_id: n for n in historical_projection.nodes}

        for role in card.mapped_roles:
            assert role.current_label == current_nodes[role.current_node_id].summary_text
            assert (
                role.historical_label
                == historical_nodes[role.historical_node_id].summary_text
            )

    def test_boundary_content_is_quoted_from_its_source_node(
        self, relation, candidate, current_projection, historical_projection
    ):
        card = _render(relation, candidate, current_projection, historical_projection)
        current_nodes = {n.node_id: n for n in current_projection.nodes}
        historical_nodes = {n.node_id: n for n in historical_projection.nodes}

        for boundary in card.boundaries:
            source = (
                current_nodes if boundary.side == "CURRENT" else historical_nodes
            )[boundary.node_id]
            assert boundary.content == source.summary_text
            assert boundary.content_hash == source.summary_text_hash

    def test_card_contains_no_text_outside_the_projections(
        self, relation, candidate, current_projection, historical_projection
    ):
        """No second model call, no generated advice, no new fact.

        Every free-text field on a rendered card must be traceable to a
        projection node; anything else would be an artifact produced after the
        confirmation gate.
        """
        card = _render(relation, candidate, current_projection, historical_projection)
        canonical = {node.summary_text for node in current_projection.nodes}
        canonical |= {node.summary_text for node in historical_projection.nodes}

        for role in card.mapped_roles:
            assert role.current_label in canonical
            assert role.historical_label in canonical
        for boundary in card.boundaries:
            assert boundary.content in canonical


class TestDeterminism:
    def test_rendering_twice_is_byte_identical(
        self, relation, candidate, current_projection, historical_projection
    ):
        first = _render(relation, candidate, current_projection, historical_projection)
        second = _render(relation, candidate, current_projection, historical_projection)
        assert first.model_dump_json() == second.model_dump_json()
        assert first.card_hash == second.card_hash


class TestTypedRefusals:
    """Each failure produces a typed result rather than a partial card."""

    @pytest.mark.parametrize("lifecycle", ["STALE", "INVALIDATED"])
    def test_revoked_relation_is_refused(
        self, relation, candidate, current_projection, historical_projection, lifecycle
    ):
        revoked = relation.model_copy(
            update={
                "lifecycle": lifecycle,
                "invalidated_at": relation.confirmed_at,
                "invalidation_reason": "upstream correction",
            }
        )
        result = _render(revoked, candidate, current_projection, historical_projection)
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.RELATION_NOT_LIVE

    def test_revoked_permission_is_refused(
        self, relation, candidate, current_projection, historical_projection
    ):
        result = _render(
            relation,
            candidate,
            current_projection,
            historical_projection,
            historical_read_permitted=False,
        )
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.PERMISSION_REVOKED

    def test_moved_knowledge_card_hash_fails_closed(
        self, relation, candidate, current_projection, historical_projection
    ):
        """The comparison the user approved was against different content."""
        drifted = current_projection.model_copy(
            update={"knowledge_card_hash": "0" * 64}
        )
        result = _render(relation, candidate, drifted, historical_projection)
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.BINDING_MISMATCH

    def test_deleted_content_refuses_the_whole_card(
        self, relation, candidate, current_projection, historical_projection
    ):
        dropped = candidate.current_boundary_node_ids[0]
        pruned = current_projection.model_copy(
            update={
                "nodes": [
                    n for n in current_projection.nodes if n.node_id != dropped
                ]
            }
        )
        result = _render(relation, candidate, pruned, historical_projection)
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.CONTENT_UNAVAILABLE
        assert dropped in result.unresolved_node_ids

    def test_partial_provenance_refuses_the_whole_card(
        self, relation, candidate, current_projection, historical_projection
    ):
        """A card missing half its provenance still looks authoritative."""
        unbacked = candidate.current_boundary_node_ids[0]
        pruned = current_projection.model_copy(
            update={
                "provenance": [
                    p for p in current_projection.provenance if p.node_id != unbacked
                ]
            }
        )
        result = _render(relation, candidate, pruned, historical_projection)
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.PARTIAL_PROVENANCE
        assert unbacked in result.unresolved_node_ids

    def test_foreign_candidate_fails_closed(
        self, relation, candidate, current_projection, historical_projection
    ):
        foreign = candidate.model_copy(
            update={"candidate_id": relation.relation_id}
        )
        result = _render(relation, foreign, current_projection, historical_projection)
        assert isinstance(result, EvidenceCardRefusal)
        assert result.reason is EvidenceCardRefusalReason.BINDING_MISMATCH


class TestNonContamination:
    """GRAG-14, at the level Wave 1 can honestly reach.

    The end-to-end confirm-then-read proof needs ticket 07. What is verifiable
    now is that rendering is a pure read: it returns a composed object and
    mutates none of its inputs.
    """

    def test_rendering_mutates_no_input(
        self, relation, candidate, current_projection, historical_projection
    ):
        before = (
            relation.model_dump_json(),
            candidate.model_dump_json(),
            current_projection.model_dump_json(),
            historical_projection.model_dump_json(),
        )
        _render(relation, candidate, current_projection, historical_projection)
        after = (
            relation.model_dump_json(),
            candidate.model_dump_json(),
            current_projection.model_dump_json(),
            historical_projection.model_dump_json(),
        )
        assert before == after

    def test_card_does_not_carry_a_snapshot_write_path(
        self, relation, candidate, current_projection, historical_projection
    ):
        """The card echoes the current binding; it never redefines it."""
        card = _render(relation, candidate, current_projection, historical_projection)
        assert card.current_knowledge_card_hash == relation.current_knowledge_card_hash
        assert card.current_version_id == relation.current_version_id


class TestPersistedNonContamination:
    """GRAG-14 at the seam that can actually break it: the database.

    The rest of this module renders from fixtures held in memory, which cannot
    demonstrate the invariant these criteria name. Nothing crashes if a relation
    read appends a content version — the asset quietly acquires history it did
    not earn, and its hash stops matching the readiness binding other relations
    depend on. Only a before/after comparison of persisted bytes makes that
    visible, so these tests read rows they did not write in the same call.
    """

    @staticmethod
    def _persisted(repository: SQLiteAssetRepository, asset_id: UUID) -> dict[str, Any]:
        connection = sqlite3.connect(repository.database_path)
        connection.row_factory = sqlite3.Row
        try:
            current = connection.execute(
                """SELECT v.version_id, v.content_json, v.content_hash
                FROM assets a JOIN asset_versions v
                  ON v.asset_id=a.asset_id AND v.version_id=a.current_version_id
                WHERE a.asset_id=?""",
                (str(asset_id),),
            ).fetchone()
            versions = connection.execute(
                "SELECT count(*) AS total FROM asset_versions WHERE asset_id=?",
                (str(asset_id),),
            ).fetchone()["total"]
            readiness = connection.execute(
                """SELECT knowledge_card_hash FROM knowledge_card_readiness
                WHERE asset_id=? AND lifecycle='ACTIVE'""",
                (str(asset_id),),
            ).fetchone()
        finally:
            connection.close()
        return {
            "version_id": current["version_id"],
            "content_json": current["content_json"],
            "content_hash": current["content_hash"],
            "version_count": versions,
            "knowledge_card_hash": readiness["knowledge_card_hash"],
        }

    @staticmethod
    def _confirmed_over(current, historical, candidate_id: UUID, card_hash: str):
        return ConfirmedAssetRelationV1(
            relation_id=uuid4(),
            source_candidate_id=candidate_id,
            relation_type=RelationType.SAME_THEME,
            current_asset_id=current["asset"].asset_id,
            current_version_id=current["asset"].version_id,
            current_projection_id=current["projection"].projection_id,
            current_knowledge_card_hash=card_hash,
            related_asset_id=historical["asset"].asset_id,
            related_version_id=historical["asset"].version_id,
            historical_projection_id=historical["projection"].projection_id,
            lifecycle=RelationLifecycle.CONFIRMED,
            confirmed_at=datetime.now(UTC),
        )

    def test_reading_a_relation_leaves_the_asset_byte_identical(self, tmp_path) -> None:
        repository = SQLiteAssetRepository(tmp_path / "contamination.sqlite3")
        repository.initialize()
        current = _real_side(repository)
        historical = _real_side(repository)
        before = self._persisted(repository, current["asset"].asset_id)

        # The read path that exists in Wave 1: projections come back out of
        # SQLite, and the card is assembled from what was stored.
        eligible = repository.list_eligible_projections(
            current_asset_id=historical["asset"].asset_id
        )
        stored_current = next(
            item
            for item in eligible
            if item.projection_id == current["projection"].projection_id
        )
        search = SQLiteSummaryLexicalRepository(repository)
        search.search(query="cache", current_asset_id=historical["asset"].asset_id)

        current_root = next(node for node in stored_current.nodes if node.is_root)
        historical_root = next(
            node for node in historical["projection"].nodes if node.is_root
        )
        resolve_bounded_detail(stored_current, (current_root.node_id,))
        resolve_bounded_detail(historical["projection"], (historical_root.node_id,))

        after = self._persisted(repository, current["asset"].asset_id)
        assert after == before
        # Spelled out separately: an equal dict would still pass if both sides
        # were empty, and these three are the fields other bindings depend on.
        assert after["content_json"] == before["content_json"]
        assert after["content_hash"] == before["content_hash"]
        assert after["knowledge_card_hash"] == before["knowledge_card_hash"]

    def test_a_detail_read_appends_no_content_version(self, tmp_path) -> None:
        repository = SQLiteAssetRepository(tmp_path / "versions.sqlite3")
        repository.initialize()
        current = _real_side(repository)
        historical = _real_side(repository)
        before = self._persisted(repository, current["asset"].asset_id)
        candidate_id = uuid4()
        relation = self._confirmed_over(
            current, historical, candidate_id, before["knowledge_card_hash"]
        )

        current_root = next(node for node in current["projection"].nodes if node.is_root)
        historical_root = next(
            node for node in historical["projection"].nodes if node.is_root
        )
        for _ in range(3):
            resolve_bounded_detail(current["projection"], (current_root.node_id,))
            resolve_bounded_detail(historical["projection"], (historical_root.node_id,))
            repository.list_eligible_projections(
                current_asset_id=historical["asset"].asset_id
            )

        after = self._persisted(repository, current["asset"].asset_id)
        assert after["version_count"] == before["version_count"]
        assert after["version_id"] == before["version_id"]
        # The relation names the card hash it was confirmed against; if a read
        # had appended a version, this binding would now point at history the
        # user never accepted.
        assert relation.current_knowledge_card_hash == after["knowledge_card_hash"]

    def test_the_card_hash_is_stable_across_reloads_from_storage(self, tmp_path) -> None:
        repository = SQLiteAssetRepository(tmp_path / "stable.sqlite3")
        repository.initialize()
        current = _real_side(repository)
        historical = _real_side(repository)
        before = self._persisted(repository, current["asset"].asset_id)
        candidate_id = uuid4()
        relation = self._confirmed_over(
            current, historical, candidate_id, before["knowledge_card_hash"]
        )
        current_root = next(node for node in current["projection"].nodes if node.is_root)
        historical_root = next(
            node for node in historical["projection"].nodes if node.is_root
        )
        candidate = RelationCandidateV1(
            candidate_id=candidate_id,
            discovery_fingerprint="d" * 64,
            current_asset_id=current["asset"].asset_id,
            current_projection_id=current["projection"].projection_id,
            related_asset_id=historical["asset"].asset_id,
            historical_projection_id=historical["projection"].projection_id,
            relation_type=RelationType.SAME_THEME,
            title="同一主题",
            summary="两次经历处理了同一类取舍。",
            node_mappings=[
                {
                    "current_node_id": current_root.node_id,
                    "historical_node_id": historical_root.node_id,
                }
            ],
            current_boundary_node_ids=[current["projection"].nodes[-1].node_id],
            historical_boundary_node_ids=[historical["projection"].nodes[-1].node_id],
            provenance=[
                {
                    "side": "CURRENT",
                    "node_id": current_root.node_id,
                    "statement_ids": [
                        str(item)
                        for item in next(
                            entry.statement_ids
                            for entry in current["projection"].provenance
                            if entry.node_id == current_root.node_id
                        )
                    ],
                },
                {
                    "side": "HISTORICAL",
                    "node_id": historical_root.node_id,
                    "statement_ids": [
                        str(item)
                        for item in next(
                            entry.statement_ids
                            for entry in historical["projection"].provenance
                            if entry.node_id == historical_root.node_id
                        )
                    ],
                },
            ],
            lifecycle=RelationLifecycle.PROPOSED,
            created_at=datetime.now(UTC),
        )

        first = render_evidence_card(
            relation=relation,
            candidate=candidate,
            current_projection=current["projection"],
            historical_projection=historical["projection"],
        )
        # Queried from an unrelated asset so both sides come back: eligibility
        # excludes the caller's own projection, which is correct and would
        # otherwise hide one half of the pair from this comparison.
        reloaded = repository.list_eligible_projections(current_asset_id=uuid4())
        second = render_evidence_card(
            relation=relation,
            candidate=candidate,
            current_projection=next(
                item
                for item in reloaded
                if item.projection_id == current["projection"].projection_id
            ),
            historical_projection=next(
                item
                for item in reloaded
                if item.projection_id == historical["projection"].projection_id
            ),
        )

        assert isinstance(first, EvidenceCardV1) and isinstance(second, EvidenceCardV1)
        # A card that changes when its inputs merely take a round trip through
        # storage would make every hash bound to it unreproducible.
        assert second.card_hash == first.card_hash
        assert second.model_dump_json() == first.model_dump_json()
        assert self._persisted(repository, current["asset"].asset_id) == before
