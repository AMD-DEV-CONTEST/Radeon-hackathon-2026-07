"""Tests for the orchestrator batch queue (concurrent diff/scan dispatch),
the tune_rocm GFX override fallback, and the phase-power split."""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from warden.config import Decision
from warden.orchestrator import WardenOrchestrator, GuardJob


# ----------------------------------------------------------------------
# Orchestrator batch queue
# ----------------------------------------------------------------------

class FakeRouter:
    def __init__(self):
        self.calls = []

    def route(self, text: str, source: str = "unknown"):
        time.sleep(0.05)  # simulate Tier 1/2 latency
        self.calls.append((text, source))
        return type("R", (), {
            "decision": Decision.ALLOW,
            "explanation": f"routed:{text}",
            "tier_reached": 1,
            "confidence": 0.9,
            "total_latency_ms": 50.0,
        })()


class FakeCamel:
    def check_tool_call(self, tool_name, args):
        return True, ""


class FakeDiffGuard:
    def __init__(self):
        self.scanned = []

    def scan_diff(self, diff):
        time.sleep(0.05)
        self.scanned.append(diff)
        return type("S", (), {"has_findings": False, "max_severity": None, "vulnerabilities": [],
                              "scanner": "fake"})()


class FakePolicy:
    def evaluate_tool_call(self, tool_name, args):
        return None


class FakeAudit:
    def log_event(self, event):
        pass


def _make_orchestrator(batch_workers=4):
    return WardenOrchestrator(
        router=FakeRouter(),
        camel=FakeCamel(),
        diff_guard=FakeDiffGuard(),
        policy=FakePolicy(),
        audit=FakeAudit(),
        mode="active",
        batch_workers=batch_workers,
    )


def test_guard_batch_preserves_order():
    orch = _make_orchestrator()
    jobs = [GuardJob(kind="input", payload=f"text-{i}", context="unknown") for i in range(5)]
    orch.guard_batch(jobs)
    assert [j.result.explanation for j in jobs] == [f"routed:text-{i}" for i in range(5)]
    assert all(j.error == "" for j in jobs)


def test_guard_batch_mixed_kinds():
    orch = _make_orchestrator()
    jobs = [
        GuardJob(kind="input", payload="hello", context="unknown"),
        GuardJob(kind="commit", payload="diff1"),
        GuardJob(kind="tool_call", payload={"tool_name": "write_file", "args": {"path": "/tmp/x"}}),
    ]
    orch.guard_batch(jobs)
    assert jobs[0].result.decision == Decision.ALLOW
    assert jobs[1].result.decision == Decision.ALLOW      # no findings → allow
    assert jobs[2].result.decision == Decision.ALLOW      # data-flow ok → allow


def test_guard_batch_unknown_kind_sets_error():
    orch = _make_orchestrator()
    jobs = [GuardJob(kind="nonsense", payload="x")]
    orch.guard_batch(jobs)
    assert jobs[0].result is None
    assert "Unknown batch job kind" in jobs[0].error


def test_guard_batch_is_faster_than_serial():
    """With 4 workers and 4 slow (50ms) jobs, wall time should be well
    under the 200ms serial bound — proves real concurrency."""
    orch = _make_orchestrator(batch_workers=4)
    jobs = [GuardJob(kind="input", payload=f"t-{i}", context="unknown") for i in range(4)]
    start = time.perf_counter()
    orch.guard_batch(jobs)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2, f"batch took {elapsed:.3f}s — not concurrent"


def test_batch_inputs_and_diffs_convenience():
    orch = _make_orchestrator()
    results = orch.batch_inputs(["a", "b", "c"], source="unknown")
    assert len(results) == 3 and all(r.decision == Decision.ALLOW for r in results)
    diff_results = orch.batch_diffs(["d1", "d2"])
    assert len(diff_results) == 2
    assert len(orch.diff_guard.scanned) == 2


def test_empty_batch_is_noop():
    orch = _make_orchestrator()
    assert orch.guard_batch([]) == []


# ----------------------------------------------------------------------
# tune_rocm GFX override fallback
# ----------------------------------------------------------------------

def test_detect_gfx_override_maps_known_cards():
    from scripts.tune_rocm import detect_gfx_override
    assert detect_gfx_override("AMD Instinct MI300X OAM") == "9.4.0"
    assert detect_gfx_override("AMD Instinct MI250X") == "9.0.0"
    assert detect_gfx_override("Radeon RX 7900 XTX") == "11.0.0"
    assert detect_gfx_override("AMD Radeon PRO W7900") == "11.0.0"
    assert detect_gfx_override("Radeon RX 6900 XT") == "10.3.0"


def test_detect_gfx_override_unknown_is_empty():
    from scripts.tune_rocm import detect_gfx_override
    assert detect_gfx_override("Some Obscure Card 9000") == ""


def test_tune_rocm_env_emits_gfx_override_when_set():
    from scripts.tune_rocm import GpuProfile
    p = GpuProfile(gfx_override="9.4.0")
    assert p.as_env()["HSA_OVERRIDE_GFX_VERSION"] == "9.4.0"
    p2 = GpuProfile()
    assert "HSA_OVERRIDE_GFX_VERSION" not in p2.as_env()


def test_tune_rocm_force_gfx_flag():
    from scripts.tune_rocm import detect_gpu
    profile = detect_gpu(force_gfx="10.3.0")
    assert profile.gfx_override == "10.3.0"


# ----------------------------------------------------------------------
# Phase-power split
# ----------------------------------------------------------------------

def test_phase_power_split_no_boundaries():
    from benchmarks.measure_power import PowerBenchmark
    bench = PowerBenchmark()
    assert bench.phase_power_split()["phases"] == []


def test_phase_power_split_slices_windows():
    from benchmarks.measure_power import PowerBenchmark
    bench = PowerBenchmark(interval_ms=1)
    # Start "1s ago" so the synthetic rows (elapsed 0.05–0.30) fall inside
    # the [start, now) monitoring window when phase_power_split runs.
    t0 = time.perf_counter() - 1.0
    bench._start_time = t0
    # Phase 1 (prefill) at 200W for 200ms, phase 2 (decode) at 400W after
    bench.phase_boundaries = [("prefill_done", t0 + 0.2)]
    bench._rows = [
        {"elapsed_s": 0.05, "power_w": 200.0},
        {"elapsed_s": 0.10, "power_w": 200.0},
        {"elapsed_s": 0.15, "power_w": 200.0},
        {"elapsed_s": 0.25, "power_w": 400.0},
        {"elapsed_s": 0.30, "power_w": 400.0},
    ]
    split = bench.phase_power_split()
    assert len(split["phases"]) == 2
    assert split["phases"][0]["name"] == "prefill_done"
    assert split["phases"][0]["avg_watts"] == 200.0
    assert split["phases"][1]["name"] == "run_end"
    assert split["phases"][1]["avg_watts"] == 400.0
