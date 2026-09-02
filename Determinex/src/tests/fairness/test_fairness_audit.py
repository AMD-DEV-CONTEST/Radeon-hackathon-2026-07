import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


def test_binary_fairness_audit_reports_group_metrics_and_fairness_gaps():
    from scripts.fairness.audit import audit_decisions

    rows = [
        {"group": "A", "y_true": 1, "y_pred": 1},
        {"group": "A", "y_true": 1, "y_pred": 1},
        {"group": "A", "y_true": 0, "y_pred": 1},
        {"group": "A", "y_true": 0, "y_pred": 0},
        {"group": "B", "y_true": 1, "y_pred": 1},
        {"group": "B", "y_true": 1, "y_pred": 0},
        {"group": "B", "y_true": 0, "y_pred": 0},
        {"group": "B", "y_true": 0, "y_pred": 0},
    ]

    report = audit_decisions(
        rows, group_field="group", truth_field="y_true", prediction_field="y_pred"
    )

    assert report["status"] == "FAIRNESS_AUDIT_COMPLETE"
    assert report["scope"]["supported_metrics"] == [
        "selection_rate",
        "true_positive_rate",
        "false_positive_rate",
        "demographic_parity_difference",
        "equal_opportunity_difference",
        "equalized_odds_difference",
    ]
    assert report["groups"]["A"]["selection_rate"] == pytest.approx(0.75)
    assert report["groups"]["A"]["true_positive_rate"] == pytest.approx(1.0)
    assert report["groups"]["A"]["false_positive_rate"] == pytest.approx(0.5)
    assert report["groups"]["B"]["selection_rate"] == pytest.approx(0.25)
    assert report["groups"]["B"]["true_positive_rate"] == pytest.approx(0.5)
    assert report["groups"]["B"]["false_positive_rate"] == pytest.approx(0.0)
    assert report["fairness_gaps"]["demographic_parity_difference"] == pytest.approx(0.5)
    assert report["fairness_gaps"]["equal_opportunity_difference"] == pytest.approx(0.5)
    assert report["fairness_gaps"]["equalized_odds_difference"] == pytest.approx(0.5)
    assert report["unsupported_claims"] == [
        "debiasing_algorithm",
        "dataset_diversity_certification",
        "bias_report_user_feedback_loop",
    ]


def test_binary_fairness_audit_requires_binary_labels():
    from scripts.fairness.audit import FairnessAuditError, audit_decisions

    rows = [{"group": "A", "y_true": 2, "y_pred": 1}]

    with pytest.raises(FairnessAuditError, match="binary"):
        audit_decisions(rows, group_field="group", truth_field="y_true", prediction_field="y_pred")


def test_binary_fairness_audit_flags_missing_denominators_without_inventing_rates():
    from scripts.fairness.audit import audit_decisions

    rows = [
        {"group": "A", "y_true": 1, "y_pred": 1},
        {"group": "A", "y_true": 1, "y_pred": 0},
        {"group": "B", "y_true": 0, "y_pred": 1},
        {"group": "B", "y_true": 0, "y_pred": 0},
    ]

    report = audit_decisions(
        rows, group_field="group", truth_field="y_true", prediction_field="y_pred"
    )

    assert report["groups"]["A"]["false_positive_rate"] is None
    assert report["groups"]["B"]["true_positive_rate"] is None
    assert "A:false_positive_rate" in report["warnings"]
    assert "B:true_positive_rate" in report["warnings"]
    assert report["fairness_gaps"]["equalized_odds_difference"] is None


def test_fairness_audit_cli_reads_csv_and_writes_json():
    scratch = Path(__file__).resolve().parent
    input_path = scratch / f"decisions_{uuid.uuid4().hex}.csv"
    try:
        input_path.write_text(
            "group,y_true,y_pred\nA,1,1\nA,0,1\nB,1,0\nB,0,1\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.fairness.audit",
                "--input",
                str(input_path),
                "--group-field",
                "group",
                "--truth-field",
                "y_true",
                "--prediction-field",
                "y_pred",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        input_path.unlink(missing_ok=True)

    report = json.loads(result.stdout)
    assert report["status"] == "FAIRNESS_AUDIT_COMPLETE"
    assert report["row_count"] == 4
    assert report["fairness_gaps"]["demographic_parity_difference"] == pytest.approx(0.5)
