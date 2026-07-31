"""
Unit tests that don't require a live GPU or inference server: the LLM and
vector store are mocked so `pytest` can run anywhere (including CI).
"""
from unittest.mock import MagicMock

import pytest

from src.agent import NovaAgent
from src.memory import ConversationMemory
from src.tools import tool_calculator, tool_list_files, _resolve_and_check, PermissionError_
import config


def test_calculator_tool_basic():
    assert "= 19" in tool_calculator("12 + 7")


def test_calculator_tool_rejects_bad_input():
    result = tool_calculator("import os; os.system('ls')")
    assert "Could not evaluate" in result


def test_permission_check_blocks_outside_paths():
    with pytest.raises(PermissionError_):
        _resolve_and_check("/etc/passwd")


def test_permission_check_allows_data_dir():
    path = _resolve_and_check(str(config.DATA_DIR / "about_nova.md"))
    assert path.exists()


def test_list_files_tool_returns_sample_doc():
    result = tool_list_files()
    assert "about_nova.md" in result


def test_memory_bounds_turns():
    memory = ConversationMemory(max_turns=2)
    for i in range(5):
        memory.add_turn("user", f"turn {i}")
        memory.add_turn("assistant", f"reply {i}")
    # max_turns=2 -> at most 4 messages retained
    assert len(memory.as_messages()) <= 4


def test_agent_routes_calculator_without_llm_seeing_math():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "The answer is 42."

    mock_store = MagicMock()
    mock_store.count.return_value = 0

    agent = NovaAgent(llm_client=mock_llm, vector_store=mock_store, memory=ConversationMemory())
    result = agent.ask("calculate: 6 * 7")

    assert result["answer"] == "The answer is 42."
    assert "tool:calculator" in result["sources"]
    mock_llm.chat.assert_called_once()


def test_agent_falls_back_to_rag_when_available():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Nova runs on ROCm."

    mock_store = MagicMock()
    mock_store.count.return_value = 3
    mock_store.query.return_value = [("Nova uses ROCm and AMD GPUs.", "about_nova.md", 0.1)]

    agent = NovaAgent(llm_client=mock_llm, vector_store=mock_store, memory=ConversationMemory())
    result = agent.ask("What GPU stack does Nova use?")

    assert result["used_context"] is True
    assert "about_nova.md" in result["sources"]
