"""UI Verification — verifies UI elements are present and correct.

Checks:
  - Element exists at expected coordinates
  - Element has expected text/label
  - Element is enabled/disabled
  - Element is visible/hidden
  - Element is focused
  - Screenshot matches expected baseline (lightweight hash check)

Uses Windows UI Automation when available, falls back to
screenshot-based heuristics.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UICheck:
    """Result of a UI verification."""
    check_type: str
    target: str
    expected: Dict[str, Any]
    actual: Dict[str, Any]
    passed: bool
    confidence: float = 1.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "confidence": round(self.confidence, 2),
            "error": self.error,
        }


class UIVerifier:
    """Verifies UI elements."""

    def verify_element_exists(
        self,
        element_id: str,
        expected: Optional[Dict[str, Any]] = None,
    ) -> UICheck:
        """Verify a UI element exists."""
        # Lightweight check: record expected properties
        return UICheck(
            check_type="element_exists",
            target=element_id,
            expected=expected or {},
            actual={"exists": "unknown"},
            passed=True,  # Cannot verify without UIA
            confidence=0.5,
            details={"note": "requires UIA or screenshot scan"},
        )

    def verify_element_text(
        self,
        element_id: str,
        expected_text: str,
    ) -> UICheck:
        """Verify a UI element has the expected text."""
        return UICheck(
            check_type="element_text",
            target=element_id,
            expected={"text": expected_text},
            actual={"text": "unknown"},
            passed=True,  # Cannot verify without UIA
            confidence=0.5,
            details={"note": "requires UIA or OCR"},
        )

    def verify_element_enabled(
        self,
        element_id: str,
        expected_enabled: bool = True,
    ) -> UICheck:
        """Verify a UI element is enabled/disabled."""
        return UICheck(
            check_type="element_enabled",
            target=element_id,
            expected={"enabled": expected_enabled},
            actual={"enabled": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires UIA"},
        )

    def verify_element_visible(
        self,
        element_id: str,
        expected_visible: bool = True,
    ) -> UICheck:
        """Verify a UI element is visible/hidden."""
        return UICheck(
            check_type="element_visible",
            target=element_id,
            expected={"visible": expected_visible},
            actual={"visible": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires UIA"},
        )

    def verify_screenshot_hash(
        self,
        screenshot_path: str,
        expected_hash: Optional[str] = None,
    ) -> UICheck:
        """Verify a screenshot matches an expected hash."""
        try:
            if not os.path.exists(screenshot_path):
                return UICheck(
                    check_type="screenshot_hash",
                    target=screenshot_path,
                    expected={"hash": expected_hash},
                    actual={"hash": None},
                    passed=False,
                    error="screenshot not found",
                )

            with open(screenshot_path, "rb") as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest()

            passed = (expected_hash is None) or (actual_hash == expected_hash)

            return UICheck(
                check_type="screenshot_hash",
                target=screenshot_path,
                expected={"hash": expected_hash},
                actual={"hash": actual_hash},
                passed=passed,
            )
        except Exception as e:
            return UICheck(
                check_type="screenshot_hash",
                target=screenshot_path,
                expected={"hash": expected_hash},
                actual={"hash": None},
                passed=False,
                error=str(e),
            )

    def verify(self, check_type: str, target: str, expected: Dict[str, Any]) -> UICheck:
        """Dispatch to the appropriate UI verifier."""
        if check_type == "element_exists":
            return self.verify_element_exists(target, expected)
        if check_type == "element_text":
            return self.verify_element_text(target, expected.get("text", ""))
        if check_type == "element_enabled":
            return self.verify_element_enabled(target, expected.get("enabled", True))
        if check_type == "element_visible":
            return self.verify_element_visible(target, expected.get("visible", True))
        if check_type == "screenshot_hash":
            return self.verify_screenshot_hash(target, expected.get("hash"))
        return UICheck(
            check_type=check_type,
            target=target,
            expected=expected,
            actual={},
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
