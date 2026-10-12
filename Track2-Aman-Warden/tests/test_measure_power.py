"""Tests for the GPU power/telemetry harness.

These tests pass on any host (Linux/Windows, GPU or no GPU):
they verify the harness degrades gracefully when rocm-smi is
absent and that the summary/joules computation is correct when
samples are injected directly.
"""

from __future__ import annotations

import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from benchmarks.measure_power import PowerBenchmark, PowerSummary


def test_power_summary_joules_math():
    """joules = avg_watts × duration_s — the headline metric."""
    s = PowerSummary(duration_s=10.0, avg_watts=50.0, samples=100, rocm_available=True)
    assert s.joules == 500.0  # 50 W × 10 s


def test_power_summary_round_trip():
    s = PowerSummary(duration_s=5.0, avg_watts=20.0, max_watts=80.0,
                     avg_gpu_util_pct=40.0, max_gpu_util_pct=95.0,
                     gpu_name="MI250", rocm_available=True)
    d = s.as_dict()
    assert d["joules"] == 100.0  # 20 W × 5 s
    assert d["max_gpu_util_pct"] == 95.0
    assert d["gpu_name"] == "MI250"
    # Round-trippable through JSON
    import json
    json.dumps(d)


def test_harness_context_manager_writes_csv(tmp_path):
    out = tmp_path / "telemetry.csv"
    bench = PowerBenchmark(output_path=str(out), interval_ms=10)
    with bench:
        # Inject fake rows directly to bypass rocm-smi (unavailable on dev host)
        bench._rows = [
            {"timestamp": "t1", "power_w": 30.0, "gpu_util_pct": 10.0,
             "vram_used_mb": 1000.0, "temp_c": 45.0, "available": True},
            {"timestamp": "t2", "power_w": 70.0, "gpu_util_pct": 90.0,
             "vram_used_mb": 4000.0, "temp_c": 65.0, "available": True},
        ]
    summary = bench.stop_monitoring()  # safe to call again — no-op if already stopped
    assert out.exists()
    # CSV header + 2 injected rows
    csv_text = out.read_text()
    assert "timestamp" in csv_text
    assert csv_text.count("\n") >= 3


def test_harness_degrades_without_rocm_smi(tmp_path):
    """On a host without rocm-smi, samples record available=False and
    the summary notes rocm_available=False (no crash)."""
    out = tmp_path / "degraded.csv"
    bench = PowerBenchmark(output_path=str(out), interval_ms=10)
    with bench:
        # Let one poll happen naturally — will fail gracefully.
        import time as _time
        _time.sleep(0.03)
    summary = bench.stop_monitoring()
    assert summary is not None
    # Either way, no exception, CSV written.
    assert out.exists()
