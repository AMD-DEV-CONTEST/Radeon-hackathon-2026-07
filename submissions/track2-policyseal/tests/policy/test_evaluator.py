from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from policyseal.domain.enums import (
    Action,
    Channel,
    Classification,
    ContentCategory,
    FileKind,
    OwnerRelation,
    Purpose,
    RecipientProfile,
)
from policyseal.domain.models import DisclosureContext, DocumentRegion
from policyseal.policy.conflicts import resolve_actions
from policyseal.policy.evaluator import evaluate_region
from policyseal.policy.loader import load_policy_pack
from policyseal.policy.schema import TransformKind


@pytest.fixture(scope="module")
def policy_pack():  # type: ignore[no-untyped-def]
    return load_policy_pack(Path("policies/v1"))


def _context(recipient: RecipientProfile, purpose: Purpose, channel: Channel) -> DisclosureContext:
    return DisclosureContext(
        recipient=recipient,
        organization="synthetic-recipient.example",
        recipient_id="recipient@synthetic-recipient.example",
        purpose=purpose,
        channel=channel,
        classification=Classification.CONFIDENTIAL,
        policy_version="1.0.0",
    )


def _region(category: ContentCategory) -> DocumentRegion:
    return DocumentRegion(
        id=f"region-{category.value}",
        file_kind=FileKind.XLSX,
        location="xlsx:Supplier Comparison:A1",
        order=0,
        text="synthetic value",
        category=category,
    )


def test_block_wins_every_conflict() -> None:
    result = resolve_actions([Action.KEEP, Action.MASK, Action.BLOCK])

    assert result.action is Action.BLOCK


def test_incompatible_transforms_require_approval() -> None:
    result = resolve_actions([Action.MASK, Action.GENERALIZE], provable_intersection=None)

    assert result.action is Action.REQUIRE_APPROVAL


@pytest.mark.parametrize(
    ("category", "expected_action", "expected_transform"),
    [
        (ContentCategory.GENERAL_BUSINESS, Action.KEEP, None),
        (ContentCategory.SUPPLIER_IDENTITY, Action.KEEP, None),
        (ContentCategory.CONTACT_PERSONAL, Action.FILTER, TransformKind.KEEP_NAME_WORK_EMAIL),
        (ContentCategory.BANK_PAYMENT, Action.REMOVE, None),
        (ContentCategory.QUOTE_COMMERCIAL_TERMS, Action.KEEP, None),
        (ContentCategory.INTERNAL_COST_BUDGET, Action.KEEP, None),
        (ContentCategory.SCORE_RANKING, Action.KEEP, None),
        (ContentCategory.INTERNAL_OPINION_APPROVAL, Action.KEEP, None),
    ],
)
def test_internal_procurement_matrix(
    policy_pack,  # type: ignore[no-untyped-def]
    category: ContentCategory,
    expected_action: Action,
    expected_transform: TransformKind | None,
) -> None:
    context = _context(
        RecipientProfile.INTERNAL_PROCUREMENT_LEAD,
        Purpose.PROCUREMENT_DECISION,
        Channel.COLLABORATION_PLATFORM,
    )

    decision = evaluate_region(policy_pack, context, _region(category))

    assert decision.action is expected_action
    assert decision.transform == (expected_transform.value if expected_transform else None)


@pytest.mark.parametrize(
    ("category", "expected_action", "expected_transform"),
    [
        (ContentCategory.GENERAL_BUSINESS, Action.KEEP, None),
        (ContentCategory.SUPPLIER_IDENTITY, Action.KEEP, None),
        (ContentCategory.CONTACT_PERSONAL, Action.REMOVE, None),
        (ContentCategory.BANK_PAYMENT, Action.MASK, TransformKind.MASK_LAST_FOUR),
        (
            ContentCategory.QUOTE_COMMERCIAL_TERMS,
            Action.FILTER,
            TransformKind.KEEP_AUDIT_AMOUNT,
        ),
        (ContentCategory.INTERNAL_COST_BUDGET, Action.FILTER, TransformKind.KEEP_AUDIT_AMOUNT),
        (ContentCategory.SCORE_RANKING, Action.REMOVE, None),
        (
            ContentCategory.INTERNAL_OPINION_APPROVAL,
            Action.GENERALIZE,
            TransformKind.GENERALIZE_APPROVAL_STATUS,
        ),
    ],
)
def test_external_audit_matrix(
    policy_pack,  # type: ignore[no-untyped-def]
    category: ContentCategory,
    expected_action: Action,
    expected_transform: TransformKind | None,
) -> None:
    context = _context(
        RecipientProfile.EXTERNAL_FINANCIAL_AUDITOR,
        Purpose.ANNUAL_FINANCIAL_AUDIT,
        Channel.SECURE_FILE_EXCHANGE,
    )

    decision = evaluate_region(policy_pack, context, _region(category))

    assert decision.action is expected_action
    assert decision.transform == (expected_transform.value if expected_transform else None)


@pytest.mark.parametrize(
    ("category", "owner_relation", "expected_action", "expected_transform"),
    [
        (ContentCategory.GENERAL_BUSINESS, OwnerRelation.NONE, Action.KEEP, None),
        (ContentCategory.SUPPLIER_IDENTITY, OwnerRelation.RECIPIENT, Action.KEEP, None),
        (
            ContentCategory.SUPPLIER_IDENTITY,
            OwnerRelation.OTHER,
            Action.FILTER,
            TransformKind.FILTER_OTHER_OWNERS,
        ),
        (ContentCategory.CONTACT_PERSONAL, OwnerRelation.RECIPIENT, Action.REMOVE, None),
        (ContentCategory.BANK_PAYMENT, OwnerRelation.RECIPIENT, Action.REMOVE, None),
        (ContentCategory.QUOTE_COMMERCIAL_TERMS, OwnerRelation.RECIPIENT, Action.KEEP, None),
        (
            ContentCategory.QUOTE_COMMERCIAL_TERMS,
            OwnerRelation.OTHER,
            Action.FILTER,
            TransformKind.FILTER_OTHER_OWNERS,
        ),
        (ContentCategory.INTERNAL_COST_BUDGET, OwnerRelation.NONE, Action.REMOVE, None),
        (
            ContentCategory.SCORE_RANKING,
            OwnerRelation.RECIPIENT,
            Action.GENERALIZE,
            TransformKind.GENERALIZE_SHORTLIST_STATUS,
        ),
        (
            ContentCategory.SCORE_RANKING,
            OwnerRelation.OTHER,
            Action.FILTER,
            TransformKind.FILTER_OTHER_OWNERS,
        ),
        (ContentCategory.INTERNAL_OPINION_APPROVAL, OwnerRelation.NONE, Action.REMOVE, None),
    ],
)
def test_bidder_matrix(
    policy_pack,  # type: ignore[no-untyped-def]
    category: ContentCategory,
    owner_relation: OwnerRelation,
    expected_action: Action,
    expected_transform: TransformKind | None,
) -> None:
    context = _context(
        RecipientProfile.SUPPLIER_BIDDER_A,
        Purpose.SUPPLIER_BID_FEEDBACK,
        Channel.CORPORATE_EMAIL,
    )

    decision = evaluate_region(
        policy_pack,
        context,
        _region(category),
        owner_relation=owner_relation,
    )

    assert decision.action is expected_action
    assert decision.transform == (expected_transform.value if expected_transform else None)


def test_personal_email_blocks_before_region_transformation(policy_pack) -> None:  # type: ignore[no-untyped-def]
    context = _context(
        RecipientProfile.SUPPLIER_BIDDER_A,
        Purpose.SUPPLIER_BID_FEEDBACK,
        Channel.PERSONAL_EMAIL,
    )

    decision = evaluate_region(
        policy_pack,
        context,
        _region(ContentCategory.GENERAL_BUSINESS),
    )

    assert decision.action is Action.BLOCK
    assert decision.rule_ids == ("PS-GLOBAL-PERSONAL-EMAIL",)


def test_unknown_category_and_policy_mismatch_fail_closed(policy_pack) -> None:  # type: ignore[no-untyped-def]
    context = _context(
        RecipientProfile.INTERNAL_PROCUREMENT_LEAD,
        Purpose.PROCUREMENT_DECISION,
        Channel.COLLABORATION_PLATFORM,
    )
    unknown = evaluate_region(policy_pack, context, _region(ContentCategory.UNCLASSIFIED))
    mismatch = evaluate_region(
        policy_pack,
        replace(context, policy_version="9.9.9"),
        _region(ContentCategory.GENERAL_BUSINESS),
    )

    assert unknown.action is Action.REQUIRE_APPROVAL
    assert mismatch.action is Action.REQUIRE_APPROVAL
    assert mismatch.rule_ids == ("PS-SYSTEM-POLICY-VERSION-MISMATCH",)
    assert mismatch.policy_sha256 == policy_pack.sha256


def test_unmatched_controlled_context_uses_the_frozen_default_citation(policy_pack) -> None:  # type: ignore[no-untyped-def]
    unmatched = _context(
        RecipientProfile.SUPPLIER_BIDDER_A,
        Purpose.ANNUAL_FINANCIAL_AUDIT,
        Channel.CORPORATE_EMAIL,
    )

    decision = evaluate_region(
        policy_pack,
        unmatched,
        _region(ContentCategory.QUOTE_COMMERCIAL_TERMS),
        owner_relation=OwnerRelation.RECIPIENT,
    )

    assert decision.action is Action.REQUIRE_APPROVAL
    assert decision.rule_ids == ("PS-DEFAULT-FAIL-CLOSED",)
    assert decision.evidence_ids == ("EV-GEN-002", "EV-GEN-003")
