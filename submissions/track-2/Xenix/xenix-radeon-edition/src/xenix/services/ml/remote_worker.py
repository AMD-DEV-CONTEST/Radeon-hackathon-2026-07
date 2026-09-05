from __future__ import annotations

import sys
from collections.abc import Callable

from .operations import (
    run_apply_task,
    run_evaluate_task,
    run_fit_task,
    run_hyperparameter_tuning_task,
)

ENTRYPOINTS: dict[str, Callable[[str], None]] = {
    "run_fit_task": run_fit_task,
    "run_hyperparameter_tuning_task": run_hyperparameter_tuning_task,
    "run_evaluate_task": run_evaluate_task,
    "run_apply_task": run_apply_task,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("Usage: python -m xenix.services.ml.remote_worker <entrypoint> <task-dir>", file=sys.stderr)
        return 2
    entrypoint_name, task_dir = args
    entrypoint = ENTRYPOINTS.get(entrypoint_name)
    if entrypoint is None:
        print(f"Unsupported ML worker entrypoint: {entrypoint_name}", file=sys.stderr)
        return 2
    entrypoint(task_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
