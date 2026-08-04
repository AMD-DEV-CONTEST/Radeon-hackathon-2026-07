from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from policyseal.documents.base import ParsedDocument
from policyseal.domain.enums import (
    Action,
    Channel,
    Classification,
    OwnerRelation,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.domain.models import DisclosureContext, DocumentRegion, PolicyDecision
from policyseal.policy.evaluator import evaluate_region
from policyseal.policy.schema import PolicyPack


@dataclass(frozen=True, slots=True)
class MatrixCell:
    context: DisclosureContext
    status: RevisionStatus
    action_counts: tuple[tuple[str, int], ...]
    action_region_ids: tuple[tuple[str, tuple[str, ...]], ...]
    decisions: tuple[PolicyDecision, ...]


@dataclass(frozen=True, slots=True)
class DisclosureMatrix:
    cells: tuple[MatrixCell, ...]


def default_xlsx_contexts() -> tuple[DisclosureContext, ...]:
    return (
        DisclosureContext(
            recipient=RecipientProfile.INTERNAL_PROCUREMENT_LEAD,
            organization="northstar.example",
            recipient_id="procurement.lead@northstar.example",
            purpose=Purpose.PROCUREMENT_DECISION,
            channel=Channel.COLLABORATION_PLATFORM,
            classification=Classification.CONFIDENTIAL,
            policy_version="1.0.0",
        ),
        DisclosureContext(
            recipient=RecipientProfile.EXTERNAL_FINANCIAL_AUDITOR,
            organization="audit-partner.example",
            recipient_id="auditor@audit-partner.example",
            purpose=Purpose.ANNUAL_FINANCIAL_AUDIT,
            channel=Channel.SECURE_FILE_EXCHANGE,
            classification=Classification.CONFIDENTIAL,
            policy_version="1.0.0",
        ),
        DisclosureContext.supplier_bidder_corporate_email(),
        DisclosureContext(
            recipient=RecipientProfile.SUPPLIER_BIDDER_A,
            organization="supplier-a.example",
            recipient_id="bidder-a@personal.example",
            purpose=Purpose.SUPPLIER_BID_FEEDBACK,
            channel=Channel.PERSONAL_EMAIL,
            classification=Classification.CONFIDENTIAL,
            policy_version="1.0.0",
        ),
    )


def _owner_relation(
    context: DisclosureContext,
    region: DocumentRegion,
) -> OwnerRelation:
    if region.owner_id is None:
        return OwnerRelation.NONE
    if context.recipient is RecipientProfile.SUPPLIER_BIDDER_A:
        if region.owner_id == "__UNKNOWN__":
            return OwnerRelation.UNKNOWN
        return (
            OwnerRelation.RECIPIENT if region.owner_id == "SUP-A" else OwnerRelation.OTHER
        )
    return OwnerRelation.NONE


def evaluate_xlsx(
    parsed: ParsedDocument,
    policy_pack: PolicyPack,
    context: DisclosureContext,
) -> tuple[PolicyDecision, ...]:
    return tuple(
        evaluate_region(
            policy_pack,
            context,
            region,
            owner_relation=_owner_relation(context, region),
        )
        for region in parsed.regions
    )


def build_xlsx_matrix(
    parsed: ParsedDocument,
    policy_pack: PolicyPack,
    contexts: tuple[DisclosureContext, ...],
) -> DisclosureMatrix:
    cells: list[MatrixCell] = []
    for context in contexts:
        decisions = evaluate_xlsx(parsed, policy_pack, context)
        counts = Counter(decision.action.value for decision in decisions)
        region_ids: dict[str, list[str]] = defaultdict(list)
        for decision in decisions:
            region_ids[decision.action.value].append(decision.region_id)
        if any(decision.action is Action.BLOCK for decision in decisions):
            status = RevisionStatus.BLOCKED
        elif any(decision.action is Action.REQUIRE_APPROVAL for decision in decisions):
            status = RevisionStatus.AWAITING_APPROVAL
        else:
            status = RevisionStatus.EXPORTABLE
        cells.append(
            MatrixCell(
                context=context,
                status=status,
                action_counts=tuple(sorted(counts.items())),
                action_region_ids=tuple(
                    (action, tuple(ids)) for action, ids in sorted(region_ids.items())
                ),
                decisions=decisions,
            )
        )
    return DisclosureMatrix(tuple(cells))
