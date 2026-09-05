"""Ticket 09 — invalidation, staleness, and restart resume.

The ticket's own instruction is to write the mutation-by-artifact matrix first,
because without it every event becomes a fresh judgement about which of eight
artifacts to touch and the ones nobody thought of stay live. These tests read
the matrix as data and drive each event through it, so an artifact added to the
matrix without an implementation fails here rather than silently staying
reachable.

Revocation is asserted at the repository seam, never only at the interface: a
UI that hides a stale relation leaves the permission intact underneath, where a
replayed request or another tab still reaches the detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.experience_asset.application.decision import DecisionService
from app.experience_asset.application.invalidation import (
    INVALIDATION_MATRIX,
    Artifact,
    InvalidationService,
    MutationEvent,
)
from app.experience_asset.application.relation_evidence import (
    EvidenceCardV1,
    read_evidence_card_traced,
)
from app.experience_asset.discovery_fingerprint import compute_discovery_fingerprint
from app.experience_asset.domain.enums import (
    DiscoveryOutcome,
    ProjectionLifecycle,
    ReadinessLifecycle,
    RelationLifecycle,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from tests.integration.test_e5_decision import (
    _decision,
    _pair,
    _settled_candidate,
)
from tests.integration.test_e5_discovery_attempt import _fingerprint


def _confirmed(repository, current, historical):
    """A confirmed relation, which is the state with something to revoke."""
    candidate = _settled_candidate(repository, current, historical)
    asset, readiness, _ = current
    DecisionService(repository).decide(
        asset.asset_id,
        candidate.candidate_id,
        _decision(candidate, readiness, "CONFIRM"),
    )
    return candidate


def _card(repository, relation_id, candidate, current):
    """Read a card the way the product does: authorize from durable state.

    The relation is re-read rather than passed in from before the mutation.
    Handing the gate a relation object captured earlier would test the gate
    against a permission that no longer exists in the database, which is the
    one thing this ticket is about.
    """
    relation = repository.read_confirmed_relation(relation_id)
    if relation is None:
        return None
    _, _, projection = current
    return read_evidence_card_traced(
        repository,
        relation=relation,
        candidate=repository.read_candidate(candidate.candidate_id),
        current_projection=projection,
        # Read regardless of lifecycle: a retired projection must not turn the
        # authorization question into a lookup failure.
        historical_projection=repository.read_projection(
            candidate.historical_projection_id
        ),
    )


# -- the matrix itself (AC-1) --------------------------------------------


def test_the_matrix_covers_every_event_against_every_artifact():
    """A gap in the matrix is an artifact that stays live after a mutation.

    The failure this guards is not a wrong state but a missing row: an event
    that never considered `detail permission` leaves a granted permission in
    place, and nothing in the product reports it.
    """
    for event in MutationEvent:
        outcomes = INVALIDATION_MATRIX[event]
        missing = set(Artifact) - set(outcomes)
        assert not missing, f"{event.value} does not say what happens to {missing}"


def test_the_matrix_names_the_events_the_boundary_record_lists():
    """The six events BOUNDARIES.md §2 fixed, none dropped in transcription."""
    assert {event.value for event in MutationEvent} == {
        "CURRENT_ASSET_CORRECTION",
        "RELATED_ASSET_CHANGE",
        "ASSET_DELETION",
        "PRIVACY_NARROWING",
        "PROJECTION_SCHEMA_CHANGE",
        "MODEL_OR_PROMPT_CHANGE",
    }


# -- current-asset correction (AC-2) -------------------------------------


def test_correcting_the_current_asset_revokes_everything_built_on_it(tmp_path):
    repository, current, historical = _pair(tmp_path, "correct.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, readiness, projection = current
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    assert isinstance(_card(repository, relation.relation_id, candidate, current), EvidenceCardV1)

    InvalidationService(repository).apply(
        MutationEvent.CURRENT_ASSET_CORRECTION,
        asset_id=asset.asset_id,
        reason="the user corrected the brief",
    )

    assert repository.read_active_readiness(asset.asset_id) is None
    assert repository.read_projection(projection.projection_id).lifecycle is (
        ProjectionLifecycle.INVALIDATED
    )
    assert repository.read_candidate(candidate.candidate_id).lifecycle is (
        RelationLifecycle.INVALIDATED
    )
    # The permission is gone at the repository, not merely hidden above it.
    assert repository.read_confirmed_relation(relation.relation_id) is None
    assert _card(repository, relation.relation_id, candidate, current) is None
    # The row survives for audit even though the access is gone.
    assert repository.read_relation_record(relation.relation_id).lifecycle is (
        RelationLifecycle.INVALIDATED
    )


def test_a_corrected_asset_is_no_longer_offered_to_anyone_elses_discovery(tmp_path):
    repository, current, historical = _pair(tmp_path, "offer.sqlite3")
    asset, _, _ = current
    assert any(
        item.asset_id == asset.asset_id
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
    )

    InvalidationService(repository).apply(
        MutationEvent.CURRENT_ASSET_CORRECTION,
        asset_id=asset.asset_id,
        reason="corrected",
    )

    assert not any(
        item.asset_id == asset.asset_id
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
    )


# -- related-asset change, GRAG-16 (AC-3) --------------------------------


def test_changing_the_related_asset_leaves_the_current_one_ready_but_stale(tmp_path):
    """GRAG-16: the current asset did not change, so its readiness must not move.

    Invalidating the current card here would be the easy over-reach: it would
    make the test above pass for the wrong reason and force the user to redo
    work on an asset nobody touched.
    """
    repository, current, historical = _pair(tmp_path, "related.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, _, _ = current
    related_asset, _, related_projection = historical
    relation = repository.list_confirmed_relations(asset.asset_id)[0]

    InvalidationService(repository).apply(
        MutationEvent.RELATED_ASSET_CHANGE,
        asset_id=related_asset.asset_id,
        reason="the related asset was corrected",
    )

    readiness = repository.read_active_readiness(asset.asset_id)
    assert readiness is not None and readiness.lifecycle is ReadinessLifecycle.ACTIVE
    assert repository.read_projection(related_projection.projection_id).lifecycle is (
        ProjectionLifecycle.INVALIDATED
    )
    # Stale, not invalidated: the comparison rested on content that changed, and
    # the user has to choose to look again rather than be handed a new answer.
    assert repository.read_candidate(candidate.candidate_id).lifecycle is (
        RelationLifecycle.STALE
    )
    assert repository.read_confirmed_relation(relation.relation_id) is None


def test_a_stale_relation_requires_a_new_discovery_rather_than_refreshing_itself(
    tmp_path,
):
    """Staleness is a visible state, not a silent refresh.

    Re-running discovery automatically would replace an answer the user has
    already reasoned about, at a moment they did not choose, with no signal that
    it changed.
    """
    repository, current, historical = _pair(tmp_path, "norefresh.sqlite3")
    candidate = _confirmed(repository, current, historical)
    related_asset, _, _ = historical

    InvalidationService(repository).apply(
        MutationEvent.RELATED_ASSET_CHANGE,
        asset_id=related_asset.asset_id,
        reason="changed",
    )

    stale = repository.read_candidate(candidate.candidate_id)
    assert stale.lifecycle is RelationLifecycle.STALE
    # No replacement was produced on its own: the latest attempt is still the
    # one the user asked for, not a refresh the system decided to run.
    assert repository.read_latest_attempt(current[0].asset_id).discovery_fingerprint == (
        candidate.discovery_fingerprint
    )


# -- deletion and privacy narrowing (AC-4) -------------------------------


@pytest.mark.parametrize(
    "event",
    [MutationEvent.ASSET_DELETION, MutationEvent.PRIVACY_NARROWING],
)
def test_deletion_and_privacy_narrowing_revoke_detail_access_immediately(
    tmp_path, event
):
    repository, current, historical = _pair(tmp_path, f"{event.value}.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, _, _ = current
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    related_asset, _, _ = historical

    InvalidationService(repository).apply(
        event, asset_id=related_asset.asset_id, reason="the user narrowed the scope"
    )

    assert repository.read_confirmed_relation(relation.relation_id) is None
    assert _card(repository, relation.relation_id, candidate, current) is None
    assert not repository.list_eligible_projections(current_asset_id=asset.asset_id)


def test_the_audit_trail_keeps_identifiers_and_hashes_but_not_deleted_content(
    tmp_path,
):
    """Retaining the content inside the audit trail would recreate, there, the
    exact copy the deletion was meant to remove."""
    repository, current, historical = _pair(tmp_path, "deleted-content.sqlite3")
    candidate = _confirmed(repository, current, historical)
    related_asset, _, related_projection = historical
    summary = candidate.summary

    InvalidationService(repository).apply(
        MutationEvent.ASSET_DELETION,
        asset_id=related_asset.asset_id,
        reason="the user deleted the asset",
    )

    invalidated = repository.read_candidate(candidate.candidate_id)
    assert invalidated.candidate_id == candidate.candidate_id
    assert invalidated.related_asset_id == related_asset.asset_id
    assert invalidated.historical_projection_id == related_projection.projection_id
    assert summary not in (invalidated.summary or "")
    assert summary not in (invalidated.title or "")


# -- projection schema change (AC-5) -------------------------------------


def test_a_projection_schema_change_retires_old_projections_from_discovery(tmp_path):
    """Old projections stay readable for audit and stop being comparable.

    A mapping validated under one role contract has no defined meaning under
    another, so mixing both in one discovery call produces a candidate whose
    explanation is not true of either contract.
    """
    repository, current, historical = _pair(tmp_path, "schema.sqlite3")
    asset, _, projection = current

    InvalidationService(repository).apply(
        MutationEvent.PROJECTION_SCHEMA_CHANGE,
        asset_id=asset.asset_id,
        reason="role contract moved to e5-role/v2",
    )

    retired = repository.read_projection(projection.projection_id)
    assert retired.lifecycle is ProjectionLifecycle.INVALIDATED
    assert retired.projection_hash == projection.projection_hash
    assert not any(
        item.projection_id == projection.projection_id
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
    )


# -- audit survives invalidation (AC-7) ----------------------------------


def test_decisions_and_attempts_remain_readable_after_invalidation(tmp_path):
    """Deleting them would make an invalidated relation indistinguishable from
    one that never existed."""
    repository, current, historical = _pair(tmp_path, "audit.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, _, _ = current
    attempts_before = repository.list_attempts(candidate.discovery_fingerprint)
    decision_before = repository.read_decision(candidate.candidate_id)
    assert attempts_before and decision_before is not None

    InvalidationService(repository).apply(
        MutationEvent.CURRENT_ASSET_CORRECTION,
        asset_id=asset.asset_id,
        reason="corrected",
    )

    assert repository.list_attempts(candidate.discovery_fingerprint) == attempts_before
    assert repository.read_decision(candidate.candidate_id) == decision_before


# -- restart, GRAG-15 (AC-8) ---------------------------------------------


def test_restart_restores_candidate_decision_and_permission(tmp_path):
    database = tmp_path / "restart.sqlite3"
    repository, current, historical = _pair(tmp_path, "restart.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, _, _ = current
    relation = repository.list_confirmed_relations(asset.asset_id)[0]

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()

    assert restarted.read_candidate(candidate.candidate_id) == repository.read_candidate(
        candidate.candidate_id
    )
    assert restarted.read_confirmed_relation(relation.relation_id) == relation
    assert restarted.read_decision(candidate.candidate_id) == repository.read_decision(
        candidate.candidate_id
    )
    assert restarted.read_active_readiness(asset.asset_id) is not None


def test_restart_does_not_resurrect_access_that_was_revoked(tmp_path):
    """The paired negative: durability must restore the revocation too."""
    database = tmp_path / "revoked.sqlite3"
    repository, current, historical = _pair(tmp_path, "revoked.sqlite3")
    _confirmed(repository, current, historical)
    asset, _, _ = current
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    InvalidationService(repository).apply(
        MutationEvent.CURRENT_ASSET_CORRECTION, asset_id=asset.asset_id, reason="fixed"
    )

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()

    assert restarted.read_confirmed_relation(relation.relation_id) is None


# -- in-flight discovery across a restart (AC-9) -------------------------


def test_a_reservation_left_in_flight_is_resolved_as_retryable_not_successful(
    tmp_path,
):
    """A process that died mid-discovery reported no outcome.

    Treating it as successful publishes a candidate nobody validated; treating
    it as failed without inspecting it discards a completed model call. It has
    to be resolved explicitly.
    """
    from app.experience_asset.domain.relation import DiscoveryAttemptV1

    repository, current, _ = _pair(tmp_path, "inflight.sqlite3")
    asset, readiness, projection = current
    fingerprint = _fingerprint(asset, readiness, projection)
    expired = DiscoveryAttemptV1(
        attempt_id=uuid4(),
        run_id=uuid4(),
        asset_id=asset.asset_id,
        discovery_fingerprint=compute_discovery_fingerprint(fingerprint),
        current_projection_id=projection.projection_id,
        eligible_set_hash="c" * 64,
        attempt_number=1,
        outcome=DiscoveryOutcome.RUNNING,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        started_at=datetime.now(UTC) - timedelta(seconds=200),
    )
    # The lease is assigned by the repository, not by the caller, so an already
    # expired timestamp on the model would simply be overwritten. A zero-second
    # lease is the honest way to express "this reservation's holder is gone".
    repository.reserve_attempt(expired, fingerprint=fingerprint, lease_seconds=0)

    recovered = repository.recover_expired_reservations()

    assert recovered == 1
    settled = repository.list_attempts(compute_discovery_fingerprint(fingerprint))[-1]
    assert settled.outcome is DiscoveryOutcome.TECHNICAL_FAILURE
    assert settled.failure_class is not None
    # A technical failure is not a semantic result, so it is not reusable as one.
    assert repository.read_settled_result(settled.discovery_fingerprint) is None


def test_a_result_produced_under_a_superseded_fingerprint_is_never_reused(tmp_path):
    """The fingerprint binds the answer to the inputs that produced it.

    After the eligible set changes, the same question has a different
    fingerprint, so the earlier answer is not offered for it — reusing it would
    present a comparison against assets that were not considered.
    """
    repository, current, historical = _pair(tmp_path, "superseded.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, readiness, projection = current
    # Sorted, because the contract requires it: an unsorted list would make the
    # same logical corpus hash differently depending on read order. The fixture's
    # projection hash is random per run, so a hand-ordered literal passes or
    # fails by luck rather than by behaviour.
    superseded = _fingerprint(
        asset,
        readiness,
        projection,
        eligible_projection_hashes=sorted([projection.projection_hash, "d" * 64]),
    )

    assert compute_discovery_fingerprint(superseded) != candidate.discovery_fingerprint
    assert repository.read_settled_result(compute_discovery_fingerprint(superseded)) is None


def test_a_correction_makes_the_earlier_fingerprinted_answer_unreachable(tmp_path):
    """AC-2's last clause. The cached answer is not deleted; it stops matching.

    The fingerprint binds an answer to the version, hash and projection that
    produced it, so a corrected asset asks a different question. Serving the old
    answer would present a comparison made against content the user has replaced,
    and nothing on screen would say so.
    """
    repository, current, historical = _pair(tmp_path, "fingerprint.sqlite3")
    candidate = _confirmed(repository, current, historical)
    asset, readiness, projection = current
    assert repository.read_settled_result(candidate.discovery_fingerprint) is not None

    corrected = _fingerprint(
        asset, readiness, projection, current_version_id=uuid4()
    )

    assert compute_discovery_fingerprint(corrected) != candidate.discovery_fingerprint
    assert repository.read_settled_result(compute_discovery_fingerprint(corrected)) is None


def test_restart_restores_a_decline_and_the_terminal_discovery_state(tmp_path):
    """AC-8's other half: a refusal must survive too.

    A restart that restored only confirmations would ask the user again about
    something they already declined, and the ticket's whole premise is that the
    answer is persistent.
    """
    database = tmp_path / "decline.sqlite3"
    repository, current, historical = _pair(tmp_path, "decline.sqlite3")
    candidate = _settled_candidate(repository, current, historical)
    asset, readiness, _ = current
    DecisionService(repository).decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "DECLINE")
    )

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()

    decision = restarted.read_decision(candidate.candidate_id)
    assert decision is not None and decision.user_action == "DECLINE"
    assert restarted.read_candidate(candidate.candidate_id).lifecycle is (
        RelationLifecycle.DECLINED
    )
    # A decline creates no permission, before or after a restart.
    assert restarted.list_confirmed_relations(asset.asset_id) == []
    # And the terminal state of the search itself comes back.
    attempt = restarted.read_latest_attempt(asset.asset_id)
    assert attempt is not None and attempt.outcome is DiscoveryOutcome.CANDIDATE
