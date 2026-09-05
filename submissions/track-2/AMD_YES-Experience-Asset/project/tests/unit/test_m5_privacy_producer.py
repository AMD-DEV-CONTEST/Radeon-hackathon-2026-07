"""The producer side of the E6 privacy gap.

E1-E5 never populate `Statement.sensitivity_tags`. These tests pin the two
properties that gap closure has to hold: a real asset gets scanned by something,
and a review nothing scanned cannot present itself as clean.
"""

from __future__ import annotations

import app.experience_asset.policy.m5 as m5_policy
from app.experience_asset.application.m5 import (
    M5IsolatedService,
    PrivacyCategoryV1,
    PrivacyProposalSourceV1,
    PrivacyReviewStatusV1,
)
from app.experience_asset.domain.enums import RouteEligibility, RouteType
from app.experience_asset.policy.privacy_text_detector import (
    PRIVACY_TEXT_DETECTOR_VERSION,
    detect_text_privacy_proposals,
)
from tests.fixtures.m5 import RUN_ID, complete_context


def _with_text(context, mapping: dict[int, str]):
    """Replace statement text by index, keeping every other field identical."""

    statements = [
        statement.model_copy(update={"text": mapping[index]})
        if index in mapping
        else statement
        for index, statement in enumerate(context.statements)
    ]
    return context.model_copy(update={"statements": statements})


PRIVACY_FIXTURE_SENTENCES = {
    0: "My name is Jordan Testperson and I work at Placeholder Industries.",
    1: "I bought a chair for 742 Sample Avenue, Apt 3, under order #TEST-000123.",
}


def test_text_detector_finds_the_public_privacy_fixture_risks() -> None:
    """qa/fixtures/chair_privacy_risk.md is the content this gap exists for."""

    context = _with_text(
        complete_context(include_sensitive_tags=False), PRIVACY_FIXTURE_SENTENCES
    )

    proposals = detect_text_privacy_proposals(context.statements)

    categories = {proposal.category for proposal in proposals}
    assert PrivacyCategoryV1.IDENTITY in categories
    assert PrivacyCategoryV1.LOCATION in categories
    assert PrivacyCategoryV1.PURCHASE_PAYMENT in categories


def test_text_detector_is_deterministic_across_runs() -> None:
    context = _with_text(
        complete_context(include_sensitive_tags=False), PRIVACY_FIXTURE_SENTENCES
    )

    first = detect_text_privacy_proposals(context.statements)
    second = detect_text_privacy_proposals(context.statements)

    assert [(p.category, p.affected_statement_ids, p.severity) for p in first] == [
        (p.category, p.affected_statement_ids, p.severity) for p in second
    ]


def test_untagged_asset_still_gets_findings_and_blocks_external_share() -> None:
    """Without the text detector this asset would review as risk-free."""

    service = M5IsolatedService()
    context = _with_text(
        complete_context(include_sensitive_tags=False), PRIVACY_FIXTURE_SENTENCES
    )

    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)

    assert review.status is PrivacyReviewStatusV1.COMPLETE
    assert review.findings, "an untagged asset with private text must not review clean"
    assert PrivacyProposalSourceV1.DETERMINISTIC_TEXT_DETECTOR in review.proposal_sources
    assert review.detector_version == PRIVACY_TEXT_DETECTOR_VERSION

    matrix = service.evaluate_routes(context, privacy_review=review)
    public = next(
        decision for decision in matrix.decisions if decision.route is RouteType.PUBLIC
    )
    assert public.eligibility is not RouteEligibility.ELIGIBLE


def test_review_with_no_proposal_source_fails_closed() -> None:
    """No producer ran, so the review must not say the content is clean."""

    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)

    review = service.review_privacy(
        context, proposals=[], run_id=RUN_ID, run_text_detector=False
    )

    assert review.status is PrivacyReviewStatusV1.FAILED
    assert review.failure_code == "NO_PRIVACY_PROPOSAL_SOURCE"
    assert review.findings == []


def test_failed_source_review_blocks_every_external_route_but_keeps_private_self() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(
        context, proposals=[], run_id=RUN_ID, run_text_detector=False
    )

    matrix = service.evaluate_routes(context, privacy_review=review)

    by_route = {decision.route: decision for decision in matrix.decisions}
    assert len(by_route) == 5, "all five routes must still execute"
    external = [
        decision
        for route, decision in by_route.items()
        if route is not RouteType.PRIVATE_SELF
    ]
    assert all(
        decision.eligibility is not RouteEligibility.ELIGIBLE for decision in external
    )
    # A route already ineligible on content keeps its own truthful reason; the
    # privacy failure only has to block the routes content would have allowed.
    assert any("PRIVACY_REVIEW_FAILED" in decision.reason_codes for decision in external)


def test_clean_text_still_records_the_producer_that_ran() -> None:
    """A genuinely clean review is distinguishable from an unexamined one."""

    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)

    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)

    assert review.status is PrivacyReviewStatusV1.COMPLETE
    assert review.findings == []
    assert review.proposal_sources == [
        PrivacyProposalSourceV1.DETERMINISTIC_TEXT_DETECTOR
    ]


def test_detector_version_is_bound_into_the_review_hash() -> None:
    """Changing what scanned the content must stale any approval built on it."""

    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)

    tampered = review.model_copy(update={"detector_version": "some-other-detector"})

    # The hash field is carried over unchanged, so only recomputation catches it.
    assert tampered.review_hash == review.review_hash
    assert m5_policy._privacy_review_hash_matches(context, review)
    assert not m5_policy._privacy_review_hash_matches(context, tampered)
