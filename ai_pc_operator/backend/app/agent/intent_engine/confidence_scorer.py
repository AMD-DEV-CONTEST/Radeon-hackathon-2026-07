"""Confidence Scoring — assigns a final confidence score to intent decisions.

Combines multiple signals into a single 0.0-1.0 confidence score:
  - Pattern match strength (from IntentDetector)
  - Entity coverage (do we have all required entities?)
  - Context consistency (does this match recent commands?)
  - Negation penalty (was the intent negated?)
  - Ambiguity penalty (multiple intents tied?)
  - Length penalty (very short commands are less confident)

The scorer also produces a "decision" — one of:
  - "high"   : score >= 0.8, proceed without confirmation
  - "medium" : 0.5 <= score < 0.8, proceed but log
  - "low"    : 0.3 <= score < 0.5, ask user to confirm
  - "reject" : score < 0.3, refuse or ask for clarification
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .intent_detector import IntentCandidate
from .entity_extractor import Entity
from .parameter_extractor import ParamExtractionResult


@dataclass
class ConfidenceScore:
    """Final confidence score with breakdown."""
    intent: str
    score: float
    decision: str  # "high" | "medium" | "low" | "reject"
    breakdown: Dict[str, float]
    reasons: List[str]
    alternatives: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "score": round(self.score, 3),
            "decision": self.decision,
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
            "reasons": self.reasons,
            "alternatives": self.alternatives,
        }


class ConfidenceScorer:
    """Computes confidence scores for intent decisions."""

    # Decision thresholds
    THRESHOLD_HIGH = 0.8
    THRESHOLD_MEDIUM = 0.5
    THRESHOLD_LOW = 0.3

    # Component weights (must sum to 1.0)
    WEIGHTS = {
        "pattern": 0.40,
        "entity_coverage": 0.25,
        "context": 0.15,
        "negation": 0.10,
        "ambiguity": 0.10,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        if weights:
            total = sum(weights.values())
            self.WEIGHTS = {k: v / total for k, v in weights.items()}

    def score(
        self,
        candidates: List[IntentCandidate],
        entities: List[Entity],
        param_result: ParamExtractionResult,
        text: str,
        context_consistency: float = 1.0,
    ) -> ConfidenceScore:
        """Compute confidence for the top candidate.

        Args:
            candidates: ranked intent candidates from IntentDetector
            entities: extracted entities
            param_result: parameter extraction result
            text: original user text
            context_consistency: 0.0-1.0, how well this matches recent context
        """
        if not candidates:
            return ConfidenceScore(
                intent="unknown",
                score=0.0,
                decision="reject",
                breakdown={},
                reasons=["no_intent_matched"],
                alternatives=[],
            )

        top = candidates[0]
        alternatives = [
            {"intent": c.intent, "score": round(c.score, 3)}
            for c in candidates[1:4]
        ]

        breakdown: Dict[str, float] = {}
        reasons: List[str] = []

        # 1. Pattern score (normalize top score)
        # Top score is sum of pattern weights; normalize by assuming max ~3.0
        pattern_raw = max(0.0, top.score)
        pattern_score = min(1.0, pattern_raw / 3.0)
        breakdown["pattern"] = pattern_score
        if pattern_score >= 0.8:
            reasons.append("strong_pattern_match")
        elif pattern_score >= 0.5:
            reasons.append("moderate_pattern_match")
        else:
            reasons.append("weak_pattern_match")

        # 2. Entity coverage
        # How many required params were filled?
        required_total = len([p for p in param_result.params]) + len(param_result.missing)
        if required_total == 0:
            entity_score = 1.0  # no required params
        else:
            filled = len(param_result.params)
            entity_score = filled / required_total
        breakdown["entity_coverage"] = entity_score
        if param_result.missing:
            reasons.append(f"missing_params:{','.join(param_result.missing)}")

        # 3. Context consistency
        context_score = max(0.0, min(1.0, context_consistency))
        breakdown["context"] = context_score
        if context_score < 0.5:
            reasons.append("context_mismatch")

        # 4. Negation penalty
        if top.score < 0:
            negation_score = 0.0
            reasons.append("negated")
        else:
            negation_score = 1.0
        breakdown["negation"] = negation_score

        # 5. Ambiguity penalty
        # If the second candidate is close to the top, penalize
        if len(candidates) > 1:
            second = candidates[1]
            if second.score > 0 and top.score > 0:
                ratio = second.score / top.score
                ambiguity_score = max(0.0, 1.0 - ratio)
                if ratio > 0.7:
                    reasons.append(f"ambiguous_with:{second.intent}")
            else:
                ambiguity_score = 1.0
        else:
            ambiguity_score = 1.0
        breakdown["ambiguity"] = ambiguity_score

        # Weighted sum
        final = sum(breakdown[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        # Length penalty: very short commands (< 3 words) get a small penalty
        word_count = len(text.split())
        if word_count < 3:
            length_penalty = 0.85
            final *= length_penalty
            reasons.append("short_command")

        # Clamp
        final = max(0.0, min(1.0, final))

        # Decision
        if final >= self.THRESHOLD_HIGH:
            decision = "high"
        elif final >= self.THRESHOLD_MEDIUM:
            decision = "medium"
        elif final >= self.THRESHOLD_LOW:
            decision = "low"
        else:
            decision = "reject"

        return ConfidenceScore(
            intent=top.intent,
            score=final,
            decision=decision,
            breakdown=breakdown,
            reasons=reasons,
            alternatives=alternatives,
        )

    def score_all(
        self,
        candidates: List[IntentCandidate],
        entities: List[Entity],
        param_results: Dict[str, ParamExtractionResult],
        text: str,
        context_consistency: float = 1.0,
    ) -> List[ConfidenceScore]:
        """Score all candidates (for ambiguity resolution)."""
        scores = []
        for cand in candidates:
            param_result = param_results.get(cand.intent) or ParamExtractionResult(params={})
            # Temporarily swap candidates
            score = self.score([cand], entities, param_result, text, context_consistency)
            scores.append(score)
        return scores
