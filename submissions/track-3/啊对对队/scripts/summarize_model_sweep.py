from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.sweep_evidence import build_sweep_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact model-sweep evidence")
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--dataset-split", required=True)
    parser.add_argument("--expected-steps", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        result = build_sweep_evidence(
            Path(args.sweep_root),
            Path(args.dataset_split),
            expected_steps=args.expected_steps,
        )
    except ValueError as exc:
        parser.error(str(exc))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"cells": len(result["cells"]), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
