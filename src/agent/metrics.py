"""Optimization and evaluation metric for Bunker's grounded RAG pipeline.

Follows the DSPy metric patterns:
- LLM-as-judge signature with a boolean output
  (https://dspy.ai/cheatsheet/, "LLM as Judge" section).
- A metric function ``(example, pred, trace=None) -> float`` that returns a
  boolean threshold during optimization (trace is not None) and a float score
  at evaluation time (https://dspy.ai/learn/evaluation/metrics/).
"""

import logging
from typing import Optional

import dspy

from src.rag.multihop_rag import extract_citations

logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT = 0.5
GROUNDING_WEIGHT = 0.3
PRESENCE_WEIGHT = 0.2
THRESHOLD = 0.7


class AnswerJudge(dspy.Signature):
    """Judge if the answer is factually correct based on the context."""

    context: str = dspy.InputField(desc="Context for the prediction")
    question: str = dspy.InputField(desc="Question to be answered")
    answer: str = dspy.InputField(desc="Answer for the question")
    factually_correct: bool = dspy.OutputField(desc="Is the answer factually correct based on the context?")


_judge = dspy.ChainOfThought(AnswerJudge)


def _semantic_score(example: dspy.Example, pred: dspy.Prediction) -> float:
    """Score semantic correctness with an LLM judge, falling back to token overlap.

    The LLM judge uses the locally configured LM. If the judge is unavailable
    (e.g. the local vLLM server is down), a deterministic token-overlap score is
    returned instead.
    """
    try:
        judgment = _judge(
            question=getattr(example, "question", "") or "",
            context="\n".join(getattr(pred, "notes", []) or []),
            answer=getattr(pred, "answer", "") or "",
        )
        return 1.0 if judgment.factually_correct else 0.0
    except Exception as exc:
        logger.warning("LLM judge unavailable (%s); using token-overlap fallback.", exc)
        gold = (getattr(example, "answer", "") or "").lower()
        answer = (getattr(pred, "answer", "") or "").lower()
        tokens = [t.strip(".,;:!?") for t in gold.split() if t.strip(".,;:!?")]
        if not tokens:
            return 1.0 if answer.strip() else 0.0
        hits = sum(1 for token in tokens if token in answer)
        return hits / len(tokens)


def _grounding_score(pred: dspy.Prediction) -> float:
    """Rule-based grounding: every [pid] cited in the answer exists in context."""
    citations = extract_citations(getattr(pred, "answer", "") or "")
    num_passages = len(getattr(pred, "notes", []) or [])
    return 1.0 if all(1 <= pid <= num_passages for pid in citations) else 0.0


def _presence_score(pred: dspy.Prediction) -> float:
    """Citation presence: the answer cites at least one passage."""
    return 1.0 if extract_citations(getattr(pred, "answer", "") or "") else 0.0


def grounded_metric(example: dspy.Example, pred: dspy.Prediction, trace: Optional[list] = None) -> float:
    """Weighted grounding metric: semantic correctness + grounding + citation presence.

    Args:
        example: The gold example (with ``question`` and ``answer``).
        pred: The program prediction (with ``answer`` and ``notes``).
        trace: Set during optimization/compilation. When not None, returns a
            boolean threshold (grounding must hold AND score >= THRESHOLD).

    Returns:
        A float in [0.0, 1.0], or a bool when ``trace is not None``.
    """
    semantic = _semantic_score(example, pred)
    grounding = _grounding_score(pred)
    presence = _presence_score(pred)
    score = (
        SEMANTIC_WEIGHT * semantic
        + GROUNDING_WEIGHT * grounding
        + PRESENCE_WEIGHT * presence
    )
    if trace is not None:
        return grounding == 1.0 and score >= THRESHOLD
    return score
