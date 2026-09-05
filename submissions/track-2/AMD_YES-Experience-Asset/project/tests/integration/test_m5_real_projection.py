"""E6 against the real E5 output, not the contract-equivalent mock.

PR #31's policy tests build `M5ContextProjectionV1` by hand, with every
statement carrying `EvidenceStrength.DIRECT` and pre-populated
`sensitivity_tags`. Neither is true of anything E1-E5 actually produces, so a
green isolated suite says nothing about the integrated head. These tests drive
one asset through the real M1-M4 API, read what the repository stored, and
project that into M5.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.application.m5 import (
    M5IsolatedService,
    PrivacyProposalSourceV1,
    PrivacyReviewStatusV1,
    RelationOutcomeV1,
)
from app.experience_asset.application.m5.contracts import M5RelationProjectionV1
from app.experience_asset.application.m5.projection import (
    build_evidence_index,
    build_m5_context,
)
from app.experience_asset.domain.enums import (
    EvidenceStrength,
    RouteEligibility,
    RouteType,
)
from app.experience_asset.persistence.repository import SQLiteAssetRepository
from tests.fixtures.m5 import RUN_ID
from tests.integration.test_m4_api import ScriptedM4Client, create_m4


def _built_asset(tmp_path: Path, name: str):
    """Run the real M1-M4 path, accept the card, return what was persisted."""

    database_path = tmp_path / name
    with TestClient(
        create_app(database_path=database_path, model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        accepted = client.post(
            f"/api/v1/m4/assets/{asset_id}/accept",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": workspace["map"]["artifact_id"],
                "expected_canonical_version_id": workspace["canonical_version_id"],
                "user_action": "CONFIRM",
            },
        )
        assert accepted.status_code == 201, accepted.text

    repository = SQLiteAssetRepository(database_path)
    repository.initialize()
    from uuid import UUID

    asset = repository.get_current(UUID(asset_id))
    readiness = repository.read_active_readiness(UUID(asset_id))
    content_hash = repository.get_version_content_hash(asset.version_id)
    return asset, readiness, content_hash


def _no_match_relation(asset, content_hash: str) -> M5RelationProjectionV1:
    return M5RelationProjectionV1(
        bound_asset_id=asset.asset_id,
        bound_version_id=asset.version_id,
        bound_content_hash=content_hash,
        outcome=RelationOutcomeV1.NO_MATCH,
        projection_hash="0" * 64,
        is_current=True,
    )


def test_real_e5_output_produces_a_usable_m5_input(tmp_path: Path):
    asset, readiness, content_hash = _built_asset(tmp_path, "m5-projection.sqlite3")
    assert readiness is not None, "M4 acceptance must mint a readiness record"

    context = build_m5_context(
        asset,
        content_hash=content_hash,
        readiness=readiness,
        relation=_no_match_relation(asset, content_hash),
    )

    # The whole point of the seam: readiness binds and the input is not stale.
    assert context.stale_reason() is None
    assert context.statements, "projection must carry the canonical statements"


def test_no_real_statement_carries_direct_evidence(tmp_path: Path):
    """The audited DIRECT gap, asserted against real data rather than assumed."""

    asset, _, _ = _built_asset(tmp_path, "m5-direct.sqlite3")

    strengths = {statement.evidence_strength for statement in asset.statements}
    assert EvidenceStrength.DIRECT not in strengths


def test_all_five_routes_execute_and_customer_stays_truthfully_ineligible(
    tmp_path: Path,
):
    asset, readiness, content_hash = _built_asset(tmp_path, "m5-routes.sqlite3")
    service = M5IsolatedService()
    context = build_m5_context(
        asset,
        content_hash=content_hash,
        readiness=readiness,
        relation=_no_match_relation(asset, content_hash),
    )

    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)

    by_route = {decision.route: decision for decision in matrix.decisions}
    assert set(by_route) == {
        RouteType.PRIVATE_SELF,
        RouteType.BEGINNER,
        RouteType.PEER,
        RouteType.CUSTOMER_EVALUATOR,
        RouteType.PUBLIC,
    }

    # E1-E5 persist no professional/client role record, so manufacturing one
    # here is the failure mode. INELIGIBLE with a concrete reason is the
    # correct customer/evaluator answer, not a matrix bug to be tuned away.
    customer = by_route[RouteType.CUSTOMER_EVALUATOR]
    assert customer.eligibility is RouteEligibility.INELIGIBLE
    assert "MISSING_QUALIFYING_CONTEXT" in customer.reason_codes
    assert customer.explanation


def test_privacy_review_over_real_statements_records_its_producer(tmp_path: Path):
    """No statement carries sensitivity_tags, so the text detector must run."""

    asset, readiness, content_hash = _built_asset(tmp_path, "m5-privacy.sqlite3")
    assert not any(statement.sensitivity_tags for statement in asset.statements)

    service = M5IsolatedService()
    context = build_m5_context(
        asset,
        content_hash=content_hash,
        readiness=readiness,
        relation=_no_match_relation(asset, content_hash),
    )

    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)

    assert review.status is PrivacyReviewStatusV1.COMPLETE
    assert review.proposal_sources == [
        PrivacyProposalSourceV1.DETERMINISTIC_TEXT_DETECTOR
    ]


def test_evidence_index_never_invents_qualifying_context(tmp_path: Path):
    asset, _, _ = _built_asset(tmp_path, "m5-evidence.sqlite3")

    evidence = build_evidence_index(asset)

    assert evidence.qualifying_context == []
    assert evidence.unsupported_professional_claim == []
    # A projection that produced nothing at all would pass the assertion above
    # for the wrong reason.
    assert evidence.personal_lesson or evidence.decision_context


def test_invalidated_readiness_makes_the_m5_input_stale(tmp_path: Path):
    asset, readiness, content_hash = _built_asset(tmp_path, "m5-stale.sqlite3")
    from datetime import UTC, datetime

    from app.experience_asset.domain.enums import ReadinessLifecycle

    # E5 requires an invalidated record to say when and why, so this is the
    # shape the ledger actually stores after the user withdraws acceptance.
    withdrawn = readiness.model_copy(
        update={
            "lifecycle": ReadinessLifecycle.INVALIDATED,
            "invalidated_at": datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
            "invalidation_reason": "user corrected the card after acceptance",
        }
    )
    context = build_m5_context(
        asset,
        content_hash=content_hash,
        readiness=withdrawn,
        relation=_no_match_relation(asset, content_hash),
    )

    assert context.stale_reason() == "M5_INPUT_STALE"
