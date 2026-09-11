from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.repeatability import analyze_repeatability_campaign


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze nested same-episode execution repeats"
    )
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        parser.error(f"output already exists: {args.output}")
    schedule = json.loads(args.schedule.read_text(encoding="utf-8"))
    summaries = {}
    for block in schedule["blocks"]:
        run_index = int(block["run_index"])
        block_root = args.runs_root / f"{run_index:02d}"
        for condition in schedule["conditions"]:
            path = block_root / condition / "expert" / "summary.json"
            if not path.is_file():
                parser.error(f"summary is missing: {path}")
            summaries[(run_index, condition)] = json.loads(
                path.read_text(encoding="utf-8")
            )
    result = analyze_repeatability_campaign(schedule, summaries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
