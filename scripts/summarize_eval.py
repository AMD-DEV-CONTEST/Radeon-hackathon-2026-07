"""Evaluation result summary script: read quality_report.json to generate a summary table."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def summarize(report_path: str) -> dict:
    """Read the evaluation report and generate a summary."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    metrics = report.get("metrics", {})
    total = report.get("total", 0)

    # Group by question type (if the report contains question type info)
    by_type = {}
    for item in report.get("details", []):
        q_type = item.get("question_type", "unknown")
        by_type.setdefault(q_type, []).append(item)

    summary = {
        "total_questions": total,
        "avg_accuracy": metrics.get("avg_accuracy", 0),
        "avg_source_hit": metrics.get("avg_source_hit", 0),
        "hallucination_rate": metrics.get("hallucination_rate", 0),
        "by_type": {
            q_type: {
                "count": len(items),
                "avg_accuracy": sum(i.get("accuracy", 0) for i in items) / len(items) if items else 0,
            }
            for q_type, items in by_type.items()
        },
    }
    return summary


def print_summary(summary: dict) -> None:
    """Print the summary table."""
    print("=" * 60)
    print("Evaluation result summary")
    print("=" * 60)
    print(f"Total questions:     {summary['total_questions']}")
    print(f"Average accuracy:    {summary['avg_accuracy']:.2%}")
    print(f"Source hit rate:     {summary['avg_source_hit']:.2%}")
    print(f"Hallucination rate:  {summary['hallucination_rate']:.2%}")

    if summary["by_type"]:
        print("\nBy question type:")
        print("-" * 40)
        for q_type, data in summary["by_type"].items():
            print(f"  {q_type:12s}  {data['count']:3d} questions   accuracy: {data['avg_accuracy']:.2%}")

    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize evaluation results")
    parser.add_argument("--input", required=True, help="path to quality_report.json")
    parser.add_argument("--output", help="optional: output JSON file path")
    args = parser.parse_args()

    summary = summarize(args.input)
    print_summary(summary)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"Summary saved: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
