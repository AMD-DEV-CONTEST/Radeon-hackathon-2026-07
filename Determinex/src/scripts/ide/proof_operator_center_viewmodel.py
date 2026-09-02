"""Proof / Operator Center view-model builder.

DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001 — rung 6.

build() refuses any view-model where:

  * blocked_actions_visible is False -> BLOCKED_ACTION_HIDDEN
  * blocked_actions_text is empty -> BLOCKED_ACTION_HIDDEN
  * any operator_action.kind is 'grant' or
    any operator_action without routes_to set -> BLOCKED_AUTHORITY_CONFUSION
  * source_mutation_authorized_now claims True at this surface ->
    BLOCKED_AUTHORITY_CONFUSION (apply gate is authoritative,
    not the operator center)
  * training_eligible_now claims True -> BLOCKED_TRAINING_CONFUSION
  * training_status_text doesn't say 'false' / 'remains false' ->
    BLOCKED_TRAINING_CONFUSION
  * programbench_provenance_read_only is False
    -> BLOCKED_AUTHORITY_CONFUSION
"""

from __future__ import annotations

from .proof_operator_center_viewmodel_record import (
    PROOF_OPERATOR_CENTER_SECTIONS,
    PROOF_OPERATOR_CENTER_VIEWMODEL_STATUS_TOKENS,
    OperatorAction,
    ProofOperatorCenterViewModel,
    ProofOperatorCenterViewModelRecord,
)


def canonical_sections() -> tuple[str, ...]:
    return PROOF_OPERATOR_CENTER_SECTIONS


def build(view_model: ProofOperatorCenterViewModel | None) -> ProofOperatorCenterViewModelRecord:
    if view_model is None:
        return ProofOperatorCenterViewModelRecord(
            decision="PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN",
            view_model=None,
            sections_present=(),
            notes=("view_model is None; operator must see real status",),
        )

    sections = PROOF_OPERATOR_CENTER_SECTIONS

    # 1) Training confusion — strongest signal first.
    if view_model.training_eligible_now:
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION",
            view_model=view_model,
            note="training_eligible_now=True; training never opens from this surface",
        )
    if "false" not in view_model.training_status_text.lower() and (
        "remains false" not in view_model.training_status_text.lower()
    ):
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION",
            view_model=view_model,
            note=(
                "training_status_text must explicitly say 'false' / 'remains false'; "
                f"got {view_model.training_status_text!r}"
            ),
        )

    # 2) Blocked actions must be visible.
    if not view_model.blocked_actions_visible:
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN",
            view_model=view_model,
            note="blocked_actions_visible=False",
        )
    if not view_model.blocked_actions_text.strip():
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN",
            view_model=view_model,
            note="blocked_actions_text is empty",
        )

    # 3) Operator actions must be requests, never grants.
    for a in view_model.operator_actions:
        if a.kind == "grant":
            return _block(
                "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
                view_model=view_model,
                note=(
                    f"operator_action {a.label!r}: kind='grant'; only "
                    "'request' actions are allowed here"
                ),
            )
        if a.visible and not a.routes_to.strip():
            return _block(
                "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
                view_model=view_model,
                note=(
                    f"operator_action {a.label!r}: visible but no routes_to "
                    "external workflow; queue request must not look like a grant"
                ),
            )

    # 4) source_mutation_authorized_now must NEVER be True at this view-model.
    if view_model.source_mutation_authorized_now:
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
            view_model=view_model,
            note=(
                "source_mutation_authorized_now=True on the operator center "
                "view-model; this surface is read-only — the apply gate is "
                "authoritative"
            ),
        )

    # 5) ProgramBench/provenance must be read-only from Claude lane.
    if not view_model.programbench_provenance_read_only:
        return _block(
            "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
            view_model=view_model,
            note=(
                "programbench_provenance_read_only=False; ProgramBench / "
                "provenance status must be a read-only mirror in the Claude lane"
            ),
        )

    return ProofOperatorCenterViewModelRecord(
        decision="PROOF_OPERATOR_CENTER_VIEWMODEL_WRITTEN",
        view_model=view_model,
        sections_present=sections,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "view-model is read-only; operator actions are requests, not grants",
            "training_status_text explicitly false",
            "blocked actions visible with non-empty text",
            "ProgramBench/provenance mirrored read-only",
        ),
    )


def _block(
    decision: str,
    *,
    view_model: ProofOperatorCenterViewModel,
    note: str,
) -> ProofOperatorCenterViewModelRecord:
    return ProofOperatorCenterViewModelRecord(
        decision=decision,
        view_model=view_model,
        sections_present=PROOF_OPERATOR_CENTER_SECTIONS,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_sections",
    "build",
    "PROOF_OPERATOR_CENTER_VIEWMODEL_STATUS_TOKENS",
    "PROOF_OPERATOR_CENTER_SECTIONS",
    "OperatorAction",
    "ProofOperatorCenterViewModel",
    "ProofOperatorCenterViewModelRecord",
]
