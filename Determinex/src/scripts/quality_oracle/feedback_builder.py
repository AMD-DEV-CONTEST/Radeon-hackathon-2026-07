"""feedback_builder.py — Convert oracle results into actionable retry prompts.

The feedback block is drop-in compatible with EvalResult.feedback_block() so
the same retry loop handles both code tasks (compiler oracle) and language
tasks (quality oracle) without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .feature_checks import FeatureResult
    from .rag_verifier import ClaimVerification


def build_feedback_block(
    verifications: list[ClaimVerification],
    feature_results: list[FeatureResult],
    score: float,
    prev_score: float | None = None,
    attempt: int = 1,
    max_hallucinations: int = 5,
    max_feature_fails: int = 5,
) -> str:
    """Build a retry prompt from oracle results.

    Args:
        verifications: Claim verification results (hallucination candidates)
        feature_results: Atomic feature check results
        score: Current oracle score (0.0-1.0)
        prev_score: Previous attempt's score (for regression context)
        attempt: Current attempt number
        max_hallucinations: Max ungrounded claims to include in feedback
        max_feature_fails: Max failed features to include

    Returns:
        Formatted retry prompt string (same structure as EvalResult.feedback_block)
    """
    parts = []
    pct = int(score * 100)

    # Header
    if prev_score is not None:
        prev_pct = int(prev_score * 100)
        delta = pct - prev_pct
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
        parts.append(f"Quality score: {pct}% ({arrow}{abs(delta)} pts from attempt {attempt - 1})")
    else:
        parts.append(f"Quality score: {pct}% (attempt {attempt})")

    parts.append("")

    # ── Hallucination failures (highest priority) ─────────────────────────────
    ungrounded = [v for v in verifications if not v.supported and not v.uncertain]
    if ungrounded:
        parts.append(f"## HALLUCINATION FAILURES ({len(ungrounded)} ungrounded claims)")
        parts.append(
            "These claims are NOT supported by the knowledge base. "
            "Either remove them or ground them in the provided context:\n"
        )
        for i, v in enumerate(ungrounded[:max_hallucinations]):
            parts.append(f'  [{i + 1}] Claim: "{v.claim_text}"')
            parts.append(f"       KB similarity: {v.similarity:.2f} (threshold: 0.72)")
            if v.evidence:
                parts.append(f'       Closest KB match: "{v.evidence[:150]}"')
                parts.append("       → If this is what you meant, rephrase to match the source")
            parts.append("")

    # ── Uncertain claims (warn but don't block) ───────────────────────────────
    uncertain = [v for v in verifications if v.uncertain]
    if uncertain:
        parts.append(f"## WEAK EVIDENCE ({len(uncertain)} claims with low KB support)")
        for v in uncertain[:3]:
            parts.append(f'  - "{v.claim_text[:80]}" (similarity: {v.similarity:.2f})')
        parts.append("")

    # ── Feature check failures ────────────────────────────────────────────────
    failed_features = [r for r in feature_results if not r.passed]
    if failed_features:
        parts.append(f"## QUALITY CHECK FAILURES ({len(failed_features)} checks failed)")
        for r in sorted(failed_features, key=lambda x: -x.weight)[:max_feature_fails]:
            pct_score = int(r.score * 100)
            parts.append(f"  ✗ {r.name} [{pct_score}%]: {r.detail}")
        parts.append("")

    # ── Passing checks (for context) ─────────────────────────────────────────
    passing = [r for r in feature_results if r.passed]
    if passing:
        names = ", ".join(r.name for r in passing[:6])
        parts.append(f"## PASSING ({len(passing)} checks): {names}")
        parts.append("")

    # ── Fix directive ─────────────────────────────────────────────────────────
    if ungrounded or failed_features:
        parts.append("## YOUR TASK FOR THE NEXT ATTEMPT")
        if ungrounded:
            parts.append(f"1. Remove or correct the {len(ungrounded)} ungrounded claim(s) above")
        if failed_features:
            failed_names = [r.name for r in failed_features[:3]]
            parts.append(f"2. Fix these quality issues: {', '.join(failed_names)}")
        parts.append("3. Do NOT change anything that is already correct")
        parts.append("4. Keep your answer grounded in the provided context/source material")

    return "\n".join(parts)


def build_regression_feedback(
    best_feedback: str,
    current_score: float,
    best_score: float,
    attempt: int,
) -> str:
    """Build feedback block when current attempt regressed from best."""
    best_pct = int(best_score * 100)
    curr_pct = int(current_score * 100)
    delta = best_pct - curr_pct

    header = (
        f"⚠ REGRESSION: This attempt scored {curr_pct}%, down from best {best_pct}% "
        f"({delta} pts lost). Best submission RESTORED.\n"
        f"Your task: fix the {best_pct}% submission's REMAINING failures below.\n"
        f"Do NOT touch anything that was passing in the {best_pct}% run.\n\n"
    )
    return header + best_feedback
