"""rubric_decomposer.py — Learn feature weights from a preference rubric.

Two modes:
  1. Zero-shot: given rubric text, use LLM to estimate feature importances
  2. Supervised: given (response, score) examples, fit sklearn LinearRegression

The output is a weight vector over FeatureChecker.STANDARD_CHECKS that
maximally predicts the preference score from atomic feature results.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RubricWeights:
    feature_names: list[str]
    weights: list[float]  # Parallel to feature_names
    intercept: float = 0.0
    source: str = "zero_shot"  # "zero_shot" | "supervised"
    r2: float = 0.0  # R² on training data (supervised only)

    def weight_for(self, feature_name: str) -> float:
        try:
            idx = self.feature_names.index(feature_name)
            return self.weights[idx]
        except ValueError:
            return 1.0


_WEIGHT_TOOL = {
    "name": "estimate_rubric_weights",
    "description": "Estimate importance weights for quality features given a rubric",
    "input_schema": {
        "type": "object",
        "properties": {
            "weights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string"},
                        "weight": {"type": "number", "description": "Importance 0.0-3.0"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["feature", "weight", "rationale"],
                },
            },
            "intercept": {"type": "number", "description": "Base score offset"},
        },
        "required": ["weights"],
    },
}


class RubricDecomposer:
    """Decompose a preference rubric into weighted feature checks."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def from_text_zero_shot(
        self,
        rubric_text: str,
        feature_names: list[str] | None = None,
    ) -> RubricWeights:
        """Use LLM to estimate feature importance from rubric text.

        Args:
            rubric_text: Natural language description of the rubric/criteria
            feature_names: Features to weight. Defaults to STANDARD_CHECKS names.
        """
        import anthropic

        from .feature_checks import STANDARD_CHECKS

        if feature_names is None:
            feature_names = [name for name, _, _ in STANDARD_CHECKS]

        features_str = "\n".join(f"- {f}" for f in feature_names)
        user_msg = (
            f"Given this evaluation rubric:\n\n{rubric_text}\n\n"
            f"Estimate the importance weight (0.0 = irrelevant, 3.0 = critical) "
            f"for each of these quality features:\n{features_str}\n\n"
            f"Weight them relative to each other based on what the rubric prioritizes."
        )

        try:
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=self.model,
                max_tokens=1024,
                tools=[_WEIGHT_TOOL],
                tool_choice={"type": "tool", "name": "estimate_rubric_weights"},
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:
            print(f"  [rubric_decomposer] API error: {e}; using uniform weights")
            return RubricWeights(
                feature_names=feature_names,
                weights=[1.0] * len(feature_names),
                source="fallback_uniform",
            )

        weights = [1.0] * len(feature_names)
        intercept = 0.0

        for block in msg.content:
            if block.type == "tool_use" and block.name == "estimate_rubric_weights":
                intercept = block.input.get("intercept", 0.0)
                for entry in block.input.get("weights", []):
                    feat = entry.get("feature", "")
                    w = float(entry.get("weight", 1.0))
                    if feat in feature_names:
                        weights[feature_names.index(feat)] = w
                break

        return RubricWeights(
            feature_names=feature_names, weights=weights, intercept=intercept, source="zero_shot"
        )

    def from_examples(
        self,
        examples: list[dict],
        feature_names: list[str] | None = None,
    ) -> RubricWeights:
        """Fit a linear model from (response, score, features) examples.

        Args:
            examples: List of {"response": str, "score": float, "features": {name: float}}
                      where features are pre-computed FeatureResult.score values.
            feature_names: Feature names in examples["features"]. Auto-detected if None.
        """
        try:
            import numpy as np
            from sklearn.linear_model import Ridge
            from sklearn.metrics import r2_score
        except ImportError:
            print("  [rubric_decomposer] sklearn not available; using uniform weights")
            from .feature_checks import STANDARD_CHECKS

            names = feature_names or [n for n, _, _ in STANDARD_CHECKS]
            return RubricWeights(
                feature_names=names, weights=[1.0] * len(names), source="fallback_uniform"
            )

        if not examples:
            raise ValueError("Need at least one example")

        if feature_names is None:
            feature_names = list(examples[0]["features"].keys())

        X = np.array([[ex["features"].get(f, 0.0) for f in feature_names] for ex in examples])
        y = np.array([ex["score"] for ex in examples])

        model = Ridge(alpha=1.0)
        model.fit(X, y)
        y_pred = model.predict(X)
        r2 = float(r2_score(y, y_pred)) if len(y) > 1 else 0.0

        weights = model.coef_.tolist()
        intercept = float(model.intercept_)

        print(f"  [rubric_decomposer] fitted on {len(examples)} examples, R²={r2:.3f}")
        return RubricWeights(
            feature_names=feature_names,
            weights=weights,
            intercept=intercept,
            source="supervised",
            r2=r2,
        )


# ── Pre-built rubrics for common benchmarks ───────────────────────────────────

MT_BENCH_RUBRIC = """
MT-Bench evaluates assistant responses on:
1. Helpfulness (most important): Does the response solve the user's problem completely?
2. Accuracy: Are all stated facts correct? No hallucinations.
3. Depth: Does the response go beyond surface-level? Provides examples, edge cases.
4. Coherence: Well-structured, logical flow, clear language.
5. Safety: No harmful content (lower weight for general tasks).
Score is 1-10, with helpfulness and accuracy driving >60% of the score.
"""

HUMANEVAL_RUBRIC = """
HumanEval evaluates code solutions on:
1. Correctness (critical): Does the code pass all test cases?
2. No hallucinated APIs: Only uses real Python stdlib or specified libraries.
3. Handles edge cases: Empty input, boundary conditions.
4. Efficiency: Not catastrophically slow (no O(n³) for large n).
Pass/fail is binary but quality within passing solutions matters for partial credit.
"""

FACTUAL_QA_RUBRIC = """
Factual QA evaluates on:
1. Factual accuracy (most important): All claims must be supported by source material.
2. Completeness: Answers the full question, not just part of it.
3. No invented details: Hallucinated specifics (dates, names, numbers) are heavily penalized.
4. Grounding: Response should cite or reference the provided context.
5. Conciseness: Answers should be complete but not padded.
"""
