import pytest

from app.tools.base import BaseTool, ToolRegistry


class _EchoTool(BaseTool):
    name = "echo"
    description = "Echoes back its input."

    async def _execute(self, message: str) -> str:
        return message


class _FailingTool(BaseTool):
    name = "always_fails"
    description = "Always raises."

    async def _execute(self, **kwargs):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_tool_run_returns_success_result():
    tool = _EchoTool()
    result = await tool.run(message="hello")
    assert result.success is True
    assert result.output == "hello"
    assert result.error is None


@pytest.mark.asyncio
async def test_tool_run_captures_failure_without_raising():
    tool = _FailingTool()
    result = await tool.run()
    assert result.success is False
    assert "boom" in result.error


def test_registry_lookup_and_unknown_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    assert registry.get("echo").name == "echo"
    with pytest.raises(Exception):
        registry.get("does_not_exist")
