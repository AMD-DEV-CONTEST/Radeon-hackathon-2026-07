"""Unified product navigation model.

DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001 — rung 1.

Declares the five top-level surfaces and the rules an audit
applies before the navigation model can be called WRITTEN /
VALIDATED:

  * Every required surface must be present.
  * Every surface must have at least one blocked_state.
  * No surface may declare ``source_mutation_boundary`` empty or
    in a way that contains the phrases 'authorized by default' or
    'open by default'.
  * Learning Studio's source_mutation_boundary must explicitly
    state 'non-mutating' or 'routes to repo_clinic gates'.
  * Proof Operator Center's source_mutation_boundary must say
    'read-only' or 'non-authorizing'.
  * No surface may declare training_eligibility_boundary in a way
    that opens training.

This module does NOT mutate anything and does NOT call any gate.
"""

from __future__ import annotations

from .unified_product_navigation_model_record import (
    SHARED_AUTHORITY_VOCABULARY,
    UNIFIED_PRODUCT_NAVIGATION_MODEL_STATUS_TOKENS,
    UNIFIED_PRODUCT_SURFACES,
    ProductSurface,
    UnifiedProductNavigationModelRecord,
)

_FORBIDDEN_MUTATION_PHRASES = (
    "authorized by default",
    "open by default",
    "auto-apply",
    "no approval required",
)


_FORBIDDEN_TRAINING_PHRASES = (
    "training eligible by default",
    "opens training",
    "training enabled",
)


_CANONICAL_SURFACES: tuple[ProductSurface, ...] = (
    ProductSurface(
        key="idea_lab",
        title="Idea Lab",
        purpose=(
            "Turn a beginner's idea into a runnable, verifier-checked "
            "local app — without claiming all apps or all languages."
        ),
        target_users=(
            "beginner_no_experience",
            "learner",
            "vibe_coder",
            "junior_developer",
            "professional_developer",
        ),
        beginner_view=(
            "Plain-language idea capture; clear support-matrix check; "
            "Build It disabled until support check passes; honest "
            "failure surface if scaffold cannot be verified."
        ),
        professional_view=(
            "Structured spec, blueprint, scaffold, acceptance tests, "
            "build/test/smoke evidence, bounded repair plan."
        ),
        inputs=("idea_text", "constraints", "optional_external_setup"),
        outputs=(
            "spec",
            "blueprint",
            "scaffold",
            "acceptance_tests",
            "build_verifier_result",
            "smoke_plan",
            "evidence_record",
        ),
        status_states=(
            "IDEA_CAPTURED",
            "SPEC_WRITTEN",
            "SUPPORT_CHECK_REQUIRED",
            "BLUEPRINT_READY",
            "SCAFFOLD_READY",
            "GENERATED_UNVERIFIED",
            "TESTS_PASSED",
            "SMOKE_PASSED",
            "VERIFIED_WORKING_LOCAL_APP",
        ),
        blocked_states=(
            "UNSUPPORTED_REQUEST",
            "BUILD_DISABLED_SUPPORT_CHECK_REQUIRED",
            "WORKING_DISABLED_NO_VERIFIER_EVIDENCE",
            "HONEST_FAILURE",
        ),
        proof_evidence_requirements=(
            "build verifier must pass before label 'TESTS_PASSED'",
            "smoke plan must run before label 'VERIFIED_WORKING_LOCAL_APP'",
            "evidence artifact written on terminal state",
        ),
        source_mutation_boundary=(
            "scaffold writes to a Determinex-managed workspace inside the "
            "operator's chosen idea_lab root; the operator's existing "
            "user repos are never touched; apply gates remain in place"
        ),
        training_eligibility_boundary=(
            "training_eligible stays False; Idea Lab does not open training"
        ),
        claim_caveats=(
            "not all apps — only the languages and frameworks in the support matrix",
            "external setup (databases, paid APIs) is the operator's "
            "responsibility and is caveated",
            "'WORKING' means build+test+smoke evidence, not production-ready",
        ),
    ),
    ProductSurface(
        key="repo_clinic",
        title="Repo Clinic",
        purpose=(
            "Diagnose, repair, refactor, or update an existing codebase "
            "with verifier-gated source mutation."
        ),
        target_users=(
            "junior_developer",
            "professional_developer",
            "maintainer",
            "security_conscious_operator",
        ),
        beginner_view=(
            "Step-by-step walkthrough of detected issues with plain-"
            "language explanations; no source mutation without explicit "
            "approval; clear blocked states when a verifier is missing."
        ),
        professional_view=(
            "Full quarantine record, temp-verify diff, approval payload, "
            "rollback snapshot ref, post-apply verifier output."
        ),
        inputs=(
            "existing_repo_path",
            "failing_test_or_error",
            "verifier_command",
        ),
        outputs=(
            "health_report",
            "diagnosis",
            "quarantined_patch_plan",
            "temp_verifier_result",
            "approval_request",
            "post_apply_evidence",
        ),
        status_states=(
            "REPO_OPENED",
            "REPO_ANALYZED",
            "ISSUE_DIAGNOSED_UNVERIFIED",
            "PATCH_PROPOSED_QUARANTINED",
            "TEMP_VERIFIER_PASSED",
            "APPROVAL_REQUIRED",
            "SOURCE_MUTATION_AUTHORIZED",
            "SOURCE_MUTATION_APPLIED",
            "POST_APPLY_VERIFIER_PASSED",
            "REPAIR_VERIFIED",
        ),
        blocked_states=(
            "TOOLCHAIN_MISSING",
            "VERIFIER_MISSING",
            "REPAIR_FAILED_HONESTLY",
            "FIXED_LABEL_DISABLED_NO_POST_APPLY_EVIDENCE",
        ),
        proof_evidence_requirements=(
            "temp verifier must pass before approval can be requested",
            "approval gate enforces canonical body hash + HMAC + symlink refusal",
            "post-apply verifier must run before label 'REPAIR_VERIFIED'",
            "rollback snapshot taken before any source mutation",
        ),
        source_mutation_boundary=(
            "source mutation gated by approval + temp_verify + snapshot + "
            "body_hash + symlink_refusal; non-mutating until every gate passes"
        ),
        training_eligibility_boundary=(
            "training_eligible stays False; Repo Clinic does not open training"
        ),
        claim_caveats=(
            "'FIXED' only after post-apply verifier passes",
            "diagnosis alone is not a fix",
            "model output is untrusted until verifier confirms",
        ),
    ),
    ProductSurface(
        key="maintenance_bay",
        title="Maintenance Bay",
        purpose=(
            "Run dependency updates, security fixes, migrations, and "
            "housekeeping with compatibility verifiers."
        ),
        target_users=(
            "professional_developer",
            "maintainer",
            "security_conscious_operator",
            "power_user",
        ),
        beginner_view=(
            "Clear risk classification per proposed change; UPDATED label "
            "disabled until compatibility verifier passes."
        ),
        professional_view=(
            "Per-change risk score, dependency graph diff, advisory IDs, rollback plan."
        ),
        inputs=(
            "existing_repo_path",
            "maintenance_type",
            "advisory_or_dependency_target",
        ),
        outputs=(
            "maintenance_plan",
            "risk_classification",
            "quarantined_update",
            "compatibility_verifier_result",
            "post_apply_evidence",
            "rollback_plan",
        ),
        status_states=(
            "MAINTENANCE_REQUESTED",
            "MAINTENANCE_PLAN_WRITTEN",
            "UPDATE_PROPOSED_QUARANTINED",
            "UPDATE_VERIFIED",
            "UPDATE_APPLIED_AFTER_APPROVAL",
        ),
        blocked_states=(
            "COMPATIBILITY_VERIFIER_REQUIRED",
            "UPDATE_BLOCKED_UNVERIFIED",
            "UPDATE_FAILED_HONESTLY",
            "UPDATED_LABEL_DISABLED_NO_VERIFIER",
        ),
        proof_evidence_requirements=(
            "compatibility verifier required before approval",
            "external advisory/scanner status caveated if not run",
            "post-apply verifier required before 'UPDATED' label",
        ),
        source_mutation_boundary=(
            "non-mutating until the compatibility verifier passes AND "
            "an explicit approval routes through the apply gate"
        ),
        training_eligibility_boundary=(
            "training_eligible stays False; Maintenance Bay does not open training"
        ),
        claim_caveats=(
            "'UPDATED' only after compatibility verifier passes",
            "scanner status read-only unless Codex lane has run it",
            "dependency advisories caveated by source",
        ),
    ),
    ProductSurface(
        key="learning_studio",
        title="Learning Studio",
        purpose=(
            "Explain, teach, compare, and walk through code at the "
            "operator's chosen level — without authorizing any change."
        ),
        target_users=(
            "beginner_no_experience",
            "learner",
            "vibe_coder",
            "junior_developer",
            "professional_developer",
        ),
        beginner_view=(
            "Plain-language explanations of repo / file / error / test "
            "failure; learning checklist; clear ‘this does not change "
            "your code’ caption on every screen."
        ),
        professional_view=(
            "Side-by-side beginner-vs-pro framing; ‘compare possible fixes’ "
            "panel; explicit handoff buttons to Repo Clinic / Idea Lab "
            "for any change that would touch source."
        ),
        inputs=(
            "repo_or_file_or_error_or_test",
            "level",
            "concept_request",
        ),
        outputs=(
            "explanation",
            "comparison",
            "walkthrough",
            "beginner_version_vs_professional_version",
            "learning_checklist",
        ),
        status_states=(
            "LEARNING_EXPLAINED",
            "LEARNING_COMPARED",
            "LEARNING_WALKTHROUGH_RENDERED",
            "LEARNING_HANDOFF_TO_REPO_CLINIC",
            "LEARNING_HANDOFF_TO_IDEA_LAB",
        ),
        blocked_states=(
            "LEARNING_CANNOT_AUTHORIZE_MUTATION",
            "LEARNING_CANNOT_MARK_REPAIR_SUCCESS",
        ),
        proof_evidence_requirements=(
            "no evidence is produced by Learning Studio; it consumes "
            "evidence from other surfaces and explains it",
        ),
        source_mutation_boundary=(
            "non-mutating by default; any suggested change routes to "
            "repo_clinic gates or idea_lab gates"
        ),
        training_eligibility_boundary=(
            "training_eligible stays False; Learning Studio does not open training"
        ),
        claim_caveats=(
            "explanations are informative, not authoritative",
            "comparing fixes is not approving a fix",
            "‘this would work’ is a teaching framing, not a verifier result",
        ),
    ),
    ProductSurface(
        key="proof_operator_center",
        title="Proof / Operator Center",
        purpose=(
            "Show evidence, gates, approvals, queues, training status, "
            "and claim safety in one read-only operator surface."
        ),
        target_users=(
            "professional_developer",
            "maintainer",
            "security_conscious_operator",
            "power_user",
        ),
        beginner_view=(
            "Plain-language ‘what is authorized / not authorized right "
            "now’ summary; visible blocked actions; training-status "
            "badge always shows training_eligible=False."
        ),
        professional_view=(
            "Full evidence ledger view, source-mutation gate state, "
            "verifier status, rollback status, operator-action queue, "
            "ProgramBench/provenance read-only mirror."
        ),
        inputs=(
            "workspace_identity",
            "evidence_index",
            "operator_action_queue",
        ),
        outputs=(
            "evidence_ledger_view",
            "gate_state_summary",
            "rollback_status",
            "training_status_badge",
            "blocked_actions_list",
            "claim_safety_status",
        ),
        status_states=(
            "PROOF_VIEW_RENDERED",
            "OPERATOR_QUEUE_DISPLAYED_NON_AUTHORIZING",
            "PROGRAMBENCH_STATUS_READ_ONLY_MIRROR",
        ),
        blocked_states=(
            "OPERATOR_QUEUE_REQUEST_IS_NOT_APPROVAL",
            "TRAINING_NEVER_OPENED_FROM_THIS_SURFACE",
            "PROGRAMBENCH_NOT_MUTABLE_FROM_CLAUDE_LANE",
        ),
        proof_evidence_requirements=(
            "evidence ledger is read-only here; canonical writer is the Codex lane",
            "no surface action may authorize source mutation or training",
        ),
        source_mutation_boundary=(
            "read-only, non-authorizing surface; operator actions here do not approve anything"
        ),
        training_eligibility_boundary=(
            "training_eligible stays False everywhere; this surface only shows the status"
        ),
        claim_caveats=(
            "operator queue request is a request, not a grant",
            "ProgramBench/provenance status reflects Codex-lane state",
            "‘blocked’ here means blocked — not ‘in progress’",
        ),
    ),
)


def canonical_surfaces() -> tuple[ProductSurface, ...]:
    return _CANONICAL_SURFACES


def build_record() -> UnifiedProductNavigationModelRecord:
    surfaces = _CANONICAL_SURFACES

    # Hard rule 1: every required surface present.
    seen = {s.key for s in surfaces}
    missing = [k for k in UNIFIED_PRODUCT_SURFACES if k not in seen]
    if missing:
        return _block(
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_MISSING_SURFACE",
            surfaces=surfaces,
            note=f"required surfaces missing: {missing!r}",
        )

    # Hard rule 2: every surface has at least one blocked_state.
    no_blocked = [s.key for s in surfaces if not s.blocked_states]
    if no_blocked:
        return _block(
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
            surfaces=surfaces,
            note=(
                f"surfaces missing visible blocked states: {no_blocked!r}; "
                "every surface must show its blocked/unsupported states"
            ),
        )

    # Hard rule 3: no surface may declare source_mutation_boundary that
    # opens mutation by default.
    bad_mut = []
    for s in surfaces:
        bound_l = s.source_mutation_boundary.lower()
        for phrase in _FORBIDDEN_MUTATION_PHRASES:
            if phrase in bound_l:
                bad_mut.append(f"{s.key!r}: contains {phrase!r}")
    if bad_mut:
        return _block(
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
            surfaces=surfaces,
            note=f"source_mutation_boundary violations: {bad_mut!r}",
        )

    # Hard rule 4: Learning Studio mutation boundary must say non-mutating
    # or route to gated workflows.
    ls = next((s for s in surfaces if s.key == "learning_studio"), None)
    if ls:
        bound = ls.source_mutation_boundary.lower()
        if not any(
            k in bound
            for k in (
                "non-mutating",
                "routes to repo_clinic",
                "routes to idea_lab",
            )
        ):
            return _block(
                "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
                surfaces=surfaces,
                note=(
                    "learning_studio source_mutation_boundary must say "
                    "non-mutating or route to gated workflows"
                ),
            )

    # Hard rule 5: Proof/Operator Center boundary must say read-only or
    # non-authorizing.
    pc = next((s for s in surfaces if s.key == "proof_operator_center"), None)
    if pc:
        bound = pc.source_mutation_boundary.lower()
        if not ("read-only" in bound or "non-authorizing" in bound):
            return _block(
                "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
                surfaces=surfaces,
                note=(
                    "proof_operator_center source_mutation_boundary must "
                    "say read-only or non-authorizing"
                ),
            )

    # Hard rule 6: training boundary may not open training anywhere.
    bad_train = []
    for s in surfaces:
        bl = s.training_eligibility_boundary.lower()
        for phrase in _FORBIDDEN_TRAINING_PHRASES:
            if phrase in bl:
                bad_train.append(f"{s.key!r}: contains {phrase!r}")
        # Positive assertion required: must say 'stays False' or 'does not open'.
        if not ("false" in bl or "does not open" in bl):
            bad_train.append(
                f"{s.key!r}: training boundary does not explicitly state "
                "training stays False / does not open"
            )
    if bad_train:
        return _block(
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
            surfaces=surfaces,
            note=f"training_eligibility_boundary violations: {bad_train!r}",
        )

    # Validated.
    return UnifiedProductNavigationModelRecord(
        decision="UNIFIED_PRODUCT_NAVIGATION_MODEL_VALIDATED",
        surfaces=surfaces,
        shared_authority_vocabulary=SHARED_AUTHORITY_VOCABULARY,
        unsupported_state_visible_per_surface={s.key: bool(s.blocked_states) for s in surfaces},
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "five surfaces declared; one shared authority vocabulary",
            "every surface has at least one visible blocked state",
            "Learning Studio non-mutating; Proof Operator Center read-only",
            "no surface opens training",
        ),
    )


def _block(
    decision: str,
    *,
    surfaces: tuple[ProductSurface, ...],
    note: str,
) -> UnifiedProductNavigationModelRecord:
    return UnifiedProductNavigationModelRecord(
        decision=decision,
        surfaces=surfaces,
        shared_authority_vocabulary=SHARED_AUTHORITY_VOCABULARY,
        unsupported_state_visible_per_surface={s.key: bool(s.blocked_states) for s in surfaces},
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_surfaces",
    "build_record",
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_STATUS_TOKENS",
    "UNIFIED_PRODUCT_SURFACES",
    "SHARED_AUTHORITY_VOCABULARY",
    "ProductSurface",
    "UnifiedProductNavigationModelRecord",
]
