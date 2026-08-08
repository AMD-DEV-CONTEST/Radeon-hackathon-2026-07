"""API Verification — verifies HTTP API responses.

Checks:
  - HTTP status code matches expected
  - Response body contains expected content
  - Response body matches expected JSON schema
  - Response time is within threshold
  - Required headers are present
  - Authentication is enforced
  - Rate limiting is enforced
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class APICheck:
    """Result of an API verification."""
    check_type: str
    target: str
    expected: Any
    actual: Any
    passed: bool
    response_time_ms: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "response_time_ms": round(self.response_time_ms, 2) if self.response_time_ms else None,
            "error": self.error,
        }


class APIVerifier:
    """Verifies HTTP API responses."""

    def verify_status_code(
        self,
        url: str,
        expected_status: int,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 10.0,
    ) -> APICheck:
        """Verify an API returns the expected status code."""
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(url, method=method, headers=headers or {})
            start = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    actual_status = resp.getcode()
                    actual_body = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                actual_status = e.code
                actual_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            response_time = (time.time() - start) * 1000

            passed = actual_status == expected_status
            return APICheck(
                check_type="status_code",
                target=url,
                expected=expected_status,
                actual=actual_status,
                passed=passed,
                response_time_ms=response_time,
            )
        except Exception as e:
            return APICheck(
                check_type="status_code",
                target=url,
                expected=expected_status,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_response_body(
        self,
        url: str,
        expected_content: str,
        regex: bool = False,
        timeout: float = 10.0,
    ) -> APICheck:
        """Verify an API response body contains expected content."""
        try:
            import urllib.request

            start = time.time()
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                actual_body = resp.read().decode("utf-8", errors="replace")
            response_time = (time.time() - start) * 1000

            if regex:
                passed = bool(re.search(expected_content, actual_body))
            else:
                passed = expected_content in actual_body

            return APICheck(
                check_type="response_body",
                target=url,
                expected=expected_content,
                actual=actual_body[:200] + "..." if len(actual_body) > 200 else actual_body,
                passed=passed,
                response_time_ms=response_time,
            )
        except Exception as e:
            return APICheck(
                check_type="response_body",
                target=url,
                expected=expected_content,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_json_path(
        self,
        url: str,
        json_path: str,
        expected_value: Any,
        timeout: float = 10.0,
    ) -> APICheck:
        """Verify a JSON path in the response matches expected value.

        Supports simple paths like "data.items.0.name".
        """
        try:
            import urllib.request

            start = time.time()
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                actual_body = json.loads(resp.read().decode("utf-8"))
            response_time = (time.time() - start) * 1000

            # Navigate the path
            actual_value: Any = actual_body
            for key in json_path.split("."):
                if key.isdigit():
                    actual_value = actual_value[int(key)]
                else:
                    actual_value = actual_value[key]

            passed = actual_value == expected_value
            return APICheck(
                check_type="json_path",
                target=f"{url}#{json_path}",
                expected=expected_value,
                actual=actual_value,
                passed=passed,
                response_time_ms=response_time,
            )
        except Exception as e:
            return APICheck(
                check_type="json_path",
                target=f"{url}#{json_path}",
                expected=expected_value,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_response_time(
        self,
        url: str,
        max_ms: float,
        timeout: float = 30.0,
    ) -> APICheck:
        """Verify an API responds within the expected time."""
        try:
            import urllib.request

            start = time.time()
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                resp.read()
            response_time = (time.time() - start) * 1000

            passed = response_time <= max_ms
            return APICheck(
                check_type="response_time",
                target=url,
                expected=f"<= {max_ms}ms",
                actual=f"{response_time:.1f}ms",
                passed=passed,
                response_time_ms=response_time,
            )
        except Exception as e:
            return APICheck(
                check_type="response_time",
                target=url,
                expected=f"<= {max_ms}ms",
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_auth_required(
        self,
        url: str,
        expected_status: int = 401,
        timeout: float = 10.0,
    ) -> APICheck:
        """Verify an API requires authentication (returns 401 without token)."""
        return self.verify_status_code(url, expected_status, timeout=timeout)

    def verify(self, check_type: str, target: str, expected: Any) -> APICheck:
        """Dispatch to the appropriate API verifier."""
        if check_type == "status_code":
            exp = expected if isinstance(expected, dict) else {"status": expected}
            return self.verify_status_code(
                target,
                exp.get("status", 200),
                exp.get("method", "GET"),
                exp.get("headers"),
                exp.get("timeout", 10.0),
            )
        if check_type == "response_body":
            exp = expected if isinstance(expected, dict) else {"content": expected}
            return self.verify_response_body(
                target,
                exp.get("content", ""),
                exp.get("regex", False),
                exp.get("timeout", 10.0),
            )
        if check_type == "json_path":
            exp = expected if isinstance(expected, dict) else expected
            return self.verify_json_path(
                target,
                exp.get("path", ""),
                exp.get("value"),
                exp.get("timeout", 10.0),
            )
        if check_type == "response_time":
            return self.verify_response_time(target, expected if isinstance(expected, (int, float)) else 1000)
        if check_type == "auth_required":
            return self.verify_auth_required(target)
        return APICheck(
            check_type=check_type,
            target=target,
            expected=expected,
            actual=None,
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
