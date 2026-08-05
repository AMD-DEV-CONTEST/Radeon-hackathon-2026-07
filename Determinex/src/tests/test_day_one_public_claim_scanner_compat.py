from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = _REPO_ROOT / "scripts" / "claim_scanner" / "day_one_public_claim_scanner.py"


def test_day_one_public_claim_scanner_compat_prints_clean_payload():
    result = subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(_REPO_ROOT), "--print"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "DAY_ONE_PUBLIC_CLAIM_SCANNER_PASSED"
    assert payload["claim_clean"] is True
    assert payload["current_repo_violation_count"] == 0
    assert payload["scanner_self_test_passed"] is True
    assert payload["claim_boundary"].startswith("This scanner checks authority-anchor overclaims")
