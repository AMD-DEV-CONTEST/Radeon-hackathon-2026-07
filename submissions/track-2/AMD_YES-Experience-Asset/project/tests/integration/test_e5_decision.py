"""Ticket 07 — confirm and decline, fail-closed, at the repository seam.

The truth table this ticket exists for: the same decision repeated, the opposite
decision on a settled candidate, an unknown candidate, a stale card version.
Each is a way a permission could be created that the user never granted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.experience_asset.application.decision import DecisionRefused, DecisionService
from app.experience_asset.discovery_fingerprint import compute_discovery_fingerprint
from app.experience_asset.domain.enums import (
    DiscoveryOutcome,
    RelationLifecycle,
    RelationType,
)
from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    DiscoveryAttemptV1,
    RelationCandidateDecisionV1,
    RelationCandidateV1,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from tests.integration.test_e5_discovery_attempt import _activated, _fingerprint


def _pair(tmp_path, name: str):
    repository = SQLiteAssetRepository(tmp_path / name)
    repository.initialize()
    current = _activated(repository)
    historical = _activated(repository)
    return repository, current, historical


def _settled_candidate(repository, current, historical):
    """Persist one candidate through the ticket-06 envelope, as ticket 05 does."""
    asset, readiness, projection = current
    _, _, historical_projection = historical
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)
    reservation = DiscoveryAttemptV1(
        attempt_id=uuid4(),
        run_id=uuid4(),
        asset_id=asset.asset_id,
        discovery_fingerprint=digest,
        current_projection_id=projection.projection_id,
        eligible_set_hash="c" * 64,
        attempt_number=1,
        outcome=DiscoveryOutcome.RUNNING,
        lease_expires_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
    )
    reserved = repository.reserve_attempt(reservation, fingerprint=fingerprint)
    current_root = next(node for node in projection.nodes if node.is_root)
    historical_root = next(
        node for node in historical_projection.nodes if node.is_root
    )
    candidate = RelationCandidateV1(
        candidate_id=uuid4(),
        discovery_fingerprint=digest,
        current_asset_id=asset.asset_id,
        current_projection_id=projection.projection_id,
        related_asset_id=historical[0].asset_id,
        historical_projection_id=historical_projection.projection_id,
        relation_type=RelationType.SAME_THEME,
        title="同一主题",
        summary="两次经历处理了同一类取舍。",
        node_mappings=[
            {
                "current_node_id": current_root.node_id,
                "historical_node_id": historical_root.node_id,
            }
        ],
        current_boundary_node_ids=[projection.nodes[-1].node_id],
        historical_boundary_node_ids=[],
        provenance=[
            {
                "side": "CURRENT",
                "node_id": current_root.node_id,
                "statement_ids": [str(uuid4())],
            },
            {
                "side": "HISTORICAL",
                "node_id": historical_root.node_id,
                "statement_ids": [str(uuid4())],
            },
        ],
        lifecycle=RelationLifecycle.PROPOSED,
        created_at=datetime.now(UTC),
    )
    repository.settle_attempt(
        reserved.model_copy(
            update={
                "outcome": DiscoveryOutcome.CANDIDATE,
                "candidate_id": candidate.candidate_id,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            }
        ),
        candidate=candidate,
    )
    return candidate


def _decision(candidate, readiness, action: str) -> RelationCandidateDecisionV1:
    return RelationCandidateDecisionV1(
        decision_id=uuid4(),
        candidate_id=candidate.candidate_id,
        current_asset_id=candidate.current_asset_id,
        current_version_id=readiness.version_id,
        current_knowledge_card_hash=readiness.knowledge_card_hash,
        related_asset_id=candidate.related_asset_id,
        user_action=action,
        decided_at=datetime.now(UTC),
    )


@pytest.fixture
def world(tmp_path):
    repository, current, historical = _pair(tmp_path, "decision.sqlite3")
    candidate = _settled_candidate(repository, current, historical)
    return repository, DecisionService(repository), current, candidate


def test_confirmation_creates_the_relation_in_the_same_transaction(world):
    repository, service, (asset, readiness, _), candidate = world

    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )

    relations = repository.list_confirmed_relations(asset.asset_id)
    assert len(relations) == 1
    relation = relations[0]
    # The relation inherits the candidate's whole identity. Binding only the id
    # would let a confirmation assert a different relation between different
    # assets while still pointing at a candidate the user really saw.
    assert relation.source_candidate_id == candidate.candidate_id
    assert relation.relation_type is candidate.relation_type
    assert relation.related_asset_id == candidate.related_asset_id
    assert relation.historical_projection_id == candidate.historical_projection_id
    assert relation.current_knowledge_card_hash == readiness.knowledge_card_hash
    assert repository.read_decision(candidate.candidate_id).user_action == "CONFIRM"


def test_the_grant_is_scoped_to_the_one_asset_shown(world):
    repository, service, (asset, readiness, _), candidate = world
    other = _activated(repository)

    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )

    authorized = {item.related_asset_id for item in service.authorized_relations(asset.asset_id)}
    # They agreed this experience is worth comparing to that one; they did not
    # agree to open the archive.
    assert authorized == {candidate.related_asset_id}
    assert other[0].asset_id not in authorized


def test_declining_persists_and_leaves_no_permission(world):
    repository, service, (asset, readiness, _), candidate = world

    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "DECLINE")
    )

    # A dismissal that lived in the browser would come back on the next load,
    # and the user would conclude the decision does not stick.
    assert repository.read_decision(candidate.candidate_id).user_action == "DECLINE"
    assert repository.list_confirmed_relations(asset.asset_id) == []
    assert repository.read_candidate(candidate.candidate_id).lifecycle is (
        RelationLifecycle.DECLINED
    )


def test_repeating_a_decision_is_idempotent(world):
    repository, service, (asset, readiness, _), candidate = world
    first = service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )

    again = service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )

    assert again.decision_id == first.decision_id
    assert len(repository.list_confirmed_relations(asset.asset_id)) == 1


@pytest.mark.parametrize("first, second", [("CONFIRM", "DECLINE"), ("DECLINE", "CONFIRM")])
def test_the_opposite_decision_is_refused_not_overwritten(world, first, second):
    repository, service, (asset, readiness, _), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, first)
    )

    with pytest.raises(DecisionRefused) as caught:
        service.decide(
            asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, second)
        )

    # The trail has to record what the user actually decided and when.
    assert caught.value.reason == "ALREADY_SETTLED"
    assert repository.read_decision(candidate.candidate_id).user_action == first
    expected = 1 if first == "CONFIRM" else 0
    assert len(repository.list_confirmed_relations(asset.asset_id)) == expected


def test_an_unknown_candidate_creates_no_permission(world):
    repository, service, (asset, readiness, _), candidate = world
    unknown = candidate.model_copy(update={"candidate_id": uuid4()})

    with pytest.raises(DecisionRefused) as caught:
        service.decide(
            asset.asset_id, unknown.candidate_id, _decision(unknown, readiness, "CONFIRM")
        )

    assert caught.value.reason == "UNKNOWN_CANDIDATE"
    assert repository.list_confirmed_relations(asset.asset_id) == []


def test_a_stale_card_version_is_refused_not_resolved(world):
    repository, service, (asset, readiness, _), candidate = world
    stale = _decision(candidate, readiness, "CONFIRM").model_copy(
        update={"current_version_id": uuid4()}
    )

    with pytest.raises(DecisionRefused) as caught:
        service.decide(asset.asset_id, candidate.candidate_id, stale)

    # Looking up the current card and proceeding is the tempting behaviour; it
    # would grant access from a decision made about different content.
    assert caught.value.reason == "STALE_BINDING"
    assert repository.list_confirmed_relations(asset.asset_id) == []
    assert repository.read_decision(candidate.candidate_id) is None


def test_a_mismatched_card_hash_is_refused(world):
    repository, service, (asset, readiness, _), candidate = world
    forged = _decision(candidate, readiness, "CONFIRM").model_copy(
        update={"current_knowledge_card_hash": "0" * 64}
    )

    with pytest.raises(DecisionRefused) as caught:
        service.decide(asset.asset_id, candidate.candidate_id, forged)

    assert caught.value.reason == "STALE_BINDING"
    assert repository.list_confirmed_relations(asset.asset_id) == []


def test_a_decision_naming_another_related_asset_is_refused(world):
    repository, service, (asset, readiness, _), candidate = world
    spliced = _decision(candidate, readiness, "CONFIRM").model_copy(
        update={"related_asset_id": uuid4()}
    )

    with pytest.raises(DecisionRefused) as caught:
        service.decide(asset.asset_id, candidate.candidate_id, spliced)

    assert caught.value.reason == "BINDING_MISMATCH"
    assert repository.list_confirmed_relations(asset.asset_id) == []


def test_authorization_re_reads_rather_than_caching(world):
    repository, service, (asset, readiness, _), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )
    assert len(service.authorized_relations(asset.asset_id)) == 1

    import sqlite3

    connection = sqlite3.connect(repository.database_path)
    connection.execute(
        """UPDATE confirmed_asset_relations
        SET lifecycle='INVALIDATED', invalidated_at=?, invalidation_reason='test'
        WHERE current_asset_id=?""",
        (datetime.now(UTC).isoformat(), str(asset.asset_id)),
    )
    connection.commit()
    connection.close()

    # A value cached in run state would keep a long-running session using a
    # relation that has since been invalidated.
    assert service.authorized_relations(asset.asset_id) == []


def test_decisions_are_append_only(world):
    repository, service, (asset, readiness, _), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )

    import sqlite3

    connection = sqlite3.connect(repository.database_path)
    total = connection.execute(
        "SELECT count(*) FROM relation_candidate_decisions"
    ).fetchone()[0]
    connection.close()

    with pytest.raises(DecisionRefused):
        service.decide(
            asset.asset_id,
            candidate.candidate_id,
            _decision(candidate, readiness, "DECLINE"),
        )

    connection = sqlite3.connect(repository.database_path)
    after = connection.execute(
        "SELECT count(*) FROM relation_candidate_decisions"
    ).fetchone()[0]
    connection.close()
    # Later invalidation removes access rather than erasing the event.
    assert after == total == 1


def test_the_evidence_card_renders_from_a_genuinely_confirmed_relation(world):
    """Ticket 08's fixture debt: the card was only ever built from a fixture.

    Its own completion note says INTEGRATION_READY waits until 07 lands and the
    card is rendered from a real confirmation. This is that render — the
    relation, the candidate and both projections all came through the product
    path rather than from `contracts/examples`.
    """
    from app.experience_asset.application.relation_evidence import (
        EvidenceCardV1,
        render_evidence_card,
        resolve_bounded_detail,
    )

    repository, service, (asset, readiness, projection), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    historical = next(
        item
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
        if item.projection_id == candidate.historical_projection_id
    )

    card = render_evidence_card(
        relation=relation,
        candidate=repository.read_candidate(candidate.candidate_id),
        current_projection=projection,
        historical_projection=historical,
    )

    assert isinstance(card, EvidenceCardV1), card
    assert card.relation_id == relation.relation_id
    assert card.current_knowledge_card_hash == readiness.knowledge_card_hash
    assert {entry.side for entry in card.provenance} == {"CURRENT", "HISTORICAL"}
    assert card.mapped_roles and card.boundaries
    # The bounded read is what the card is allowed to quote, and it resolves
    # against the same stored projections the relation names.
    detail = resolve_bounded_detail(
        historical, tuple(item.historical_node_id for item in card.mapped_roles)
    )
    assert detail.statement_ids


def test_a_declined_relation_never_produces_an_evidence_card(world):
    from app.experience_asset.application.relation_evidence import (
        EvidenceCardRefusal,
        render_evidence_card,
    )

    repository, service, (asset, readiness, projection), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "DECLINE")
    )

    assert repository.list_confirmed_relations(asset.asset_id) == []
    # GRAG-10 from the other side: with no confirmation there is no relation to
    # render, so the detail the gate defers is never even addressable.
    historical = next(
        item
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
        if item.projection_id == candidate.historical_projection_id
    )
    stale_relation = ConfirmedAssetRelationV1(
        relation_id=uuid4(),
        source_candidate_id=candidate.candidate_id,
        relation_type=candidate.relation_type,
        current_asset_id=candidate.current_asset_id,
        current_version_id=readiness.version_id,
        current_projection_id=candidate.current_projection_id,
        current_knowledge_card_hash=readiness.knowledge_card_hash,
        related_asset_id=candidate.related_asset_id,
        related_version_id=uuid4(),
        historical_projection_id=candidate.historical_projection_id,
        lifecycle=RelationLifecycle.INVALIDATED,
        confirmed_at=datetime.now(UTC),
        invalidated_at=datetime.now(UTC),
        invalidation_reason="declined",
    )
    result = render_evidence_card(
        relation=stale_relation,
        candidate=repository.read_candidate(candidate.candidate_id),
        current_projection=projection,
        historical_projection=historical,
    )
    assert isinstance(result, EvidenceCardRefusal)


def _advance_asset_version(repository, asset_id) -> str:
    """Move the asset one version forward, as a post-confirmation edit would."""
    import sqlite3

    connection = sqlite3.connect(repository.database_path)
    connection.row_factory = sqlite3.Row
    try:
        current = connection.execute(
            "SELECT v.* FROM assets a JOIN asset_versions v "
            "ON v.version_id=a.current_version_id WHERE a.asset_id=?",
            (str(asset_id),),
        ).fetchone()
        new_version = str(uuid4())
        connection.execute(
            """INSERT INTO asset_versions(
                version_id, asset_id, parent_version_id, schema_version,
                change_kind, change_reason, created_at, content_json, content_hash
            ) VALUES (?, ?, ?, ?, 'PROBE', 'edited after confirming', ?, ?, ?)""",
            (
                new_version,
                str(asset_id),
                current["version_id"],
                current["schema_version"],
                datetime.now(UTC).isoformat(),
                current["content_json"],
                "9" * 64,
            ),
        )
        connection.execute(
            "UPDATE assets SET current_version_id=? WHERE asset_id=?",
            (new_version, str(asset_id)),
        )
        connection.commit()
        return new_version
    finally:
        connection.close()


def test_readiness_stops_answering_once_the_asset_moves_past_it(world):
    """The positive half: readiness is bound to the version it was accepted on."""
    repository, service, (asset, readiness, _), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )
    assert repository.read_active_readiness(asset.asset_id) is not None

    _advance_asset_version(repository, asset.asset_id)

    # Fail-closed by construction: a record left active over a superseded
    # version would keep answering "ready" for content the user has replaced.
    assert repository.read_active_readiness(asset.asset_id) is None


def test_a_confirmed_relation_does_not_outlive_the_card_it_was_confirmed_against(world):
    """The permission surface shrinks with its binding. Closed by ticket 09.

    This test previously asserted the opposite, as the reproduction of a gap
    documented in the E6 handoff: a confirmation stayed listed after the asset
    moved to a new version, while readiness had already withdrawn, so the two
    disagreed about whether the card was usable. A consumer reading only the
    relation list would have authorized history against a card the user had
    since changed.

    The fix is in the read, not in a caller: authorization re-projects from the
    repository at every policy evaluation, so a binding checked anywhere else
    can be bypassed by the next caller that forgets to check it.
    """
    repository, service, (asset, readiness, _), candidate = world
    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )
    relation = repository.list_confirmed_relations(asset.asset_id)[0]

    new_version = _advance_asset_version(repository, asset.asset_id)

    assert repository.list_confirmed_relations(asset.asset_id) == []
    assert repository.read_confirmed_relation(relation.relation_id) is None
    # Readiness and relations now agree, which is the property that was missing.
    assert repository.read_active_readiness(asset.asset_id) is None
    # The row is still there, still naming the version it was confirmed against.
    # Revoking access must not erase the fact that the user confirmed it, or an
    # invalidated relation becomes indistinguishable from one that never was.
    archived = repository.read_relation_record(relation.relation_id)
    assert str(archived.current_version_id) == str(relation.current_version_id)
    assert archived.current_knowledge_card_hash == relation.current_knowledge_card_hash
    assert str(archived.current_version_id) != new_version


def test_a_decline_leaves_the_asset_free_to_continue(world):
    """GRAG-18, the half E5 can prove: comparison is optional, not a gate.

    The behaviour states that after a no-match or a decline, M5 route evaluation
    remains available. M5 has no surface in E5 — it is E6's milestone — so what
    is checkable here is that E5 leaves nothing locked: the card stays ready,
    the asset stays active, and its milestone states are untouched. If a refused
    comparison moved any of those, an optional assisting step would have become
    a mandatory checkpoint, and the user would be stuck because they said no.
    """
    repository, service, (asset, readiness, _), candidate = world
    before = repository.get_current(asset.asset_id)

    service.decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "DECLINE")
    )

    after = repository.get_current(asset.asset_id)
    assert after.version_id == before.version_id
    assert after.lifecycle is before.lifecycle
    assert after.milestone_states == before.milestone_states
    # The card the user accepted is still the ready one: declining a comparison
    # is not a statement about the card.
    still_ready = repository.read_active_readiness(asset.asset_id)
    assert still_ready is not None
    assert still_ready.knowledge_card_hash == readiness.knowledge_card_hash
