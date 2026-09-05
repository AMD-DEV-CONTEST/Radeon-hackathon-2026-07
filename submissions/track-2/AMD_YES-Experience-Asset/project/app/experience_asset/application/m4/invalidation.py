"""Pure M3-to-M4 correction invalidation calculated before atomic persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m3 import DecisionEvidenceLedgerV1
from app.experience_asset.domain.m4 import InsightBoundaryMapV1


def successor_after_m3_transition(
    map_artifact: InsightBoundaryMapV1,
    *,
    old_m3: DecisionEvidenceLedgerV1,
    new_m3: DecisionEvidenceLedgerV1,
    new_canonical_version_id: UUID,
    changed_at: datetime,
) -> InsightBoundaryMapV1:
    """Calculate the exact M4 successor for one M3 transition.

    A correction the map does not depend on must not invalidate it: rebuilding a
    map whose evidence is untouched discards work the user already reviewed and
    trains them to ignore the invalidated state, which is the one signal that has
    to stay meaningful.
    """
    old_entries = {entry.decision_id: entry for entry in old_m3.entries}
    new_entries = {entry.decision_id: entry for entry in new_m3.entries}
    changed_decisions = set(old_entries) ^ set(new_entries)
    changed_decisions |= {
        decision_id
        for decision_id in set(old_entries) & set(new_entries)
        if old_entries[decision_id] != new_entries[decision_id]
    }
    old_statements = {
        statement.statement_id: statement
        for entry in old_m3.entries
        for statement in entry.statements
    }
    new_statements = {
        statement.statement_id: statement
        for entry in new_m3.entries
        for statement in entry.statements
    }
    changed_statements = set(old_statements) ^ set(new_statements)
    changed_statements |= {
        statement_id
        for statement_id in set(old_statements) & set(new_statements)
        if old_statements[statement_id] != new_statements[statement_id]
    }
    if old_m3.state != new_m3.state:
        # Acceptance or invalidation of the ledger is itself a dependency
        # transition: the map was drawn from a ledger the user has since
        # re-judged, whatever the individual rows now say.
        changed_decisions |= set(map_artifact.dependency_decision_ids)
    affected = bool(
        changed_decisions & set(map_artifact.dependency_decision_ids)
        or changed_statements & set(map_artifact.dependency_statement_ids)
    )
    successor = (
        invalidate_after_m3_correction(
            map_artifact,
            changed_decision_ids=changed_decisions,
            changed_statement_ids=changed_statements,
            new_m3_artifact_id=new_m3.artifact_id,
            new_canonical_version_id=new_canonical_version_id,
            changed_at=changed_at,
        )
        if affected
        else map_artifact.model_copy(
            update={
                "base_m3_artifact_id": new_m3.artifact_id,
                "base_canonical_version_id": new_canonical_version_id,
                "updated_at": changed_at,
            }
        )
    )
    return successor.model_copy(update={"artifact_id": uuid4()})


def invalidate_after_m3_correction(
    map_artifact: InsightBoundaryMapV1,
    *,
    changed_decision_ids: set[UUID],
    changed_statement_ids: set[UUID],
    new_m3_artifact_id: UUID,
    new_canonical_version_id: UUID,
    changed_at: datetime,
) -> InsightBoundaryMapV1:
    """Invalidate only when the new M3 state changes a declared dependency."""

    affected_decisions = set(map_artifact.dependency_decision_ids) & changed_decision_ids
    affected_statements = set(map_artifact.dependency_statement_ids) & changed_statement_ids
    if not affected_decisions and not affected_statements:
        return map_artifact
    if new_m3_artifact_id == map_artifact.base_m3_artifact_id:
        raise ValueError("new M3 artifact must differ from the map base")
    if new_canonical_version_id == map_artifact.base_canonical_version_id:
        raise ValueError("new canonical version must differ from the map base")
    if changed_at.tzinfo is None or changed_at < map_artifact.updated_at:
        raise ValueError("changed_at must be timezone-aware and not regress")

    changed_refs = [
        *(f"decision:{item}" for item in sorted(affected_decisions, key=str)),
        *(f"statement:{item}" for item in sorted(affected_statements, key=str)),
    ]
    affected_insights = [
        entry.insight_id
        for entry in map_artifact.entries
        if set(entry.source_decision_ids) & affected_decisions
        or any(
            (set(statement.source_statement_ids) | set(statement.source_decision_ids))
            & (affected_statements | affected_decisions)
            for statement in entry.statements
        )
    ]
    reusable_insights = [
        entry.insight_id
        for entry in map_artifact.entries
        if entry.insight_id not in affected_insights
    ]
    return map_artifact.model_copy(
        update={
            "state": MilestoneState.INVALIDATED,
            "updated_at": changed_at,
            "invalidated_by_m3_artifact_id": new_m3_artifact_id,
            "invalidated_by_canonical_version_id": new_canonical_version_id,
            "invalidation_reason": (
                "M3 correction changed dependencies used by this insight map: "
                + ", ".join(changed_refs)
            ),
            "affected_insight_ids": affected_insights,
            "reusable_insight_ids": reusable_insights,
        }
    )
