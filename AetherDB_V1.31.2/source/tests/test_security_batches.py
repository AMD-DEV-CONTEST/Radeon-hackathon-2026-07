import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "batch",
    (
        "batch_01_core.py",
        "batch_02_infra.py",
        "batch_03_revised.py",
        "batch_04_regression.py",
        "batch_05_missing.py",
    ),
)
def test_security_batch_is_hermetic_and_returns_a_real_exit_code(batch):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests" / batch)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
