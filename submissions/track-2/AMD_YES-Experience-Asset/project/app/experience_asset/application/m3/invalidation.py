"""Pure M2-to-M3 correction invalidation prepared ahead of E3 integration."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m2 import CriticalMomentMapV1
from app.experience_asset.domain.m3 import DecisionEvidenceLedgerV1


def successor_after_m2_transition(
    ledger: DecisionEvidenceLedgerV1,
    *,
    old_m2: CriticalMomentMapV1,
    new_m2: CriticalMomentMapV1,
    new_canonical_version_id: UUID,
    changed_at: datetime,
) -> DecisionEvidenceLedgerV1:
    """Calculate the exact M3 successor in application logic before atomic persistence."""
    old_moments = {item.moment_id: item for item in old_m2.moments}
    new_moments = {item.moment_id: item for item in new_m2.moments}
    changed_moments = set(old_moments) ^ set(new_moments)
    changed_moments |= {
        item
        for item in set(old_moments) & set(new_moments)
        if old_moments[item] != new_moments[item]
    }
    changed_statements = set(old_m2.dependency_statement_ids) ^ set(new_m2.dependency_statement_ids)
    if old_m2.state != new_m2.state:
        # Acceptance/invalidation is itself a semantic dependency transition.
        changed_moments |= set(ledger.dependency_moment_ids)
    affected = bool(
        changed_moments & set(ledger.dependency_moment_ids)
        or changed_statements & set(ledger.dependency_statement_ids)
    )
    successor = (
        invalidate_after_m2_correction(
            ledger,
            changed_moment_ids=changed_moments,
            changed_statement_ids=changed_statements,
            new_m2_artifact_id=new_m2.artifact_id,
            new_canonical_version_id=new_canonical_version_id,
            changed_at=changed_at,
        )
        if affected
        else ledger.model_copy(
            update={
                "base_m2_artifact_id": new_m2.artifact_id,
                "base_canonical_version_id": new_canonical_version_id,
                "updated_at": changed_at,
            }
        )
    )
    return successor.model_copy(update={"artifact_id": uuid4()})


def invalidate_after_m2_correction(
    ledger: DecisionEvidenceLedgerV1,
    *,
    changed_moment_ids: set[UUID],
    changed_statement_ids: set[UUID],
    new_m2_artifact_id: UUID,
    new_canonical_version_id: UUID,
    changed_at: datetime,
) -> DecisionEvidenceLedgerV1:
    """Invalidate only when the new M2 state changes a declared dependency."""

    affected_moments = set(ledger.dependency_moment_ids) & changed_moment_ids
    affected_statements = set(ledger.dependency_statement_ids) & changed_statement_ids
    if not affected_moments and not affected_statements:
        return ledger
    if new_m2_artifact_id == ledger.base_m2_artifact_id:
        raise ValueError("new M2 artifact must differ from the ledger base")
    if new_canonical_version_id == ledger.base_canonical_version_id:
        raise ValueError("new canonical version must differ from the ledger base")
    if changed_at.tzinfo is None or changed_at < ledger.updated_at:
        raise ValueError("changed_at must be timezone-aware and not regress")

    changed_refs = [
        *(f"moment:{item}" for item in sorted(affected_moments, key=str)),
        *(f"statement:{item}" for item in sorted(affected_statements, key=str)),
    ]
    affected_entries = [
        entry.decision_id
        for entry in ledger.entries
        if set(entry.source_moment_ids) & affected_moments
        or any(
            (set(statement.source_statement_ids) | set(statement.derived_from_statement_ids))
            & affected_statements
            for statement in entry.statements
        )
    ]
    reusable_entries = [
        entry.decision_id for entry in ledger.entries if entry.decision_id not in affected_entries
    ]
    return ledger.model_copy(
        update={
            "state": MilestoneState.INVALIDATED,
            "updated_at": changed_at,
            "invalidated_by_m2_artifact_id": new_m2_artifact_id,
            "invalidated_by_canonical_version_id": new_canonical_version_id,
            "invalidation_reason": (
                "M2 correction changed dependencies used by this M3 ledger: "
                + ", ".join(changed_refs)
            ),
            "affected_entry_ids": affected_entries,
            "affected_dependency_refs": changed_refs,
            "reusable_entry_ids": reusable_entries,
        }
    )
