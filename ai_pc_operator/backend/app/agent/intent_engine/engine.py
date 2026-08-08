"""Intent Engine — orchestrator that ties all 6 stages together.

Pipeline:
  1. Intent Detection       → candidate intents with raw scores
  2. Entity Extraction      → typed entities from text
  3. Parameter Extraction   → typed tool parameters
  4. Context Resolution     → fill gaps using prior context
  5. Confidence Scoring     → final 0.0-1.0 score + decision
  6. Ambiguity Resolution   → pick_best | disambiguate | multi_intent | reject

The engine returns a single IntentResult that contains everything the
Planner needs to build an execution plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .intent_detector import IntentDetector, IntentCandidate
from .entity_extractor import EntityExtractor, Entity
from .parameter_extractor import ParameterExtractor, ParamExtractionResult
from .context_resolver import ContextResolver, ContextEntry, ResolutionResult
from .confidence_scorer import ConfidenceScorer, ConfidenceScore
from .ambiguity_resolver import AmbiguityResolver, AmbiguityResolution


@dataclass
class IntentResult:
    """Final result of the Intent Engine pipeline."""
    text: str
    intent: str
    confidence: float
    decision: str  # "high" | "medium" | "low" | "reject"
    params: Dict[str, Any]
    entities: List[Entity]
    candidates: List[IntentCandidate]
    scores: List[ConfidenceScore]
    ambiguity: AmbiguityResolution
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    clarification_options: List[Dict[str, Any]] = field(default_factory=list)
    multi_intents: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "decision": self.decision,
            "params": self.params,
            "entities": [e.to_dict() for e in self.entities],
            "candidates": [
                {"intent": c.intent, "score": round(c.score, 3),
                 "matched_patterns": c.matched_patterns}
                for c in self.candidates
            ],
            "scores": [s.to_dict() for s in self.scores],
            "ambiguity": self.ambiguity.to_dict(),
            "resolutions": self.resolutions,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "clarification_options": self.clarification_options,
            "multi_intents": self.multi_intents,
        }


class IntentEngine:
    """The full Intent Engine pipeline."""

    MULTI_INTENT_SEPARATORS = [
        r"\band then\b", r"\bthen\b", r"\bafter that\b",
        r"\bafterwards\b", r"\band\b", r"\balso\b",
        r"\bplus\b",
    ]

    def __init__(
        self,
        detector: Optional[IntentDetector] = None,
        entity_extractor: Optional[EntityExtractor] = None,
        param_extractor: Optional[ParameterExtractor] = None,
        context_resolver: Optional[ContextResolver] = None,
        confidence_scorer: Optional[ConfidenceScorer] = None,
        ambiguity_resolver: Optional[AmbiguityResolver] = None,
    ):
        self.detector = detector or IntentDetector()
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.param_extractor = param_extractor or ParameterExtractor(self.entity_extractor)
        self.context_resolver = context_resolver or ContextResolver()
        self.scorer = confidence_scorer or ConfidenceScorer()
        self.ambiguity_resolver = ambiguity_resolver or AmbiguityResolver()

    def process(self, text: str) -> IntentResult:
        """Run the full Intent Engine pipeline on user text.

        Returns an IntentResult with the chosen intent, params, confidence,
        and any clarification needs.
        """
        # Stage 1: Intent Detection
        candidates = self.detector.detect(text)
        has_multi = self._has_multi_intent_separators(text)

        # Stage 2: Entity Extraction
        entities = self.entity_extractor.extract(text)

        # Stage 3: Parameter Extraction (for top candidate)
        top_intent = candidates[0].intent if candidates else "unknown"
        param_result = self.param_extractor.extract(text, top_intent)

        # Stage 4: Context Resolution
        context_consistency = self._compute_context_consistency(top_intent)
        resolution = self.context_resolver.resolve(text, top_intent, param_result.params)
        resolved_params = resolution.resolved_params

        # Stage 5: Confidence Scoring
        score = self.scorer.score(
            candidates=candidates,
            entities=entities,
            param_result=ParamExtractionResult(
                params=resolved_params,
                missing=param_result.missing,
                errors=param_result.errors,
                used_entities=param_result.used_entities,
            ),
            text=text,
            context_consistency=context_consistency,
        )

        # Score alternatives too (for ambiguity resolution)
        all_scores = [score]
        for cand in candidates[1:4]:
            alt_param = self.param_extractor.extract(text, cand.intent)
            alt_score = self.scorer.score(
                candidates=[cand],
                entities=entities,
                param_result=alt_param,
                text=text,
                context_consistency=context_consistency,
            )
            all_scores.append(alt_score)

        # Stage 6: Ambiguity Resolution
        ambiguity = self.ambiguity_resolver.resolve(
            candidates=candidates,
            scores=all_scores,
            text=text,
            has_multi_intent_separators=has_multi,
        )

        # Build result
        result = IntentResult(
            text=text,
            intent=ambiguity.chosen_intent or top_intent,
            confidence=score.score,
            decision=score.decision,
            params=resolved_params,
            entities=entities,
            candidates=candidates,
            scores=all_scores,
            ambiguity=ambiguity,
            resolutions=resolution.resolutions,
            needs_clarification=(ambiguity.strategy == "disambiguate"),
            clarification_question=ambiguity.clarification_question,
            clarification_options=ambiguity.clarification_options,
            multi_intents=ambiguity.multi_intents,
        )

        # Record in context history
        self.context_resolver.add_entry(ContextEntry(
            text=text,
            intent=result.intent,
            params=resolved_params,
            entities=[e.to_dict() for e in entities],
        ))

        return result

    def record_result(self, intent: str, result: Any) -> None:
        """Record the result of executing an intent (for context)."""
        if self.context_resolver.history:
            self.context_resolver.history[-1].result = result

    def _has_multi_intent_separators(self, text: str) -> bool:
        """Check if text contains multi-intent separators."""
        text_lower = text.lower()
        for sep in self.MULTI_INTENT_SEPARATORS:
            if re.search(sep, text_lower):
                return True
        return False

    def _compute_context_consistency(self, intent: str) -> float:
        """Compute how consistent the intent is with recent context."""
        if not self.context_resolver.history:
            return 1.0
        last = self.context_resolver.history[-1]
        if last.intent == intent:
            return 1.0
        # Check related intents
        related_groups = [
            {"open_website", "browser_close", "search_web", "download_file", "login"},
            {"open_app", "browser_close"},
            {"list_files", "delete_files"},
            {"screen_scan", "screen_click"},
        ]
        for group in related_groups:
            if intent in group and last.intent in group:
                return 0.7
        return 0.4
