"""Binary decision fairness metrics for audited Determinex outputs.

This module measures group-level outcome disparities. It does not debias a model
or certify dataset representativeness.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

SUPPORTED_METRICS = [
    "selection_rate",
    "true_positive_rate",
    "false_positive_rate",
    "demographic_parity_difference",
    "equal_opportunity_difference",
    "equalized_odds_difference",
]

UNSUPPORTED_CLAIMS = [
    "debiasing_algorithm",
    "dataset_diversity_certification",
    "bias_report_user_feedback_loop",
]


class FairnessAuditError(ValueError):
    """Raised when a fairness audit input is malformed or out of scope."""


def _as_binary(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return int(value.strip())
    raise FairnessAuditError(f"{field} must contain binary 0/1 labels")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _gap(values: Sequence[float | None]) -> float | None:
    complete = [value for value in values if value is not None]
    if len(complete) != len(values):
        return None
    if len(complete) < 2:
        return 0.0
    return max(complete) - min(complete)


def audit_decisions(
    rows: Iterable[Mapping[str, object]],
    *,
    group_field: str,
    truth_field: str,
    prediction_field: str,
) -> dict:
    materialized = list(rows)
    if not materialized:
        raise FairnessAuditError("fairness audit requires at least one row")

    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "predicted_positive": 0,
            "actual_positive": 0,
            "actual_negative": 0,
            "true_positive": 0,
            "false_positive": 0,
            "true_negative": 0,
            "false_negative": 0,
        }
    )

    for index, row in enumerate(materialized, start=1):
        for field in (group_field, truth_field, prediction_field):
            if field not in row:
                raise FairnessAuditError(f"row {index} missing required field {field!r}")

        group = str(row[group_field]).strip()
        if not group:
            raise FairnessAuditError(f"row {index} has empty group field {group_field!r}")

        truth = _as_binary(row[truth_field], field=truth_field)
        prediction = _as_binary(row[prediction_field], field=prediction_field)
        bucket = counts[group]
        bucket["total"] += 1
        bucket["predicted_positive"] += prediction
        bucket["actual_positive"] += truth
        bucket["actual_negative"] += 1 - truth
        if truth == 1 and prediction == 1:
            bucket["true_positive"] += 1
        elif truth == 0 and prediction == 1:
            bucket["false_positive"] += 1
        elif truth == 0 and prediction == 0:
            bucket["true_negative"] += 1
        else:
            bucket["false_negative"] += 1

    groups: dict[str, dict[str, float | int | None]] = {}
    warnings: list[str] = []

    for group in sorted(counts):
        c = counts[group]
        selection_rate = _rate(c["predicted_positive"], c["total"])
        true_positive_rate = _rate(c["true_positive"], c["actual_positive"])
        false_positive_rate = _rate(c["false_positive"], c["actual_negative"])
        if true_positive_rate is None:
            warnings.append(f"{group}:true_positive_rate")
        if false_positive_rate is None:
            warnings.append(f"{group}:false_positive_rate")
        groups[group] = {
            **c,
            "selection_rate": selection_rate,
            "true_positive_rate": true_positive_rate,
            "false_positive_rate": false_positive_rate,
        }

    selection_gap = _gap([g["selection_rate"] for g in groups.values()])  # type: ignore[list-item]
    tpr_gap = _gap([g["true_positive_rate"] for g in groups.values()])  # type: ignore[list-item]
    fpr_gap = _gap([g["false_positive_rate"] for g in groups.values()])  # type: ignore[list-item]
    equalized_odds = None if tpr_gap is None or fpr_gap is None else max(tpr_gap, fpr_gap)

    return {
        "status": "FAIRNESS_AUDIT_COMPLETE",
        "version": 1,
        "row_count": len(materialized),
        "scope": {
            "decision_type": "binary_classification_or_binary_decision",
            "group_field": group_field,
            "truth_field": truth_field,
            "prediction_field": prediction_field,
            "supported_metrics": SUPPORTED_METRICS,
            "note": "Measurement only; no debiasing or dataset-diversity certification.",
        },
        "groups": groups,
        "fairness_gaps": {
            "demographic_parity_difference": selection_gap,
            "equal_opportunity_difference": tpr_gap,
            "equalized_odds_difference": equalized_odds,
        },
        "warnings": warnings,
        "unsupported_claims": UNSUPPORTED_CLAIMS,
    }


def _load_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise FairnessAuditError("JSON input must be a list of row objects")
        return data

    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit binary decision fairness metrics.")
    parser.add_argument(
        "--input", required=True, help="CSV or JSON rows with group/truth/prediction fields"
    )
    parser.add_argument("--group-field", required=True)
    parser.add_argument("--truth-field", required=True)
    parser.add_argument("--prediction-field", required=True)
    args = parser.parse_args(argv)

    rows = _load_rows(Path(args.input))
    report = audit_decisions(
        rows,
        group_field=args.group_field,
        truth_field=args.truth_field,
        prediction_field=args.prediction_field,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
