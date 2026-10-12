"""Tests for the CaMeL capability tracker (the descoped-shipped subset).

The dual-LLM P-LLM / Q-LLM split (quarantine_content, plan_with_refs,
LabeledRef) was removed from warden.camel.interpreter — keeping only
the data-flow check_tool_call that is actually wired into the
orchestrator. These tests cover what ships.
"""

from warden.camel.interpreter import CaMeLInterpreter


class TestCaMeLCapabilityTracker:
    def setup_method(self):
        self.interpreter = CaMeLInterpreter()

    def test_check_tool_call_allows_when_no_policy(self):
        """Without a policy engine, every tool call is permitted."""
        assert self.interpreter.check_tool_call("read_file", {"path": "/etc/passwd"})
        assert self.interpreter.check_tool_call("run_command", {"cmd": "rm -rf /"})
        assert self.interpreter.check_tool_call("write_file", {"path": "/tmp/x"})

    def test_check_tool_call_blocks_via_policy_evaluate_tool_call(self):
        """If policy.evaluate_tool_call returns decision='block' the call is blocked."""
        class FakePolicy:
            def evaluate_tool_call(self, tool, args):
                if tool == "run_command" and "rm -rf" in args.get("cmd", ""):
                    return {"decision": "block", "reason": "destructive"}
                return {"decision": "allow"}
        i = CaMeLInterpreter(policy=FakePolicy())
        assert not i.check_tool_call("run_command", {"cmd": "rm -rf /"})
        assert i.check_tool_call("run_command", {"cmd": "ls"})

    def test_check_tool_call_blocks_via_legacy_policy_evaluate(self):
        """If policy only implements evaluate() (legacy), the block path still works."""
        class LegacyPolicy:
            def evaluate(self, name, kind):
                if kind == "tool_call" and name == "delete":
                    return {"decision": "block"}
                return {"decision": "allow"}
        i = CaMeLInterpreter(policy=LegacyPolicy())
        assert not i.check_tool_call("delete", {"target": "/x"})
        assert i.check_tool_call("read_file", {"path": "/etc/passwd"})

    def test_llm_and_audit_log_args_accepted_but_unused(self):
        """The ctor still accepts llm/audit_log for backward-compat with cli.py
        wiring, but check_tool_call doesn't depend on them. The descoped
        dual-LLM methods that used them are gone."""
        i = CaMeLInterpreter(llm=object(), audit_log=object())
        # Should still work — neither arg is dereferenced.
        assert i.check_tool_call("read_file", {"path": "/x"})

    def test_interpreter_has_no_dual_llm_methods(self):
        """Regression guard: the descoped methods stay deleted."""
        assert not hasattr(i := CaMeLInterpreter(), "quarantine_content")
        assert not hasattr(i, "plan_with_refs")
        # No LabeledRef state to leak between calls.
        assert not hasattr(i, "trusted_refs")
