from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_public_submission_snapshot.py"
SPEC = importlib.util.spec_from_file_location("validate_public_submission_snapshot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_public_health_omits_local_setup_error_path() -> None:
    private_path = "C:/" + "Users/private/model.bin"
    raw = json.dumps({
        "status": "ok",
        "version": "1",
        "configured": False,
        "setupError": f"missing {private_path}",
    })
    value = MODULE.public_health(raw)
    assert value == {
        "status": "ok",
        "version": "1",
        "configured": False,
        "setupErrorPresent": True,
    }
    assert "Users" not in json.dumps(value)


def test_pytest_passed_count_accepts_current_suite_size() -> None:
    assert MODULE.pytest_passed_count("................................ [100%]\n96 passed in 2.40s\n") == 96
    assert MODULE.pytest_passed_count("1 failed, 95 passed in 2.40s") == 95
    assert MODULE.pytest_passed_count("no tests ran") is None
