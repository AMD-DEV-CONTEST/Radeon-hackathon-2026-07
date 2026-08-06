import json
from pathlib import Path

import numpy as np
import pytest
import torch

from colorgraph.evaluation.precision_gate import (
    _srgb_to_lab,
    run_precision_gate,
)
from colorgraph.grading.precision import (
    MASTER_PRECISION_BUDGET,
    PREVIEW_PRECISION_BUDGET,
)


def test_precision_budgets_define_pixel_and_perceptual_limits() -> None:
    assert (
        MASTER_PRECISION_BUDGET.maximum_normalized_channel_error
        < PREVIEW_PRECISION_BUDGET.maximum_normalized_channel_error
    )
    assert (
        MASTER_PRECISION_BUDGET.maximum_delta_e_2000
        < PREVIEW_PRECISION_BUDGET.maximum_delta_e_2000
    )
    assert not MASTER_PRECISION_BUDGET.mixed_precision_allowed
    assert PREVIEW_PRECISION_BUDGET.mixed_precision_allowed


def test_srgb_to_lab_uses_d65_reference_values() -> None:
    samples = torch.tensor(
        [
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=torch.float32,
    ).reshape(3, 3, 1, 1)
    lab = _srgb_to_lab(samples).reshape(3, 3)

    assert np.allclose(lab[0], [0.0, 0.0, 0.0], atol=1e-6)
    assert np.allclose(lab[1], [100.0, 0.0, 0.0], atol=2e-4)
    assert np.allclose(
        lab[2],
        [53.2408, 80.0925, 67.2032],
        atol=5e-4,
    )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="accelerator is unavailable")
def test_precision_gate_writes_reproducible_accelerator_report(
    tmp_path: Path,
) -> None:
    runtime = "rocm" if torch.version.hip else "cuda"
    report_path = tmp_path / "precision-report.json"

    report = run_precision_gate(
        report_path,
        expected_runtime=runtime,
        repeats=2,
    )

    assert report.status == "passed"
    assert report.hardware.runtime == runtime
    assert report.master.passed
    assert report.preview.passed
    assert report.determinism.passed
    assert len(report.determinism.output_sha256) == 2
    assert report.determinism.output_sha256[0] == (
        report.determinism.output_sha256[1]
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "colorgraph.precision-gate-report/v1"
    assert payload["graph_sha256"] == report.graph_sha256
