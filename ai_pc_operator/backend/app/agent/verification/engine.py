"""Verification Engine — orchestrator that ties all verifiers together.

Provides a single entry point for running multiple verification checks
across different domains (state, UI, DOM, OCR, file, API, process).

Usage:
    engine = VerificationEngine()
    report = engine.verify([
        {"type": "file", "check": "exists", "target": "/path/to/file"},
        {"type": "api", "check": "status_code", "target": "http://...", "expected": 200},
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .state_verification import StateVerifier, StateCheck
from .ui_verification import UIVerifier, UICheck
from .dom_verification import DOMVerifier, DOMCheck
from .ocr_verification import OCRVerifier, OCRCheck
from .file_verification import FileVerifier, FileCheck
from .api_verification import APIVerifier, APICheck
from .process_verification import ProcessVerifier, ProcessCheck


# Union of all check result types
CheckResult = Union[
    StateCheck, UICheck, DOMCheck, OCRCheck, FileCheck, APICheck, ProcessCheck
]


@dataclass
class VerificationReport:
    """Aggregated verification report."""
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    overall_passed: bool = True
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "overall_passed": self.overall_passed,
            "results": self.results,
            "errors": self.errors,
        }


class VerificationEngine:
    """Orchestrator that runs verification checks across all domains."""

    def __init__(self) -> None:
        self.state = StateVerifier()
        self.ui = UIVerifier()
        self.dom = DOMVerifier()
        self.ocr = OCRVerifier()
        self.file = FileVerifier()
        self.api = APIVerifier()
        self.process = ProcessVerifier()

    def verify(self, checks: List[Dict[str, Any]]) -> VerificationReport:
        """Run a list of verification checks.

        Each check is a dict with:
          - type: "state" | "ui" | "dom" | "ocr" | "file" | "api" | "process"
          - check: the specific check name
          - target: the target to verify
          - expected: the expected value (optional)
        """
        report = VerificationReport()

        for check_spec in checks:
            check_type = check_spec.get("type", "").lower()
            check_name = check_spec.get("check", "")
            target = check_spec.get("target")
            expected = check_spec.get("expected")

            try:
                result = self._dispatch(check_type, check_name, target, expected)
                report.total_checks += 1
                if result.passed:
                    report.passed_checks += 1
                else:
                    report.failed_checks += 1
                    report.overall_passed = False
                report.results.append(result.to_dict())
            except Exception as e:
                report.total_checks += 1
                report.failed_checks += 1
                report.overall_passed = False
                report.errors.append(f"{check_type}.{check_name}: {e}")

        return report

    def _dispatch(
        self,
        check_type: str,
        check_name: str,
        target: Any,
        expected: Any,
    ) -> CheckResult:
        """Dispatch a check to the appropriate verifier."""
        if check_type == "state":
            return self.state.verify(check_name, target, expected)
        if check_type == "ui":
            return self.ui.verify(check_name, target, expected)
        if check_type == "dom":
            return self.dom.verify(check_name, target, expected)
        if check_type == "ocr":
            return self.ocr.verify(check_name, target, expected)
        if check_type == "file":
            return self.file.verify(check_name, target, expected)
        if check_type == "api":
            return self.api.verify(check_name, target, expected)
        if check_type == "process":
            return self.process.verify(check_name, target, expected)
        raise ValueError(f"unknown check type: {check_type}")

    def verify_file(self, path: str, check: str = "exists", expected: Any = None) -> FileCheck:
        """Convenience: verify a file."""
        return self.file.verify(check, path, expected)

    def verify_api(self, url: str, check: str = "status_code", expected: Any = None) -> APICheck:
        """Convenience: verify an API."""
        return self.api.verify(check, url, expected)

    def verify_process(self, target: Any, check: str = "exit_code", expected: Any = None) -> ProcessCheck:
        """Convenience: verify a process."""
        return self.process.verify(check, target, expected)

    def verify_state(self, target: str, check: str = "process", expected: Any = None) -> StateCheck:
        """Convenience: verify system state."""
        return self.state.verify(check, target, expected)
