import types
from unittest.mock import patch

import dspy

from src import dspy_runtime
from src.agent.signatures import ReActStep, TaskPlan, plan_task, react_step


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


def test_taskplan_signature_fields():
    """TaskPlan exposes the expected input/output fields."""
    assert set(TaskPlan.input_fields) == {"user_request", "available_tools"}
    assert set(TaskPlan.output_fields) == {"plan"}
    assert TaskPlan.__doc__.startswith("Create a step-by-step plan")


def test_plan_task_parses_structured_steps():
    """plan_task (ChainOfThought) returns a parsed list[dict] plan."""
    fake = _fake_completion_response(
        "[[ ## reasoning ## ]]\nFirst search the database, then summarize.\n\n"
        "[[ ## plan ## ]]\n"
        '[{"step": 1, "action": "search_db", "tool": "rag_search", "rationale": "find docs"},'
        '{"step": 2, "action": "summarize", "tool": "summarizer", "rationale": "condense"}]'
        "\n\n[[ ## completed ## ]]"
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", return_value=fake):
        result = plan_task(
            user_request="Summarize the research on Qwen",
            available_tools="- rag_search: search the knowledge base\n- summarizer: condense text",
        )
    assert isinstance(result.plan, list)
    assert result.plan[0]["step"] == 1
    assert result.plan[0]["tool"] == "rag_search"
    assert result.reasoning


def test_reactstep_signature_fields():
    """ReActStep exposes the expected input/output fields."""
    assert set(ReActStep.input_fields) == {
        "user_message",
        "tool_descriptions",
        "observation_context",
    }
    assert set(ReActStep.output_fields) == {
        "thought",
        "next_action",
        "action_input",
        "final_answer",
    }
    assert "final answer" in ReActStep.__doc__.lower()


def test_react_step_parses_tool_call():
    """react_step (Predict) returns a parsed tool-call decision."""
    fake = _fake_completion_response(
        "[[ ## thought ## ]]\nThe user wants current news, so search the web.\n\n"
        "[[ ## next_action ## ]]\nweb_search\n\n"
        "[[ ## action_input ## ]]\n{\"query\": \"latest news\"}\n\n"
        "[[ ## final_answer ## ]]\n\n\n"
        "[[ ## completed ## ]]"
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", return_value=fake):
        result = react_step(
            user_message="What's the latest news?",
            tool_descriptions="- web_search: search the web",
            observation_context="",
        )
    assert result.next_action == "web_search"
    assert isinstance(result.action_input, dict)
    assert result.action_input["query"] == "latest news"
    assert result.thought


def test_react_step_parses_final_answer():
    """react_step returns an empty action_input when the model answers directly."""
    fake = _fake_completion_response(
        "[[ ## thought ## ]]\nI already know the answer.\n\n"
        "[[ ## next_action ## ]]\nfinal_answer\n\n"
        "[[ ## action_input ## ]]\n{}\n\n"
        "[[ ## final_answer ## ]]\n2 + 2 is 4.\n\n"
        "[[ ## completed ## ]]"
    )
    with patch.object(dspy_runtime.BUNKER_LM, "forward", return_value=fake):
        result = react_step(
            user_message="What is 2+2?",
            tool_descriptions="",
            observation_context="",
        )
    assert result.next_action == "final_answer"
    assert result.action_input == {}
    assert result.final_answer == "2 + 2 is 4."
