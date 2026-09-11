from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parcel_sorter.evaluation import aggregate_checkpoint_evaluations


def _candidate_files(inputs: list[str]) -> list[Path]:
    candidates: set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            candidates.update(path.rglob("*.json"))
        elif path.is_file():
            candidates.add(path)
        else:
            raise FileNotFoundError(f"evaluation input not found: {path}")
    return sorted(candidates)


def _load_records(paths: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    records = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if "checkpoint" in payload and "episodes" in payload:
            records.append((str(path), payload))
    if not records:
        raise ValueError("no ACT evaluation summaries found")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank ACT checkpoints by non-overlapping closed-loop evaluations"
    )
    parser.add_argument("inputs", nargs="+", help="summary files or directories")
    parser.add_argument("--output", default="outputs/act-checkpoint-ranking.json")
    args = parser.parse_args()

    aggregates = aggregate_checkpoint_evaluations(
        _load_records(_candidate_files(args.inputs))
    )
    payload = {
        "selection_rule": [
            "safety_violation_rate ascending (hard gate)",
            "macro_profile_success_rate descending",
            "success_rate descending",
            "drop_rate ascending",
            "p95_inference_latency_ms ascending",
            "max_contact_force_n ascending",
        ],
        "recommended_checkpoint": aggregates[0].checkpoint,
        "checkpoints": [aggregate.to_dict() for aggregate in aggregates],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
