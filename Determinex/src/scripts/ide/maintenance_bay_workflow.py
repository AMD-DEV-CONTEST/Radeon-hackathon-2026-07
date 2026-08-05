"""Maintenance Bay workflow checker.

DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001 — rung 4.

evaluate() refuses:

  * 'updated' or 'maintained' label without post-apply verifier
    pass -> BLOCKED_FALSE_UPDATED_LABEL
  * compatibility verifier missing while update applied
    -> BLOCKED_MISSING_COMPATIBILITY_VERIFIER
  * proposed update treated as applied/verified, or update applied
    without approval, or risk hidden, or external advisory status
    not caveated -> BLOCKED_AUTHORITY_CONFUSION
"""

from __future__ import annotations

from .maintenance_bay_workflow_record import (
    MAINTENANCE_BAY_WORKFLOW_STATUS_TOKENS,
    MAINTENANCE_STATES,
    MAINTENANCE_TYPES,
    MaintenanceBayWorkflowRecord,
)


def canonical_maintenance_types() -> tuple[str, ...]:
    return MAINTENANCE_TYPES


def canonical_states() -> tuple[str, ...]:
    return MAINTENANCE_STATES


def evaluate(
    *,
    maintenance_type: str,
    risk_visible: bool,
    compatibility_verifier_present: bool,
    compatibility_verifier_passed: bool,
    advisory_status_caveated: bool,
    approval_present: bool,
    update_proposed_quarantined: bool,
    update_applied_label_enabled: bool,
    updated_label_enabled: bool,
    post_apply_verifier_passed: bool,
    rollback_plan_present: bool,
) -> MaintenanceBayWorkflowRecord:
    common = dict(
        maintenance_type=maintenance_type,
        risk_visible=risk_visible,
        compatibility_verifier_present=compatibility_verifier_present,
        compatibility_verifier_passed=compatibility_verifier_passed,
        advisory_status_caveated=advisory_status_caveated,
        approval_present=approval_present,
        update_proposed_quarantined=update_proposed_quarantined,
        update_applied_label_enabled=update_applied_label_enabled,
        updated_label_enabled=updated_label_enabled,
        post_apply_verifier_passed=post_apply_verifier_passed,
        rollback_plan_present=rollback_plan_present,
    )

    # 1. Type must be in the canonical set.
    if maintenance_type not in MAINTENANCE_TYPES:
        return _block(
            "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
            note=f"unknown maintenance_type {maintenance_type!r}",
            common=common,
        )

    # 2. Dependency / security must show risk and caveat advisory status.
    if maintenance_type in ("dependency_update", "security_fix"):
        if not risk_visible:
            return _block(
                "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
                note=(
                    f"{maintenance_type!r} requires risk_visible=True; "
                    "the operator must see what changes"
                ),
                common=common,
            )
        if not advisory_status_caveated:
            return _block(
                "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
                note=(
                    f"{maintenance_type!r} requires advisory_status_caveated="
                    "True; external advisory/scanner status caveated if not run"
                ),
                common=common,
            )

    # 3. Compatibility verifier missing while update applied label set.
    if update_applied_label_enabled and not compatibility_verifier_present:
        return _block(
            "MAINTENANCE_BAY_WORKFLOW_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
            note=("update_applied_label_enabled=True without compatibility_verifier_present"),
            common=common,
        )

    # 4. 'Updated' label without post-apply verifier pass.
    if updated_label_enabled and not post_apply_verifier_passed:
        return _block(
            "MAINTENANCE_BAY_WORKFLOW_BLOCKED_FALSE_UPDATED_LABEL",
            note=(
                "'updated' / 'maintained' label cannot be shown without post_apply_verifier_passed"
            ),
            common=common,
        )

    # 5. Authority confusion: proposed -> applied conflations.
    if update_applied_label_enabled and not approval_present:
        return _block(
            "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
            note=(
                "update_applied_label_enabled=True without approval_present; "
                "a proposed update cannot be called applied"
            ),
            common=common,
        )
    if update_applied_label_enabled and not compatibility_verifier_passed:
        return _block(
            "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
            note=(
                "update_applied_label_enabled=True without "
                "compatibility_verifier_passed; a proposed update cannot "
                "be called verified"
            ),
            common=common,
        )

    return MaintenanceBayWorkflowRecord(
        decision="MAINTENANCE_BAY_WORKFLOW_WRITTEN",
        states=MAINTENANCE_STATES,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "maintenance type known; risk visible; advisory caveated when relevant",
            "compatibility verifier required to apply",
            "'updated' label requires post-apply verifier pass",
            "training_eligible False",
        ),
        **common,
    )


def _block(decision: str, *, note: str, common: dict) -> MaintenanceBayWorkflowRecord:
    return MaintenanceBayWorkflowRecord(
        decision=decision,
        states=MAINTENANCE_STATES,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
        **common,
    )


__all__ = [
    "canonical_maintenance_types",
    "canonical_states",
    "evaluate",
    "MAINTENANCE_BAY_WORKFLOW_STATUS_TOKENS",
    "MAINTENANCE_TYPES",
    "MAINTENANCE_STATES",
    "MaintenanceBayWorkflowRecord",
]
