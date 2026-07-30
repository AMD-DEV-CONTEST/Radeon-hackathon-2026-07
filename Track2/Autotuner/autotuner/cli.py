from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import List, Optional

from autotuner.config import load_config
from autotuner.hardware import inspect_hardware
from autotuner.report import load_record, write_reports
from autotuner.runner import run_tuning
from autotuner.space import build_candidates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autotuner",
        description="Tune local language model serving on AMD Radeon GPUs",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    demo = actions.add_parser("demo", help="run a deterministic simulation")
    demo.add_argument("output", nargs="?")
    tune = actions.add_parser("tune", help="run tuning on a Radeon endpoint")
    tune.add_argument("config")
    tune.add_argument("output", nargs="?")
    inspect = actions.add_parser(
        "inspect", help="inspect the local ROCm environment"
    )
    inspect.add_argument("output", nargs="?")
    validate = actions.add_parser(
        "validate", help="validate a tuning configuration"
    )
    validate.add_argument("config")
    report = actions.add_parser(
        "report", help="rebuild reports from a run record"
    )
    report.add_argument("run")
    report.add_argument("output", nargs="?")
    return parser


def _default_output(prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"{prefix}_{stamp}"


def main(arguments: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(arguments)
    if args.action == "demo":
        demo_resource = resources.files("autotuner.data").joinpath(
            "demo.json"
        )
        config = load_config(Path(str(demo_resource)))
        output = Path(args.output) if args.output else _default_output("demo")
        run_tuning(config, output, mock=True, progress=print)
        print(f"Dashboard: {(output / 'dashboard.html').resolve()}")
        return 0
    if args.action == "tune":
        config = load_config(Path(args.config))
        output = (
            Path(args.output) if args.output else _default_output("radeon")
        )
        run_tuning(config, output, mock=False, progress=print)
        print(f"Dashboard: {(output / 'dashboard.html').resolve()}")
        return 0
    if args.action == "inspect":
        payload = inspect_hardware()
        rendered = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf8")
        else:
            print(rendered)
        return 0
    if args.action == "validate":
        config = load_config(Path(args.config))
        candidates = build_candidates(config)
        print(
            f"Valid configuration with {len(candidates)} candidates and "
            f"{min(config.trials, len(candidates))} planned trials"
        )
        return 0
    if args.action == "report":
        record = load_record(Path(args.run))
        output = Path(args.output) if args.output else Path(args.run).parent
        write_reports(record, output)
        print(f"Reports written to {output.resolve()}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
