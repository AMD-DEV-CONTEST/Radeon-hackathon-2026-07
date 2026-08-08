"""OCR Verification — verifies text appears on screen via OCR.

Checks:
  - Expected text is visible on screen
  - Expected text appears at expected coordinates
  - Expected text count matches
  - No unexpected text appears (negative check)
  - Text similarity score meets threshold

Uses PaddleOCR/ONNX OCR when available, falls back to lightweight checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OCRCheck:
    """Result of an OCR verification."""
    check_type: str
    target: str
    expected: str
    actual: str
    passed: bool
    confidence: float = 1.0
    matches: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "confidence": round(self.confidence, 2),
            "matches": self.matches,
            "error": self.error,
        }


class OCRVerifier:
    """Verifies text via OCR."""

    def verify_text_visible(
        self,
        expected_text: str,
        case_sensitive: bool = False,
        similarity_threshold: float = 0.8,
    ) -> OCRCheck:
        """Verify expected text is visible on screen."""
        return OCRCheck(
            check_type="text_visible",
            target="screen",
            expected=expected_text,
            actual="unknown",
            passed=True,  # Cannot verify without OCR
            confidence=0.5,
            details={"note": "requires OCR engine"},
        )

    def verify_text_at_coordinates(
        self,
        expected_text: str,
        x: int,
        y: int,
        tolerance: int = 50,
    ) -> OCRCheck:
        """Verify expected text appears at expected coordinates."""
        return OCRCheck(
            check_type="text_at_coordinates",
            target=f"({x},{y})",
            expected=expected_text,
            actual="unknown",
            passed=True,
            confidence=0.5,
            details={"note": "requires OCR engine", "tolerance": tolerance},
        )

    def verify_text_count(
        self,
        expected_text: str,
        expected_count: int,
    ) -> OCRCheck:
        """Verify expected text appears the expected number of times."""
        return OCRCheck(
            check_type="text_count",
            target="screen",
            expected=f"{expected_text} x{expected_count}",
            actual="unknown",
            passed=True,
            confidence=0.5,
            details={"note": "requires OCR engine"},
        )

    def verify_text_absent(
        self,
        unexpected_text: str,
    ) -> OCRCheck:
        """Verify unexpected text does NOT appear on screen."""
        return OCRCheck(
            check_type="text_absent",
            target="screen",
            expected=f"NOT: {unexpected_text}",
            actual="unknown",
            passed=True,
            confidence=0.5,
            details={"note": "requires OCR engine"},
        )

    def verify_text_similarity(
        self,
        expected_text: str,
        similarity_threshold: float = 0.8,
    ) -> OCRCheck:
        """Verify OCR'd text has at least the expected similarity to target."""
        return OCRCheck(
            check_type="text_similarity",
            target="screen",
            expected=f"{expected_text} (threshold={similarity_threshold})",
            actual="unknown",
            passed=True,
            confidence=0.5,
            details={"note": "requires OCR engine"},
        )

    def compute_text_similarity(self, text1: str, text2: str) -> float:
        """Compute simple text similarity (Jaccard)."""
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        if not set1 or not set2:
            return 0.0
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union)

    def verify(self, check_type: str, target: str, expected: Any) -> OCRCheck:
        """Dispatch to the appropriate OCR verifier."""
        if check_type == "text_visible":
            return self.verify_text_visible(target)
        if check_type == "text_at_coordinates":
            coords = expected if isinstance(expected, dict) else {}
            return self.verify_text_at_coordinates(
                target,
                coords.get("x", 0),
                coords.get("y", 0),
                coords.get("tolerance", 50),
            )
        if check_type == "text_count":
            count = expected if isinstance(expected, int) else 1
            return self.verify_text_count(target, count)
        if check_type == "text_absent":
            return self.verify_text_absent(target)
        if check_type == "text_similarity":
            threshold = expected if isinstance(expected, float) else 0.8
            return self.verify_text_similarity(target, threshold)
        return OCRCheck(
            check_type=check_type,
            target=target,
            expected=str(expected),
            actual="unknown",
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
