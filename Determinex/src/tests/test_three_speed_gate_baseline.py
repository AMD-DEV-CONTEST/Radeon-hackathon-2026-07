"""tests/test_three_speed_gate_baseline.py — iter-1 lesson shard rule.

The new rule (after iter-1 hyperfine/genact/direnv showed +0.00pp despite
heavy rc-family share): pass shard only if ≥3 of 5 tools improve OR
≥+2pp avg delta, with zero regressions. Falls back to legacy aggregate-floor
when no baseline supplied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from three_speed_gate import (  # noqa: E402
    GATE_SHARD_MIN_AVG_DELTA_PP,
    GATE_SHARD_MIN_IMPROVED_TOOLS,
    _evaluate_shard_verdict,
    _per_tool_baseline_scores,
)


def _write_eval(root: Path, iid: str, passed: int, total: int) -> Path:
    d = root / iid
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{iid}.eval.json"
    tr = [{"status": "passed"} for _ in range(passed)]
    tr += [{"status": "failure"} for _ in range(total - passed)]
    p.write_text(json.dumps({"test_results": tr}), encoding="utf-8")
    return p


def test_per_tool_baseline_scores_computes_pass_rate(tmp_path):
    """Per-tool score = passed / total × 100."""
    base = tmp_path / "base"
    _write_eval(base, "a__a.111", 1, 4)  # 25%
    _write_eval(base, "b__b.222", 0, 5)  # 0%
    scores = _per_tool_baseline_scores(base, ["a__a.111", "b__b.222", "c__c.333"])
    assert scores == {"a__a.111": 25.0, "b__b.222": 0.0}  # c missing


def test_verdict_legacy_aggregate_floor_when_no_baseline():
    """No baseline → legacy rule kicks in."""
    shard = {"aggregate_score": 5.0, "instances": []}
    ok, detail = _evaluate_shard_verdict(shard_result=shard, baseline_scores={})
    assert ok is True
    assert detail["rule"] == "legacy_aggregate_floor"


def test_verdict_pass_when_three_tools_improve():
    """≥3 of 5 tools improve, no regression → pass even with low avg."""
    shard = {
        "instances": [
            {"instance_id": "t1", "score": 1.5},  # +0.5
            {"instance_id": "t2", "score": 2.0},  # +1.0
            {"instance_id": "t3", "score": 3.0},  # +0.5
            {"instance_id": "t4", "score": 4.0},  # +0.0 flat
            {"instance_id": "t5", "score": 5.0},  # +0.0 flat
        ]
    }
    baseline = {"t1": 1.0, "t2": 1.0, "t3": 2.5, "t4": 4.0, "t5": 5.0}
    ok, detail = _evaluate_shard_verdict(shard_result=shard, baseline_scores=baseline)
    assert ok is True
    assert detail["n_improved"] == 3
    assert detail["n_regressed"] == 0


def test_verdict_pass_when_avg_delta_meets_threshold():
    """≥+2pp avg with zero regressions → pass even if only 1 tool improved."""
    shard = {
        "instances": [
            {"instance_id": "t1", "score": 25.0},  # +20.0 (heavy lift)
            {"instance_id": "t2", "score": 1.0},  # +0.0
            {"instance_id": "t3", "score": 2.0},  # +0.0
            {"instance_id": "t4", "score": 3.0},  # +0.0
            {"instance_id": "t5", "score": 4.0},  # +0.0
        ]
    }
    baseline = {"t1": 5.0, "t2": 1.0, "t3": 2.0, "t4": 3.0, "t5": 4.0}
    ok, detail = _evaluate_shard_verdict(shard_result=shard, baseline_scores=baseline)
    assert ok is True
    assert detail["n_improved"] == 1
    assert detail["avg_delta_pp"] == 4.0  # 20/5


def test_verdict_fail_iter1_actual_scenario():
    """The exact iter-1 shard outcome: 1 tool lift, 3 flat, avg < 2pp."""
    shard = {
        "instances": [
            {"instance_id": "hyperfine", "score": 1.34},
            {"instance_id": "nomino", "score": 8.28},  # +3.55
            {"instance_id": "genact", "score": 0.42},
            {"instance_id": "direnv", "score": 7.49},
        ]
    }
    baseline = {"hyperfine": 1.34, "nomino": 4.73, "genact": 0.42, "direnv": 7.49}
    ok, detail = _evaluate_shard_verdict(shard_result=shard, baseline_scores=baseline)
    assert ok is False, "iter-1 actual outcome must fail the new gate rule"
    assert detail["n_improved"] == 1
    assert detail["n_regressed"] == 0
    assert detail["avg_delta_pp"] < GATE_SHARD_MIN_AVG_DELTA_PP


def test_verdict_fail_on_any_regression():
    """Zero-regression rule: even with 4 tools improving, 1 regression fails."""
    shard = {
        "instances": [
            {"instance_id": "t1", "score": 5.0},  # +2.0
            {"instance_id": "t2", "score": 5.0},  # +2.0
            {"instance_id": "t3", "score": 5.0},  # +2.0
            {"instance_id": "t4", "score": 5.0},  # +2.0
            {"instance_id": "t5", "score": 2.0},  # -3.0 REGRESSION
        ]
    }
    baseline = {"t1": 3.0, "t2": 3.0, "t3": 3.0, "t4": 3.0, "t5": 5.0}
    ok, detail = _evaluate_shard_verdict(shard_result=shard, baseline_scores=baseline)
    assert ok is False
    assert detail["n_improved"] == 4
    assert detail["n_regressed"] == 1


def test_thresholds_are_what_we_documented():
    """Constants must match the verdict markdown — they're load-bearing for the gate rule."""
    assert GATE_SHARD_MIN_IMPROVED_TOOLS == 3
    assert GATE_SHARD_MIN_AVG_DELTA_PP == 2.0
