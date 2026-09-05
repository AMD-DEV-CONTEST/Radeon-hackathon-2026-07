"""Build the read-only M5 input from the real canonical asset and E5 sidecars.

PR #31's policy slice ran against a contract-equivalent mock. This module is the
seam that replaces the mock with what E1-E5 actually persist: the canonical
`ExperienceAssetV1` snapshot, E5's readiness sidecar, and E5's relation ledger.

The mapping is deliberately conservative. Where the canonical model holds no
record for a route signal, the signal stays empty and the route comes back
`BLOCKED` or `INELIGIBLE`. Filling a gap with the nearest available statement
would turn "we have no qualifying client context" into a confident customer
route, which is the exact failure the route contract exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from app.experience_asset.domain.enums import Milestone, StatementStatus
from app.experience_asset.domain.models import ExperienceAssetV1
from app.experience_asset.domain.relation import KnowledgeCardReadinessRecordV1

from .contracts import (
    M5_ROUTE_POLICY_IDENTITY,
    M5_SCHEMA_IDENTITY,
    M5_WORKFLOW_IDENTITY,
    M5ContextProjectionV1,
    M5EvidenceIndexV1,
    M5RelationProjectionV1,
)


def _unique(values: Iterable[UUID]) -> list[UUID]:
    seen: dict[UUID, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _m4_role_statement_ids(asset: ExperienceAssetV1) -> dict[str, list[UUID]]:
    """Recover M4 role groupings from canonical insights and the M4 artifact.

    `InsightRecord` stores the lesson as text and the other roles as ID lists,
    so the lesson's own statement ID is only recoverable as the M4 artifact IDs
    that no role list claims.
    """

    roles: dict[str, list[UUID]] = {
        "SUPPORT": [],
        "COUNTERFACTUAL": [],
        "LIMITATION": [],
        "COUNTEREXAMPLE": [],
        "APPLICABILITY": [],
    }
    for insight in asset.insights:
        roles["SUPPORT"].extend(insight.support_statement_ids)
        roles["COUNTERFACTUAL"].extend(insight.counterfactual_statement_ids)
        roles["LIMITATION"].extend(insight.limitation_statement_ids)
        roles["COUNTEREXAMPLE"].extend(insight.counterexample_statement_ids)
        roles["APPLICABILITY"].extend(insight.applicability_statement_ids)

    claimed = {statement_id for ids in roles.values() for statement_id in ids}
    artifact = next(
        (item for item in asset.milestone_artifacts if item.milestone is Milestone.M4),
        None,
    )
    lesson_ids = (
        [item for item in artifact.statement_ids if item not in claimed]
        if artifact is not None
        else []
    )
    roles["LESSON"] = lesson_ids
    return {key: _unique(value) for key, value in roles.items()}


def build_evidence_index(asset: ExperienceAssetV1) -> M5EvidenceIndexV1:
    """Compose deterministic route signals from canonical E1-E5 records only."""

    roles = _m4_role_statement_ids(asset)
    current_ids = {statement.statement_id for statement in asset.statements}

    decision_ids: list[UUID] = []
    reason_ids: list[UUID] = []
    alternative_ids: list[UUID] = []
    action_ids: list[UUID] = []
    result_ids: list[UUID] = []
    evidence_ids: list[UUID] = []
    for decision in asset.decisions:
        decision_ids.extend(decision.decision_statement_ids)
        reason_ids.extend(decision.reason_statement_ids)
        alternative_ids.extend(decision.alternative_statement_ids)
        action_ids.extend(decision.action_statement_ids)
        result_ids.extend(decision.result_statement_ids)
        evidence_ids.extend(decision.evidence_statement_ids)

    moment_ids: list[UUID] = []
    for moment in asset.critical_moments:
        moment_ids.extend(moment.cue_statement_ids)
        moment_ids.extend(moment.change_statement_ids)
        moment_ids.extend(moment.surprise_statement_ids)
        moment_ids.extend(moment.conflict_statement_ids)

    unresolved = [
        statement.statement_id
        for statement in asset.statements
        if statement.status is StatementStatus.UNRESOLVED
    ]
    unresolved_set = set(unresolved)

    def keep(*groups: Iterable[UUID]) -> list[UUID]:
        """Route support must be current and not itself an unresolved gap."""

        return _unique(
            statement_id
            for group in groups
            for statement_id in group
            if statement_id in current_ids and statement_id not in unresolved_set
        )

    return M5EvidenceIndexV1(
        decision_context=keep(decision_ids, reason_ids),
        personal_lesson=keep(roles["LESSON"]),
        # Applicability conditions are the closest canonical record of "what has
        # to be true before this applies", which is what a beginner needs first.
        beginner_prerequisite=keep(roles["APPLICABILITY"]),
        beginner_guidance_basis=keep(roles["SUPPORT"], action_ids),
        common_mistake_or_risk=keep(roles["COUNTEREXAMPLE"], roles["COUNTERFACTUAL"]),
        peer_comparison=keep(alternative_ids, roles["COUNTERFACTUAL"]),
        peer_evidence=keep(roles["SUPPORT"], evidence_ids),
        tradeoff_or_constraint=keep(roles["LIMITATION"]),
        # Left empty on purpose. E1-E5 persist no professional/client role
        # record, so any value here would be manufactured qualifying context and
        # the route must stay INELIGIBLE until a real one exists.
        qualifying_context=[],
        verifiable_result=keep(result_ids, evidence_ids),
        event_arc=keep(moment_ids, decision_ids),
        transferable_lesson=keep(roles["LESSON"]),
        applicability_boundary=keep(roles["APPLICABILITY"], roles["LIMITATION"]),
        disclosure_basis=keep(roles["LIMITATION"], roles["COUNTEREXAMPLE"]),
        # No canonical producer classifies a claim as universal or professional
        # overreach; leaving these empty never makes a route more permissive.
        unsupported_universal_claim=[],
        unsupported_professional_claim=[],
        unresolved_statement_ids=unresolved,
    )


def build_m5_context(
    asset: ExperienceAssetV1,
    *,
    content_hash: str,
    readiness: KnowledgeCardReadinessRecordV1 | None,
    relation: M5RelationProjectionV1,
    current_version_id: UUID | None = None,
    model_run_id: UUID | None = None,
) -> M5ContextProjectionV1:
    """Project one canonical version plus its E5 sidecars into the M5 input.

    `content_hash` is supplied by the caller rather than recomputed here: the
    repository already owns snapshot hashing, and a second implementation would
    eventually disagree with the stored value that readiness is bound to.
    """

    evidence = build_evidence_index(asset)
    authorized = set(relation.authorized_historical_statement_ids)
    statements = [
        statement
        for statement in asset.statements
        if statement.statement_id not in authorized
    ]
    return M5ContextProjectionV1(
        asset_id=asset.asset_id,
        version_id=asset.version_id,
        content_hash=content_hash,
        current_version_id=current_version_id or asset.version_id,
        readiness=readiness,
        statements=statements,
        sources=list(asset.sources),
        evidence=evidence,
        relation=relation,
        schema_identity=M5_SCHEMA_IDENTITY,
        workflow_identity=M5_WORKFLOW_IDENTITY,
        policy_identity=M5_ROUTE_POLICY_IDENTITY,
        model_run_id=model_run_id,
    )
