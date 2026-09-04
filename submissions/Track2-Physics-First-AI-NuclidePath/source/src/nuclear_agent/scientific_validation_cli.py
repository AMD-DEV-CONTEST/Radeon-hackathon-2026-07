"""CLI for the fail-closed Cs exchange calibration/hold-out gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scientific_validation import (
    AcceptancePolicy,
    MODEL_SCHEMA,
    ModelSpec,
    ObservationDataset,
    build_validation_report,
    require_experimental_validation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="observation dataset JSON")
    parser.add_argument("--model", type=Path, required=True, help="model specification JSON")
    parser.add_argument("--acceptance", type=Path, help="acceptance policy JSON")
    parser.add_argument("--output", type=Path, required=True, help="validation report JSON")
    parser.add_argument(
        "--require-promotion",
        action="store_true",
        help="return non-zero unless the measured-data hold-out gate opens",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset = ObservationDataset.from_mapping(json.loads(args.dataset.read_text(encoding="utf-8")))
    model_payload = json.loads(args.model.read_text(encoding="utf-8"))
    if model_payload.get("schema") != MODEL_SCHEMA:
        raise SystemExit("unsupported model schema")
    model = ModelSpec.from_mapping(model_payload)
    acceptance = None
    if args.acceptance:
        acceptance = AcceptancePolicy.from_mapping(
            json.loads(args.acceptance.read_text(encoding="utf-8"))
        )
    report = build_validation_report(dataset, model, acceptance=acceptance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.require_promotion:
        try:
            require_experimental_validation(report)
        except Exception as exc:  # CLI boundary: report remains useful on failure.
            raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
