"""Frontend authority visual audit.

CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001 — rung 6.

The audit takes a list of SectionState entries (one per visual
section the frontend renders) and refuses any layout that mixes
authority signals, hides blocked state, or shows a green success
state without a 'does NOT authorize X' caption.
"""

from __future__ import annotations

from collections.abc import Iterable

from .frontend_authority_visual_audit_record import (
    FRONTEND_AUTHORITY_VISUAL_AUDIT_STATUS_TOKENS,
    FRONTEND_VISUAL_SECTIONS,
    SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION,
    FrontendAuthorityVisualAuditRecord,
    SectionState,
)


def audit(sections: Iterable[SectionState]) -> FrontendAuthorityVisualAuditRecord:
    sec_list = tuple(sections or ())
    seen_names = {s.section for s in sec_list}

    ambiguities: list[str] = []
    section_merges: list[str] = []
    blocked_state_hidden: list[str] = []
    missing_negative_authority: list[str] = []

    # 1) Every required section must be represented.
    missing = [s for s in FRONTEND_VISUAL_SECTIONS if s not in seen_names]
    if missing:
        ambiguities.append(f"required sections missing from layout: {missing!r}")

    # 2) Unknown sections.
    for s in sec_list:
        if s.section not in FRONTEND_VISUAL_SECTIONS:
            ambiguities.append(f"unknown section: {s.section!r}")

    # 3) Section-merge check (no compound names).
    for s in sec_list:
        if "+" in s.section or "/" in s.section or "&" in s.section:
            section_merges.append(
                f"section name {s.section!r} looks merged (must be a single distinct section)"
            )
        # Common mismatches called out by the audit spec:
        # diagnosis + source_mutation; operator_queue + approval.
        compound_patterns = (
            (
                "diagnosis_and_source_mutation",
                "diagnosis must be separate from source_mutation_status",
            ),
            ("operator_queue_and_approval", "operator queue must be separate from approval grants"),
        )
        for pat, msg in compound_patterns:
            if pat in s.section:
                section_merges.append(f"{s.section!r}: {msg}")

    # 4) Hidden blocked state.
    for s in sec_list:
        if s.is_blocked_state and not s.visible:
            blocked_state_hidden.append(
                f"section {s.section!r} is in a blocked state but visible=False"
            )
        if s.is_blocked_state and not s.blocked_text:
            blocked_state_hidden.append(
                f"section {s.section!r} is blocked but blocked_text is empty"
            )

    # 5) Success state without negative-authority caption.
    for s in sec_list:
        if (
            s.is_success_state
            and s.section in SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION
            and not s.negative_authority_caption.strip()
        ):
            missing_negative_authority.append(
                f"section {s.section!r} is in success state but "
                "negative_authority_caption is empty — every green "
                "state must say what it does NOT authorize"
            )

    # Decision precedence: missing negative authority is the most
    # specific failure mode and takes priority for distinguishing it
    # from the more general ambiguity bucket.
    if missing_negative_authority:
        decision = "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_MISSING_NEGATIVE_AUTHORITY"
    elif blocked_state_hidden:
        decision = "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_BLOCKED_STATE_HIDDEN"
    elif section_merges:
        decision = "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_SECTION_MERGE"
    elif ambiguities:
        decision = "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE"
    else:
        decision = "FRONTEND_AUTHORITY_VISUAL_AUDIT_PASSED"

    return FrontendAuthorityVisualAuditRecord(
        decision=decision,
        sections=sec_list,
        ambiguities=tuple(ambiguities),
        section_merges=tuple(section_merges),
        blocked_state_hidden=tuple(blocked_state_hidden),
        missing_negative_authority=tuple(missing_negative_authority),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "audit operates on backend view-model description",
            "no frontend rendering performed",
            "does not authorize source mutation or training",
        ),
    )


def default_passing_layout() -> tuple[SectionState, ...]:
    """A reference layout that satisfies the audit. Useful both
    for tests and for the IDE wiring layer to clone."""
    captions = {
        "diagnosis": "diagnosis ≠ approval, does NOT authorize source mutation",
        "patch_preview": "preview ≠ apply, does NOT authorize source mutation",
        "verifier_result": "verifier passed on temp workspace, does NOT authorize source mutation",
        "approval_request": "approval ≠ source mutation, does NOT authorize training",
        "evidence_status": "evidence is a record, does NOT authorize source mutation",
        "training_eligibility_status": "training remains FALSE, does NOT authorize training",
    }
    return tuple(
        SectionState(
            section=name,
            visible=True,
            is_success_state=True,
            negative_authority_caption=captions.get(name, ""),
            is_blocked_state=False,
            blocked_text="",
        )
        for name in FRONTEND_VISUAL_SECTIONS
    )


__all__ = [
    "audit",
    "default_passing_layout",
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_STATUS_TOKENS",
    "FRONTEND_VISUAL_SECTIONS",
    "SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION",
    "FrontendAuthorityVisualAuditRecord",
    "SectionState",
]
