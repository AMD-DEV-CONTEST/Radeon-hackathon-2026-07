"""Mock adapter — drives the test framework without any LLM.

Two modes:
- correct:   replies with golden (ideal-behavior) responses -> every
             scenario should PASS. Used for CI self-check of the framework.
- confused:  replies with deliberately memory-confused responses ->
             every scenario should FAIL. Proves the judge catches mixing.

Zero external dependencies: works on any machine with plain Python.
"""

from __future__ import annotations

from .scenarios_data import golden_turns, confused_turns


class MockAdapter:
    """Deterministic fake agent for framework self-testing."""

    USES_MEMORY = False

    def __init__(self, scenarios: list[dict], mode: str = "correct"):
        self.mode = mode
        self._golden = golden_turns(scenarios)
        self._confused = confused_turns(scenarios)

    def respond(self, prompt, history, scenario_id, session, turn_index):
        table = self._confused if self.mode == "confused" else self._golden
        turns = table.get(scenario_id, [])
        idx = turn_index - 1
        if 0 <= idx < len(turns):
            return turns[idx]
        return f"[mock:{scenario_id}] 无第 {turn_index} 轮回复数据"
