#!/usr/bin/env python3
"""Run MEM-03..05 and EXP-01..06, then emit reports from measured logs."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.memory.experiment import run_memory_experiment  # noqa: E402
from experiments.memory.streaming import model_name  # noqa: E402
from experiments.sparse_feedback.leaderboard import (  # noqa: E402
    generate_leaderboard,
    render_report,
)
from experiments.sparse_feedback.prompt_ab import run_prompt_ab  # noqa: E402
from experiments.sparse_feedback.rag_grid import run_rag_grid  # noqa: E402


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
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    wall_started = time.perf_counter()
    selected_model = model_name()
    memory = run_memory_experiment(
        args.output_dir / "memory",
        max_tokens=args.max_tokens,
        concurrency=args.concurrency,
    )
    rag = run_rag_grid(args.output_dir)
    prompt = run_prompt_ab(args.output_dir, max_tokens=args.max_tokens)
    leaderboard = generate_leaderboard(
        args.output_dir,
        rag_result=rag,
        prompt_result=prompt,
    )
    report = render_report(
        memory_result=memory,
        rag_result=rag,
        prompt_result=prompt,
        leaderboard=leaderboard,
    )
    (args.output_dir / "report.md").write_text(report + "\n", encoding="utf-8")
    args.documentation.parent.mkdir(parents=True, exist_ok=True)
    args.documentation.write_text(report + "\n", encoding="utf-8")
    execution = {
        "schema_version": 1,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.perf_counter() - wall_started, 3),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model": selected_model,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "memory_fidelity_passed": memory["comparison"]["fidelity_passed"],
        "protected_field_retention": memory["comparison"][
            "protected_field_retention"
        ],
        "rag_configurations": len(rag["configurations"]),
        "prompt_runs": len(prompt["runs"]),
        "feedback_records": len(prompt["feedback"]),
        "leaderboard_rows": len(leaderboard),
        "best_configuration": leaderboard[0]["configuration"],
        "best_score": leaderboard[0]["composite_score"],
        "artifacts": {
            "leaderboard": str(args.output_dir / "leaderboard.csv"),
            "report": str(args.output_dir / "report.md"),
            "documentation": str(args.documentation),
        },
    }
    (args.output_dir / "execution_report.json").write_text(
        json.dumps(execution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(execution, ensure_ascii=False, indent=2))
    return 0 if memory["comparison"]["fidelity_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
