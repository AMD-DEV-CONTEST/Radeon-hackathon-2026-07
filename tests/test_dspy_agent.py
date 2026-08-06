import types
from unittest.mock import patch

import pytest

from src import dspy_runtime
from src.agent import DspyReActAgent, PermissionController
from src.agent.dspy_agent import BunkerAgentSignature
from src.tools.dspy_tools import build_bunker_tools


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


# ---------------------------------------------------------------------------
# Tool list
# ---------------------------------------------------------------------------


def test_build_bunker_tools_exposes_nine_tools():
    """build_bunker_tools returns all nine registry tools as dspy.Tool."""
    controller = PermissionController()
    tools = build_bunker_tools(controller)
    names = [t.name for t in tools]
    assert names == [
        "file_read",
        "file_write",
        "file_search",
        "file_list",
        "email_draft",
        "email_search",
        "calendar_query",
        "calendar_create_event",
        "web_search",
    ]
    # Tools read the wrapped function's type hints for their arg schema.
    file_read = next(t for t in tools if t.name == "file_read")
    assert file_read.args == {"path": {"type": "string", "description": "The relative path to the file"}}
    assert "Read the contents" in file_read.desc


def test_gated_tool_body_denies_without_consent(tmp_path):
    """A dangerous tool call is blocked *inside* the tool body when denied."""
    controller = PermissionController()  # demo_mode off -> dangerous tools denied
    tools = build_bunker_tools(controller, base_dir=str(tmp_path))
    file_write = next(t for t in tools if t.name == "file_write")

    result = file_write(path="out.txt", content="secret")

    assert "Permission denied" in result
    assert not (tmp_path / "out.txt").exists()
    history = controller.get_history()
    assert len(history) == 1
    assert history[0]["tool"] == "file_write"
    assert history[0]["approved"] is False


def test_gated_tool_body_writes_when_approved(tmp_path):
    """A dangerous tool call proceeds when demo mode approves it."""
    controller = PermissionController({"demo_mode": True})
    tools = build_bunker_tools(controller, base_dir=str(tmp_path))
    file_write = next(t for t in tools if t.name == "file_write")

    result = file_write(path="out.txt", content="hello")

    assert "Written 5 bytes to out.txt" in result
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"
    history = controller.get_history()
    assert history[0]["approved"] is True


def test_safe_tool_runs_without_gate(tmp_path):
    """Safe tools never hit the consent gate."""
    controller = PermissionController()
    tools = build_bunker_tools(controller, base_dir=str(tmp_path))
    file_read = next(t for t in tools if t.name == "file_read")

    result = file_read(path="missing.txt")

    assert "Error" in result
    assert controller.get_history() == []


# ---------------------------------------------------------------------------
# Agent signature + loop
# ---------------------------------------------------------------------------


def test_bunker_agent_signature_fields():
    """BunkerAgentSignature declares the expected input/output fields."""
    assert set(BunkerAgentSignature.input_fields) == {"user_message", "history", "plan"}
    assert set(BunkerAgentSignature.output_fields) == {"answer"}
    assert "AMD Radeon GPU" in BunkerAgentSignature.instructions


def test_react_agent_reads_file(tmp_path):
    """A canned tool-use request runs the read tool and returns the answer."""
    (tmp_path / "notes.txt").write_text("hello world", encoding="utf-8")
    controller = PermissionController()
    agent = DspyReActAgent(permission_controller=controller, base_dir=str(tmp_path))

    responses = [
        _plan_response('[{"step": 1, "action": "read", "tool": "file_read", "rationale": "read notes"}]'),
        _react_response("Read the file.", "file_read", '{"path": "notes.txt"}'),
        _react_response("I have the info.", "finish", "{}"),
        _extract_response("The file says: hello world."),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        result = agent.run("Read notes.txt and summarize it")

    assert result["status"] == "success"
    assert result["response"] == "The file says: hello world."
    assert result["tool_calls"][0]["tool"] == "file_read"
    assert result["tool_calls"][0]["args"] == {"path": "notes.txt"}
    assert result["trajectory"]["observation_0"] == "hello world"
    assert result["iterations"] == 2
    # Safe tool: no consent gate was recorded.
    assert controller.get_history() == []


def test_react_agent_write_gate_called_and_denied(tmp_path):
    """A write trajectory triggers PermissionController.gate() via the tool body."""
    controller = PermissionController()  # demo_mode off -> file_write denied
    agent = DspyReActAgent(permission_controller=controller, base_dir=str(tmp_path))

    responses = [
        _plan_response('[]'),
        _react_response("Write the file.", "file_write", '{"path": "out.txt", "content": "secret"}'),
        _react_response("Done.", "finish", "{}"),
        _extract_response("Done."),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        result = agent.run("Write secret to out.txt")

    assert "Permission denied" in result["trajectory"]["observation_0"]
    assert not (tmp_path / "out.txt").exists()
    history = controller.get_history()
    assert len(history) == 1
    assert history[0]["tool"] == "file_write"
    assert history[0]["approved"] is False


def test_react_agent_write_gate_approved_in_demo_mode(tmp_path):
    """A write trajectory writes the file when demo mode approves consent."""
    controller = PermissionController({"demo_mode": True})
    agent = DspyReActAgent(permission_controller=controller, base_dir=str(tmp_path))

    responses = [
        _plan_response('[]'),
        _react_response("Write the file.", "file_write", '{"path": "out.txt", "content": "hello"}'),
        _react_response("Done.", "finish", "{}"),
        _extract_response("Wrote it."),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        result = agent.run("Write hello to out.txt")

    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"
    history = controller.get_history()
    assert len(history) == 1
    assert history[0]["tool"] == "file_write"
    assert history[0]["approved"] is True
