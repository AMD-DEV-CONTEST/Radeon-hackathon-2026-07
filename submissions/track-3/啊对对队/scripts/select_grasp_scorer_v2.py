#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_model_selection import select_grasp_scorer_candidate
from parcel_sorter.grasp_scoring import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply the frozen v2 development gate to grasp scorers."
    )
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        metavar="NAME=EVALUATION_JSON",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_candidates(values: list[str]) -> list[tuple[str, dict[str, Any]]]:
    candidates = []
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path:
            raise ValueError("candidate must use NAME=EVALUATION_JSON")
        path = Path(raw_path).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evaluation_file"] = str(path)
        payload["evaluation_file_sha256"] = sha256_file(path)
        candidates.append((name, payload))
    return candidates


def main() -> int:
    args = parse_args()
    result = select_grasp_scorer_candidate(load_candidates(args.candidate))
    result["selection_code"] = str(Path(__file__).resolve())
    result["selection_code_sha256"] = sha256_file(Path(__file__).resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": result["status"],
                "selected": result["selected"],
                "holdout_opened": result["holdout_opened"],
            },
            allow_nan=False,
        )
    )
    return 0 if result["status"] == "promoted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
