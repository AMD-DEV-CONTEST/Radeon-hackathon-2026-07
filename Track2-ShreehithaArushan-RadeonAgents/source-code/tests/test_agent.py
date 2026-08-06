"""
Basic unit tests for RadeonAgents core components.
These tests do not require a GPU.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from src.core.tools import ToolRegistry, _safe_eval_math
from src.core.planner import HierarchicalPlanner


def test_safe_calculator():
    assert _safe_eval_math("2 + 3 * 4") == "14"
    assert _safe_eval_math("2 ** 10") == "1024"
    assert "error" in _safe_eval_math("import os").lower() or "Unsupported" in _safe_eval_math("import os")


def test_tool_registry_basic():
    tools = ToolRegistry(enable_python=True, enable_fs=True, enable_web=False)
    assert "calculator" in tools.list_tool_names()
    assert "python_interpreter" in tools.list_tool_names()
    result = tools.call("calculator", "10 * 5 + 2")
    assert result == "52"


def test_python_tool_restricted():
    tools = ToolRegistry(enable_python=True)
    code = "result = sum(range(10))"
    out = tools.call("python_interpreter", code)
    assert "45" in out


def test_list_files():
    tools = ToolRegistry(enable_fs=True, workspace_root=str(ROOT))
    out = tools.call("list_files", ".")
    assert "src" in out or "README.md" in out or "config" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
