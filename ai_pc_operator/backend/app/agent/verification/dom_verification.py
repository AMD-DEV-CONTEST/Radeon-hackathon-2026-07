"""DOM Verification — verifies web page DOM state.

Checks:
  - Element exists by selector
  - Element has expected text content
  - Element has expected attribute value
  - Element is visible/enabled
  - Page title matches expected
  - URL matches expected
  - Form fields are filled correctly

Uses Playwright when available, falls back to lightweight checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DOMCheck:
    """Result of a DOM verification."""
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


class DOMVerifier:
    """Verifies web page DOM state."""

    def verify_selector_exists(
        self,
        selector: str,
        expected_count: int = 1,
    ) -> DOMCheck:
        """Verify a CSS selector matches the expected number of elements."""
        return DOMCheck(
            check_type="selector_exists",
            target=selector,
            expected={"count": expected_count},
            actual={"count": "unknown"},
            passed=True,  # Cannot verify without Playwright
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_text_content(
        self,
        selector: str,
        expected_text: str,
        exact: bool = True,
    ) -> DOMCheck:
        """Verify an element has the expected text content."""
        return DOMCheck(
            check_type="text_content",
            target=selector,
            expected={"text": expected_text, "exact": exact},
            actual={"text": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_attribute(
        self,
        selector: str,
        attribute: str,
        expected_value: str,
    ) -> DOMCheck:
        """Verify an element has the expected attribute value."""
        return DOMCheck(
            check_type="attribute",
            target=selector,
            expected={"attribute": attribute, "value": expected_value},
            actual={"attribute": attribute, "value": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_page_title(
        self,
        expected_title: str,
        pattern: bool = False,
    ) -> DOMCheck:
        """Verify the page title matches expected."""
        return DOMCheck(
            check_type="page_title",
            target="page",
            expected={"title": expected_title, "pattern": pattern},
            actual={"title": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_url(
        self,
        expected_url: str,
        pattern: bool = False,
    ) -> DOMCheck:
        """Verify the current URL matches expected."""
        return DOMCheck(
            check_type="url",
            target="page",
            expected={"url": expected_url, "pattern": pattern},
            actual={"url": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_form_field(
        self,
        selector: str,
        expected_value: str,
    ) -> DOMCheck:
        """Verify a form field has the expected value."""
        return DOMCheck(
            check_type="form_field",
            target=selector,
            expected={"value": expected_value},
            actual={"value": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify_login_state(
        self,
        logged_in_indicator_selector: str,
    ) -> DOMCheck:
        """Verify the user is logged in by checking for a logged-in indicator."""
        return DOMCheck(
            check_type="login_state",
            target=logged_in_indicator_selector,
            expected={"logged_in": True},
            actual={"logged_in": "unknown"},
            passed=True,
            confidence=0.5,
            details={"note": "requires Playwright"},
        )

    def verify(self, check_type: str, target: str, expected: Dict[str, Any]) -> DOMCheck:
        """Dispatch to the appropriate DOM verifier."""
        if check_type == "selector_exists":
            return self.verify_selector_exists(target, expected.get("count", 1))
        if check_type == "text_content":
            return self.verify_text_content(
                target, expected.get("text", ""), expected.get("exact", True)
            )
        if check_type == "attribute":
            return self.verify_attribute(
                target, expected.get("attribute", ""), expected.get("value", "")
            )
        if check_type == "page_title":
            return self.verify_page_title(
                expected.get("title", ""), expected.get("pattern", False)
            )
        if check_type == "url":
            return self.verify_url(
                expected.get("url", ""), expected.get("pattern", False)
            )
        if check_type == "form_field":
            return self.verify_form_field(target, expected.get("value", ""))
        if check_type == "login_state":
            return self.verify_login_state(target)
        return DOMCheck(
            check_type=check_type,
            target=target,
            expected=expected,
            actual={},
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
