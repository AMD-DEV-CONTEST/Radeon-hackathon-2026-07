"""Pre-apply confirmation panel builder.

CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001 — rung 4.

The frontend renders a PreApplyConfirmationPanelViewModel before
the operator can authorize source mutation. This module is the
single source of truth for what fields the panel must surface and
which UI state it must be in.

Hard rules:

  * The view-model must include canonical_patch_body_hash and
    diff_hash (otherwise BLOCKED_MISSING_HASH).
  * It must include a verifier_status string (otherwise
    BLOCKED_MISSING_VERIFIER).
  * It must include a rollback_snapshot_ref string for
    states past DRY_RUN (otherwise BLOCKED_MISSING_SNAPSHOT).
  * If the panel reaches SOURCE_MUTATION_AUTHORIZED, then
    source_mutation_consequence_text must be non-empty AND must
    contain the warning that training_eligible remains False.
  * If panel says source_mutation_authorized=True but
    ui_state is not the authorized/applied state, that's an
    AUTHORITY_AMBIGUITY block.
  * Any panel whose training_eligible=True is BLOCKED.
"""

from __future__ import annotations

from collections.abc import Sequence

from .pre_apply_confirmation_panel_record import (
    PRE_APPLY_CONFIRMATION_PANEL_STATUS_TOKENS,
    PRE_APPLY_UI_STATES,
    PreApplyConfirmationPanelRecord,
    PreApplyConfirmationPanelViewModel,
)

_REQUIRED_CONSEQUENCE_KEYWORDS = (
    "will write",
    "source mutation",
)

_REQUIRED_TRAINING_KEYWORDS = (
    "training",
    "false",  # "remains false" / "is false"
)


def build_view_model(
    *,
    ui_state: str,
    files_affected: Sequence[str],
    canonical_patch_body_hash: str,
    diff_hash: str,
    verifier_status: str,
    rollback_snapshot_ref: str,
    source_mutation_consequence_text: str,
    training_eligibility_text: str,
    source_mutation_authorized: bool = False,
) -> PreApplyConfirmationPanelViewModel:
    """Construct the view-model the frontend will render."""
    return PreApplyConfirmationPanelViewModel(
        ui_state=ui_state,
        files_affected=tuple(files_affected or ()),
        canonical_patch_body_hash=canonical_patch_body_hash,
        diff_hash=diff_hash,
        verifier_status=verifier_status,
        rollback_snapshot_ref=rollback_snapshot_ref,
        source_mutation_consequence_text=source_mutation_consequence_text,
        training_eligibility_text=training_eligibility_text,
        source_mutation_authorized=source_mutation_authorized,
        training_eligible=False,  # NEVER set true here
    )


def check(panel: PreApplyConfirmationPanelViewModel | None) -> PreApplyConfirmationPanelRecord:
    if panel is None:
        return PreApplyConfirmationPanelRecord(
            decision="PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
            panel=None,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=("panel is None — operator must see a real view-model",),
        )

    # Training eligibility — must never be opened by the panel.
    if panel.training_eligible:
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_TRAINING_OPENED",
            panel=panel,
            note="panel.training_eligible is True; training must remain False",
        )

    if panel.ui_state not in PRE_APPLY_UI_STATES:
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
            panel=panel,
            note=f"unknown ui_state={panel.ui_state!r}",
        )

    if not panel.canonical_patch_body_hash or not panel.diff_hash:
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_HASH",
            panel=panel,
            note="canonical_patch_body_hash or diff_hash empty",
        )

    if not panel.verifier_status:
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_VERIFIER",
            panel=panel,
            note="verifier_status empty",
        )

    # Past DRY_RUN, a rollback snapshot reference is required.
    state_needs_snapshot = panel.ui_state in (
        "PRE_APPLY_UI_APPROVED",
        "PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        "PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",
    )
    if state_needs_snapshot and not panel.rollback_snapshot_ref:
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_SNAPSHOT",
            panel=panel,
            note=f"rollback_snapshot_ref empty in state {panel.ui_state!r}",
        )

    # source_mutation_authorized may only be True for the two
    # post-approval states.
    if panel.source_mutation_authorized and panel.ui_state not in (
        "PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        "PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",
    ):
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
            panel=panel,
            note=(
                f"source_mutation_authorized=True but ui_state="
                f"{panel.ui_state!r}; only post-approval states may carry"
                " this flag"
            ),
        )

    # The reverse: APPLIED state must report source_mutation_authorized True.
    if (
        panel.ui_state == "PRE_APPLY_UI_SOURCE_MUTATION_APPLIED"
        and not panel.source_mutation_authorized
    ):
        return _block(
            "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
            panel=panel,
            note=(
                "ui_state=APPLIED but source_mutation_authorized=False; "
                "APPLIED is the post-fact state and must carry the flag"
            ),
        )

    if panel.source_mutation_authorized:
        # The consequence text MUST contain the keywords that warn the
        # operator about what authorizing means.
        ct = (panel.source_mutation_consequence_text or "").lower()
        if not all(kw in ct for kw in _REQUIRED_CONSEQUENCE_KEYWORDS):
            return _block(
                "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
                panel=panel,
                note=(
                    "source_mutation_consequence_text missing required "
                    f"phrases {_REQUIRED_CONSEQUENCE_KEYWORDS!r}"
                ),
            )
        tt = (panel.training_eligibility_text or "").lower()
        if not all(kw in tt for kw in _REQUIRED_TRAINING_KEYWORDS):
            return _block(
                "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
                panel=panel,
                note=("training_eligibility_text must say training remains False"),
            )

    return PreApplyConfirmationPanelRecord(
        decision="PRE_APPLY_CONFIRMATION_PANEL_PASSED",
        panel=panel,
        source_mutation_authorized=panel.source_mutation_authorized,
        training_eligible=False,
        notes=(
            "panel surfaces all bound fields",
            "ui_state vs source_mutation_authorized consistent",
            "training_eligible False",
        ),
    )


def _block(decision: str, *, panel, note: str) -> PreApplyConfirmationPanelRecord:
    return PreApplyConfirmationPanelRecord(
        decision=decision,
        panel=panel,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "build_view_model",
    "check",
    "PRE_APPLY_CONFIRMATION_PANEL_STATUS_TOKENS",
    "PRE_APPLY_UI_STATES",
    "PreApplyConfirmationPanelRecord",
    "PreApplyConfirmationPanelViewModel",
]
