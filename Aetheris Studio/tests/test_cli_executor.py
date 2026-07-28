"""
Unit tests for Aetheris CLI tool execution seam and approval intent workflow.
Verifies read-only tool immediate execution, mutating tool approval intent generation, and approved execution re-validation.
"""

from typing import Any, Dict
from aetheris_cli.policy.executor import BaseToolExecutor, OutcomeKind
from aetheris_cli.policy.spec import PolicySpec


class DummyExecutor(BaseToolExecutor):
    def run_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "executed": name}


def test_read_only_tool_executes_immediately():
    exec_inst = DummyExecutor()
    outcome = exec_inst.execute("read_file", {"path": "README.md"})
    assert outcome.kind == OutcomeKind.RESULT
    assert outcome.result == {"status": "ok", "executed": "read_file"}


def test_mutating_tool_requires_approval_intent():
    exec_inst = DummyExecutor()
    outcome = exec_inst.execute("write_file", {"path": "test.txt", "content": "hello"})
    assert outcome.kind == OutcomeKind.APPROVAL_REQUIRED
    assert outcome.intent is not None
    assert outcome.intent.name == "write_file"


def test_execute_approved_runs_after_intent():
    exec_inst = DummyExecutor()
    outcome = exec_inst.execute_approved("write_file", {"path": "test.txt", "content": "hello"})
    assert outcome.kind == OutcomeKind.RESULT
    assert outcome.result == {"status": "ok", "executed": "write_file"}


def test_execute_approved_revalidates_risky_bash():
    pol = PolicySpec(allow_bash="false")
    exec_inst = DummyExecutor(policy=pol)
    outcome = exec_inst.execute_approved("bash", {"command": "rm -rf /"})
    assert outcome.kind == OutcomeKind.ERROR
    assert "Denied by policy" in outcome.error
