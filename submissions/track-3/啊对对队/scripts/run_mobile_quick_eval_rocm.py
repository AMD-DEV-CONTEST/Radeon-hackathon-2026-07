#!/usr/bin/env python3
"""Run a four-profile PASH diagnostic and record representative media."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_LABELS = {
    "small_carton": "小纸箱 / Small carton",
    "flat_mailer": "扁平快递袋 / Flat mailer",
    "electronics_box": "电子产品盒 / Electronics box",
    "medium_carton": "中型纸箱 / Medium carton",
}


def _format_rate(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def render_report(audit: dict[str, Any]) -> str:
    lines = [
        "# PASH 快速评测 / Quick Evaluation",
        "",
        f"总结果 / Overall: **{audit['successes']}/{audit['trials']} "
        f"({_format_rate(float(audit['success_rate']))})**",
        "",
        "| 快递类型 / Profile | 成功 / Trials | 成功率 | Wilson 95% | 成功放置平均误差 | 35 N 越界 | 失败阶段 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for profile, item in audit.get("profile_summaries", {}).items():
        error = item.get("mean_success_placement_error_m")
        error_text = f"{100.0 * float(error):.2f} cm" if error is not None else "N/A"
        low, high = item.get("wilson_95", (0.0, 0.0))
        failures = item.get("failure_stages") or {}
        failure_text = ", ".join(f"{key}: {value}" for key, value in failures.items()) or "-"
        lines.append(
            f"| {PROFILE_LABELS.get(profile, profile)} | "
            f"{item['successes']}/{item['trials']} | "
            f"{_format_rate(float(item['success_rate']))} | "
            f"{_format_rate(float(low))}-{_format_rate(float(high))} | {error_text} | "
            f"{item['force_violation_count']} | {failure_text} |"
        )
    lines.extend(
        (
            "",
            "> 这是快速诊断集，不替代冻结 100 回合晋级评测，也不用于训练。",
            "> This rapid diagnostic does not replace the frozen 100-trial promotion campaign and is never training data.",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "mobile_quick_eval_v1.json",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT_ROOT / "configs" / "active_mobile_smolvla.json",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--no-media", action="store_true")
    parser.add_argument("--require-vla-goal-verdict", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be absent or empty")
    if args.workers < 1:
        parser.error("workers must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    collection_dir = args.output / "campaign"
    collection_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "collect_mobile_suction_dataset_rocm.py"),
        "--config",
        str(args.config.resolve()),
        "--output",
        str(collection_dir),
        "--backend",
        "rocm",
        "--audit-only",
        "--smolvla-checkpoint",
        str(args.checkpoint.resolve()),
        "--policy-mode",
        "base_residual",
        "--policy-hz",
        "3",
        "--workers",
        str(args.workers),
    ]
    if args.max_episodes is not None:
        collection_command.extend(("--max-episodes", str(args.max_episodes)))
    if not args.no_media:
        collection_command.append("--record-media-per-profile")
    if args.require_vla_goal_verdict:
        collection_command.append("--require-vla-goal-verdict")

    with (args.output / "collection.log").open("w", encoding="utf-8") as log:
        collected = subprocess.run(
            collection_command, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    if collected.returncode != 0:
        raise RuntimeError(f"quick evaluation collection failed; inspect {args.output / 'collection.log'}")
    if not args.no_media:
        for source in collection_dir.glob("shards/*/run/media/*"):
            if source.suffix.lower() in {".mp4", ".png"}:
                shutil.copy2(source, args.output / source.name)

    audit_path = args.output / "audit.json"
    summary_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "summarize_mobile_vla_campaign.py"),
        "--collection-summary",
        str(collection_dir / "collection-summary.json"),
        "--output",
        str(audit_path),
    ]
    with (args.output / "summary.log").open("w", encoding="utf-8") as log:
        summarized = subprocess.run(
            summary_command, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    if summarized.returncode != 0:
        raise RuntimeError(f"quick evaluation summary failed; inspect {args.output / 'summary.log'}")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    report = render_report(audit)
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
