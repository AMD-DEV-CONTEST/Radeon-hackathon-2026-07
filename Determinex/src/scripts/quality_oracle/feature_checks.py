"""feature_checks.py — Atomic, deterministic quality checks.

Each check is a pure function: (response, ...) → FeatureResult(passed, score, detail).
These are the decomposed units of preference score — the "atoms" that annotators
implicitly check when scoring a response.

Adding a new check: define a function matching the FeatureCheckFn signature
and register it in STANDARD_CHECKS or a custom rubric.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class FeatureResult:
    name: str
    passed: bool
    score: float  # 0.0-1.0 normalized score
    detail: str = ""  # Human-readable explanation (for feedback block)
    weight: float = 1.0  # Rubric weight (set by RubricDecomposer)


FeatureCheckFn = Callable[..., FeatureResult]


class FeatureChecker:
    """Run a set of feature checks against a response and aggregate results."""

    def __init__(self, checks: list[tuple[str, FeatureCheckFn, float]] | None = None):
        """
        Args:
            checks: List of (name, fn, weight). Defaults to STANDARD_CHECKS.
        """
        self.checks = checks or STANDARD_CHECKS

    def run(
        self,
        response: str,
        question: str = "",
        context: str = "",
        verifications: list | None = None,
    ) -> list[FeatureResult]:
        """Run all checks and return results."""
        results = []
        for name, fn, weight in self.checks:
            try:
                r = fn(
                    response=response,
                    question=question,
                    context=context,
                    verifications=verifications or [],
                )
                r.name = name
                r.weight = weight
                results.append(r)
            except Exception as e:
                results.append(
                    FeatureResult(
                        name=name,
                        passed=False,
                        score=0.0,
                        detail=f"check error: {e}",
                        weight=weight,
                    )
                )
        return results

    def aggregate_score(self, results: list[FeatureResult]) -> float:
        """Weighted average of feature scores."""
        total_weight = sum(r.weight for r in results)
        if total_weight == 0:
            return 0.0
        return sum(r.score * r.weight for r in results) / total_weight

    def failed_checks(self, results: list[FeatureResult]) -> list[FeatureResult]:
        return [r for r in results if not r.passed]


# ── Individual check functions ────────────────────────────────────────────────


def check_answers_question(response: str, question: str = "", **_) -> FeatureResult:
    """Does the response address the question/task?"""
    if not question:
        return FeatureResult("answers_question", True, 1.0, "no question provided")

    # Extract key terms from question (nouns, verbs — skip stopwords)
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "how",
        "why",
        "when",
        "where",
        "which",
        "who",
        "does",
        "do",
        "can",
        "could",
        "would",
        "should",
        "will",
    }
    q_words = {
        w.lower()
        for w in re.findall(r"\b\w+\b", question)
        if len(w) > 2 and w.lower() not in stopwords
    }
    r_words = {w.lower() for w in re.findall(r"\b\w+\b", response)}

    if not q_words:
        return FeatureResult("answers_question", True, 1.0, "")

    overlap = q_words & r_words
    score = len(overlap) / len(q_words)
    passed = score >= 0.4

    detail = (
        ""
        if passed
        else (
            f"Response may not address question. Key terms missing: "
            f"{', '.join(sorted(q_words - r_words)[:5])}"
        )
    )
    return FeatureResult("answers_question", passed, score, detail)


def check_no_hallucinations(response: str = "", verifications: list = None, **_) -> FeatureResult:
    """Are all factual claims supported by the knowledge base?"""
    if not verifications:
        return FeatureResult("no_hallucinations", True, 1.0, "no claims to verify")

    ungrounded = [v for v in verifications if not v.supported and not v.uncertain]
    uncertain = [v for v in verifications if v.uncertain]
    total = len(verifications)

    if total == 0:
        return FeatureResult("no_hallucinations", True, 1.0, "")

    hallucination_rate = len(ungrounded) / total
    score = 1.0 - hallucination_rate
    passed = len(ungrounded) == 0

    if not passed:
        claims_str = "; ".join(f'"{v.claim_text[:60]}"' for v in ungrounded[:3])
        detail = (
            f"{len(ungrounded)}/{total} claims not found in knowledge base: {claims_str}. "
            f"Verify these before asserting them."
        )
    elif uncertain:
        detail = f"{len(uncertain)} claims have weak KB support — double-check accuracy"
    else:
        detail = ""

    return FeatureResult("no_hallucinations", passed, score, detail)


def check_coherent_structure(response: str = "", **_) -> FeatureResult:
    """Is the response coherent and well-structured?"""
    if len(response) < 20:
        return FeatureResult("coherent_structure", False, 0.0, "response too short")

    issues = []

    # Check for repeated sentences (copy-paste artifacts)
    sentences = re.split(r"[.!?]+", response)
    sentences = [s.strip().lower() for s in sentences if len(s.strip()) > 20]
    if len(sentences) != len(set(sentences)) and len(sentences) > 2:
        issues.append("contains repeated sentences")

    # Check for unfinished sentences (ends mid-word or with comma)
    stripped = response.strip()
    if stripped and stripped[-1] not in ".!?\"`'":
        if len(stripped) > 100:  # not just a short label
            issues.append("response appears truncated")

    # Check for excessive repetition of a single word
    words = re.findall(r"\b\w{4,}\b", response.lower())
    if words:
        from collections import Counter

        common = Counter(words).most_common(1)[0]
        if common[1] > max(5, len(words) * 0.15):
            issues.append(f"word '{common[0]}' repeated excessively ({common[1]}x)")

    passed = len(issues) == 0
    score = max(0.0, 1.0 - len(issues) * 0.3)
    return FeatureResult("coherent_structure", passed, score, "; ".join(issues) if issues else "")


def check_appropriate_length(response: str = "", context: str = "", **_) -> FeatureResult:
    """Is response length appropriate for the task?"""
    words = len(re.findall(r"\b\w+\b", response))

    # Heuristic bounds — override per rubric as needed
    min_words, max_words = 10, 2000

    # If context hints at expected length, adjust
    if context:
        if "brief" in context.lower() or "short" in context.lower():
            max_words = 150
        elif "detailed" in context.lower() or "comprehensive" in context.lower():
            min_words = 100

    if words < min_words:
        return FeatureResult(
            "appropriate_length",
            False,
            words / min_words,
            f"Response too short ({words} words, min {min_words})",
        )
    if words > max_words:
        return FeatureResult(
            "appropriate_length",
            False,
            max_words / words,
            f"Response too long ({words} words, max {max_words})",
        )

    score = 1.0 - abs(words - (min_words + max_words) / 2) / (max_words - min_words)
    return FeatureResult("appropriate_length", True, max(0.5, score), "")


def check_no_refusal(response: str = "", **_) -> FeatureResult:
    """Does the response actually attempt to answer (not refuse)?"""
    refusal_patterns = [
        r"i (?:cannot|can't|am unable to|won't|will not) (?:help|assist|answer|provide)",
        r"(?:this|that) (?:is|would be) (?:inappropriate|unethical|harmful)",
        r"i (?:don't|do not) have (?:information|knowledge|access)",
        r"(?:as an ai|as a language model)",
    ]
    low = response.lower()
    for pat in refusal_patterns:
        if re.search(pat, low):
            return FeatureResult("no_refusal", False, 0.0, "Response appears to refuse the task")
    return FeatureResult("no_refusal", True, 1.0, "")


def check_grounded_in_context(response: str = "", context: str = "", **_) -> FeatureResult:
    """For RAG tasks: does the response draw from the provided context?"""
    if not context:
        return FeatureResult("grounded_in_context", True, 1.0, "no context provided")

    # Extract key noun phrases from context
    context_words = set(re.findall(r"\b[A-Za-z][a-z]{3,}\b", context))
    response_words = set(re.findall(r"\b[A-Za-z][a-z]{3,}\b", response))

    overlap = context_words & response_words
    if not context_words:
        return FeatureResult("grounded_in_context", True, 1.0, "")

    score = min(1.0, len(overlap) / max(10, len(context_words) * 0.1))
    passed = score >= 0.3

    detail = (
        ""
        if passed
        else (
            "Response doesn't appear to draw from the provided context. "
            "Use the context to ground your answer."
        )
    )
    return FeatureResult("grounded_in_context", passed, score, detail)


# ── Standard check registry ───────────────────────────────────────────────────
# (name, fn, default_weight)

STANDARD_CHECKS: list[tuple[str, FeatureCheckFn, float]] = [
    ("answers_question", check_answers_question, 2.0),
    ("no_hallucinations", check_no_hallucinations, 3.0),
    ("coherent_structure", check_coherent_structure, 1.0),
    ("appropriate_length", check_appropriate_length, 0.5),
    ("no_refusal", check_no_refusal, 2.0),
    ("grounded_in_context", check_grounded_in_context, 1.5),
]

CODE_CHECKS: list[tuple[str, FeatureCheckFn, float]] = [
    ("answers_question", check_answers_question, 1.0),
    ("no_hallucinations", check_no_hallucinations, 2.0),
    ("coherent_structure", check_coherent_structure, 0.5),
    ("no_refusal", check_no_refusal, 2.0),
]
