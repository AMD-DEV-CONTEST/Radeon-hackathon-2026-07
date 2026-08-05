"""A prompt the server silently clipped must never be returned as a model answer.

Two providers, one failure mode, found within an hour of each other on real work:

* vLLM REJECTS an over-long request, loudly -- but the provider computed its output budget
  from a character heuristic, so a real repair prompt measured 3,841 tokens where the
  estimate said ~3,712 and every one of six samples died as "GENERATION ERROR". The run
  read as the model being unable to fix the bug. It was never asked.
* Ollama does NOT reject it. It drops the overflow, keeps the tail, returns HTTP 200 --
  and the model answers from whatever survived. Measured on real source at repair scale:
  prompt_eval_count pinned at 2050 for a 25,048-char prompt, and the model returned a
  confident, well-formed, entirely invented answer.

The second is the dangerous one. A fabrication that reaches the oracle scores as a wrong
answer, and the system records "the model failed" for a prompt nobody ever sent. This is
the same class as the fenced-candidate bug -- a harness defect wearing a model verdict --
except silent, so there is no error anywhere to notice.

Nothing here talks to a server: the arithmetic and the guard are pure, and they are the
parts that were wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import determinex_providers as P  # noqa: E402


class _Usage:
    def __init__(self, prompt_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens


class _Resp:
    def __init__(self, prompt_tokens: int) -> None:
        self.usage = _Usage(prompt_tokens)


# --------------------------------------------------------------------------------------
# vLLM: the server states both numbers in its rejection, so the retry must not guess.
# --------------------------------------------------------------------------------------

REAL_REJECTION = (
    'litellm.BadRequestError: Hosted_vllmException - {"error":{"message":"You passed '
    "3841 input tokens and requested 256 output tokens. However, this model's maximum "
    'context length is 4096 tokens."}}'
)


def test_retry_budget_is_taken_from_the_servers_own_numbers():
    budget = P._vllm_retry_budget(REAL_REJECTION)
    assert budget == 254
    # The whole point: the retry must actually fit, with no off-by-one. Two heuristics
    # died on exactly this -- 1025+3072=4097 and 3841+256=4097, both one token over.
    assert 3841 + budget < 4096


@pytest.mark.parametrize(
    "message",
    [
        "Timeout",  # nothing to parse
        "You passed 3841 input tokens",  # no limit stated
        "maximum context length is 4096 tokens",  # no prompt size stated
        "You passed 5000 input tokens ... maximum context length is 4096 tokens",  # hopeless
    ],
)
def test_retry_budget_declines_rather_than_inventing_one(message: str):
    """0 means "re-raise the real error". A guessed budget would replace a precise server
    message with a second, more confusing failure."""
    assert P._vllm_retry_budget(message) == 0


# --------------------------------------------------------------------------------------
# Ollama: num_ctx must be raised, and only for models Ollama actually serves.
# --------------------------------------------------------------------------------------


def test_ollama_context_is_raised_from_the_2048_default(monkeypatch):
    monkeypatch.setattr(P, "_ollama_model_ctx", lambda m, *a, **k: 32768)
    prompt = "x" * 25048  # the measured size of a real repair prompt
    ctx = P._ollama_ctx_kwargs("ollama/qwen2.5-coder:14b-instruct-q4_K_M", prompt)["num_ctx"]
    assert ctx > 2048, "the default is 2048; leaving it is what truncated the prompt"
    assert ctx <= 32768, "never ask for more context than the model was trained with"


def test_non_ollama_models_are_left_alone(monkeypatch):
    """num_ctx is an Ollama option. Sending it elsewhere is at best ignored, at worst a
    400 on a provider that rejects unknown fields."""
    monkeypatch.setattr(P, "_ollama_model_ctx", lambda m, *a, **k: 32768)
    for model in ("claude-sonnet-5", "hosted_vllm/Qwen2.5-Coder-32B", "openrouter/deepseek"):
        assert P._ollama_ctx_kwargs(model, "x" * 25048) == {}


def test_context_request_is_capped_so_a_huge_prompt_cannot_exhaust_memory(monkeypatch):
    monkeypatch.setattr(P, "_ollama_model_ctx", lambda m, *a, **k: 131072)
    monkeypatch.setenv("DETERMINEX_OLLAMA_CTX_CAP", "8192")
    ctx = P._ollama_ctx_kwargs("ollama/big", "x" * 4_000_000)["num_ctx"]
    assert ctx == 8192


def test_unknown_context_length_changes_nothing(monkeypatch):
    """/api/show unreachable -> send no num_ctx rather than a fabricated one."""
    monkeypatch.setattr(P, "_ollama_model_ctx", lambda m, *a, **k: 0)
    assert P._ollama_ctx_kwargs("ollama/whatever", "x" * 25048) == {}


# --------------------------------------------------------------------------------------
# The guard itself: silence must not be the outcome of a clipped prompt.
# --------------------------------------------------------------------------------------


def test_a_clipped_prompt_raises_instead_of_returning_a_fabrication():
    """The measured case. 25,048 chars in, 2,050 tokens evaluated, and the model returned
    'TASK-12345' -- fluent, plausible, and about a prompt that was never sent."""
    with pytest.raises(RuntimeError, match="PROMPT TRUNCATED"):
        P._assert_prompt_not_truncated("ollama/m", "x" * 25048, _Resp(prompt_tokens=2050))


def test_the_error_names_the_numbers_needed_to_act_on_it():
    with pytest.raises(RuntimeError) as exc:
        P._assert_prompt_not_truncated("ollama/m", "x" * 25048, _Resp(prompt_tokens=2050))
    text = str(exc.value)
    assert "2050" in text and "25048" in text
    # Whoever reads this must not file it as a model-quality problem.
    assert "NOT a model-capability result" in text


def test_a_prompt_that_fits_passes_silently():
    """One-sided by design. 5,898 chars evaluating 1,312 tokens is normal tokenisation,
    not truncation, and a guard that fired here would block ordinary work."""
    P._assert_prompt_not_truncated("ollama/m", "x" * 5898, _Resp(prompt_tokens=1312))


def test_a_provider_that_reports_no_usage_is_not_accused():
    """Absent telemetry is not evidence of truncation."""
    P._assert_prompt_not_truncated("claude-sonnet-5", "x" * 25048, _Resp(prompt_tokens=0))
    P._assert_prompt_not_truncated("claude-sonnet-5", "x" * 25048, object())


def test_the_bound_is_slack_enough_for_genuinely_dense_tokenisation():
    """8 chars/token is beyond what real text reaches, so the guard cannot fire on a
    prompt that merely tokenised well -- only on one that was demonstrably cut."""
    P._assert_prompt_not_truncated("ollama/m", "x" * 16000, _Resp(prompt_tokens=2001))
