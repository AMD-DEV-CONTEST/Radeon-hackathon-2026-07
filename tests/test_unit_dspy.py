"""Deterministic unit tests for the DSPy layer (no network, no GPU).

These tests never touch the live vLLM server. ``FakeLM`` stands in for
``dspy.LM`` and returns canned responses, so the assertions below are
exact-match instead of statistical.

Verified against dspy 3.3.0 (installed in ``.venv310``):

* ``dspy.LM(model, model_type="chat", temperature=None, max_tokens=None,
  cache=True, callbacks=None, num_retries=3, provider=None, ...,
  **kwargs)`` — ``api_base``/``api_key`` ride through ``**kwargs`` and land
  in ``lm.kwargs`` (https://dspy.ai/api/models/LM/).
* Adapters call ``lm(messages=..., **data)``, which runs ``BaseLM.__call__``
  -> ``forward()`` and post-processes the returned OpenAI-shaped completion
  into a ``dspy.Prediction`` (``dspy/adapters/base.py:_call_lm``,
  ``dspy/clients/base_lm.py:_process_completion``). ``FakeLM`` therefore
  returns a completion-shaped canned response rather than a raw Prediction.
"""

import ast
import types
from pathlib import Path

import dspy
import pytest

from src import dspy_runtime
from src.config import get_config
from src.rag.multihop_rag import GroundedAnswer

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def _completion_response(text: str, model: str) -> types.SimpleNamespace:
    """Build an OpenAI chat-completion-shaped object a dspy adapter can parse."""
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


class FakeLM(dspy.LM):
    """A network-free ``dspy.LM`` that replays canned responses in order.

    ``responses`` is a list of response dicts. Each dict must carry a
    ``"content"`` key whose value is the raw completion text (in the
    ``[[ ## field ## ]]`` adapter format). ``forward`` pops the next canned
    response on every call and wraps it in an OpenAI chat-completion-shaped
    object so the ChatAdapter parses it into a ``dspy.Prediction``.

    The instance points at ``http://localhost:8000/v1`` (never a cloud
    endpoint) and disables caching, mirroring the runtime's observability
    requirement, but ``forward`` never opens a socket.
    """

    def __init__(self, responses, model="openai/bunker-fake", **kwargs):
        kwargs.setdefault("api_base", "http://localhost:8000/v1")
        kwargs.setdefault("api_key", "EMPTY")
        kwargs.setdefault("cache", False)
        super().__init__(model=model, **kwargs)
        self._responses = list(responses)
        self.calls = []  # (prompt, messages) for every forward() invocation

    def forward(self, prompt=None, messages=None, **kwargs):
        self.calls.append((prompt, messages))
        if not self._responses:
            raise AssertionError(
                "FakeLM ran out of canned responses: the module made more "
                f"LM calls ({len(self.calls)}) than responses were provided."
            )
        canned = self._responses.pop(0)
        if isinstance(canned, str):
            content = canned
        elif isinstance(canned, dict):
            content = canned["content"]
        else:
            raise TypeError(
                "FakeLM responses must be dicts with a 'content' key or raw "
                f"strings, got {type(canned).__name__}."
            )
        return _completion_response(content, model=self.model)


# ---------------------------------------------------------------------------
# Runtime wiring: localhost-only, no caching
# ---------------------------------------------------------------------------


def test_dspy_runtime_configures_localhost_only():
    """build_lm produces an LM pinned to the local vLLM with caching off."""
    config = get_config().model_copy(deep=True)
    config.inference.backend = "vllm"

    lm = dspy_runtime.build_lm(config)

    api_base = lm.kwargs["api_base"]
    assert api_base.startswith(("http://localhost", "http://127.0.0.1")), api_base
    assert api_base == f"http://{config.inference.vllm_host}:{config.inference.vllm_port}/v1"
    assert lm.cache is False
    assert lm.kwargs.get("cache", False) is not True


def test_imported_bunker_lm_points_at_local_vllm():
    """The process-wide default LM (import side effect) stays on localhost."""
    assert dspy.settings.lm is dspy_runtime.BUNKER_LM
    assert dspy_runtime.BUNKER_LM.kwargs["api_base"].startswith(
        ("http://localhost", "http://127.0.0.1")
    )
    assert dspy_runtime.BUNKER_LM.cache is False


# ---------------------------------------------------------------------------
# GroundedAnswer signature through a canned LM
# ---------------------------------------------------------------------------


def test_grounded_answer_has_required_fields():
    """ChainOfThought(GroundedAnswer) returns the parsed Prediction fields."""
    fake = FakeLM([
        {
            "content": (
                "[[ ## reasoning ## ]]\nThe context notes cite Paris.\n\n"
                "[[ ## answer ## ]]\nParis is in France. [1]\n\n"
                "[[ ## completed ## ]]"
            )
        },
    ])

    with dspy.context(lm=fake):
        module = dspy.ChainOfThought(GroundedAnswer)
        result = module(
            context="[1] Paris is the capital of France.",
            question="Where is Paris?",
        )

    assert isinstance(result, dspy.Prediction)
    assert result.reasoning == "The context notes cite Paris."
    assert result.answer == "Paris is in France. [1]"
    assert len(fake.calls) == 1
    assert set(GroundedAnswer.input_fields) == {"context", "question"}
    assert set(GroundedAnswer.output_fields) == {"answer"}


def test_grounded_answer_replays_responses_sequentially():
    """FakeLM pops canned responses in order across multiple module calls."""
    fake = FakeLM([
        {"content": "[[ ## answer ## ]]\nFirst. [1]\n\n[[ ## completed ## ]]\n\n\n"},
        {"content": "[[ ## answer ## ]]\nSecond. [1]\n\n[[ ## completed ## ]]\n\n\n"},
    ])

    module = dspy.Predict(GroundedAnswer)
    with dspy.context(lm=fake):
        first = module(context="[1] one", question="q1")
        second = module(context="[1] one", question="q2")

    assert first.answer == "First. [1]"
    assert second.answer == "Second. [1]"
    assert len(fake.calls) == 2


def test_fake_lm_raises_when_responses_exhausted():
    """A module that makes more calls than canned responses fails loudly."""
    fake = FakeLM([{"content": "[[ ## answer ## ]]\nOnly one.\n\n[[ ## completed ## ]]"}] * 1)
    module = dspy.Predict(GroundedAnswer)

    with dspy.context(lm=fake):
        module(context="[1] one", question="q1")
        with pytest.raises(AssertionError, match="ran out of canned responses"):
            module(context="[1] one", question="q2")


# ---------------------------------------------------------------------------
# AST guard: the optimizer must never run from src/
# ---------------------------------------------------------------------------

_STDLIB_COMPILE_RECEIVERS = {"re", "code", "types", "typing"}


def _receiver_root_name(node) -> str | None:
    """Return the leftmost identifier of an attribute chain (e.g. ``re`` in ``re.compile``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return _receiver_root_name(node.func)
    return None


def _find_compile_calls(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, source-line) for every non-stdlib ``.compile(...)`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "compile":
            continue
        if _receiver_root_name(func.value) in _STDLIB_COMPILE_RECEIVERS:
            continue
        hits.append((node.lineno, path.read_text(encoding="utf-8").splitlines()[node.lineno - 1]))
    return hits


def test_compile_is_only_called_from_script():
    """DSPy optimizer ``.compile()`` must not appear anywhere under src/."""
    offenders = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for lineno, line in _find_compile_calls(path):
            offenders.append(f"{path.relative_to(SRC_ROOT.parent)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Found .compile() calls outside scripts/ (the optimizer must only run "
        f"from scripts/compile_bunker.py):\n" + "\n".join(offenders)
    )
