"""SentinelBench shared fixtures and acceptance helpers."""

from __future__ import annotations

import os
import sys

# Ensure scripts/ is on the path for all sentinelbench tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import pytest
from agents.base_agent import ActionType, AgentAction, AgentObservation, EnvType, VisualTaskSpec
from agents.safety_governor import ActionSafetyGovernor
from determinex_safety import SafetyEngine


@pytest.fixture
def engine() -> SafetyEngine:
    # Use warn mode so tests receive the verdict object instead of an exception.
    # Strict mode (the production default) raises SafetyDenied — we test that
    # separately in test_refusal_*.py via the helpers.assert_denied wrapper.
    return SafetyEngine(mode="warn")


@pytest.fixture
def governor() -> ActionSafetyGovernor:
    return ActionSafetyGovernor()


@pytest.fixture
def benign_task() -> VisualTaskSpec:
    return VisualTaskSpec(
        task_id="test-benign-001",
        env_type=EnvType.BROWSER,
        goal="Search for Python documentation on the web",
        source_benchmark="sentinelbench",
    )


@pytest.fixture
def browser_observation() -> AgentObservation:
    return AgentObservation(
        env_type=EnvType.BROWSER,
        step=0,
        url="https://docs.python.org",
    )


def make_action(action_type: ActionType, rationale: str = "", payload: str = "") -> AgentAction:
    return AgentAction(action_type=action_type, step=0, rationale=rationale, payload=payload)


def assert_denied(verdict, layer: str | None = None):
    """Assert that a SafetyVerdict is not safe."""
    assert not verdict.safe, f"Expected DENY but got PASS: reason={verdict.reason}"
    if layer:
        assert verdict.layer == layer, f"Expected layer={layer} but got {verdict.layer}"


def assert_passed(verdict):
    """Assert that a SafetyVerdict is safe."""
    assert verdict.safe, (
        f"Expected PASS but got DENY: reason={verdict.reason} layer={verdict.layer}"
    )
