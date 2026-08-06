import types
from unittest.mock import patch

import dspy
import pytest

from src import dspy_runtime
from src.agent.metrics import (
    AnswerJudge,
    SEMANTIC_WEIGHT,
    GROUNDING_WEIGHT,
    PRESENCE_WEIGHT,
    grounded_metric,
)
from src.rag.multihop_rag import BunkerMultiHopRAG


def _fake_completion_response(text: str):
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def _judge_response(correct: bool):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nJudge the answer.\n\n"
        f"[[ ## factually_correct ## ]]\n{correct}\n\n"
        "[[ ## completed ## ]]"
    )


def _example(question: str, answer: str):
    return dspy.Example(question=question, answer=answer)


def _prediction(answer: str, notes):
    return dspy.Prediction(answer=answer, notes=notes)


def test_answer_judge_signature_fields():
    assert set(AnswerJudge.input_fields) == {"context", "question", "answer"}
    assert set(AnswerJudge.output_fields) == {"factually_correct"}


def test_grounded_metric_full_score_with_mocked_judge():
    """A correct, grounded, cited answer scores the full weighted sum."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Paris, the capital of France. [1]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True)]):
        score = grounded_metric(example, pred)

    assert score == pytest.approx(1.0)


def test_grounded_metric_penalizes_fake_pid():
    """A cited [pid] missing from the notes zeroes the grounding component."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Berlin. [9]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(False)]):
        score = grounded_metric(example, pred)

    expected = SEMANTIC_WEIGHT * 0.0 + GROUNDING_WEIGHT * 0.0 + PRESENCE_WEIGHT * 1.0
    assert score == pytest.approx(expected)


def test_grounded_metric_trace_toggle_returns_bool():
    """During optimization (trace not None) the metric returns a boolean threshold."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    good = _prediction(
        "The Eiffel Tower is in Paris, the capital of France. [1]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    bad = _prediction(
        "The Eiffel Tower is in Berlin. [9]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True), _judge_response(False)]):
        assert grounded_metric(example, good, trace=[]) is True
        assert grounded_metric(example, bad, trace=[]) is False


def test_grounded_metric_falls_back_to_token_overlap_when_judge_unavailable():
    """When the judge LM fails, semantic correctness uses gold-token overlap."""
    from src.agent import metrics

    example = _example("Capital of France?", "Paris is the capital of France")
    pred = _prediction(
        "The capital of France is Paris. [1]",
        ["Paris is the capital of France."],
    )
    with patch.object(metrics._judge, "forward", side_effect=RuntimeError("vLLM down")):
        score = grounded_metric(example, pred)

    # All three gold tokens ("paris", "capital", "france") are in the answer.
    expected = SEMANTIC_WEIGHT * 1.0 + GROUNDING_WEIGHT * 1.0 + PRESENCE_WEIGHT * 1.0
    assert score == pytest.approx(expected)


def test_grounded_metric_trace_rejects_ungrounded_high_score():
    """Trace path: grounding fails but score >= THRESHOLD must still be False."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Berlin. [9]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True)]):
        assert grounded_metric(example, pred, trace=[]) is False


def test_grounded_metric_trace_rejects_low_score_with_grounding():
    """Trace path: grounding holds (vacuous) but score < THRESHOLD is False."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is a landmark.",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(False)]):
        assert grounded_metric(example, pred, trace=[]) is False


def test_grounded_metric_multi_passage_mid_range_citation():
    """A valid mid-range [pid] in a multi-passage context is fully grounded."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Paris. [2]",
        ["passage one", "The Eiffel Tower is located in Paris, France.", "passage three"],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True)]):
        score = grounded_metric(example, pred)

    assert score == pytest.approx(1.0)


def test_grounded_metric_zero_pid_penalized():
    """A [0] citation is out of bounds and zeroes the grounding component."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Paris. [0]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True)]):
        score = grounded_metric(example, pred)

    expected = SEMANTIC_WEIGHT * 1.0 + GROUNDING_WEIGHT * 0.0 + PRESENCE_WEIGHT * 1.0
    assert score == pytest.approx(expected)


def test_grounded_metric_uncited_answer_presence_zero():
    """No citation at all: presence is 0.0 and grounding is vacuously satisfied."""
    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is located in Paris, the capital of France.",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=[_judge_response(True)]):
        score = grounded_metric(example, pred)

    expected = SEMANTIC_WEIGHT * 1.0 + GROUNDING_WEIGHT * 1.0 + PRESENCE_WEIGHT * 0.0
    assert score == pytest.approx(expected)


def test_grounded_metric_fallback_partial_token_overlap():
    """Partial gold-token overlap yields a fractional semantic score."""
    from src.agent import metrics

    example = _example("Capital of France?", "Paris is the capital")
    pred = _prediction(
        "The capital is Berlin. [1]",
        ["Paris is the capital of France."],
    )
    with patch.object(metrics._judge, "forward", side_effect=RuntimeError("vLLM down")):
        score = grounded_metric(example, pred)

    # Gold tokens "paris", "is", "the", "capital": only "is", "the", "capital" hit.
    expected = SEMANTIC_WEIGHT * (3 / 4) + GROUNDING_WEIGHT * 1.0 + PRESENCE_WEIGHT * 1.0
    assert score == pytest.approx(expected)


def test_grounded_metric_fallback_empty_gold_with_answer():
    """Empty gold answer enters the no-token branch: non-empty answer scores 1.0."""
    from src.agent import metrics

    example = _example("Capital of France?", "")
    pred = _prediction(
        "The capital of France is Paris. [1]",
        ["Paris is the capital of France."],
    )
    with patch.object(metrics._judge, "forward", side_effect=RuntimeError("vLLM down")):
        score = grounded_metric(example, pred)

    expected = SEMANTIC_WEIGHT * 1.0 + GROUNDING_WEIGHT * 1.0 + PRESENCE_WEIGHT * 1.0
    assert score == pytest.approx(expected)


def test_grounded_metric_fallback_empty_gold_and_empty_answer():
    """Empty gold and empty answer: the no-token branch returns semantic 0.0."""
    from src.agent import metrics

    example = _example("Capital of France?", "")
    pred = _prediction("", ["Paris is the capital of France."])
    with patch.object(metrics._judge, "forward", side_effect=RuntimeError("vLLM down")):
        score = grounded_metric(example, pred)

    expected = SEMANTIC_WEIGHT * 0.0 + GROUNDING_WEIGHT * 1.0 + PRESENCE_WEIGHT * 0.0
    assert score == pytest.approx(expected)


def test_grounded_metric_judge_receives_answer_and_context():
    """The LLM judge must receive the question, context, and answer verbatim."""
    from src.agent import metrics

    example = _example("What country is the Eiffel Tower in?", "Paris, France")
    pred = _prediction(
        "The Eiffel Tower is in Paris. [1]",
        ["The Eiffel Tower is located in Paris, France."],
    )
    with patch.object(metrics, "_judge", return_value=types.SimpleNamespace(factually_correct=True)) as mock_judge:
        score = grounded_metric(example, pred)

    assert score == pytest.approx(1.0)
    assert mock_judge.call_count == 1
    kwargs = mock_judge.call_args.kwargs
    assert kwargs["question"] == "What country is the Eiffel Tower in?"
    assert kwargs["context"] == "The Eiffel Tower is located in Paris, France."
    assert kwargs["answer"] == "The Eiffel Tower is in Paris. [1]"
