"""Tests for negative paths and graceful degradation.

Bunker must fail gracefully when real-world inputs go wrong: the user denies
a tool call, the vector store has nothing to retrieve, or the local 0.6B LM
emits unparseable output. These tests pin that behaviour so an edge case
cannot turn into a crash, a hallucination, or an infinite loop.

* ``test_tool_denial_graceful_handling`` — a denied ``file_write`` is
  surfaced to the user and the ReAct loop stays within its iteration bound.
* ``test_empty_retrieval_handling`` — an empty ChromaDB retrieval returns
  ``INSUFFICIENT_CONTEXT`` instead of a hallucinated answer.
* ``test_malformed_llm_output`` / ``test_gradio_ui_swallows_agent_errors`` —
  unparseable LM output is caught by the agent and the Gradio layer, so a
  raw Python exception never escapes to the UI.
"""

import types
from unittest.mock import patch

import pytest

from src import dspy_runtime
from src.agent import DspyReActAgent, PermissionController
from src.rag.multihop_rag import BunkerMultiHopRAG, make_chromadb_search
from src.ui.gradio_app import BunkerGradioApp


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


def _plan_response(plan_json: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nPlan the steps.\n\n"
        f"[[ ## plan ## ]]\n{plan_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _react_response(thought: str, tool_name: str, tool_args_json: str):
    return _fake_completion_response(
        f"[[ ## next_thought ## ]]\n{thought}\n\n"
        f"[[ ## next_tool_name ## ]]\n{tool_name}\n\n"
        f"[[ ## next_tool_args ## ]]\n{tool_args_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _extract_response(answer: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


def _query_response(query: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nDecide the next query.\n\n"
        f"[[ ## query ## ]]\n{query}\n\n"
        "[[ ## completed ## ]]"
    )


def _notes_response(notes_json: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nExtract new facts.\n\n"
        f"[[ ## new_notes ## ]]\n{notes_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _answer_response(answer: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the grounded answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


class EmptyStore:
    """Stand-in for ChromaDB returning zero passages for every query."""

    def search(self, query: str, k: int = 5, **kwargs):
        return []


# ---------------------------------------------------------------------------
# Tool denial
# ---------------------------------------------------------------------------


def test_tool_denial_graceful_handling(tmp_path):
    """A denied write is surfaced, never crashes, and never retries unbounded."""
    controller = PermissionController()
    agent = DspyReActAgent(
        permission_controller=controller,
        base_dir=str(tmp_path),
        max_iters=4,
    )

    # The user denies every write (consent flag always False) while the model
    # insists on calling file_write every iteration, ignoring the denial.
    responses = [
        _plan_response('[]'),
        _react_response("Write the file.", "file_write", '{"path": "exfil.txt", "content": "secret"}'),
        _react_response("Write the file.", "file_write", '{"path": "exfil.txt", "content": "secret"}'),
        _react_response("Write the file.", "file_write", '{"path": "exfil.txt", "content": "secret"}'),
        _react_response("Write the file.", "file_write", '{"path": "exfil.txt", "content": "secret"}'),
        _extract_response("The write was denied by the user."),
    ]
    with patch.object(controller, "request_approval", return_value=False):
        with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
            result = agent.run("Save secret to exfil.txt")

    assert result["status"] == "success"  # the loop completed; no crash
    assert result["iterations"] <= agent.max_iters  # bounded, never infinite
    assert result["iterations"] == agent.max_iters  # the denial loop was cut off
    for i in range(result["iterations"]):
        assert "Permission denied" in result["trajectory"][f"observation_{i}"]
    assert not (tmp_path / "exfil.txt").exists()  # nothing hit the disk
    assert "denied" in result["response"].lower()  # the user is informed


# ---------------------------------------------------------------------------
# Empty retrieval
# ---------------------------------------------------------------------------


def test_empty_retrieval_handling():
    """Zero retrieved passages yield INSUFFICIENT_CONTEXT, not a hallucination."""
    rag = BunkerMultiHopRAG(
        search=make_chromadb_search(EmptyStore()),
        num_hops=2,
        num_docs=3,
        max_backtracks=2,
    )

    # The model fabricates notes from nothing AND is primed to answer — the
    # empty-retrieval guard must fire before the answer module ever runs.
    responses = [
        _query_response("Search query for hop 1."),
        _notes_response('["Paris is the capital of France."]'),
        _query_response("Search query for hop 2."),
        _notes_response('["Paris is the capital of France."]'),
        _answer_response("Paris is the capital of France. [1]"),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses) as mock_lm:
        result = rag(question="What is the capital of France?")

    assert result.answer == "INSUFFICIENT_CONTEXT"
    assert result.grounded is False
    assert result.citation_count == 0
    assert len(result.queries) == 2
    # The answer module was never invoked: only 2 query + 2 notes calls. The
    # hallucinated answer response in the script would have been consumed
    # (and returned) if the guard were absent.
    assert mock_lm.call_count == 4


# ---------------------------------------------------------------------------
# Malformed LLM output
# ---------------------------------------------------------------------------


def test_malformed_llm_output(tmp_path):
    """Unparseable LM output is caught and becomes a generic fallback."""
    agent = DspyReActAgent(
        permission_controller=PermissionController(),
        base_dir=str(tmp_path),
    )

    garbage = [_fake_completion_response("this is not a react response at all")] * 20
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=garbage):
        result = agent.run("Write a file")

    assert result["status"] == "error"
    assert "unexpected response" in result["response"]
    assert result["iterations"] == 0
    assert result["tool_calls"] == []


def test_gradio_ui_swallows_agent_errors():
    """A crashing agent yields a generic user-facing error, not a raw exception."""

    class BoomAgent:
        def run(self, message, session_id):
            raise RuntimeError("AdapterParseError: LM response cannot be serialized")

    app = BunkerGradioApp(
        agent=BoomAgent(),
        privacy_dashboard=object(),
        session_store=object(),
        context_manager=object(),
        permission_controller=object(),
    )

    history, thoughts, cleared = app.handle_message("Write a file", [], "s1")

    assert thoughts == "Execution failed."
    assert history[0][1] == "❌ Error processing request: AdapterParseError: LM response cannot be serialized"
