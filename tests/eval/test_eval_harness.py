"""DSPy evaluation harness: quality-regression gate over the compiled RAG program.

The harness runs ``dspy.Evaluate`` (https://dspy.ai/learn/evaluation/) over the
golden devset in ``golden.py``. Because the compiled artifact
(``artifacts/bunker_rag_mipro.json``) is produced by
``scripts/compile_bunker.py`` against the live local vLLM server, the gate
skips with a clear message when the artifact is absent rather than evaluating
the uncompiled program (which is never what runs in production).

The metric follows the DSPy contract ``metric(example, pred, trace=None) ->
float`` (https://dspy.ai/learn/evaluation/metrics/): a grounded pass requires
both the expected answer and a valid ``[pid]`` citation whose number exists
inside the example's numbered context.
"""

import re
from pathlib import Path

import dspy
import pytest

from src import dspy_runtime  # noqa: F401 -- configures the default local BUNKER_LM
from src.rag.multihop_rag import extract_citations, load_bunker_rag_program
from tests.eval.golden import BUNKER_GOLDEN

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2] / "artifacts" / "bunker_rag_mipro.json"
)

# Quality bar: at least 2 of the 3 golden questions must be answered in a
# fully grounded way (expected answer present AND a valid [pid] citation).
QUALITY_THRESHOLD = 0.66


def grounded_metric(example, pred, trace=None) -> float:
    """Return 1.0 when ``pred.answer`` matches the expected answer AND cites a valid [pid]."""
    answer_raw = str(getattr(pred, "answer", "") or "")
    answer = answer_raw.lower()
    expected = str(getattr(example, "expected_answer", "") or "").lower()
    context = str(getattr(example, "context", "") or "")

    num_passages = len(re.findall(r"\[\d+\]", context))
    citations = extract_citations(answer_raw)
    contains_expected = bool(expected) and expected in answer
    valid_citation = bool(citations) and all(1 <= pid <= num_passages for pid in citations)
    return float(contains_expected and valid_citation)


@pytest.mark.eval
def test_quality_regression_threshold():
    if not ARTIFACT_PATH.is_file():
        pytest.skip(
            "Compiled RAG artifact not found at "
            f"{ARTIFACT_PATH}. Run scripts/compile_bunker.py against the local "
            "vLLM server to produce it, then re-run this quality-regression gate."
        )

    program = load_bunker_rag_program(artifact_path=str(ARTIFACT_PATH))
    evaluator = dspy.Evaluate(
        devset=BUNKER_GOLDEN,
        metric=grounded_metric,
        num_threads=1,
        display_progress=False,
        display_table=False,
    )
    result = evaluator(program)
    score = result.score / 100.0
    assert score >= QUALITY_THRESHOLD, (
        f"Quality regression: RAG eval score {result.score:.2f}% "
        f"({score:.3f}) is below the {QUALITY_THRESHOLD} threshold "
        f"({int(QUALITY_THRESHOLD * len(BUNKER_GOLDEN))} of "
        f"{len(BUNKER_GOLDEN)} golden questions)."
    )
