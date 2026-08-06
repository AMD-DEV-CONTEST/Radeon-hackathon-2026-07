"""Ticket 06 — fingerprint idempotency, reservation, retry and recovery.

These read rows the test did not write in the same call: every assertion goes
back through the repository, because the defect class this ticket exists to
prevent is a cache that looks correct in memory and is wrong on disk.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.experience_asset.discovery_fingerprint import (
    FINGERPRINT_SCHEMA_VERSION,
    FINGERPRINT_UNICODE_FORM,
    MAX_DISCOVERY_ATTEMPTS,
    RETRYABLE_FAILURE_CLASSES,
    canonical_fingerprint_payload,
    compute_discovery_fingerprint,
    is_retryable,
    retry_backoff_seconds,
)
from app.experience_asset.domain.enums import (
    DiscoveryFailureClass,
    DiscoveryOutcome,
    RelationLifecycle,
    RelationType,
)
from app.experience_asset.domain.relation import (
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    RelationCandidateV1,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.persistence.relation_ledger import (
    LedgerConflictError,
    ReservationHeldError,
)
from app.experience_asset.role_graph import build_role_graph_projection
from tests.integration.test_e5_role_graph_projection import (
    NOW,
    _persist_ready_inputs,
    _ready_asset,
)


def _activated(repository: SQLiteAssetRepository):
    asset, artifact, readiness = _ready_asset()
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset, m4_artifact=artifact, readiness=readiness, created_at=NOW
    )
    repository.activate_projection(projection)
    return asset, readiness, projection


def _fingerprint(asset, readiness, projection, **overrides) -> DiscoveryFingerprintV1:
    fields = {
        "current_asset_id": asset.asset_id,
        "current_version_id": asset.version_id,
        "current_knowledge_card_hash": readiness.knowledge_card_hash,
        "current_projection_hash": projection.projection_hash,
        "eligible_projection_hashes": [projection.projection_hash],
        "model_identity": "qwen3-30b-a3b",
        "model_revision": "2026-07-01",
        "prompt_version": "e5-discovery-prompt/v1",
        "role_contract_version": "e5-role/v1",
        "validation_contract_version": "e5-relation/v1",
        "discovery_intent_version": "e5-intent/v1",
        "inference_parameters_hash": "b" * 64,
        "prefilter_config_version": "e5-prefilter/v1",
    }
    fields.update(overrides)
    return DiscoveryFingerprintV1(**fields)


def _reservation(asset, projection, fingerprint) -> DiscoveryAttemptV1:
    return DiscoveryAttemptV1(
        attempt_id=uuid4(),
        run_id=uuid4(),
        asset_id=asset.asset_id,
        discovery_fingerprint=compute_discovery_fingerprint(fingerprint),
        current_projection_id=projection.projection_id,
        eligible_set_hash="c" * 64,
        attempt_number=1,
        outcome=DiscoveryOutcome.RUNNING,
        lease_expires_at=NOW + timedelta(seconds=120),
        started_at=NOW,
    )


def _settle(attempt: DiscoveryAttemptV1, outcome: DiscoveryOutcome, **overrides):
    fields = {
        "outcome": outcome,
        "lease_expires_at": None,
        "finished_at": datetime.now(UTC),
        "elapsed_ms": 12,
    }
    fields.update(overrides)
    return attempt.model_copy(update=fields)


# -- canonicalization (AC-1, AC-2) ---------------------------------------


def test_canonicalization_is_specified_and_stable() -> None:
    fingerprint = DiscoveryFingerprintV1(
        current_asset_id=UUID("11111111-1111-4111-8111-111111111111"),
        current_version_id=UUID("22222222-2222-4222-8222-222222222222"),
        current_knowledge_card_hash="a" * 64,
        current_projection_hash="b" * 64,
        eligible_projection_hashes=["c" * 64, "d" * 64],
        model_identity="qwen3-30b-a3b",
        model_revision="2026-07-01",
        prompt_version="e5-discovery-prompt/v1",
        role_contract_version="e5-role/v1",
        validation_contract_version="e5-relation/v1",
        discovery_intent_version="e5-intent/v1",
        inference_parameters_hash="e" * 64,
        prefilter_config_version="e5-prefilter/v1",
    )
    payload = canonical_fingerprint_payload(fingerprint)

    assert FINGERPRINT_SCHEMA_VERSION == "e5-fingerprint/v1"
    assert FINGERPRINT_UNICODE_FORM == "NFC"
    # Keys sorted and no insignificant whitespace, so field order in the model
    # definition cannot move the digest.
    keys = list(json.loads(payload).keys())
    assert keys == sorted(keys)
    assert ", " not in payload and '": ' not in payload
    # UUIDs lowercase hyphenated, one rendering only.
    assert "11111111-1111-4111-8111-111111111111" in payload
    assert compute_discovery_fingerprint(fingerprint) == compute_discovery_fingerprint(
        fingerprint.model_copy()
    )
    assert len(compute_discovery_fingerprint(fingerprint)) == 64


@pytest.mark.parametrize(
    "field, value",
    [
        ("current_knowledge_card_hash", "9" * 64),
        ("current_projection_hash", "8" * 64),
        ("model_identity", "qwen3-32b"),
        ("model_revision", "2026-08-01"),
        ("prompt_version", "e5-discovery-prompt/v2"),
        ("validation_contract_version", "e5-relation/v2"),
        ("inference_parameters_hash", "7" * 64),
        ("prefilter_config_version", "e5-prefilter/v2"),
    ],
)
def test_every_covered_input_moves_the_fingerprint(tmp_path, field, value) -> None:
    """AC-6: a changed card, projection, model, prompt or config is a new question."""
    repository = SQLiteAssetRepository(tmp_path / "fp.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    base = _fingerprint(asset, readiness, projection)

    changed = _fingerprint(asset, readiness, projection, **{field: value})

    assert compute_discovery_fingerprint(changed) != compute_discovery_fingerprint(base)


def test_a_newly_eligible_historical_asset_moves_the_fingerprint(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "corpus.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    base = _fingerprint(asset, readiness, projection)

    widened = _fingerprint(
        asset,
        readiness,
        projection,
        eligible_projection_hashes=sorted([projection.projection_hash, "f" * 64]),
    )

    assert compute_discovery_fingerprint(widened) != compute_discovery_fingerprint(base)


# -- idempotency (AC-3) --------------------------------------------------


def test_the_same_fingerprint_serves_one_cached_answer(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "cache.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)

    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    repository.settle_attempt(_settle(reserved, DiscoveryOutcome.NO_MATCH))

    cached = repository.read_settled_result(digest)
    assert cached is not None
    assert cached.outcome is DiscoveryOutcome.NO_MATCH
    assert cached.attempt_id == reserved.attempt_id

    # Reserving again for an unchanged question would spend a model call
    # re-deciding what the ledger already answered.
    with pytest.raises(LedgerConflictError):
        repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )
    assert len(repository.list_attempts(digest)) == 1


def test_fingerprint_inputs_are_recoverable_for_audit(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "audit.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)

    repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )

    # Without the inputs on record the digest is a number nobody can re-derive,
    # so "the same input returns the same answer" cannot be checked.
    stored = repository.read_fingerprint_inputs(digest)
    assert stored == fingerprint
    assert compute_discovery_fingerprint(stored) == digest


# -- technical failures (AC-4, AC-5) -------------------------------------


def test_a_technical_failure_is_retained_but_never_served_as_no_match(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "failure.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)

    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    repository.settle_attempt(
        _settle(
            reserved,
            DiscoveryOutcome.TECHNICAL_FAILURE,
            failure_class=DiscoveryFailureClass.MODEL_UNAVAILABLE,
        )
    )

    # Retained for audit...
    attempts = repository.list_attempts(digest)
    assert [item.outcome for item in attempts] == [DiscoveryOutcome.TECHNICAL_FAILURE]
    assert attempts[0].failure_class is DiscoveryFailureClass.MODEL_UNAVAILABLE
    # ...but a five-minute outage must not permanently erase a relation.
    assert repository.read_settled_result(digest) is None

    retried = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    assert retried.attempt_number == 2


def test_a_deterministic_rejection_is_not_retried(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "deterministic.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)

    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    repository.settle_attempt(
        _settle(
            reserved,
            DiscoveryOutcome.TECHNICAL_FAILURE,
            failure_class=DiscoveryFailureClass.RUNTIME_VALIDATION_REJECTED,
        )
    )

    # The same inputs failed a deterministic check; retrying would hammer local
    # inference with a request that cannot succeed.
    assert is_retryable(DiscoveryFailureClass.RUNTIME_VALIDATION_REJECTED) is False
    assert DiscoveryFailureClass.STALE_BINDING not in RETRYABLE_FAILURE_CLASSES
    with pytest.raises(LedgerConflictError, match="deterministic"):
        repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )


def test_the_retry_budget_is_bounded_and_terminates(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "budget.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)

    for expected in range(1, MAX_DISCOVERY_ATTEMPTS + 1):
        reserved = repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )
        assert reserved.attempt_number == expected
        repository.settle_attempt(
            _settle(
                reserved,
                DiscoveryOutcome.TECHNICAL_FAILURE,
                failure_class=DiscoveryFailureClass.MODEL_TIMED_OUT,
            )
        )

    with pytest.raises(LedgerConflictError, match="budget"):
        repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )
    assert retry_backoff_seconds(1) == 0.0
    assert retry_backoff_seconds(3) > retry_backoff_seconds(2) > 0


# -- reservation and recovery (AC-7, AC-8) -------------------------------


def test_a_second_click_joins_the_running_reservation(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "concurrent.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)

    repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )

    # Without the reservation, two simultaneous clicks make two model calls and
    # two candidate rows for one logical question, and whichever commits last
    # silently becomes the answer.
    with pytest.raises(ReservationHeldError):
        repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )
    assert len(repository.list_attempts(digest)) == 1


def test_a_crash_mid_flight_is_recovered_as_retryable_never_successful(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "crash.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)

    repository.reserve_attempt(
        _reservation(asset, projection, fingerprint),
        fingerprint=fingerprint,
        lease_seconds=0,
    )

    assert repository.recover_expired_reservations() == 1
    recovered = repository.list_attempts(digest)[0]
    # Assuming success would publish a candidate nobody validated.
    assert recovered.outcome is DiscoveryOutcome.TECHNICAL_FAILURE
    # Named for what happened rather than for the nearest available class. This
    # recorded MODEL_TIMED_OUT until ticket 01 added LEASE_EXPIRED, which
    # asserted the model was asked and did not answer — nothing here knows that,
    # and it sends an investigator to the inference server when the fault is in
    # process lifecycle. Criterion 8 was blocked on the class not existing.
    assert recovered.failure_class is DiscoveryFailureClass.LEASE_EXPIRED
    assert is_retryable(recovered.failure_class) is True
    assert recovered.lease_expires_at is None
    assert recovered.finished_at is not None
    assert repository.read_settled_result(digest) is None

    reopened = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    assert reopened.attempt_number == 2
    assert repository.recover_expired_reservations() == 0


def test_an_unrecovered_expired_reservation_blocks_a_fresh_one(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "unrecovered.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)

    repository.reserve_attempt(
        _reservation(asset, projection, fingerprint),
        fingerprint=fingerprint,
        lease_seconds=0,
    )

    # Reserving over an open reservation would leave two rows claiming to be in
    # flight for one fingerprint, and recovery could no longer tell which.
    with pytest.raises(LedgerConflictError, match="expired reservation"):
        repository.reserve_attempt(
            _reservation(asset, projection, fingerprint), fingerprint=fingerprint
        )


# -- settlement invariants and observability (AC-10) ---------------------


def test_a_candidate_and_its_attempt_commit_together(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "candidate.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    historical_asset, _, historical_projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)
    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    candidate_id = uuid4()
    current_root = next(node for node in projection.nodes if node.is_root)
    historical_root = next(
        node for node in historical_projection.nodes if node.is_root
    )
    candidate = RelationCandidateV1(
        candidate_id=candidate_id,
        discovery_fingerprint=digest,
        current_asset_id=asset.asset_id,
        current_projection_id=projection.projection_id,
        related_asset_id=historical_asset.asset_id,
        historical_projection_id=historical_projection.projection_id,
        relation_type=RelationType.SAME_THEME,
        title="同一主题",
        summary="两次经历都处理了同一类取舍。",
        # SAME_THEME claims a root-to-root correspondence, so both roles are
        # absent; pairing a root with a member would describe a correspondence
        # between things of different kinds.
        node_mappings=[
            {
                "current_node_id": current_root.node_id,
                "historical_node_id": historical_root.node_id,
            }
        ],
        current_boundary_node_ids=[projection.nodes[-1].node_id],
        historical_boundary_node_ids=[historical_projection.nodes[-1].node_id],
        provenance=[
            {"side": "CURRENT", "node_id": current_root.node_id,
             "statement_ids": [str(uuid4())]},
            {"side": "HISTORICAL", "node_id": historical_root.node_id,
             "statement_ids": [str(uuid4())]},
        ],
        lifecycle=RelationLifecycle.PROPOSED,
        created_at=datetime.now(UTC),
    )

    repository.settle_attempt(
        _settle(reserved, DiscoveryOutcome.CANDIDATE, candidate_id=candidate_id),
        candidate=candidate,
    )

    cached = repository.read_settled_result(digest)
    assert cached is not None and cached.candidate_id == candidate_id


def test_settlement_refuses_a_mismatched_or_missing_candidate(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "mismatch.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )

    # A CANDIDATE outcome with no candidate would leave the attempt pointing at
    # a row that does not exist.
    with pytest.raises(LedgerConflictError):
        repository.settle_attempt(
            _settle(reserved, DiscoveryOutcome.CANDIDATE, candidate_id=uuid4())
        )
    assert repository.list_attempts(reserved.discovery_fingerprint)[0].outcome is (
        DiscoveryOutcome.RUNNING
    )


def test_observability_records_identity_and_timing_without_bodies(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "observability.sqlite3")
    repository.initialize()
    asset, readiness, projection = _activated(repository)
    fingerprint = _fingerprint(asset, readiness, projection)
    digest = compute_discovery_fingerprint(fingerprint)
    reserved = repository.reserve_attempt(
        _reservation(asset, projection, fingerprint), fingerprint=fingerprint
    )
    repository.settle_attempt(_settle(reserved, DiscoveryOutcome.NO_MATCH))

    attempt = repository.list_attempts(digest)[0]
    assert attempt.discovery_fingerprint == digest
    assert attempt.current_projection_id == projection.projection_id
    assert attempt.attempt_number == 1
    assert attempt.elapsed_ms is not None and attempt.elapsed_ms >= 0
    inputs = repository.read_fingerprint_inputs(digest)
    assert inputs is not None
    assert inputs.model_identity and inputs.prompt_version
    assert inputs.validation_contract_version and inputs.prefilter_config_version

    # Prompt and response bodies would be a second store of exactly the private
    # content the local-inference boundary exists to contain.
    columns = set(DiscoveryAttemptV1.model_fields) | set(DiscoveryFingerprintV1.model_fields)
    assert not {name for name in columns if "prompt_body" in name or "response" in name}
