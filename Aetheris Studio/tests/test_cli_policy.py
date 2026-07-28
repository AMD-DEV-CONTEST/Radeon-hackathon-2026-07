"""
Unit tests for Aetheris CLI policy authorization engine.
Verifies table-driven decision outcomes for automated policies including default deny, tool allowlisting, bash policy escalation, and planner mode constraints.
"""

import pytest
from aetheris_cli.policy.automated import AutomatedAuthorizer
from aetheris_cli.policy.authorizer import DecisionOutcome, ToolRequest
from aetheris_cli.policy.spec import PolicySpec


def test_policy_default_deny():
    spec = PolicySpec.parse()
    authorizer = AutomatedAuthorizer(spec)
    req = ToolRequest(tool="write_file", content="test.txt")
    decision = authorizer.decide(req)
    assert decision.outcome == DecisionOutcome.DENY
    assert decision.is_automated is True


def test_policy_allow_exact_tool():
    spec = PolicySpec.parse(allow_str="write_file")
    authorizer = AutomatedAuthorizer(spec)
    req = ToolRequest(tool="write_file", content="test.txt")
    decision = authorizer.decide(req)
    assert decision.outcome == DecisionOutcome.ALLOW

    req_other = ToolRequest(tool="edit_file", content="test.txt")
    decision_other = authorizer.decide(req_other)
    assert decision_other.outcome == DecisionOutcome.DENY


def test_policy_bash_escalation():
    spec_normal_bash = PolicySpec.parse(allow_bash_val="true")
    auth_normal = AutomatedAuthorizer(spec_normal_bash)

    req_safe = ToolRequest(tool="bash", content="ls -la")
    assert auth_normal.decide(req_safe).outcome == DecisionOutcome.ALLOW

    req_risky = ToolRequest(tool="bash", content="rm -rf /")
    assert auth_normal.decide(req_risky).outcome == DecisionOutcome.DENY

    spec_risky_bash = PolicySpec.parse(allow_bash_val="risky")
    auth_risky = AutomatedAuthorizer(spec_risky_bash)
    assert auth_risky.decide(req_risky).outcome == DecisionOutcome.ALLOW


def test_policy_plan_only_blocks_mutations():
    spec = PolicySpec.parse(allow_str="write_file", plan_only=True)
    authorizer = AutomatedAuthorizer(spec)
    req = ToolRequest(tool="write_file", content="test.txt")
    decision = authorizer.decide(req)
    assert decision.outcome == DecisionOutcome.DENY
