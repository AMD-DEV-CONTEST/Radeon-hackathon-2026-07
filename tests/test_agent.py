import pytest
from unittest.mock import MagicMock

from src.agent import ReActAgent, TaskPlanner, PermissionController


@pytest.fixture
def permission_controller():
    return PermissionController()


def test_permission_controller_safe_tools_auto_approve(permission_controller):
    """Safe tools (file_read, file_search, file_list, calendar_query) auto-approve."""
    assert permission_controller.request_approval("file_read", {"path": "test.txt"}) is True
    assert permission_controller.request_approval("file_search", {"query": "test"}) is True
    assert permission_controller.request_approval("file_list", {"directory": "."}) is True
    assert permission_controller.request_approval("calendar_query", {"start_date": "2026-08-01"}) is True


def test_permission_controller_requires_approval_dangerous_tools(permission_controller):
    """Dangerous tools require explicit approval by default."""
    assert permission_controller.request_approval("file_write", {"path": "test.txt", "content": "hi"}) is False
    assert permission_controller.request_approval("email_draft", {"to": "a@b.com", "subject": "hi", "body": "hi"}) is False
    assert permission_controller.request_approval("calendar_create_event", {"title": "mtg", "start": "2026-08-01T10:00:00", "end": "2026-08-01T11:00:00"}) is False


def test_permission_controller_dangerous_tools_cannot_be_auto_approved_by_override(permission_controller):
    """dangerous tools cannot be auto-approved by set_auto_approve override"""
    permission_controller.set_auto_approve("file_write", True)
    assert permission_controller.requires_approval("file_write") is True
    assert permission_controller.request_approval("file_write", {"path": "test.txt"}) is False


def test_permission_controller_non_dangerous_override(permission_controller):
    """Non-dangerous custom tool override works."""
    permission_controller.set_auto_approve("custom_tool", True)
    assert permission_controller.requires_approval("custom_tool") is False
    assert permission_controller.request_approval("custom_tool", {}) is True


def test_permission_controller_history(permission_controller):
    """request_approval recorded in history"""
    permission_controller.request_approval("file_read", {"path": "test.txt"})
    history = permission_controller.get_history()
    assert len(history) == 1
    assert history[0]["tool"] == "file_read"


@pytest.fixture
def planner():
    model_mock = MagicMock()
    model_mock.generate.return_value = '1. {"step": 1, "action": "Test action", "tool": "test_tool", "rationale": "reason"}'
    return TaskPlanner(model_manager=model_mock)


def test_planner_returns_steps(planner):
    """TaskPlanner.plan() returns list of dicts with 'step' key"""
    plan = planner.plan("Do something", available_tools=[])
    assert isinstance(plan, list)
    assert len(plan) == 1
    assert plan[0]["step"] == 1


def test_planner_fallback_on_failure():
    """returns single-step plan when model fails"""
    model_mock = MagicMock()
    model_mock.generate.side_effect = Exception("Model failed")
    planner = TaskPlanner(model_manager=model_mock)
    plan = planner.plan("Do something", available_tools=[])
    assert len(plan) == 1
    assert plan[0]["action"] == "direct_execution"


@pytest.fixture
def react_agent():
    model_manager = MagicMock()
    tool_registry = MagicMock()
    tool_registry.list_tools.return_value = []
    audit_logger = MagicMock()
    return ReActAgent(
        model_manager=model_manager,
        tool_registry=tool_registry,
        audit_logger=audit_logger
    )


def test_react_agent_final_answer(react_agent):
    """ReActAgent successful final answer includes tokens_used and status='success'"""
    react_agent.model_manager.generate.return_value = "Final Answer: The task is complete."
    result = react_agent.run("Do task")
    assert result["status"] == "success"
    assert result["response"] == "The task is complete."
    assert "tokens_used" in result
    assert result["tokens_used"] > 0


def test_react_agent_max_iterations(react_agent):
    """ReActAgent stops at max_iterations returning status='failed' and clear reason"""
    react_agent.model_manager.generate.return_value = "Thought: Thinking\nAction: unknown_tool\nAction Input: {}"
    react_agent.max_iterations = 2
    result = react_agent.run("Do task")
    assert result["status"] == "failed"
    assert "reason" in result
    assert "Max iterations reached" in result["reason"]
    assert result["iterations"] == 2


def test_react_agent_token_budget_exceeded(react_agent):
    """ReActAgent stops on token budget exceeded with status='failed' and reason containing 'Token budget'"""
    react_agent.max_tokens_per_turn = 10
    react_agent.model_manager.generate.return_value = "Thought: " + "word " * 50
    result = react_agent.run("Do task")
    assert result["status"] == "failed"
    assert "reason" in result
    assert "Token budget" in result["reason"]


def test_react_agent_tool_permission_check(react_agent):
    """tool requiring approval goes through permission_controller"""
    react_agent.model_manager.generate.side_effect = [
        'Thought: Thinking\nAction: file_write\nAction Input: {"path": "test"}',
        'Final Answer: Done'
    ]
    react_agent.tool_registry.execute.return_value = "Success"
    react_agent.permission_controller = MagicMock()
    react_agent.permission_controller.request_approval.return_value = True

    react_agent.run("Write file")
    react_agent.permission_controller.request_approval.assert_called_once()


def test_react_agent_parse_output_final(react_agent):
    """_parse_react_output handles 'Final Answer:' correctly"""
    text = "Thought: I know the answer.\nFinal Answer: 42"
    parsed = react_agent._parse_react_output(text)
    assert parsed["type"] == "final_answer"
    assert parsed["content"] == "42"


def test_react_agent_parse_output_action(react_agent):
    """_parse_react_output handles 'Action:' correctly"""
    text = 'Thought: Need a tool.\nAction: read_file\nAction Input: {"path": "a.txt"}'
    parsed = react_agent._parse_react_output(text)
    assert parsed["type"] == "action"
    assert parsed["action"] == "read_file"
    assert "path" in parsed["action_input"]
