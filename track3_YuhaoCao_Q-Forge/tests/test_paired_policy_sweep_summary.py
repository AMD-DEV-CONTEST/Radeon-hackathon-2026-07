import json
from pathlib import Path

import pytest

from scripts.summarize_paired_sweep import exact_mcnemar_pvalue, load_records


def test_exact_mcnemar_for_policy_pairs():
    assert exact_mcnemar_pvalue(0, 0) == 1.0
    assert exact_mcnemar_pvalue(3, 0) == pytest.approx(0.25)


def test_policy_records_are_keyed_by_reset_state(tmp_path: Path):
    path = tmp_path / "seed_2001" / "reset_7"
    path.mkdir(parents=True)
    (path / "closed_loop_metrics.json").write_text(
        json.dumps({"task_reset_state_id": 7, "success": True})
    )
    records = load_records(tmp_path, 2001)
    assert records[7]["success"] is True
