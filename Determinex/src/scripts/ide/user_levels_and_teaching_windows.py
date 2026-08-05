"""User levels and teaching windows.

DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001 — rung 7.

Eight user levels with per-level profiles. Hard rules:

  * Every level keeps proof_status_visible=True (beginner mode
    must NOT hide proof; power-user mode must NOT loosen gates).
  * Every level keeps authority_gates_active=True.
  * Every level's teaching_windows must explain WHY something is
    blocked (teaching_window_explains_blocked_reason=True).
  * Every level must declare a teaching window that includes the
    phrase 'training stays false' in 'what_not_to_hide'.
"""

from __future__ import annotations

from .user_levels_and_teaching_windows_record import (
    USER_LEVELS,
    USER_LEVELS_TEACHING_WINDOWS_STATUS_TOKENS,
    UserLevelProfile,
    UserLevelsAndTeachingWindowsRecord,
)


def _profile(
    level: str,
    *,
    detail: str,
    ui: str,
    explanations: str,
    warnings: tuple[str, ...] = (),
    teaching: tuple[str, ...] = (),
    next_action: str = "open Idea Lab or Repo Clinic",
    not_hide: tuple[str, ...] = (
        "proof status",
        "training stays false",
        "blocked reasons",
    ),
    not_over_explain: tuple[str, ...] = (),
) -> UserLevelProfile:
    return UserLevelProfile(
        level=level,
        default_explanations=explanations,
        level_of_detail=detail,
        warnings_caveats=warnings,
        ui_complexity=ui,
        teaching_windows=teaching,
        suggested_next_action=next_action,
        what_not_to_hide=not_hide,
        what_not_to_over_explain=not_over_explain,
        proof_status_visible=True,
        authority_gates_active=True,
        teaching_window_explains_blocked_reason=True,
    )


_CANONICAL_PROFILES: tuple[UserLevelProfile, ...] = (
    _profile(
        "beginner_no_experience",
        detail="plain language, short",
        ui="minimal",
        explanations=(
            "explain in everyday words; reframe technical terms; show why "
            "each step happens before showing the step"
        ),
        warnings=(
            "this is a learning environment, not a production setup",
            "you do not need to memorize the gates — they protect you",
        ),
        teaching=(
            "what is a verifier",
            "why approval is required",
            "why this button is disabled right now",
        ),
        next_action="open Idea Lab for a starter project",
        not_over_explain=("internal lock IDs",),
    ),
    _profile(
        "learner",
        detail="conceptual + example",
        ui="minimal",
        explanations="show concept, then example, then next step",
        teaching=(
            "diagnosis vs repair",
            "preview vs apply",
            "why this is blocked",
        ),
        next_action="try the Learning Studio walk-through",
    ),
    _profile(
        "vibe_coder",
        detail="visual, short",
        ui="moderate",
        explanations="show the panel, the green-vs-blocked badge, and one sentence",
        teaching=("blocked reason hover-card",),
        next_action="open Repo Clinic on a fixture",
    ),
    _profile(
        "junior_developer",
        detail="structured with code",
        ui="moderate",
        explanations="annotated code samples, comparison with a senior version",
        teaching=(
            "verifier output reading",
            "rollback semantics",
            "approval payload anatomy",
        ),
        next_action="open Maintenance Bay against a fixture",
    ),
    _profile(
        "professional_developer",
        detail="full surface, terse",
        ui="full",
        explanations="just the deltas and the gate state",
        teaching=("authority vocabulary classifier",),
        next_action="open Repo Clinic on the active repo",
        not_over_explain=("what diagnosis is",),
    ),
    _profile(
        "maintainer",
        detail="full surface, risk-emphasized",
        ui="full",
        explanations="risk classification + rollback plan first",
        teaching=("dependency advisory caveat semantics",),
        next_action="open Maintenance Bay",
    ),
    _profile(
        "security_conscious_operator",
        detail="full surface, gate-emphasized",
        ui="full",
        explanations="HMAC binding, signature kind, replay/staleness state",
        warnings=(
            "free-string operator identity is refused",
            "fixture approvals do not authorize source mutation",
        ),
        teaching=(
            "operator identity bound to admission payload",
            "approval replay/staleness rules",
            "symlinked workspaces refused",
        ),
        next_action="open Proof / Operator Center",
    ),
    _profile(
        "power_user",
        detail="full surface, no hand-holding",
        ui="full",
        explanations="raw record fields and minimal narrative",
        warnings=(
            "no shortcut bypasses the apply gate",
            "no shortcut opens training",
        ),
        teaching=("how the campaign final-state evaluator reads disk",),
        next_action="open Proof / Operator Center",
        not_over_explain=("basic gate purpose",),
    ),
)


def canonical_profiles() -> tuple[UserLevelProfile, ...]:
    return _CANONICAL_PROFILES


def build_record() -> UserLevelsAndTeachingWindowsRecord:
    profiles = _CANONICAL_PROFILES

    # 1) All required levels present.
    seen = {p.level for p in profiles}
    missing = [l for l in USER_LEVELS if l not in seen]
    if missing:
        return _block(
            "USER_LEVELS_BLOCKED_PROOF_HIDDEN",
            profiles=profiles,
            note=f"required levels missing: {missing!r}",
        )

    # 2) Proof status visible everywhere.
    proof_hidden = [p.level for p in profiles if not p.proof_status_visible]
    if proof_hidden:
        return _block(
            "USER_LEVELS_BLOCKED_PROOF_HIDDEN",
            profiles=profiles,
            note=(
                f"proof_status_visible=False at levels: {proof_hidden!r}; "
                "beginner mode must not hide proof status"
            ),
        )

    # 3) Authority gates active everywhere.
    inactive = [p.level for p in profiles if not p.authority_gates_active]
    if inactive:
        return _block(
            "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS",
            profiles=profiles,
            note=(
                f"authority_gates_active=False at levels: {inactive!r}; "
                "power user / professional must not bypass gates"
            ),
        )

    # 4) Teaching windows must explain blocked reason for every level.
    no_blocked = [p.level for p in profiles if not p.teaching_window_explains_blocked_reason]
    if no_blocked:
        return _block(
            "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS",
            profiles=profiles,
            note=(f"teaching_window_explains_blocked_reason=False at levels: {no_blocked!r}"),
        )

    # 5) Every level must keep training_stays_false in what_not_to_hide.
    missing_training_hide = [
        p.level
        for p in profiles
        if not any("training" in s.lower() and "false" in s.lower() for s in p.what_not_to_hide)
    ]
    if missing_training_hide:
        return _block(
            "USER_LEVELS_BLOCKED_PROOF_HIDDEN",
            profiles=profiles,
            note=(
                f"levels missing 'training stays false' in what_not_to_hide: "
                f"{missing_training_hide!r}"
            ),
        )

    return UserLevelsAndTeachingWindowsRecord(
        decision="USER_LEVELS_TEACHING_WINDOWS_VALIDATED",
        levels=profiles,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "8 levels declared; every level keeps proof visible",
            "every level keeps authority gates active",
            "every teaching window explains why something is blocked",
            "training stays false everywhere",
        ),
    )


def _block(
    decision: str,
    *,
    profiles: tuple[UserLevelProfile, ...],
    note: str,
) -> UserLevelsAndTeachingWindowsRecord:
    return UserLevelsAndTeachingWindowsRecord(
        decision=decision,
        levels=profiles,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_profiles",
    "build_record",
    "USER_LEVELS_TEACHING_WINDOWS_STATUS_TOKENS",
    "USER_LEVELS",
    "UserLevelProfile",
    "UserLevelsAndTeachingWindowsRecord",
]
