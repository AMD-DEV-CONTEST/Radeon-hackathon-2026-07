"""Integration tests against the live local Qwen3:0.6B vLLM server.

These tests require a running vLLM server on ``http://localhost:8000/v1``
serving ``config.inference.primary_model``. They are excluded from the
default suite via the ``integration`` marker:

    pytest tests/test_integration_qwen.py -v -m integration

Live-model assertions are statistical (LLM output is non-deterministic even
at temperature 0 with a 0.6B model): ``_pass_rate`` runs each probe 10 times
and the thresholds below are proportions, not exact matches.

No cloud endpoint is ever contacted. ``qwen_lm`` pins the base URL to
``http://localhost:8000/v1`` and ``test_no_cloud_calls_during_integration``
actively fails the test if any socket connects to a non-loopback address.
"""

import re
import socket as socket_module

import dspy
import pytest

from src.config import get_config
from src.rag.multihop_rag import GroundedAnswer

REAL_CONTEXT = (
    "[1] The Eiffel Tower is an iron lattice tower located on the Champ de Mars in Paris, France.\n"
    "[2] Paris is the capital and largest city of France.\n"
    "[3] France is a country located primarily in Western Europe."
)
REAL_QUESTION = "Where is the Eiffel Tower located?"

# A [pid]-style citation is a '[' followed by digits, e.g. "[1]".
_CITATION_RE = re.compile(r"\[\d")

_PASS_THRESHOLD = 0.8  # >= 80% of live runs must satisfy the predicate
_NUM_RUNS = 10


def _vllm_is_healthy() -> bool:
    """Return True when a vLLM server is answering on localhost:8000."""
    try:
        import requests

        return requests.get("http://localhost:8000/health", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.fixture
def qwen_lm():
    """The live local Qwen model, pinned to localhost:8000/v1 with caching off."""
    if not _vllm_is_healthy():
        pytest.skip("No live vLLM server on localhost:8000")

    served_model = get_config().inference.primary_model
    if not served_model.startswith("openai/"):
        served_model = f"openai/{served_model}"

    return dspy.LM(
        served_model,
        api_base="http://localhost:8000/v1",
        api_key="EMPTY",
        temperature=0.0,
        cache=False,
    )


def _answer_is_grounded(answer: str) -> bool:
    """A grounded answer cites a passage ([1]...) or explicitly refuses."""
    return (
        "[pid" in answer
        or bool(_CITATION_RE.search(answer))
        or "INSUFFICIENT_CONTEXT" in answer
    )


def _pass_rate(fn, k=_NUM_RUNS) -> float:
    """Run ``fn`` k times and return the fraction of runs that succeeded.

    Exceptions (transient transport errors, malformed parses) count as
    failed runs so a flaky model lowers the rate instead of crashing it.
    """
    successes = 0
    for _ in range(k):
        try:
            if fn():
                successes += 1
        except Exception:
            continue
    return successes / k


@pytest.mark.integration
def test_grounded_answer_emits_citation_or_refuses(qwen_lm):
    """GroundedAnswer cites its source or refuses, in >= 80% of live runs."""
    module = dspy.Predict(GroundedAnswer)

    def run() -> bool:
        with dspy.context(lm=qwen_lm):
            result = module(context=REAL_CONTEXT, question=REAL_QUESTION)
        return _answer_is_grounded(str(result.answer))

    rate = _pass_rate(run, k=_NUM_RUNS)

    assert rate >= _PASS_THRESHOLD, (
        f"Grounded citation/refusal pass rate was {rate:.0%} "
        f"(need >= {_PASS_THRESHOLD:.0%}) across {_NUM_RUNS} live runs."
    )


@pytest.mark.integration
def test_no_cloud_calls_during_integration(qwen_lm, monkeypatch):
    """Every socket created during a live query connects only to loopback."""
    attempted = []

    class GuardedSocket(socket_module.socket):
        def connect(self, address):
            host = address[0]
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise AssertionError(
                    f"Non-loopback connection attempt during integration test: {address!r}"
                )
            attempted.append(address)
            return super().connect(address)

    monkeypatch.setattr(socket_module, "socket", GuardedSocket)

    # The guard must reject any non-loopback target outright.
    with pytest.raises(AssertionError, match="Non-loopback"):
        GuardedSocket().connect(("8.8.8.8", 80))

    module = dspy.Predict(GroundedAnswer)
    with dspy.context(lm=qwen_lm):
        result = module(context=REAL_CONTEXT, question=REAL_QUESTION)

    # litellm keeps pooled keep-alive connections to localhost, so a live query
    # may legitimately open zero *new* sockets; the invariant is that every
    # socket that IS opened (pooled or fresh) targets loopback only.
    assert all(addr[0] in ("127.0.0.1", "localhost", "::1") for addr in attempted), attempted
    assert str(result.answer)
