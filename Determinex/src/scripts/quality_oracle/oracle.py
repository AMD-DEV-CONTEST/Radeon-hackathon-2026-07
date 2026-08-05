"""oracle.py — QualityOracle: the main entry point.

Drop-in analog to the compiler oracle for language/preference tasks.
score() returns an OracleResult whose feedback_block() matches the
interface expected by the retry loop.

Usage:
    oracle = QualityOracle(rubric=FACTUAL_QA_RUBRIC)

    # In the retry loop:
    result = oracle.score(response, context=source_chunks, question=task_prompt)
    print(f"Score: {result.score:.2f}")
    if not result.solved:
        retry_prompt = result.feedback_block()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .claim_extractor import Claim, ClaimExtractor
from .feature_checks import CODE_CHECKS, FeatureChecker, FeatureResult
from .feedback_builder import build_feedback_block, build_regression_feedback
from .rag_verifier import ClaimVerification, RagVerifier
from .rubric_decomposer import RubricDecomposer, RubricWeights


@dataclass
class OracleResult:
    """Result of a quality oracle evaluation. Mirrors EvalResult interface."""

    score: float  # 0.0-1.0 normalized quality score
    score_pct: int = 0  # Integer 0-100 for display
    solved: bool = False  # True if score >= solve_threshold
    attempt: int = 1

    claims: list[Claim] = field(default_factory=list)
    verifications: list[ClaimVerification] = field(default_factory=list)
    feature_results: list[FeatureResult] = field(default_factory=list)

    hallucination_count: int = 0
    failed_feature_count: int = 0

    _feedback: str = field(default="", repr=False)
    elapsed_s: float = 0.0

    def __post_init__(self):
        self.score_pct = int(self.score * 100)
        self.hallucination_count = sum(
            1 for v in self.verifications if not v.supported and not v.uncertain
        )
        self.failed_feature_count = sum(1 for r in self.feature_results if not r.passed)

    def feedback_block(self) -> str:
        return self._feedback

    def summary(self) -> str:
        lines = [
            f"Score: {self.score_pct}%  |  "
            f"Hallucinations: {self.hallucination_count}  |  "
            f"Feature failures: {self.failed_feature_count}  |  "
            f"Claims checked: {len(self.verifications)}"
        ]
        return "\n".join(lines)


class QualityOracle:
    """Deterministic quality oracle for language and preference benchmarks.

    Combines:
      1. Claim extraction (factual assertions in the response)
      2. RAG verification (are those assertions supported by the KB?)
      3. Feature checks (atomic quality dimensions)
      4. Weighted aggregation → score
      5. Feedback block generation → retry prompt

    Args:
        rubric: Rubric text or pre-built RubricWeights. If a string, weights
                are estimated zero-shot from the text.
        feature_checker: Custom FeatureChecker. Defaults to STANDARD_CHECKS.
        rag_verifier: Custom RagVerifier. Defaults to global KB.
        claim_extractor: Custom ClaimExtractor.
        solve_threshold: Score above which the task is considered solved.
        verify_claims: If False, skip RAG verification (faster, less accurate).
        inline_context: If True, verify claims against provided context chunks
                        instead of the global KB (for task-specific grounding).
    """

    def __init__(
        self,
        rubric: str | RubricWeights | None = None,
        feature_checker: FeatureChecker | None = None,
        rag_verifier: RagVerifier | None = None,
        claim_extractor: ClaimExtractor | None = None,
        solve_threshold: float = 0.85,
        verify_claims: bool = True,
        inline_context: bool = False,
    ):
        self.extractor = claim_extractor or ClaimExtractor()
        self.verifier = rag_verifier or RagVerifier()
        self.checker = feature_checker or FeatureChecker()
        self.solve_threshold = solve_threshold
        self.verify_claims = verify_claims
        self.inline_context = inline_context

        # Resolve rubric → weights
        if rubric is None:
            self.weights = None
        elif isinstance(rubric, RubricWeights):
            self.weights = rubric
        else:
            decomposer = RubricDecomposer()
            self.weights = decomposer.from_text_zero_shot(rubric)
            if self.weights:
                print(
                    f"  [oracle] rubric decomposed: {len(self.weights.weights)} features weighted"
                )

        # Apply rubric weights to feature checker
        if self.weights and self.checker:
            weighted_checks = []
            for name, fn, default_w in self.checker.checks:
                w = self.weights.weight_for(name) if self.weights else default_w
                weighted_checks.append((name, fn, w))
            self.checker = FeatureChecker(weighted_checks)

    def score(
        self,
        response: str,
        question: str = "",
        context: str = "",
        context_chunks: list[str] | None = None,
        attempt: int = 1,
        prev_result: OracleResult | None = None,
    ) -> OracleResult:
        """Evaluate a response and return an OracleResult.

        Args:
            response: The model's response to evaluate
            question: The original task/question (for relevance checking)
            context: String context provided to the model (for grounding check)
            context_chunks: List of source chunks (for inline verification)
            attempt: Current attempt number
            prev_result: Previous attempt's result (for regression detection)
        """
        t0 = time.time()
        claims: list[Claim] = []
        verifications: list[ClaimVerification] = []

        # 1. Extract and verify claims
        if self.verify_claims and response.strip():
            print("  [oracle] extracting claims...", end=" ", flush=True)
            claims = self.extractor.extract(response, task_context=question)
            print(f"{len(claims)} found", flush=True)

            if claims:
                print(f"  [oracle] verifying {len(claims)} claims...", end=" ", flush=True)
                if self.inline_context and context_chunks:
                    verifications = self.verifier.verify_inline(response, context_chunks)
                else:
                    verifications = self.verifier.verify_all(claims)
                hall = sum(1 for v in verifications if not v.supported and not v.uncertain)
                print(f"done ({hall} ungrounded)", flush=True)

        # 2. Run feature checks
        feature_results = self.checker.run(
            response=response,
            question=question,
            context=context,
            verifications=verifications,
        )

        # 3. Aggregate score
        feature_score = self.checker.aggregate_score(feature_results)

        # Hallucination penalty: each ungrounded claim reduces score
        hall_count = sum(1 for v in verifications if not v.supported and not v.uncertain)
        hall_penalty = min(0.5, hall_count * 0.1)  # max 50% penalty from hallucinations

        raw_score = max(0.0, feature_score - hall_penalty)
        score = round(raw_score, 4)

        # 4. Build feedback block
        feedback = build_feedback_block(
            verifications=verifications,
            feature_results=feature_results,
            score=score,
            prev_score=prev_result.score if prev_result else None,
            attempt=attempt,
        )

        result = OracleResult(
            score=score,
            solved=score >= self.solve_threshold,
            attempt=attempt,
            claims=claims,
            verifications=verifications,
            feature_results=feature_results,
            _feedback=feedback,
            elapsed_s=round(time.time() - t0, 1),
        )
        return result

    def score_with_regression_check(
        self,
        response: str,
        best_result: OracleResult | None,
        attempt: int,
        **kwargs,
    ) -> tuple[OracleResult, bool]:
        """Score and detect regression vs. best result.

        Returns (result, is_regression).
        If regressed, result._feedback is updated to use best's failures as targets.
        """
        result = self.score(response, attempt=attempt, **kwargs)

        if best_result is not None and result.score < best_result.score:
            # Regression: override feedback to point at best's failures
            result._feedback = build_regression_feedback(
                best_feedback=best_result.feedback_block(),
                current_score=result.score,
                best_score=best_result.score,
                attempt=attempt,
            )
            return result, True

        return result, False

    @classmethod
    def for_code_tasks(cls, **kwargs) -> QualityOracle:
        """Pre-configured oracle for code generation tasks."""
        from .rubric_decomposer import HUMANEVAL_RUBRIC

        return cls(rubric=HUMANEVAL_RUBRIC, feature_checker=FeatureChecker(CODE_CHECKS), **kwargs)

    @classmethod
    def for_factual_qa(cls, **kwargs) -> QualityOracle:
        """Pre-configured oracle for factual question answering."""
        from .rubric_decomposer import FACTUAL_QA_RUBRIC

        return cls(rubric=FACTUAL_QA_RUBRIC, verify_claims=True, **kwargs)

    @classmethod
    def for_mt_bench(cls, **kwargs) -> QualityOracle:
        """Pre-configured oracle for MT-Bench style evaluation."""
        from .rubric_decomposer import MT_BENCH_RUBRIC

        return cls(rubric=MT_BENCH_RUBRIC, **kwargs)
