"""Shared helpers for SentinelBench tests — import from here, not conftest."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from agents.base_agent import ActionType, AgentAction


def make_action(action_type: ActionType, rationale: str = "", payload: str = "") -> AgentAction:
    return AgentAction(action_type=action_type, step=0, rationale=rationale, payload=payload)


def assert_denied(verdict, layer: str | None = None) -> None:
    assert not verdict.safe, f"Expected DENY but got PASS: reason={verdict.reason}"
    if layer:
        assert verdict.layer == layer, f"Expected layer={layer} but got {verdict.layer}"


def assert_passed(verdict) -> None:
    assert verdict.safe, (
        f"Expected PASS but got DENY: reason={verdict.reason} layer={verdict.layer}"
    )
