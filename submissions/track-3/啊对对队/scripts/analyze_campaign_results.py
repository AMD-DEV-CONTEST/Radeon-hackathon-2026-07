from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.evaluation_statistics import build_campaign_evaluation


def _run_argument(value: str) -> tuple[str, Path]:
    run_id, separator, raw_path = value.partition("=")
    if not separator or not run_id or not raw_path:
        raise argparse.ArgumentTypeError("run must use RUN_ID=/path/to/summary.json")
    return run_id, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze two or more matched closed-loop campaign runs"
    )
    parser.add_argument(
        "--run",
        action="append",
        type=_run_argument,
        required=True,
        metavar="RUN_ID=SUMMARY_JSON",
    )
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    run_paths = dict(args.run)
    if len(run_paths) != len(args.run):
        parser.error("run IDs must be unique")
    if args.output.exists() and not args.overwrite:
        parser.error(f"output already exists: {args.output}")
    payloads = {
        run_id: json.loads(path.read_text(encoding="utf-8"))
        for run_id, path in run_paths.items()
    }
    result = build_campaign_evaluation(payloads, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
