"""Approval UX copy.

Exact user-facing text for the IDE approval flow. Plain, direct,
non-hype. No claims that AI is always correct or that approval is
risk-free.
"""

from __future__ import annotations

APPROVAL_UX_COPY: dict[str, str] = {
    "diagnosis_advisory": (
        "The diagnosis above is a suggestion from a model. The model can be "
        "wrong. The verifier result, not the model, is the source of truth."
    ),
    "patch_plan_untrusted": (
        "This patch plan was produced by a model and has not been verified. "
        "Treat it as a draft. Read every change before approving."
    ),
    "verifier_result_explanation": (
        "The verifier ran on a temporary copy of your workspace. A pass means "
        "the patched code compiled and the configured tests passed in that "
        "temp copy. It does not mean the change is correct for your use case."
    ),
    "temp_workspace_explanation": (
        "The patch was applied only to a temporary workspace. Your original "
        "files were not modified. You can dismiss the patch at any time before "
        "approval."
    ),
    "source_mutation_warning": (
        "Approving will eventually apply the diff to your real files. This "
        "step is not yet wired up in this build — even an approve action here "
        "produces only a fixture/dry-run record. Real source mutation will "
        "require a separate, explicit step."
    ),
    "approval_consequences": (
        "Approving records your operator identity and a signature over the "
        "diff. Approvals can be revoked, but not retroactively: any later "
        "audit will see that you approved this packet at this time."
    ),
    "reject_option": (
        "You can reject this packet. Rejection records the reason and "
        "discards the temp workspace. Nothing is changed in your repo."
    ),
    "evidence_trail_explanation": (
        "Every step in this flow is recorded under assurance/evidence/. "
        "Each lock manifest under locks/sentinel/ describes what the step "
        "proves and what it does NOT prove."
    ),
    "training_eligibility_notice": (
        "Nothing from this flow becomes training data. The corpus eligibility "
        "guard refuses to admit any output produced by a mocked, advisory, "
        "fixture, or temp-only step."
    ),
    "live_model_disclaimer": (
        "Even when a live local model is admitted, its output is treated as "
        "untrusted. The model can hallucinate code, misread your repo, or "
        "produce plausible-looking patches that fail the verifier."
    ),
    "no_blind_approval": (
        "Read the diff. Read the verifier output. If anything is unclear, reject the packet."
    ),
}


REQUIRED_SECTIONS = (
    "diagnosis_advisory",
    "patch_plan_untrusted",
    "verifier_result_explanation",
    "temp_workspace_explanation",
    "source_mutation_warning",
    "approval_consequences",
    "reject_option",
    "evidence_trail_explanation",
    "training_eligibility_notice",
    "live_model_disclaimer",
    "no_blind_approval",
)


_FORBIDDEN_PHRASES = (
    "always correct",
    "guaranteed to work",
    "risk-free",
    "trust the AI",
    "the model is always right",
    "blindly approve",
    "no need to read",
)


def all_copy() -> dict[str, str]:
    return dict(APPROVAL_UX_COPY)


def forbidden_phrases() -> tuple[str, ...]:
    return _FORBIDDEN_PHRASES


def required_sections() -> tuple[str, ...]:
    return REQUIRED_SECTIONS


__all__ = [
    "APPROVAL_UX_COPY",
    "REQUIRED_SECTIONS",
    "all_copy",
    "forbidden_phrases",
    "required_sections",
]
