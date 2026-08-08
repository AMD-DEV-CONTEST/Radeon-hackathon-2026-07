"""Tests for the new performance and strategy systems:
  - Native bridge (C + Python fallback)
  - Strategy engine (circuit breaker, intent memory, adaptive retry, prefetch)
  - Telemetry system
"""

import asyncio
import time

import pytest

from app.runtime.native_bridge import (
    C_AVAILABLE,
    fuzzy_score,
    levenshtein,
    rank_elements,
    rolling_hash,
    validate_bounds,
    xxhash64,
)
from app.runtime.strategy import (
    CircuitBreaker,
    IntentMemory,
    RetryPolicy,
    SpeculativePrefetcher,
    StrategyRouter,
    classify_failure,
)
from app.runtime.telemetry import Telemetry, CommandTrace, StepTrace


# ═══════════════════════════════════════════════════════════════
#  Native Bridge Tests
# ═══════════════════════════════════════════════════════════════

class TestNativeBridge:
    def test_c_core_available(self):
        """Report whether native C core is loaded."""
        print(f"\n  Native C core available: {C_AVAILABLE}")

    def test_levenshtein_identical(self):
        assert levenshtein("hello", "hello") == 0

    def test_levenshtein_empty(self):
        assert levenshtein("", "hello") == 5
        assert levenshtein("hello", "") == 5

    def test_levenshtein_distance(self):
        assert levenshtein("kitten", "sitting") == 3
        assert levenshtein("saturday", "sunday") == 3

    def test_fuzzy_score_exact(self):
        assert fuzzy_score("hello", "hello") == 1.0

    def test_fuzzy_score_contains(self):
        score = fuzzy_score("hell", "hello world")
        assert score > 0.5  # Should get containment bonus

    def test_fuzzy_score_prefix(self):
        score = fuzzy_score("hel", "hello")
        assert score > 0.7  # Should get prefix bonus

    def test_fuzzy_score_similar(self):
        score = fuzzy_score("btn", "button")
        assert score > 0.1  # Subsequence match

    def test_fuzzy_score_empty(self):
        assert fuzzy_score("", "hello") == 0.0
        assert fuzzy_score("hello", "") == 0.0

    def test_xxhash64_deterministic(self):
        h1 = xxhash64(b"hello world")
        h2 = xxhash64(b"hello world")
        assert h1 == h2

    def test_xxhash64_different(self):
        h1 = xxhash64(b"hello")
        h2 = xxhash64(b"world")
        assert h1 != h2

    def test_xxhash64_empty(self):
        h = xxhash64(b"")
        assert isinstance(h, int)

    def test_rolling_hash_deterministic(self):
        h1 = rolling_hash(b"test data")
        h2 = rolling_hash(b"test data")
        assert h1 == h2

    def test_rolling_hash_different(self):
        h1 = rolling_hash(b"abc")
        h2 = rolling_hash(b"xyz")
        assert h1 != h2

    def test_validate_bounds_valid(self):
        valid = validate_bounds(
            x1=[10, 50, 200],
            y1=[10, 50, 200],
            x2=[100, 150, 400],
            y2=[100, 150, 400],
            is_pane=[0, 0, 0],
            screen_w=1920, screen_h=1080,
        )
        assert len(valid) == 3

    def test_validate_bounds_too_small(self):
        valid = validate_bounds(
            x1=[10],
            y1=[10],
            x2=[12],  # width = 2 < 4px minimum
            y2=[12],
            is_pane=[0],
            screen_w=1920, screen_h=1080,
        )
        assert len(valid) == 0

    def test_validate_bounds_offscreen(self):
        valid = validate_bounds(
            x1=[-100, 50],
            y1=[-100, 50],
            x2=[-90, 150],
            y2=[-90, 150],
            is_pane=[0, 0],
            screen_w=1920, screen_h=1080,
        )
        assert len(valid) == 1  # Only second element valid

    def test_validate_bounds_fullscreen_not_pane(self):
        valid = validate_bounds(
            x1=[0],
            y1=[0],
            x2=[1920],
            y2=[1080],
            is_pane=[0],
            screen_w=1920, screen_h=1080,
        )
        assert len(valid) == 0  # Fullscreen non-pane is rejected

    def test_validate_bounds_fullscreen_pane(self):
        valid = validate_bounds(
            x1=[0],
            y1=[0],
            x2=[1920],
            y2=[1080],
            is_pane=[1],
            screen_w=1920, screen_h=1080,
        )
        assert len(valid) == 1  # Pane is allowed fullscreen

    def test_rank_elements_best_match(self):
        elements = [
            {"label": "Save", "confidence": 0.9, "bounds": [10, 10, 100, 40], "source": "uia"},
            {"label": "Open", "confidence": 0.8, "bounds": [10, 50, 100, 80], "source": "uia"},
            {"label": "Cancel", "confidence": 0.7, "bounds": [10, 90, 100, 120], "source": "vision"},
        ]
        best = rank_elements(elements, "Save")
        assert best == 0  # "Save" is exact match

    def test_rank_elements_fuzzy(self):
        elements = [
            {"label": "Sve", "confidence": 0.9, "bounds": [10, 10, 100, 40], "source": "uia"},
            {"label": "Open", "confidence": 0.8, "bounds": [10, 50, 100, 80], "source": "uia"},
        ]
        best = rank_elements(elements, "Save")
        assert best == 0  # "Sve" is closest to "Save"

    def test_rank_elements_empty(self):
        best = rank_elements([], "anything")
        assert best == -1


# ═══════════════════════════════════════════════════════════════
#  Strategy Engine Tests
# ═══════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.is_available("tool_a")

    def test_failure_opens_circuit(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tool_a")
        assert not cb.is_available("tool_a")

    def test_success_resets_circuit(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tool_a")
        assert not cb.is_available("tool_a")
        cb.record_success("tool_a")
        assert cb.is_available("tool_a")

    def test_status(self):
        cb = CircuitBreaker()
        cb.record_failure("tool_a")
        status = cb.status()
        assert "tool_a" in status
        assert status["tool_a"]["failures"] == 1


class TestIntentMemory:
    def test_record_and_retrieve(self, tmp_path):
        mem = IntentMemory(path=tmp_path / "test_memory.json")
        mem.record_success("delete_files", ["file.scan", "file.quarantine"], 150.0)
        tools = mem.best_tools_for_intent("delete_files")
        assert tools == ["file.scan", "file.quarantine"]

    def test_failure_reduces_reliability(self, tmp_path):
        mem = IntentMemory(path=tmp_path / "test_memory.json")
        mem.record_success("test", ["tool_a"], 100.0)
        mem.record_failure("test", ["tool_a"])
        mem.record_failure("test", ["tool_a"])
        mem.record_failure("test", ["tool_a"])
        mem.record_failure("test", ["tool_a"])
        mem.record_failure("test", ["tool_a"])
        tools = mem.best_tools_for_intent("test")
        # 1 success, 5 failure = 0.167 rate, below 0.3 threshold with 6 total
        assert tools is None  # Too unreliable

    def test_unknown_intent(self, tmp_path):
        mem = IntentMemory(path=tmp_path / "test_memory.json")
        assert mem.best_tools_for_intent("nonexistent") is None

    def test_persistence(self, tmp_path):
        path = tmp_path / "test_memory.json"
        mem = IntentMemory(path=path)
        mem.record_success("persist_test", ["tool_x"], 50.0)
        # Reload from disk
        mem2 = IntentMemory(path=path)
        tools = mem2.best_tools_for_intent("persist_test")
        assert tools == ["tool_x"]


class TestSpeculativePrefetcher:
    def test_cooccurrence(self):
        pf = SpeculativePrefetcher()
        pf.record_cooccurrence("file.scan", "file.quarantine")
        pf.record_cooccurrence("file.scan", "file.quarantine")
        pf.record_cooccurrence("file.scan", "file.list")
        next_tools = pf.predict_next_tools("file.scan")
        assert "file.quarantine" in next_tools

    def test_prefetch_candidates(self, tmp_path):
        pf = SpeculativePrefetcher()
        mem = IntentMemory(path=tmp_path / "test_memory.json")
        mem.record_success("search", ["browser.search", "browser.read"], 200.0)
        candidates = pf.get_prefetch_candidates("search", mem)
        assert "browser.search" in candidates


class TestAdaptiveRetry:
    def test_classify_failure_timeout(self):
        assert classify_failure("Connection timed out") == "timeout"

    def test_classify_failure_connection(self):
        assert classify_failure("Connection refused") == "connection"

    def test_classify_failure_not_found(self):
        assert classify_failure("Element not found on screen") == "not_found"

    def test_classify_failure_permission(self):
        assert classify_failure("Permission denied") == "permission"

    def test_classify_failure_busy(self):
        assert classify_failure("Resource busy") == "busy"

    def test_classify_failure_unknown(self):
        assert classify_failure("Something weird happened") == "unknown"


class TestStrategyRouter:
    def test_initial_status(self):
        router = StrategyRouter()
        status = router.status()
        assert "circuit_breaker" in status
        assert "intent_memory_intents" in status

    def test_prefetch_list(self, tmp_path):
        router = StrategyRouter()
        router.intent_memory.record_success(
            "open_app", ["system.open_app"], 50.0
        )
        tools = router.get_prefetch_list("open_app")
        assert "system.open_app" in tools

    @pytest.mark.asyncio
    async def test_execute_with_strategy_success(self):
        router = StrategyRouter()

        async def mock_exec(tool_name, args):
            return {"status": "success", "tool": tool_name}

        result = await router.execute_with_strategy(
            "test_tool", {}, mock_exec, intent="test_intent"
        )
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_with_strategy_failure_opens_circuit(self):
        router = StrategyRouter()

        async def failing_exec(tool_name, args):
            raise ConnectionError("Connection refused")

        for _ in range(3):
            await router.execute_with_strategy(
                "bad_tool", {}, failing_exec, intent="test"
            )

        # Circuit should now be open
        result = await router.execute_with_strategy(
            "bad_tool", {}, failing_exec, intent="test"
        )
        assert result["status"] == "failed"
        assert "Circuit breaker" in result["error"]


# ═══════════════════════════════════════════════════════════════
#  Telemetry Tests
# ═══════════════════════════════════════════════════════════════

class TestTelemetry:
    def test_trace_command(self):
        telemetry = Telemetry()

        async def _test():
            async with telemetry.trace_command(1, "test command", "device1") as trace:
                step = trace.add_step("planning")
                time.sleep(0.01)
                trace.finish_step(step, "ok")
                trace.intent = "open_app"
                trace.tools_used = ["system.open_app"]

            assert telemetry._stats["total_commands"] == 1
            assert telemetry._stats["successful_commands"] == 1
            assert telemetry._stats["intent_counts"]["open_app"] == 1

        asyncio.run(_test())

    def test_live_dashboard(self):
        telemetry = Telemetry()
        telemetry.record_tool_call(1, "browser.search", 150.0, True)
        telemetry.record_tool_call(1, "browser.read", 200.0, True)

        dashboard = telemetry.get_live_dashboard()
        assert "stats" in dashboard
        assert "tool_latencies" in dashboard["stats"]
        assert "browser.search" in dashboard["stats"]["tool_latencies"]

    def test_step_trace(self):
        step = StepTrace(name="test", started=time.time())
        time.sleep(0.01)
        step.finished = time.time()
        assert step.duration_ms > 0

    def test_command_trace_steps(self):
        trace = CommandTrace(command_id=1)
        s1 = trace.add_step("step1")
        time.sleep(0.01)
        trace.finish_step(s1, "ok", "done")
        s2 = trace.add_step("step2")
        time.sleep(0.01)
        trace.finish_step(s2, "ok")
        trace.finished = time.time()

        assert len(trace.steps) == 2
        assert trace.total_ms >= 0
        assert "step1" in trace.step_summary


class TestNativeCoreIntegration:
    """Integration test: verify native bridge + strategy + telemetry work together."""

    @pytest.mark.asyncio
    async def test_full_pipeline_simulation(self):
        """Simulate: command → strategy → telemetry → results."""
        router = StrategyRouter()
        telemetry = Telemetry()
        executed_tools = []

        async def mock_execute(tool_name, args):
            executed_tools.append(tool_name)
            await asyncio.sleep(0.001)
            return {"status": "success", "tool": tool_name, "output": "done"}

        # Simulate a 3-step command: search → click → read
        tools_to_run = ["browser.search", "screen.click_text", "browser.read"]
        results = []

        async with telemetry.trace_command(99, "search for X and click", "test_device") as trace:
            for tool in tools_to_run:
                result = await router.execute_with_strategy(
                    tool, {"query": "test"}, mock_execute, intent="search_web"
                )
                results.append(result)
                telemetry.record_tool_call(99, tool, 10.0, result["status"] == "success")

            trace.intent = "search_web"

        # Verify
        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)
        assert executed_tools == tools_to_run
        assert telemetry._stats["total_commands"] == 1
        assert telemetry._stats["total_tool_calls"] == 3

        # Verify fuzzy scoring works on same data
        score = fuzzy_score("search", "browser.search")
        assert score > 0.5

        # Verify hash works for screen dedup
        h1 = xxhash64(b"screen_state_1")
        h2 = xxhash64(b"screen_state_2")
        assert h1 != h2
