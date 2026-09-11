from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.comparison import compare_expert_runs


def _load(path: str) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare expert runs on exactly the same episode indices"
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--allowed-config-difference",
        action="append",
        dest="allowed_config_differences",
        help="require config differences to match exactly; repeat for multiple paths",
    )
    args = parser.parse_args()

    result = compare_expert_runs(
        _load(args.baseline),
        _load(args.candidate),
        allowed_config_differences=(
            tuple(args.allowed_config_differences)
            if args.allowed_config_differences is not None
            else None
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
