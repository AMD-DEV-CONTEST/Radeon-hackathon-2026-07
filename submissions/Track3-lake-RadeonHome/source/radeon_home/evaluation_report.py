"""Simulator-independent regression checks and bilingual evaluation reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def classify_trial(result: dict) -> dict:
    """Normalize a trial into stage outcomes without assuming every key exists."""
    grasp = bool(result.get("grasp_success", False))
    place = bool(result.get("place_success", False))
    transport = bool(result.get("transport_success", False))
    if transport:
        failure_stage = None
    elif not grasp:
        failure_stage = "grasp"
    elif result.get("terminated_reason") == "payload_lost_during_retract":
        failure_stage = "retract"
    elif result.get("terminated_reason") == "payload_lost_during_transport":
        failure_stage = "transport"
    else:
        failure_stage = "placement"
    return {
        "seed": result.get("seed"),
        "object_id": result.get("object_id"),
        "source_zone": result.get("source_zone"),
        "target_zone": result.get("target_zone"),
        "grasp_success": grasp,
        "place_success": place,
        "transport_success": transport,
        "retry_count": int(result.get("retry_count", 0)),
        "failure_stage": failure_stage,
        "terminated_reason": result.get("terminated_reason"),
    }


def compare_modes(physical: dict, latch: dict) -> dict:
    physical_rate = float(physical.get("transport_success_rate", 0.0))
    latch_rate = float(latch.get("transport_success_rate", 0.0))
    physical_trials = [classify_trial(item) for item in physical.get("trials", [])]
    latch_trials = [classify_trial(item) for item in latch.get("trials", [])]
    return {
        "physical_contact": {
            "trial_count": int(physical.get("attempted_trials", 0)),
            "success_rate": physical_rate,
            "trials": physical_trials,
        },
        "verified_latch": {
            "trial_count": int(latch.get("attempted_trials", 0)),
            "success_rate": latch_rate,
            "mean_place_xy_error_m": latch.get("mean_place_xy_error_m"),
            "trials": latch_trials,
        },
        "success_rate_gain_percentage_points": (latch_rate - physical_rate) * 100.0,
        "disclosure": (
            "verified_latch is a task-level simulation constraint and must not be "
            "reported as a pure physical-contact grasp success rate"
        ),
    }


def render_markdown(comparison: dict) -> str:
    physical = comparison["physical_contact"]
    latch = comparison["verified_latch"]
    error = latch.get("mean_place_xy_error_m")
    error_text = f"{error:.3f} m" if error is not None else "N/A"
    gain = comparison["success_rate_gain_percentage_points"]
    return f"""# RadeonHome Evaluation / 评测摘要

## 中文

- 纯物理接触：{physical['success_rate']:.1%}（{physical['trial_count']} 次）
- Verified latch：{latch['success_rate']:.1%}（{latch['trial_count']} 次）
- 成功率差值：{gain:.1f} 个百分点
- Verified latch 平均投放误差：{error_text}
- 重要说明：Verified latch 是任务级仿真约束，不代表纯物理抓取成功率。

## English

- Physical contact: {physical['success_rate']:.1%} across {physical['trial_count']} trials
- Verified latch: {latch['success_rate']:.1%} across {latch['trial_count']} trials
- Success-rate difference: {gain:.1f} percentage points
- Mean verified-latch placement error: {error_text}
- Disclosure: Verified latch is a task-level simulation constraint, not a
  pure physical-contact grasp success rate.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare RadeonHome evaluation modes")
    parser.add_argument("--physical", type=Path, required=True)
    parser.add_argument("--latch", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    physical = json.loads(args.physical.read_text(encoding="utf-8"))
    latch = json.loads(args.latch.read_text(encoding="utf-8"))
    comparison = compare_modes(physical, latch)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    args.output_markdown.write_text(
        render_markdown(comparison), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
