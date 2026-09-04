#!/usr/bin/env python3
"""Rebuild derived sparse feedback/report files without rerunning the model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.sparse_feedback.leaderboard import render_report  # noqa: E402
from experiments.sparse_feedback.prompt_ab import (  # noqa: E402
    _feedback_record,
    _write_feedback,
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=Path("experiments/results")
    )
    parser.add_argument(
        "--documentation",
        type=Path,
        default=Path("docs/memory_sparse_feedback_report.md"),
    )
    args = parser.parse_args()
    fixtures = load(Path("experiments/fixtures/cases.json"))["cases"]
    prompt = load(args.output_dir / "prompt_ab_results.json")
    feedback = []
    for fixture in fixtures:
        pair = {
            prompt_id: next(
                row
                for row in prompt["runs"]
                if row["case_id"] == fixture["case_id"]
                and row["prompt_id"] == prompt_id
            )
            for prompt_id in ("A", "B")
        }
        feedback.append(_feedback_record(fixture, pair))
    _write_feedback(args.output_dir / "sparse_feedback.jsonl", feedback)
    feedback_payload = [item.model_dump(mode="json") for item in feedback]
    (args.output_dir / "sparse_feedback_sample.json").write_text(
        json.dumps(feedback_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    prompt["feedback"] = feedback_payload
    memory = {
        "baseline": load(args.output_dir / "memory/baseline.json"),
        "optimized": load(args.output_dir / "memory/optimized.json"),
        "comparison": load(args.output_dir / "memory/comparison.json"),
    }
    rag = load(args.output_dir / "rag_grid_results.json")
    leaderboard = load(args.output_dir / "leaderboard.json")["rows"]
    report = render_report(
        memory_result=memory,
        rag_result=rag,
        prompt_result=prompt,
        leaderboard=leaderboard,
    )
    (args.output_dir / "report.md").write_text(report + "\n", encoding="utf-8")
    args.documentation.write_text(report + "\n", encoding="utf-8")
    execution_path = args.output_dir / "execution_report.json"
    execution = load(execution_path)
    preferences: dict[str, int] = {}
    for item in feedback_payload:
        preferred = str(item["preferred"])
        preferences[preferred] = preferences.get(preferred, 0) + 1
    execution["feedback_preferences"] = preferences
    archived = args.output_dir.parent / "results_run_500_truncated"
    if archived.exists():
        execution["archived_failed_run"] = str(archived)
    execution_path.write_text(
        json.dumps(execution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"feedback_preferences": preferences, "report": str(args.documentation)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
