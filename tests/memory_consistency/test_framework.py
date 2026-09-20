"""Framework self-check tests — runnable anywhere (no LLM / GPU / network).

- test_mock_correct_all_pass:      golden replies must PASS every scenario
- test_mock_confused_detected:     confused replies must FAIL every scenario
- test_react_adapter_import:       react adapter imports cleanly (no side effects)

Run:  cd track2-agentic-ai && pytest tests/memory_consistency/ -v
"""

from __future__ import annotations

from .runner import load_scenarios, ScenarioRunner
from .adapters.mock import MockAdapter

SCENARIOS = load_scenarios()


def _run_all(mode: str) -> list[dict]:
    adapter = MockAdapter(SCENARIOS, mode=mode)
    return ScenarioRunner(adapter).run_all(SCENARIOS)


def test_mock_correct_all_pass():
    """Ideal-behavior golden replies must pass every scenario."""
    results = _run_all("correct")
    failed = [r for r in results if r["status"] != "PASS"]
    assert len(results) == len(SCENARIOS), "场景数不匹配"
    assert not failed, (
        "以下场景未通过（框架或 golden 有误）: "
        + "; ".join(f"{r['id']}:{r['status']} {r['details']}" for r in failed)
    )


def test_mock_confused_detected():
    """Deliberately memory-mixed replies must be caught as failures."""
    results = _run_all("confused")
    caught = [r for r in results if r["status"] != "PASS"]
    assert len(results) == len(SCENARIOS)
    assert len(caught) == len(SCENARIOS), (
        "混淆回复未被全部判失败: "
        + "; ".join(f"{r['id']}:{r['status']}" for r in results if r["status"] == "PASS")
    )


def test_react_adapter_import_clean():
    """Importing the react adapter must not touch src (no side effects)."""
    from .adapters import react  # noqa: F401
    assert react.ReactAdapter is not None
