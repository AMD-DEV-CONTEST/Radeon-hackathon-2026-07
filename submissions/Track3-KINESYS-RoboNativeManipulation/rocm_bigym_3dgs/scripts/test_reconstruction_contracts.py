#!/usr/bin/env python3
"""Dependency-light tests for reconstruction quality selection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "reconstruction/src/select_training_candidate.py"


def candidate(root: Path, name: str, metrics: dict[str, float]) -> None:
    directory = root / f"{name}-30000"
    (directory / "stats").mkdir(parents=True)
    (directory / "ckpts").mkdir()
    (directory / "stats/val_step29999.json").write_text(
        json.dumps(metrics), encoding="utf-8"
    )
    (directory / "ckpts/ckpt_29999_rank0.pt").write_bytes(b"test-only")


def run_case(
    root: Path, default_metrics: dict[str, float], mcmc_metrics: dict[str, float]
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    training = root / "training"
    candidate(training, "default", default_metrics)
    candidate(training, "mcmc", mcmc_metrics)
    output = root / "selection.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SELECTOR),
            "--training-root",
            str(training),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(output.read_text(encoding="utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        result, payload = run_case(
            Path(directory),
            {"psnr": 31.0, "ssim": 0.94, "lpips": 0.14},
            {"psnr": 35.0, "ssim": 0.96, "lpips": 0.12},
        )
        assert result.returncode == 0, result.stderr
        assert payload["status"] == "passed"
        assert payload["formal_export_allowed"] is True
        assert payload["selected"]["name"] == "mcmc"

    with tempfile.TemporaryDirectory() as directory:
        result, payload = run_case(
            Path(directory),
            {"psnr": 28.0, "ssim": 0.90, "lpips": 0.20},
            {"psnr": 29.0, "ssim": 0.91, "lpips": 0.18},
        )
        assert result.returncode == 2
        assert payload["status"] == "quality_target_not_met"
        assert payload["formal_export_allowed"] is False

    print("RECONSTRUCTION_CONTRACT_TESTS_OK")


if __name__ == "__main__":
    main()
