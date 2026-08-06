from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402


class AuditResult(unittest.TextTestResult):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.successes: list[str] = []

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        super().addSuccess(test)
        self.successes.append(test.id())


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths = (
        sorted((root / "src").rglob("*.py"))
        + sorted((root / "tests").rglob("test_*.py"))
        + sorted((root / "scripts").glob("*.py"))
        + sorted((root / "scripts").glob("*.mjs"))
        + sorted((root / "config").glob("*.json"))
        + sorted((root / "config").rglob("*.yaml"))
        + sorted((root / "notebooks").glob("*.ipynb"))
        + [
            root / "README.md",
            root / "SUBMISSION_GATE.json",
            root / "docs" / "CORTEX_X_V10_1500_TODO.md",
            root / "docs" / "CORTEX_X_V10_EXECUTION_ORDER.md",
            root / "docs" / "FRONTIER_1500_EXECUTION_PROTOCOL.md",
        ]
    )
    paths = sorted({path for path in paths if path.is_file()})
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="evidence/v10/local-test-report.json",
    )
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream,
        verbosity=2,
        resultclass=AuditResult,
    )
    result = runner.run(suite)
    duration = time.perf_counter() - started
    failures = [
        {"test": test.id(), "traceback": traceback}
        for test, traceback in result.failures
    ]
    errors = [
        {"test": test.id(), "traceback": traceback}
        for test, traceback in result.errors
    ]
    skipped = [
        {"test": test.id(), "reason": reason}
        for test, reason in result.skipped
    ]
    payload = {
        "schema": "ProofLaunchLocalTestReportV10",
        "status": "passed" if result.wasSuccessful() else "failed",
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 6),
        "command": (
            "PYTHONPATH=src .venv/bin/python "
            "scripts/run_v10_local_suite.py"
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "source_tree_sha256": _source_digest(ROOT),
        "counts": {
            "run": result.testsRun,
            "passed": len(result.successes),
            "failures": len(failures),
            "errors": len(errors),
            "skipped": len(skipped),
        },
        "passed_tests": sorted(result.successes),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "runner_output": stream.getvalue(),
        "truth_boundary": (
            "This receipt proves only the listed local Python unit execution. "
            "It is not Radeon execution, model training, independent human "
            "evaluation, accessibility conformance, production reliability, "
            "or causal business-outcome evidence."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "run": result.testsRun,
                "passed": len(result.successes),
                "failures": len(failures),
                "errors": len(errors),
                "skipped": len(skipped),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
