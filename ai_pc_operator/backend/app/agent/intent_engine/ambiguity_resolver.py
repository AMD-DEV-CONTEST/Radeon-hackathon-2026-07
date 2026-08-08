"""Ambiguity Resolution — handles cases where intent is unclear.

When multiple intents score similarly, or when the confidence is low,
the AmbiguityResolver decides what to do:

  - DISAMBIGUATE: ask the user to clarify (returns a clarification question)
  - PICK_BEST: pick the highest-scoring intent and proceed
  - MULTI_INTENT: split into multiple intents and execute in sequence
  - REJECT: refuse to act (confidence too low)

Strategies:
  1. If top-2 scores are within 15% → DISAMBIGUATE
  2. If text contains multi-intent separators → MULTI_INTENT
  3. If confidence is "high" → PICK_BEST
  4. If confidence is "medium" → PICK_BEST with logging
  5. If confidence is "low" → DISAMBIGUATE
  6. If confidence is "reject" → REJECT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .confidence_scorer import ConfidenceScore
from .intent_detector import IntentCandidate


@dataclass
class AmbiguityResolution:
    """Result of ambiguity resolution."""
    strategy: str  # "pick_best" | "disambiguate" | "multi_intent" | "reject"
    chosen_intent: Optional[str] = None
    chosen_score: Optional[ConfidenceScore] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    clarification_question: Optional[str] = None
    clarification_options: List[Dict[str, str]] = field(default_factory=list)
    multi_intents: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "chosen_intent": self.chosen_intent,
            "chosen_score": self.chosen_score.to_dict() if self.chosen_score else None,
            "alternatives": self.alternatives,
            "clarification_question": self.clarification_question,
            "clarification_options": self.clarification_options,
            "multi_intents": self.multi_intents,
            "reason": self.reason,
        }


class AmbiguityResolver:
    """Resolves ambiguous intent decisions."""

    # Score ratio threshold: if top2/top1 > this, consider ambiguous
    AMBIGUITY_RATIO = 0.85

    # Templates for clarification questions per intent
    CLARIFICATION_TEMPLATES = {
        "open_website": "Did you mean to open a website? Which one?",
        "open_app": "Which application should I open?",
        "search_web": "What would you like to search for?",
        "delete_files": "Which files should I delete?",
        "list_files": "Which folder should I list?",
        "screen_click": "What should I click?",
        "login": "Which site should I log into?",
        "download_file": "What file should I download?",
    }

    def __init__(self, ambiguity_ratio: Optional[float] = None):
        self.AMBIGUITY_RATIO = ambiguity_ratio or self.AMBIGUITY_RATIO

    def resolve(
        self,
        candidates: List[IntentCandidate],
        scores: List[ConfidenceScore],
        text: str,
        has_multi_intent_separators: bool = False,
    ) -> AmbiguityResolution:
        """Resolve ambiguity among candidates.

        Args:
            candidates: ranked intent candidates
            scores: confidence scores for each candidate
            text: original user text
            has_multi_intent_separators: whether text contains "and", "then", etc.
        """
        if not candidates or not scores:
            return AmbiguityResolution(
                strategy="reject",
                reason="no_candidates",
            )

        top_score = scores[0]

        # 1. Multi-intent: split and execute sequentially
        if has_multi_intent_separators and len(candidates) >= 2:
            return self._resolve_multi_intent(candidates, scores, text)

        # 2. Reject if confidence is too low
        if top_score.decision == "reject":
            return AmbiguityResolution(
                strategy="reject",
                chosen_score=top_score,
                reason="confidence_too_low",
            )

        # 3. Disambiguate if top-2 are close
        if len(scores) >= 2:
            second = scores[1]
            if top_score.score > 0 and second.score > 0:
                ratio = second.score / top_score.score
                if ratio >= self.AMBIGUITY_RATIO and top_score.decision in ("low", "medium"):
                    return self._resolve_disambiguate(candidates, scores, text)

        # 4. Disambiguate if decision is "low"
        if top_score.decision == "low":
            return self._resolve_disambiguate(candidates, scores, text)

        # 5. Pick best (high or medium confidence)
        return AmbiguityResolution(
            strategy="pick_best",
            chosen_intent=top_score.intent,
            chosen_score=top_score,
            alternatives=[
                {"intent": s.intent, "score": round(s.score, 3)}
                for s in scores[1:4]
            ],
            reason=f"confidence_{top_score.decision}",
        )

    def _resolve_disambiguate(
        self,
        candidates: List[IntentCandidate],
        scores: List[ConfidenceScore],
        text: str,
    ) -> AmbiguityResolution:
        """Build a clarification question for the user."""
        top = scores[0]
        question = self.CLARIFICATION_TEMPLATES.get(
            top.intent,
            f"Did you mean to {top.intent.replace('_', ' ')}?",
        )

        options = []
        for s in scores[:4]:
            options.append({
                "label": s.intent.replace("_", " "),
                "value": s.intent,
                "score": round(s.score, 3),
            })

        return AmbiguityResolution(
            strategy="disambiguate",
            chosen_score=top,
            alternatives=[
                {"intent": s.intent, "score": round(s.score, 3)}
                for s in scores[1:4]
            ],
            clarification_question=question,
            clarification_options=options,
            reason="ambiguous_top_candidates",
        )

    def _resolve_multi_intent(
        self,
        candidates: List[IntentCandidate],
        scores: List[ConfidenceScore],
        text: str,
    ) -> AmbiguityResolution:
        """Split into multiple intents and execute sequentially."""
        multi_intents = []
        for cand, score in zip(candidates[:3], scores[:3]):
            if score.score > 0.3:
                multi_intents.append({
                    "intent": cand.intent,
                    "score": round(score.score, 3),
                })

        return AmbiguityResolution(
            strategy="multi_intent",
            chosen_intent=multi_intents[0]["intent"] if multi_intents else None,
            chosen_score=scores[0] if scores else None,
            multi_intents=multi_intents,
            reason="multi_intent_detected",
        )
