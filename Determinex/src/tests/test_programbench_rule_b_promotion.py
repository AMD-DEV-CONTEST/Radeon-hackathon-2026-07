from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pb_candidate_gate import run_gate

SLUG = "owner__tool.abcdef0"


def _write_eval(path: Path, statuses: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_results": [
            {"name": f"tests.test_tool.test_{i}", "status": status}
            for i, status in enumerate(statuses)
        ],
        "executable_hash": "abc123",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_rule_b_promotion_accepts_stable_second_eval(tmp_path):
    baseline_eval = tmp_path / "baseline.eval.json"
    run_root = tmp_path / "run"
    candidate_eval = run_root / SLUG / f"{SLUG}.eval.json"
    statuses = ["passed", "passed", "failure", "failure"]
    _write_eval(baseline_eval, statuses)
    _write_eval(candidate_eval, statuses)

    result = run_gate(
        SLUG,
        run_root,
        baseline_eval,
        min_baseline_passed=2,
        skip_eval=True,
        allow_stable_certification=True,
    )

    assert result["decision"] == "accept"
    assert result["decision_rule"] == "A"
    assert result["promotion_certification"] is True
    assert "certified" in result["reason"]


def test_normal_gate_still_rejects_tie(tmp_path):
    baseline_eval = tmp_path / "baseline.eval.json"
    run_root = tmp_path / "run"
    candidate_eval = run_root / SLUG / f"{SLUG}.eval.json"
    statuses = ["passed", "passed", "failure"]
    _write_eval(baseline_eval, statuses)
    _write_eval(candidate_eval, statuses)

    result = run_gate(
        SLUG,
        run_root,
        baseline_eval,
        min_baseline_passed=2,
        skip_eval=True,
    )

    assert result["decision"] == "reject"
    assert result["decision_rule"] is None
    assert result["promotion_certification"] is False


def test_rule_b_promotion_rejects_unstable_runnable_surface(tmp_path):
    baseline_eval = tmp_path / "baseline.eval.json"
    run_root = tmp_path / "run"
    candidate_eval = run_root / SLUG / f"{SLUG}.eval.json"
    _write_eval(baseline_eval, ["passed", "passed", "failure"])
    _write_eval(candidate_eval, ["passed", "passed", "failure", "failure"])

    result = run_gate(
        SLUG,
        run_root,
        baseline_eval,
        min_baseline_passed=2,
        skip_eval=True,
        allow_stable_certification=True,
    )

    assert result["decision"] == "reject"
    assert "runnable changed" in result["reason"]
