"""Explicit adapter between strict domain values and the frozen public QA schema."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .enums import RelationLifecycle, RouteEligibility, RouteType, StatementStatus
from .models import ExperienceAssetV1, RouteDecision
from .relation import ConfirmedAssetRelationV1

STATEMENT_TO_PUBLIC = {
    StatementStatus.SOURCE_FACT: "source_fact",
    StatementStatus.USER_JUDGMENT: "user_judgment",
    StatementStatus.AGENT_INFERENCE: "agent_inference",
    StatementStatus.UNRESOLVED: "unresolved",
}
STATEMENT_FROM_PUBLIC = {value: key for key, value in STATEMENT_TO_PUBLIC.items()}

ELIGIBILITY_TO_PUBLIC = {
    RouteEligibility.ELIGIBLE: "eligible",
    RouteEligibility.INELIGIBLE: "ineligible",
    RouteEligibility.ELIGIBLE_AFTER_PRIVACY_APPROVAL: "eligible_after_privacy_approval",
    RouteEligibility.BLOCKED: "blocked",
}
ELIGIBILITY_FROM_PUBLIC = {value: key for key, value in ELIGIBILITY_TO_PUBLIC.items()}

ROUTE_TO_PUBLIC = {
    RouteType.PRIVATE_SELF: "private_self",
    RouteType.BEGINNER: "beginner",
    RouteType.PEER: "peer",
    RouteType.CUSTOMER_EVALUATOR: "customer_evaluator",
    RouteType.PUBLIC: "public",
}


class PublicSerializationError(ValueError):
    """Canonical state is valid but not ready for the stricter public artifact gate."""


def statement_status_to_public(value: StatementStatus) -> str:
    return STATEMENT_TO_PUBLIC[value]


def statement_status_from_public(value: str) -> StatementStatus:
    try:
        return STATEMENT_FROM_PUBLIC[value]
    except KeyError as exc:
        raise PublicSerializationError(f"unknown public statement status: {value}") from exc


def eligibility_to_public(value: RouteEligibility) -> str:
    return ELIGIBILITY_TO_PUBLIC[value]


def eligibility_from_public(value: str) -> RouteEligibility:
    try:
        return ELIGIBILITY_FROM_PUBLIC[value]
    except KeyError as exc:
        raise PublicSerializationError(f"unknown public eligibility: {value}") from exc


def _compose_relations(
    asset: ExperienceAssetV1,
    relations: Sequence[ConfirmedAssetRelationV1],
) -> list[dict[str, object]]:
    """Project confirmed relations onto one exact version.

    A relation bound to a different version of this asset is not a relation of
    *this* version: its stated reason was formed against content this export
    does not contain. Silently including it would attach an explanation to
    evidence the reader cannot find here, so the mismatch is refused instead.

    Invalidated and stale relations are dropped rather than rejected: they are a
    normal outcome of the user correcting an asset, and the export simply has
    nothing to say about them.
    """
    composed: list[dict[str, object]] = []
    for relation in relations:
        if relation.current_asset_id != asset.asset_id:
            raise PublicSerializationError(
                "relation belongs to a different asset than the snapshot"
            )
        if relation.current_version_id != asset.version_id:
            raise PublicSerializationError(
                "relation is bound to a different version than the snapshot; its "
                "stated reason was formed against content this export does not "
                "contain"
            )
        if relation.lifecycle is not RelationLifecycle.CONFIRMED:
            continue
        composed.append(
            {
                "relation_id": str(relation.relation_id),
                "related_asset_id": str(relation.related_asset_id),
                "relation": relation.relation_type.value,
                "confirmed_by_user": True,
            }
        )
    return composed


def to_public_asset(
    asset: ExperienceAssetV1,
    *,
    relations: Sequence[ConfirmedAssetRelationV1],
    route_decisions: Sequence[RouteDecision] | None = None,
) -> dict[str, Any]:
    """Serialize one saved canonical version without adding or rewriting claims.

    Relation state lives in the sidecar ledger, so it has to be passed in rather
    than read off the snapshot. The parameter is explicit for two reasons.

    Reading the ledger inside this function would make the output of a *saved,
    immutable version* depend on state that changes after the version was
    written, so two exports of the same version could differ — which is exactly
    what an immutable snapshot exists to rule out. The caller composes, and the
    caller is the one that knows which relations were current.

    The argument is **required**, with no default. An optional parameter that
    fell back to an empty list is the worse of the two failures: confirmed
    relations would exist in the ledger while the public output claimed there
    were none, and nothing at the call site would distinguish "there are no
    relations" from "nobody asked the ledger". Callers with nothing to report
    pass `()` explicitly, which is a statement rather than an omission.

    `route_decisions` exists for the same reason. E6 evaluates the five routes
    and stores the result in its own binding-scoped store, while the canonical
    snapshot still carries the placeholder decisions written before M5 ran.
    Serializing those placeholders publishes "every route blocked for missing
    evidence" while the product surface shows three routes eligible — an export
    that materially misstates what the product did. It stays optional only so
    that pre-M5 callers keep serializing their own snapshot honestly; any caller
    that has run M5 must pass the decisions M5 produced.
    """

    if not asset.statements:
        raise PublicSerializationError("public artifact requires at least one statement")

    sources = {source.source_id: source for source in asset.sources}
    first_source = asset.sources[0] if asset.sources else None
    provenance = {
        "source_kind": first_source.kind.value.lower() if first_source else "unknown",
        "adapted": bool(first_source and first_source.kind.value == "ADAPTED_PUBLIC_FIXTURE"),
        "first_party_testimony": bool(
            first_source and first_source.authorship.value == "USER_AUTHORED"
        ),
        "source_url": first_source.source_url if first_source else None,
    }

    statements = []
    for statement in asset.statements:
        evidence_ref = None
        if statement.source_refs:
            source = sources[statement.source_refs[0]]
            evidence_ref = f"source:{source.source_id}"
        statements.append(
            {
                "text": statement.text,
                "status": statement_status_to_public(statement.status),
                "evidence_ref": evidence_ref,
                "presented_as_fact": statement.status is StatementStatus.SOURCE_FACT,
            }
        )

    decisions = asset.route_decisions if route_decisions is None else route_decisions
    routes = {
        ROUTE_TO_PUBLIC[decision.route]: {
            "eligibility": eligibility_to_public(decision.eligibility),
            "reason": "; ".join(decision.reason_codes) or decision.explanation,
        }
        for decision in decisions
    }
    composed_relations = _compose_relations(asset, relations)
    prior_versions = (
        [str(asset.lineage.parent_version_id)] if asset.lineage.parent_version_id else []
    )
    return {
        "asset_id": str(asset.asset_id),
        "version": f"v{asset.schema_version}",
        "created_utc": asset.created_at.isoformat(),
        "provenance": provenance,
        "context": asset.context,
        "goal": asset.goal,
        "statements": statements,
        "routes": routes,
        "prior_versions": prior_versions,
        "relations": composed_relations,
    }
