"""Intent Engine — 6-stage pipeline for understanding user commands.

Stages:
  1. Intent Detection       (intent_detector.py)
  2. Entity Extraction      (entity_extractor.py)
  3. Parameter Extraction   (parameter_extractor.py)
  4. Context Resolution     (context_resolver.py)
  5. Confidence Scoring     (confidence_scorer.py)
  6. Ambiguity Resolution   (ambiguity_resolver.py)

Orchestrator:
  - IntentEngine            (engine.py)

Usage:
    from app.agent.intent_engine import IntentEngine

    engine = IntentEngine()
    result = engine.process("open youtube")
    # result.intent == "open_website"
    # result.confidence == 0.95
    # result.params == {"url": "https://www.youtube.com"}
"""

from .intent_detector import (
    IntentDetector,
    IntentPattern,
    IntentCandidate,
)
from .entity_extractor import (
    EntityExtractor,
    Entity,
)
from .parameter_extractor import (
    ParameterExtractor,
    ParamSpec,
    ParamExtractionResult,
)
from .context_resolver import (
    ContextResolver,
    ContextEntry,
    ResolutionResult,
)
from .confidence_scorer import (
    ConfidenceScorer,
    ConfidenceScore,
)
from .ambiguity_resolver import (
    AmbiguityResolver,
    AmbiguityResolution,
)
from .engine import (
    IntentEngine,
    IntentResult,
)

__all__ = [
    # Stage 1
    "IntentDetector",
    "IntentPattern",
    "IntentCandidate",
    # Stage 2
    "EntityExtractor",
    "Entity",
    # Stage 3
    "ParameterExtractor",
    "ParamSpec",
    "ParamExtractionResult",
    # Stage 4
    "ContextResolver",
    "ContextEntry",
    "ResolutionResult",
    # Stage 5
    "ConfidenceScorer",
    "ConfidenceScore",
    # Stage 6
    "AmbiguityResolver",
    "AmbiguityResolution",
    # Orchestrator
    "IntentEngine",
    "IntentResult",
]
