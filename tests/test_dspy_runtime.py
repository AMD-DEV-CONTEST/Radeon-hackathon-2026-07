import types
from unittest.mock import patch

import pytest
import dspy

from src import dspy_runtime
from src.config import get_config


def _fake_completion_response(text: str):
    """Build an OpenAI chat-completion-shaped object for a mocked LM.forward()."""
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def _vllm_is_healthy() -> bool:
    try:
        import requests

        return requests.get("http://localhost:8000/health", timeout=2).status_code == 200
    except Exception:
        return False


def test_dspy_runtime_configures_local_lm():
    """Importing src.dspy_runtime wires dspy.settings.lm to the local vLLM."""
    assert dspy.settings.lm is dspy_runtime.BUNKER_LM
    assert dspy_runtime.BUNKER_LM.model == f"openai/{get_config().inference.primary_model}"
    assert dspy_runtime.BUNKER_LM.kwargs["api_base"].startswith("http://localhost:")
    assert dspy_runtime.BUNKER_LM.kwargs["api_base"].endswith("/v1")
    assert dspy_runtime.BUNKER_LM.kwargs["api_key"] == "EMPTY"
    assert dspy_runtime.BUNKER_LM.cache is False


def test_predict_against_live_vllm():
    """Runs a real dspy.Predict against the local vLLM when it is up."""
    if not _vllm_is_healthy():
        pytest.skip("No live vLLM server on localhost:8000")

    result = dspy.Predict("question -> answer")(question="2+2")
    assert result.answer
    assert str(result.answer).strip()


def test_predict_with_mocked_lm():
    """dspy.Predict returns a non-empty answer with a mocked LM response."""
    fake = _fake_completion_response("[[ ## answer ## ]]\n42\n\n[[ ## completed ## ]]")
    with patch.object(dspy_runtime.BUNKER_LM, "forward", return_value=fake):
        result = dspy.Predict("question -> answer")(question="2+2")
    assert str(result.answer).strip() == "42"
