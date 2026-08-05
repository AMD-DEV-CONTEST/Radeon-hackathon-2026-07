"""Public claims ledger.

CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001 — rung 7. Classifies every
Claude/IDE-lane public claim into one of five disjoint states and
applies four hard rules to refuse over-claiming.
"""

from __future__ import annotations

from .public_claims_ledger_record import (
    CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY,
    PUBLIC_CLAIM_CLASSIFICATIONS,
    PUBLIC_CLAIMS_LEDGER_STATUS_TOKENS,
    PublicClaim,
    PublicClaimsLedgerRecord,
)

# The canonical ledger — every Claude/IDE-lane claim required by the
# campaign spec. Entries here are public-facing language. An empty
# evidence_ref triggers an implementation_ambiguity refusal.
_CANONICAL_LEDGER: tuple[PublicClaim, ...] = (
    PublicClaim(
        key="local_model_detection_admission",
        classification="implemented",
        short=(
            "Local-model detection and admission is gated by "
            "REAL_LOCAL_MODEL_ADMISSION_LOCK_001 and the no-bypass lock."
        ),
        evidence_ref="REAL_LOCAL_MODEL_ADMISSION_LOCK_001",
        blocks_or_gates=("source_mutation_authorized=False",),
    ),
    PublicClaim(
        key="local_model_healthcheck",
        classification="implemented",
        short=("Local-model healthcheck is the precondition for diagnose-with-verifier-context."),
        evidence_ref="REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001",
    ),
    PublicClaim(
        key="diagnose_with_verifier_context",
        classification="implemented",
        short=(
            "Diagnose-with-verifier-context quarantines model output; "
            "patch is NOT applied at this rung."
        ),
        evidence_ref="REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001",
        blocks_or_gates=("output_trusted=False", "patch_applied=False"),
    ),
    PublicClaim(
        key="quarantined_patch_plan",
        classification="implemented",
        short=(
            "Patch plans are quarantined and schema/path-validated before any other rung sees them."
        ),
        evidence_ref="REAL_PATCH_PLAN_QUARANTINE_LOCK_001",
    ),
    PublicClaim(
        key="temp_patch_verifier",
        classification="implemented",
        short=(
            "Temp-patch verifier runs against an isolated temp workspace; "
            "real workspace is unchanged."
        ),
        evidence_ref="REAL_TEMP_PATCH_VERIFY_LOCK_001",
    ),
    PublicClaim(
        key="human_approval_source_mutation_gate",
        classification="implemented",
        short=("Human approval is required AND fixture approvals are refused at the apply gate."),
        evidence_ref="APPLY_GATE_FIXTURE_REFUSAL_LOCK_001",
        blocks_or_gates=("source_mutation_authorized=False",),
    ),
    PublicClaim(
        key="canonical_patch_body_binding",
        classification="implemented",
        short=(
            "Approval is bound to a canonical sha256 of the patch body; "
            "tampered bodies are refused."
        ),
        evidence_ref="REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001",
    ),
    PublicClaim(
        key="cryptographic_local_approval_binding",
        classification="implemented_but_gated_or_blocked",
        short=(
            "Approval signatures are HMAC-SHA256 over a canonical payload "
            "using a per-host local secret. Asymmetric crypto is the "
            "next upgrade."
        ),
        evidence_ref="APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001",
        blocks_or_gates=("asymmetric_crypto=NOT_YET_IMPLEMENTED",),
    ),
    PublicClaim(
        key="rollback_snapshot",
        classification="implemented_but_gated_or_blocked",
        short=(
            "Rollback snapshots are taken before any source mutation. "
            "Symlinked workspaces are refused, not preserved."
        ),
        evidence_ref="SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001,ROLLBACK_SYMLINK_SEMANTICS_LOCK_001",
        blocks_or_gates=("symlinks=REFUSED",),
    ),
    PublicClaim(
        key="post_apply_verifier",
        classification="implemented",
        short=(
            "Post-apply verifier never defaults to pass; missing or stub verifiers are refused."
        ),
        evidence_ref="POST_APPLY_VERIFIER_NO_DEFAULT_PASS_LOCK_001",
    ),
    PublicClaim(
        key="frontend_repair_panel",
        classification="implemented_but_gated_or_blocked",
        short=(
            "Repair panel view-model is locked. Live React mount + visual "
            "audit hooks are in progress."
        ),
        evidence_ref="CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001,CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001",
    ),
    PublicClaim(
        key="source_mutation",
        classification="implemented_but_gated_or_blocked",
        short=(
            "Source mutation is implemented but ALWAYS gated behind "
            "approval, verifier, snapshot, body-hash and symlink checks. "
            "source_mutation_authorized stays False unless every gate "
            "explicitly passes."
        ),
        evidence_ref="SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001",
        blocks_or_gates=(
            "approval_required",
            "verifier_required",
            "snapshot_required",
            "body_hash_required",
            "symlink_refused",
        ),
    ),
    PublicClaim(
        key="training_eligibility",
        classification="not_claimed",
        short=(
            "Training eligibility is NOT opened by any Claude IDE lane "
            "lock. training_eligible remains False everywhere."
        ),
        evidence_ref="CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001",
        blocks_or_gates=("training_eligible=False everywhere",),
    ),
    PublicClaim(
        key="release_readiness",
        classification="planned",
        short=(
            "Public release is gated on install / demo / repo scrub. "
            "Not declared release-ready by the Claude lane today."
        ),
        evidence_ref="docs/CLAUDE_PUBLIC_CLAIMS_LEDGER.md",
    ),
    PublicClaim(
        key="public_packaging",
        classification="planned",
        short=("Public packaging (signed installer, demo bundle) is planned, not implemented."),
        evidence_ref="docs/CLAUDE_PUBLIC_CLAIMS_LEDGER.md",
    ),
    PublicClaim(
        key="federated_forge",
        classification="research_track",
        short=(
            "Forge / federated-learning surface is a research track; "
            "not implemented in the Claude IDE lane."
        ),
        evidence_ref="docs/CLAUDE_PUBLIC_CLAIMS_LEDGER.md",
    ),
    PublicClaim(
        key="mobile_console",
        classification="research_track",
        short=("Mobile console is a research track; not implemented in the Claude IDE lane."),
        evidence_ref="docs/CLAUDE_PUBLIC_CLAIMS_LEDGER.md",
    ),
)


# Required claim keys (from the campaign spec).
REQUIRED_CLAIM_KEYS = frozenset(
    {
        "local_model_detection_admission",
        "local_model_healthcheck",
        "diagnose_with_verifier_context",
        "quarantined_patch_plan",
        "temp_patch_verifier",
        "human_approval_source_mutation_gate",
        "canonical_patch_body_binding",
        "cryptographic_local_approval_binding",
        "rollback_snapshot",
        "post_apply_verifier",
        "frontend_repair_panel",
        "source_mutation",
        "training_eligibility",
        "release_readiness",
        "public_packaging",
        "federated_forge",
        "mobile_console",
    }
)


def canonical_ledger() -> tuple[PublicClaim, ...]:
    return _CANONICAL_LEDGER


def build_record() -> PublicClaimsLedgerRecord:
    """Build the live record by classifying the canonical ledger and
    enforcing the four hard rules."""
    overclaims: list[str] = []
    ambiguities: list[str] = []
    keys_seen = set()

    for c in _CANONICAL_LEDGER:
        # Classification must be one of the five.
        if c.classification not in PUBLIC_CLAIM_CLASSIFICATIONS:
            ambiguities.append(f"{c.key}: unknown classification {c.classification!r}")
            continue
        # Every claim except 'not_claimed' must have an evidence ref.
        if c.classification != "not_claimed" and not c.evidence_ref:
            ambiguities.append(
                f"{c.key}: classification {c.classification!r} requires non-empty evidence_ref"
            )
        # Short text must be non-empty.
        if not c.short:
            ambiguities.append(f"{c.key}: short summary empty")

        keys_seen.add(c.key)

    missing = REQUIRED_CLAIM_KEYS - keys_seen
    if missing:
        ambiguities.append(f"required claim keys missing: {sorted(missing)!r}")

    # Hard rule 1: training never implemented.
    training = _find_claim("training_eligibility")
    if training and training.classification in CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY:
        overclaims.append(
            "training_eligibility classified as 'implemented'; only a "
            "negative guard exists. Reclassify as 'not_claimed' or 'planned'."
        )

    # Hard rule 2: release_readiness must not imply ready today.
    release = _find_claim("release_readiness")
    if release and release.classification in CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY:
        overclaims.append(
            "release_readiness classified as 'implemented'; install/demo/"
            "repo scrub is incomplete. Reclassify as 'planned'."
        )
    public_pkg = _find_claim("public_packaging")
    if public_pkg and public_pkg.classification in CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY:
        overclaims.append("public_packaging classified as 'implemented'; not yet shipped.")

    # Hard rule 3: no claim implies benchmark execution from Claude lane.
    for c in _CANONICAL_LEDGER:
        kl = c.key.lower()
        if "benchmark" in kl or "programbench" in kl or "swebench" in kl:
            overclaims.append(
                f"{c.key}: Claude lane claims must not imply benchmark "
                "execution. Move to the Codex/ProgramBench lane."
            )

    # Hard rule 4: source_mutation must remain gated.
    sm = _find_claim("source_mutation")
    if sm:
        if sm.classification == "implemented" and not sm.blocks_or_gates:
            overclaims.append(
                "source_mutation classified as 'implemented' without "
                "declaring its gates. Use 'implemented_but_gated_or_blocked'."
            )
        # Forbidden words check
        kw_forbidden = ("freely", "without approval", "no gate")
        if any(kw in sm.short.lower() for kw in kw_forbidden):
            overclaims.append("source_mutation short text contains forbidden phrasing")

    if overclaims:
        decision = "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM"
    elif ambiguities:
        decision = "PUBLIC_CLAIMS_LEDGER_BLOCKED_IMPLEMENTATION_AMBIGUITY"
    else:
        decision = "PUBLIC_CLAIMS_LEDGER_WRITTEN"

    return PublicClaimsLedgerRecord(
        decision=decision,
        claims=_CANONICAL_LEDGER,
        overclaims=tuple(overclaims),
        implementation_ambiguities=tuple(ambiguities),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "ledger is the single source of truth for public claims",
            "training never opens; source_mutation always gated",
            "Claude lane does not claim benchmark execution",
        ),
    )


def _find_claim(key: str) -> PublicClaim | None:
    for c in _CANONICAL_LEDGER:
        if c.key == key:
            return c
    return None


__all__ = [
    "canonical_ledger",
    "build_record",
    "REQUIRED_CLAIM_KEYS",
    "PUBLIC_CLAIMS_LEDGER_STATUS_TOKENS",
    "PUBLIC_CLAIM_CLASSIFICATIONS",
    "PublicClaim",
    "PublicClaimsLedgerRecord",
]
